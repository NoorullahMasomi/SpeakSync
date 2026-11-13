"""A SpeakSync project: one video + the parts where you speak + your recordings.

The project is one folder the user chooses:

    My video/
        project.speaksync      <- this file (JSON)
        takes/p_ab12cd.webm    <- one recording per part
        takes/old/...          <- earlier tries, never deleted
        export/                <- finished videos and subtitles

Script format (plain text, any language) - the easiest way to write a whole script:

    [0:01 - 0:03] Hello and welcome.

    [0:05 - 0:12] In this video I show you ...

    A part without time gets its time later, when you mark it on the video.

A blank line starts a new part. SRT subtitle files work too (import and export).
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from pathlib import Path

PROJECT_FILE = "project.speaksync"
FORMAT = 1
AUDIO_EXT = (".webm", ".ogg", ".mp4", ".m4a", ".wav", ".mp3")
MODES = ("fit", "wait")         # fit = voice on the video's time;  wait = the video waits for the voice


def new_id() -> str:
    return "p_" + secrets.token_hex(4)


# ------------------------------------------------------------------ time text
def fmt_time(t: float, srt: bool = False) -> str:
    """seconds -> '1:05.3'   (srt=True -> '00:01:05,300')"""
    t = max(0.0, float(t))
    if srt:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    s_txt = f"{s:04.1f}".rstrip("0").rstrip(".") if s % 1 else f"{int(s):02d}"
    if "." in s_txt and len(s_txt.split(".")[0]) < 2:
        s_txt = "0" + s_txt
    return f"{h}:{m:02d}:{s_txt}" if h else f"{m}:{s_txt}"


_NUM = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*$")


def parse_time(txt: str) -> float | None:
    """'1:05.3' / '65.3' / '0:01:05,300' / '1' -> seconds.  Bad text -> None."""
    m = _NUM.match(str(txt or ""))
    if not m:
        return None
    a, b, c = m.group(1), m.group(2), m.group(3).replace(",", ".")
    if a and b:
        return int(a) * 3600 + int(b) * 60 + float(c)
    if a:
        return int(a) * 60 + float(c)
    return float(c)


# ------------------------------------------------------------------ script text
_TIMED = re.compile(r"^\s*\[\s*([0-9:.,]+)\s*(?:-|–|—|to)\s*([0-9:.,]+)\s*\]\s*(.*)$", re.S)
_SRT_TIME = re.compile(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)")


def parse_script(text: str) -> list[dict]:
    """Script text -> parts [{start, end, text}] (start/end None when the part has no time yet)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    if _SRT_TIME.search(text):
        return parse_srt(text)
    parts = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        m = _TIMED.match(block)
        start = end = None
        if m:
            start, end = parse_time(m.group(1)), parse_time(m.group(2))
            block = m.group(3).strip()
            if start is not None and end is not None and end <= start:
                start = end = None
        parts.append({"start": start, "end": end, "text": " ".join(block.split())})
    return parts


def parse_srt(text: str) -> list[dict]:
    parts = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if m:
                body = " ".join(" ".join(lines[i + 1:]).split())
                body = re.sub(r"<[^>]+>", "", body)          # <i> tags
                parts.append({"start": parse_time(m.group(1)), "end": parse_time(m.group(2)), "text": body})
                break
    return parts


def script_text(parts: list[dict]) -> str:
    out = []
    for p in parts:
        if p.get("start") is not None and p.get("end") is not None:
            out.append(f"[{fmt_time(p['start'])} - {fmt_time(p['end'])}] {p.get('text', '')}".rstrip())
        else:
            out.append(p.get("text", ""))
    return "\n\n".join(out) + "\n"


def srt_text(cues: list[tuple[float, float, str]]) -> str:
    out = []
    for i, (s, e, t) in enumerate(cues, 1):
        out.append(f"{i}\n{fmt_time(s, True)} --> {fmt_time(e, True)}\n{t.strip() or '...'}\n")
    return "\n".join(out)


# ------------------------------------------------------------------ the project
class ProjectError(Exception):
    pass


