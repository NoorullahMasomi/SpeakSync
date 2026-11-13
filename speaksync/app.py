"""SpeakSync main program: a small web server on this PC only + the app window (Microsoft Edge in app mode).

Nothing leaves the computer. The only internet call is the daily "new version?" question to GitHub.
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import APP_NAME, AUTHOR, HOMEPAGE, VERSION, updates
from .media import Job, MediaError, open_path, probe
from .project import PROJECT_FILE, Project, ProjectError, script_text, srt_text

# ------------------------------------------------------------------ places on disk
if getattr(sys, "frozen", False):
    WEB = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "web"
else:
    WEB = Path(__file__).resolve().parent / "web"

def _local_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

LOCAL = _local_dir()
SETTINGS_FILE = LOCAL / "settings.json"
RUNNING_FILE = LOCAL / "running.json"
LOG_FILE = LOCAL / "speaksync.log"


def log(msg: str) -> None:
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2_000_000:
            LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def documents() -> Path:
    if sys.platform == "win32":
        try:
            import ctypes.wintypes
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)      # 5 = My Documents
            if buf.value:
                return Path(buf.value)
        except Exception:                                                    # noqa: BLE001
            pass
    return Path.home() / "Documents"


# ------------------------------------------------------------------ settings
class Settings:
    def __init__(self):
        self.lock = threading.Lock()
        try:
            self.data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("recent", [])
        self.data.setdefault("ui_lang", "")

    def save(self) -> None:
        with self.lock:
            tmp = SETTINGS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(SETTINGS_FILE)

    def add_recent(self, folder: Path) -> None:
        f = str(folder)
        r = [x for x in self.data["recent"] if x.lower() != f.lower()]
        self.data["recent"] = [f, *r][:12]
        self.save()


SETTINGS = Settings()


# ------------------------------------------------------------------ Windows file dialogs (one thread)
_dlg_q: queue.Queue = queue.Queue()


def _dialog_thread() -> None:
    import tkinter as tk
    from tkinter import filedialog
    while True:
        kind, kw, box = _dlg_q.get()
        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            root.update()
            fn = {"open": filedialog.askopenfilename, "save": filedialog.asksaveasfilename,
                  "folder": filedialog.askdirectory}[kind]
            box["result"] = fn(parent=root, **kw) or ""
        except Exception as e:                                                # noqa: BLE001
            box["result"] = ""
            box["error"] = str(e)
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:                                             # noqa: BLE001
                    pass
            box["done"].set()


threading.Thread(target=_dialog_thread, daemon=True, name="dialogs").start()


def dialog(kind: str, **kw) -> str:
    box = {"done": threading.Event()}
    _dlg_q.put((kind, kw, box))
    box["done"].wait()
    return box.get("result", "")


VIDEO_TYPES = [("Video", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.wmv *.mpg *.mpeg *.flv"), ("All files", "*.*")]


# ------------------------------------------------------------------ the open project
class State:
    project: Project | None = None
    lock = threading.RLock()
    job = Job()
    last_ping = 0.0
    bye_at = 0.0


def need_project() -> Project:
    if State.project is None:
        raise ProjectError("No project is open.")
    return State.project


def safe_name(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", name).strip(" .")
    return s[:80] or "My video"


# ------------------------------------------------------------------ API actions
def api_state() -> dict:
    recent = []
    for f in SETTINGS.data["recent"]:
        p = Path(f)
        recent.append({"path": f, "name": p.name, "ok": (p / PROJECT_FILE).exists()})
    return {"app": APP_NAME, "version": VERSION, "author": AUTHOR, "homepage": HOMEPAGE,
            "ui_lang": SETTINGS.data.get("ui_lang", ""), "recent": recent,
            "documents": str(documents() / APP_NAME),
            "project": State.project.info() if State.project else None,
            "update": SETTINGS.data.get("update") or {}}


def api_pick_video() -> dict:
    start = SETTINGS.data.get("last_video_dir") or str(Path.home() / "Videos")
    path = dialog("open", title="Choose your video", filetypes=VIDEO_TYPES, initialdir=start)
    if not path:
        return {"ok": False}
    SETTINGS.data["last_video_dir"] = str(Path(path).parent)
    SETTINGS.save()
    info = probe(Path(path))
    return {"ok": True, "path": str(Path(path)), "name": Path(path).stem, "duration": info.duration,
            "width": info.width, "height": info.height, "has_audio": info.has_audio}


def api_pick_folder(start: str) -> dict:
    path = dialog("folder", title="Where should SpeakSync keep this project?",
                  initialdir=start if Path(start).exists() else str(documents()), mustexist=False)
    return {"ok": bool(path), "path": str(Path(path)) if path else ""}


def api_create(body: dict) -> dict:
    video = Path(body.get("video") or "")
    if not video.is_file():
        raise ProjectError("Choose a video first.")
    name = safe_name(str(body.get("name") or video.stem))
    folder = Path(body.get("folder") or (documents() / APP_NAME / name))
    if folder.exists() and any(folder.iterdir()) and not (folder / PROJECT_FILE).exists():
        folder = folder / name                    # never fill a used folder with our files
    info = probe(video)
    with State.lock:
        p = Project.create(folder, name, video, info.duration)
        if body.get("script"):
            p.import_script(str(body["script"]), replace=True)
            p.save()
        State.project = p
    SETTINGS.add_recent(p.folder)
    return {"ok": True, "project": p.info()}


def api_open(body: dict) -> dict:
    path = body.get("path")
    if not path:
        path = dialog("open", title="Open a SpeakSync project",
                      filetypes=[("SpeakSync project", "*.speaksync"), ("All files", "*.*")],
                      initialdir=str(documents() / APP_NAME))
        if not path:
            return {"ok": False}
    with State.lock:
        p = Project.open(Path(path))
        State.project = p
    SETTINGS.add_recent(p.folder)
    return {"ok": True, "project": p.info()}


def api_relink() -> dict:
    p = need_project()
    path = dialog("open", title="Where is the video now?", filetypes=VIDEO_TYPES,
                  initialdir=str(p.video.parent if p.video.parent.exists() else Path.home()))
    if not path:
        return {"ok": False}
    info = probe(Path(path))
    with State.lock:
        p.data["video"] = str(Path(path).resolve())
        p.data["duration"] = info.duration
        p.save()
    return {"ok": True, "project": p.info()}


def api_settings(body: dict) -> dict:
    p = need_project()
    with State.lock:
        d = p.data
        if body.get("mode") in ("fit", "wait"):
            d["mode"] = body["mode"]
        for k, lo, hi in (("bg_volume", 0, 2), ("voice_volume", 0, 3)):
            if k in body:
                d[k] = max(lo, min(hi, float(body[k])))
        for k in ("duck", "speed_fit"):
            if k in body:
                d[k] = bool(body[k])
        if body.get("name"):
            d["name"] = safe_name(str(body["name"]))
        p.save()
    return {"ok": True, "project": p.info()}


def api_parts(body: dict) -> dict:
    p = need_project()
    with State.lock:
        p.set_parts(list(body.get("parts") or []))
        p.save()
    return {"ok": True, "project": p.info()}


def api_script(body: dict) -> dict:
    p = need_project()
    text = body.get("text")
    if text is None:                                   # from a file
        path = dialog("open", title="Choose a script or subtitle file",
                      filetypes=[("Script or subtitles", "*.txt *.srt"), ("All files", "*.*")],
                      initialdir=str(p.folder))
        if not path:
            return {"ok": False}
        raw = Path(path).read_bytes()
        for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    with State.lock:
        n = p.import_script(str(text), replace=bool(body.get("replace")))
        p.save()
    return {"ok": True, "count": n, "project": p.info()}


def api_save_script(body: dict) -> dict:
    p = need_project()
    kind = "srt" if body.get("kind") == "srt" else "txt"
    path = dialog("save", title="Save the script" if kind == "txt" else "Save subtitles",
                  initialdir=str(p.folder), initialfile=f"{p.data['name']}.{kind}",
                  defaultextension=f".{kind}", filetypes=[("Text" if kind == "txt" else "Subtitles", f"*.{kind}")])
    if not path:
        return {"ok": False}
    parts = p.data["parts"]
    if kind == "txt":
        Path(path).write_text(script_text(parts), encoding="utf-8")
    else:
        cues = [(x["start"], x["end"], x.get("text", "")) for x in parts if x.get("start") is not None]
        Path(path).write_text(srt_text(cues), encoding="utf-8")
    return {"ok": True, "path": path}


def api_export(body: dict) -> dict:
    p = need_project()
    if State.job.status().get("running"):
        return {"ok": False, "error": "busy"}
    p.export_dir.mkdir(parents=True, exist_ok=True)
    path = body.get("path") if body.get("ask") is False else None
    if not path:
        path = dialog("save", title="Save the finished video", initialdir=str(p.export_dir),
                      initialfile=f"{p.data['name']} - SpeakSync.mp4", defaultextension=".mp4",
                      filetypes=[("MP4 video", "*.mp4")])
        if not path:
            return {"ok": False}
    out = Path(path)
    if out.suffix.lower() != ".mp4":
        out = out.with_suffix(".mp4")
    if out.resolve() == p.video.resolve():
        raise ProjectError("Choose another name - this is your original video.")
    return State.job.start(p, out)


def api_open_path(body: dict) -> dict:
    what = body.get("what")
    if what == "homepage":
        webbrowser.open(HOMEPAGE)
    elif what == "update":
        u = SETTINGS.data.get("update") or {}
        webbrowser.open(u.get("page") or f"{HOMEPAGE}/releases/latest")
    elif what == "folder":
        open_path(need_project().folder)
    elif what in ("output", "output_folder"):
        out = Path(State.job.status().get("out") or "")
        if out.exists():
            open_path(out if what == "output" else out.parent)
    return {"ok": True}


# ------------------------------------------------------------------ HTTP
TOKEN = secrets.token_urlsafe(18)
PREFERRED_PORT = 47815


class Handler(BaseHTTPRequestHandler):
    server_version = APP_NAME
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---------------------------------------------------------- helpers
    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str | None = None) -> None:
        size = path.stat().st_size
        ctype = ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and size:
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass

    def _body(self, limit: int = 5_000_000) -> bytes:
        size = int(self.headers.get("Content-Length") or 0)
        if size < 0 or size > limit:
            raise ProjectError("The data is too big.")
        return self.rfile.read(size) if size else b""

    def _jbody(self) -> dict:
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _allowed(self, url) -> bool:
        """Only our own window may talk to us: right Host and the secret key of this run."""
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        key = self.headers.get("X-Key") or parse_qs(url.query).get("k", [""])[0]
        return secrets.compare_digest(key, TOKEN)

    def _route(self, method: str) -> None:
        url = urlparse(self.path)
        parts = [x for x in url.path.split("/") if x]
        try:
            if method == "GET" and (not parts or parts[0] == "static"):
                return self._static(parts)
            if not self._allowed(url):
                return self._json({"error": "forbidden"}, 403)
            State.last_ping = time.time()
            return self._api(method, parts)
        except (ProjectError, MediaError) as e:
            return self._json({"ok": False, "error": str(e)}, 200)
        except Exception as e:                                                 # noqa: BLE001
            log("ERROR " + traceback.format_exc())
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def _static(self, parts: list[str]) -> None:
        if not parts:
            return self._file(WEB / "index.html", "text/html; charset=utf-8")
        rel = Path(*parts[1:])
        f = (WEB / rel).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml"}.get(f.suffix.lower())
        return self._file(f, ctype)

    def _api(self, method: str, p: list[str]) -> None:
        key = (method, "/".join(p[:3]))
        if p and p[0] == "media" and method in ("GET", "HEAD"):
            proj = need_project()
            if p[1:] == ["video"]:
                if not proj.video.exists():
                    return self._json({"error": "missing"}, 404)
                return self._file(proj.video)
            if len(p) == 3 and p[1] == "take":
                t = proj.take_path(p[2])
                return self._file(t) if t else self._json({"error": "none"}, 404)
            return self._json({"error": "not found"}, 404)
        if len(p) == 3 and p[:2] == ["api", "take"]:
            proj = need_project()
            if method == "PUT":
                data = self._body(300_000_000)
                if len(data) < 200:
                    raise ProjectError("The recording is empty.")
                ctype = self.headers.get("Content-Type", "")
                ext = ".ogg" if "ogg" in ctype else ".mp4" if "mp4" in ctype else ".wav" if "wav" in ctype else ".webm"
                with State.lock:
                    proj.save_take(p[2], data, ext)
                return self._json({"ok": True, "project": proj.info()})
            if method == "DELETE":
                with State.lock:
                    proj.delete_take(p[2])
                return self._json({"ok": True, "project": proj.info()})
        routes = {
            ("GET", "api/state"): lambda: api_state(),
            ("POST", "api/ping"): lambda: {"ok": True},
            ("POST", "api/bye"): lambda: (setattr(State, "bye_at", time.time()), {"ok": True})[1],
            ("POST", "api/ui"): lambda: self._set_ui(),
            ("POST", "api/pick/video"): lambda: api_pick_video(),
            ("POST", "api/pick/folder"): lambda: api_pick_folder(self._jbody().get("start", "")),
            ("POST", "api/project/create"): lambda: api_create(self._jbody()),
            ("POST", "api/project/open"): lambda: api_open(self._jbody()),
            ("POST", "api/project/close"): lambda: self._close(),
            ("POST", "api/project/relink"): lambda: api_relink(),
            ("POST", "api/project/settings"): lambda: api_settings(self._jbody()),
            ("PUT", "api/project/parts"): lambda: api_parts(self._jbody()),
            ("POST", "api/project/script"): lambda: api_script(self._jbody()),
            ("POST", "api/project/savescript"): lambda: api_save_script(self._jbody()),
            ("POST", "api/export"): lambda: api_export(self._jbody()),
            ("GET", "api/export"): lambda: State.job.status(),
            ("POST", "api/export/cancel"): lambda: (State.job.cancel(), {"ok": True})[1],
            ("POST", "api/open"): lambda: api_open_path(self._jbody()),
            ("GET", "api/update"): lambda: updates.check(SETTINGS.data, force=True),
        }
        fn = routes.get(key)
        if fn is None:
            return self._json({"error": "not found"}, 404)
        out = fn()
        if key == ("GET", "api/update"):
            SETTINGS.save()
        return self._json(out)

    def _set_ui(self) -> dict:
        lang = str(self._jbody().get("lang", ""))
        if re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", lang):
            SETTINGS.data["ui_lang"] = lang
            SETTINGS.save()
        return {"ok": True}

    def _close(self) -> dict:
        with State.lock:
            State.project = None
        return {"ok": True}

    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("HEAD")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")


# ------------------------------------------------------------------ the window
def find_edge() -> str | None:
    pf = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("ProgramFiles", r"C:\Program Files"),
          os.environ.get("LOCALAPPDATA", "")]
    for base in pf:
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return None


def open_window(url: str) -> None:
    edge = find_edge()
    if edge:
        prof = LOCAL / "window"
        subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={prof}", "--window-size=1440,920",
                          "--no-first-run", "--no-default-browser-check", "--disable-features=Translate",
                          "--autoplay-policy=no-user-gesture-required"])
    else:
        webbrowser.open(url)


def already_running() -> str | None:
    """If SpeakSync is already open, return its address (we only bring its window back)."""
    try:
        info = json.loads(RUNNING_FILE.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(info['port'])}/"
        req = urllib.request.Request(url + "api/ping", data=b"", method="POST", headers={"X-Key": info["token"]})
        with urllib.request.urlopen(req, timeout=1.5) as r:                    # noqa: S310 - our own local server
            if r.status == 200:
                return url + "?k=" + info["token"]
    except Exception:                                                          # noqa: BLE001
        pass
    return None


def watchdog(srv: ThreadingHTTPServer, started: float) -> None:
    """Stop the program when its window is closed (the page stops saying 'I am here')."""
    while True:
        time.sleep(2)
        now = time.time()
        if State.job.status().get("running"):
            continue
        if State.bye_at and now - State.bye_at > 6 and State.last_ping <= State.bye_at:
            break
        if State.last_ping and now - State.last_ping > 180:
            break
        if not State.last_ping and now - started > 180:
            break
    log("window closed - stopping")
    srv.shutdown()


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    to_open = next((a for a in argv if not a.startswith("--") and a.lower().endswith(".speaksync")), None)
    other = already_running()
    if other and "--new" not in argv:
        if to_open:                                  # double-clicked a project: the open app shows it
            try:
                base, key = other.split("?k=")
                req = urllib.request.Request(base + "api/project/open", method="POST",
                                             data=json.dumps({"path": to_open}).encode("utf-8"),
                                             headers={"X-Key": key, "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()                    # noqa: S310 - our own local server
            except Exception:                                                    # noqa: BLE001
                pass
        open_window(other)
        return
    if to_open:
        try:
            State.project = Project.open(Path(to_open))
            SETTINGS.add_recent(State.project.folder)
        except ProjectError as e:
            log(f"could not open {to_open}: {e}")
    # A fixed port keeps the same address every time, so Windows/Edge remember "allow the microphone".
    port = PREFERRED_PORT
    for a in argv:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:                                  # the port is used by another program
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    global TOKEN
    if "--dev-key" in argv:                       # tests only: a fixed key
        TOKEN = "dev"
    RUNNING_FILE.write_text(json.dumps({"port": port, "token": TOKEN, "pid": os.getpid()}), encoding="utf-8")
    url = f"http://127.0.0.1:{port}/?k={TOKEN}"
    log(f"{APP_NAME} {VERSION} started on port {port}")
    print(f"{APP_NAME} {VERSION}: {url}", flush=True)

    def first_update_check():
        try:
            updates.check(SETTINGS.data)
            SETTINGS.save()
        except Exception:                                                        # noqa: BLE001
            pass

    threading.Thread(target=first_update_check, daemon=True).start()
    if "--no-window" not in argv:
        threading.Timer(0.3, open_window, [url]).start()
    if "--stay" not in argv:
        threading.Thread(target=watchdog, args=(srv, time.time()), daemon=True).start()
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            info = json.loads(RUNNING_FILE.read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                RUNNING_FILE.unlink()
        except (OSError, ValueError):
            pass