class Project:
    def __init__(self, folder: Path, data: dict):
        self.folder = Path(folder)
        self.data = data

    # ---------------------------------------------------------- open / save
    @classmethod
    def create(cls, folder: Path, name: str, video: Path, duration: float) -> "Project":
        folder = Path(folder)
        if (folder / PROJECT_FILE).exists():
            raise ProjectError("This folder already has a SpeakSync project. Open it instead.")
        folder.mkdir(parents=True, exist_ok=True)
        now = time.time()
        data = {"app": "SpeakSync", "format": FORMAT, "name": name.strip() or Path(video).stem,
                "video": str(Path(video).resolve()), "duration": round(float(duration), 3),
                "mode": "fit", "bg_volume": 0.25, "duck": True, "voice_volume": 1.0, "speed_fit": True,
                "lang": "", "parts": [], "created": now, "updated": now}
        p = cls(folder, data)
        p.save()
        return p

    @classmethod
    def open(cls, path: Path) -> "Project":
        path = Path(path)
        folder = path if path.is_dir() else path.parent
        f = folder / PROJECT_FILE
        if not f.exists():
            raise ProjectError("No SpeakSync project in this folder.")
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ProjectError(f"The project file cannot be read: {e}") from e
        if data.get("app") != "SpeakSync":
            raise ProjectError("This is not a SpeakSync project file.")
        if int(data.get("format", 1)) > FORMAT:
            raise ProjectError("This project was made by a newer SpeakSync. Please update the app.")
        data.setdefault("parts", [])
        data.setdefault("mode", "fit")
        data.setdefault("bg_volume", 0.25)
        data.setdefault("duck", True)
        data.setdefault("voice_volume", 1.0)
        data.setdefault("speed_fit", True)
        return cls(folder, data)

    def save(self) -> None:
        self.data["updated"] = time.time()
        f = self.folder / PROJECT_FILE
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)                                      # never a half-written project file

    # ---------------------------------------------------------- paths
    @property
    def video(self) -> Path:
        v = Path(self.data["video"])
        if not v.is_absolute():
            v = self.folder / v
        return v

    @property
    def takes_dir(self) -> Path:
        return self.folder / "takes"

    @property
    def export_dir(self) -> Path:
        return self.folder / "export"

    def take_path(self, pid: str) -> Path | None:
        d = self.takes_dir
        if not d.is_dir():
            return None
        for ext in AUDIO_EXT:
            p = d / f"{pid}{ext}"
            if p.exists():
                return p
        return None

    # ---------------------------------------------------------- parts
    def part(self, pid: str) -> dict:
        for p in self.data["parts"]:
            if p["id"] == pid:
                return p
        raise ProjectError("Unknown part.")

    def sort_parts(self) -> None:
        """Parts with a time come in time order; parts without a time keep their place at the end."""
        timed = [p for p in self.data["parts"] if p.get("start") is not None]
        untimed = [p for p in self.data["parts"] if p.get("start") is None]
        timed.sort(key=lambda p: p["start"])
        self.data["parts"] = timed + untimed

    def set_parts(self, parts: list[dict]) -> None:
        """Replace all parts (from the page). Keeps ids, so recordings stay with their part."""
        dur = float(self.data.get("duration") or 0)
        clean = []
        seen = set()
        for p in parts:
            pid = str(p.get("id") or "")
            if not re.fullmatch(r"p_[0-9a-f]{8}", pid) or pid in seen:
                pid = new_id()
            seen.add(pid)
            s, e = p.get("start"), p.get("end")
            s = None if s is None else max(0.0, round(float(s), 3))
            e = None if e is None else round(float(e), 3)
            if dur > 0:
                if s is not None:
                    s = min(s, dur)
                if e is not None:
                    e = min(e, dur)
            if s is None or e is None:                      # a part has both times or none
                s = e = None
            elif e - s < 0.2:                               # too short: make it 0.2 s
                e = round(s + 0.2, 3)
                if dur > 0 and e > dur:
                    s, e = round(max(0.0, dur - 0.2), 3), dur
            clean.append({"id": pid, "start": s, "end": e, "text": str(p.get("text") or "")[:20000]})
        self.data["parts"] = clean
        self.sort_parts()

    def import_script(self, text: str, replace: bool) -> int:
        """Script text -> parts. replace=False: the text goes into the existing parts in order, extra
        paragraphs become new parts. Returns how many parts the script had."""
        new = parse_script(text)
        if replace:
            old = self.data["parts"]
            # keep the ids (and recordings) of the first parts when only the text changes
            self.data["parts"] = [{"id": old[i]["id"] if i < len(old) else new_id(), **p} for i, p in enumerate(new)]
        else:
            parts = self.data["parts"]
            for i, p in enumerate(new):
                if i < len(parts):
                    parts[i]["text"] = p["text"]
                    if p["start"] is not None and parts[i].get("start") is None:
                        parts[i]["start"], parts[i]["end"] = p["start"], p["end"]
                else:
                    parts.append({"id": new_id(), **p})
        self.set_parts(self.data["parts"])
        return len(new)

    # ---------------------------------------------------------- recordings
    def save_take(self, pid: str, data: bytes, ext: str) -> Path:
        self.part(pid)                                      # must exist
        self.takes_dir.mkdir(parents=True, exist_ok=True)
        old = self.take_path(pid)
        if old is not None:                                 # keep the old try
            keep = self.takes_dir / "old"
            keep.mkdir(exist_ok=True)
            shutil.move(str(old), keep / f"{pid}_{time.strftime('%Y%m%d_%H%M%S')}{old.suffix}")
        out = self.takes_dir / f"{pid}{ext}"
        out.write_bytes(data)
        return out

    def delete_take(self, pid: str) -> None:
        old = self.take_path(pid)
        if old is not None:
            keep = self.takes_dir / "old"
            keep.mkdir(exist_ok=True)
            shutil.move(str(old), keep / f"{pid}_{time.strftime('%Y%m%d_%H%M%S')}{old.suffix}")

    # ---------------------------------------------------------- for the page
    def info(self) -> dict:
        parts = []
        for p in self.data["parts"]:
            t = self.take_path(p["id"])
            parts.append({**p, "take": bool(t), "stamp": int(t.stat().st_mtime) if t else 0})
        d = {k: v for k, v in self.data.items() if k != "parts"}
        return {**d, "folder": str(self.folder), "video_ok": self.video.exists(), "parts": parts}
