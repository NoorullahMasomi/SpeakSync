"""Everything that touches ffmpeg: read a video, clean a recording, and make the finished video.

Two timing modes:
  fit   the video stays as it is. Each recording starts at its part's start time. A recording that is
        longer than the room before the next part is played a little faster (up to 1.25x).
  wait  the video waits for your voice: when you talk longer than the part, the last picture of the
        part stays on screen until you finish. Good for slides, screen recordings and lessons.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .project import Project, fmt_time, srt_text

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0      # no black console window
BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0
MAX_TEMPO = 1.25


class MediaError(Exception):
    pass


# ------------------------------------------------------------------ ffmpeg
_ffmpeg: str | None = None


def ffmpeg() -> str:
    global _ffmpeg
    if _ffmpeg:
        return _ffmpeg
    here = []
    if getattr(sys, "frozen", False):                        # the packed app: bin/ffmpeg.exe beside it
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        here += [base / "bin" / "ffmpeg.exe", Path(sys.executable).parent / "bin" / "ffmpeg.exe"]
    here.append(Path(__file__).resolve().parent.parent / "bin" / "ffmpeg.exe")
    for p in here:
        if p.exists():
            _ffmpeg = str(p)
            return _ffmpeg
    try:
        import imageio_ffmpeg                                 # developer copy
        _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        return _ffmpeg
    except Exception:                                         # noqa: BLE001
        pass
    found = shutil.which("ffmpeg")
    if found:
        _ffmpeg = found
        return found
    raise MediaError("ffmpeg was not found. Please install SpeakSync again.")


def run(args: list[str], what: str) -> subprocess.CompletedProcess:
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if r.returncode != 0:
        tail = " | ".join(l.strip() for l in r.stderr.strip().splitlines()[-3:])
        raise MediaError(f"{what} failed: {tail}")
    return r


# ------------------------------------------------------------------ read a video
@dataclass
class VideoInfo:
    duration: float
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 30.0


def probe(path: Path) -> VideoInfo:
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    err = r.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise MediaError("This file is not a video SpeakSync can read.")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    vline = next((l for l in err.splitlines() if "Stream #" in l and "Video:" in l and "attached pic" not in l), "")
    if not vline:
        raise MediaError("This file has no picture (no video stream).")
    w = h = 0
    sm = re.search(r",\s*(\d{2,5})x(\d{2,5})", vline)
    if sm:
        w, h = int(sm.group(1)), int(sm.group(2))
    fm = re.search(r"([\d.]+)\s*fps", vline) or re.search(r"([\d.]+)\s*tbr", vline)
    fps = float(fm.group(1)) if fm else 30.0
    if not 1 <= fps <= 240:
        fps = 30.0
    has_audio = any("Stream #" in l and "Audio:" in l for l in err.splitlines())
    return VideoInfo(round(dur, 3), has_audio, w, h, fps)


# ------------------------------------------------------------------ recordings
def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def clean_voice(src: Path, dst: Path, trim: bool = True) -> float:
    """Recording -> clean 48 kHz mono wav: low hum cut, silence cut at both ends, even loudness.
    Returns the length in seconds (0 = nothing but silence)."""
    chain = ["highpass=f=70"]
    if trim:
        chain += ["silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08",
                  "areverse", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.25", "areverse"]
    chain.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    run(["-y", "-i", str(src), "-af", ",".join(chain), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        "Cleaning a recording")
    return wav_seconds(dst) if dst.exists() else 0.0


# ------------------------------------------------------------------ where each voice goes
@dataclass
class Place:
    pid: str
    wav: Path
    start: float           # in the finished video
    length: float          # after any speed-up
    tempo: float = 1.0
    text: str = ""


@dataclass
class Piece:                # wait mode: one piece of the original video, maybe held at its end
    a: float
    b: float
    hold: float = 0.0


@dataclass
class Plan:
    places: list[Place] = field(default_factory=list)
    pieces: list[Piece] = field(default_factory=list)      # empty in fit mode
    duration: float = 0.0
    cues: list[tuple[float, float, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def make_plan(parts: list[dict], voices: dict[str, tuple[Path, float]], mode: str, video_dur: float,
              speed_fit: bool = True) -> Plan:
    """parts: project parts in time order. voices: part id -> (clean wav, seconds)."""
    plan = Plan()
    timed = sorted([p for p in parts if p.get("start") is not None and p.get("end") is not None],
                   key=lambda p: p["start"])
    if mode == "wait":
        cursor = 0.0           # where we are in the original video
        shift = 0.0            # how much later the finished video is than the original
        for i, p in enumerate(timed):
            s, e = max(p["start"], cursor), p["end"]
            if e - s < 0.05:
                plan.warnings.append(f"Part {fmt_time(p['start'])} overlaps the part before it and was skipped.")
                continue
            if s > cursor + 0.01:
                plan.pieces.append(Piece(cursor, s))
            v = voices.get(p["id"])
            hold = 0.0
            if v:
                wav, secs = v
                hold = max(0.0, secs + 0.3 - (e - s))      # 0.3 s of rest after you finish
                plan.places.append(Place(p["id"], wav, s + shift, secs, 1.0, p.get("text", "")))
                plan.cues.append((s + shift, s + shift + secs, p.get("text", "")))
            elif p.get("text"):
                plan.cues.append((s + shift, e + shift, p["text"]))
            plan.pieces.append(Piece(s, e, round(hold, 3)))
            shift += hold
            cursor = e
        if video_dur - cursor > 0.01:
            plan.pieces.append(Piece(cursor, video_dur))
        plan.duration = video_dur + shift
        return plan

    # fit
    plan.duration = video_dur
    for i, p in enumerate(timed):
        nxt = timed[i + 1]["start"] if i + 1 < len(timed) else video_dur
        room = max(0.2, nxt - p["start"])
        v = voices.get(p["id"])
        if not v:
            if p.get("text"):
                plan.cues.append((p["start"], p["end"], p["text"]))
            continue
        wav, secs = v
        tempo = 1.0
        if secs > room and speed_fit:
            tempo = min(MAX_TEMPO, secs / room)
        length = secs / tempo
        if length > room + 0.05:
            plan.warnings.append(f"Part at {fmt_time(p['start'])} is {length - room:.1f} s too long - "
                                 f"it runs into the next part. Record it shorter or use 'Video waits for my voice'.")
        plan.places.append(Place(p["id"], wav, p["start"], length, round(tempo, 4), p.get("text", "")))
        plan.cues.append((p["start"], min(p["start"] + length, video_dur), p.get("text", "")))
    return plan


def tempo_chain(t: float) -> str:
    if abs(t - 1.0) < 0.005:
        return ""
    return f"atempo={t:.4f},"      # 0.5..2.0 is fine for one atempo


# ------------------------------------------------------------------ the export job
class Job:
    """One export at a time. The page asks status() every second."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state: dict = {"running": False}
        self.proc: subprocess.Popen | None = None
        self.cancelled = False

    def status(self) -> dict:
        with self.lock:
            return dict(self.state)

    def _set(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)

    def cancel(self) -> None:
        self.cancelled = True
        p = self.proc
        if p and p.poll() is None:
            p.kill()

    def start(self, project: Project, out: Path) -> dict:
        with self.lock:
            if self.state.get("running"):
                return {"ok": False, "error": "busy"}
            self.state = {"running": True, "stage": "prepare", "pct": 0, "out": str(out), "warnings": [],
                          "started": time.time()}
        self.cancelled = False
        threading.Thread(target=self._run, args=(project, out), daemon=True).start()
        return {"ok": True}

    # ---------------------------------------------------------------- work
    def _ff(self, args: list[str], total: float, lo: float, hi: float, what: str) -> None:
        """Run ffmpeg and move the progress bar from lo to hi %."""
        if self.cancelled:
            raise MediaError("cancelled")
        cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-progress", "pipe:1", "-nostats", *args]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", errors="replace", creationflags=NO_WINDOW | BELOW_NORMAL)
        err_lines: list[str] = []
        t = threading.Thread(target=lambda: err_lines.extend(self.proc.stderr), daemon=True)
        t.start()
        for line in self.proc.stdout:
            if line.startswith("out_time_us=") and total > 0:
                try:
                    done = int(line.split("=")[1]) / 1e6
                except ValueError:
                    continue
                self._set(pct=round(lo + (hi - lo) * max(0.0, min(1.0, done / total)), 1))
        self.proc.wait()
        t.join(2)
        for pipe in (self.proc.stdout, self.proc.stderr):
            pipe.close()
        if self.cancelled:
            raise MediaError("cancelled")
        if self.proc.returncode != 0:
            tail = " | ".join(l.strip() for l in err_lines[-3:])
            raise MediaError(f"{what} failed: {tail}")
        self._set(pct=hi)

    def _run(self, project: Project, out: Path) -> None:
        work = project.folder / "export" / "_work"
        try:
            video = project.video
            if not video.exists():
                raise MediaError("The video file is missing. Open the project and choose the video again.")
            info = probe(video)
            parts = project.data["parts"]
            mode = project.data.get("mode", "fit")
            work.mkdir(parents=True, exist_ok=True)

            # 1) clean each recording
            self._set(stage="voices", pct=1)
            voices: dict[str, tuple[Path, float]] = {}
            with_take = [p for p in parts if p.get("start") is not None and project.take_path(p["id"])]
            if not with_take:
                raise MediaError("No part with a time has a recording yet.")
            for k, p in enumerate(with_take):
                if self.cancelled:
                    raise MediaError("cancelled")
                wav = work / f"{p['id']}.wav"
                secs = clean_voice(project.take_path(p["id"]), wav)
                if secs < 0.15:
                    self.state["warnings"].append(f"Part at {fmt_time(p['start'])}: the recording is silent - left out.")
                    continue
                voices[p["id"]] = (wav, secs)
                self._set(pct=round(1 + 19 * (k + 1) / len(with_take), 1))
            plan = make_plan(parts, voices, mode, info.duration, bool(project.data.get("speed_fit", True)))
            self.state["warnings"].extend(plan.warnings)

            # 2) wait mode: rebuild the picture with the held frames
            base = video
            copy_video = True
            if plan.pieces and any(pc.hold > 0 for pc in plan.pieces):
                self._set(stage="video", pct=20)
                base = self._rebuild(video, info, plan, work)
            # 3) put the voices on the video
            self._set(stage="mix", pct=70 if base is not video else 20)
            try:
                self._mix(base, info if base is video else probe(base), plan, project, out, copy_video, 70 if base is not video else 20)
            except MediaError:
                if self.cancelled:
                    raise
                self._set(stage="mix")                  # some videos cannot be copied: encode the picture
                self._mix(base, info if base is video else probe(base), plan, project, out, False, 20)
            srt = out.with_suffix(".srt")
            srt.write_text(srt_text(plan.cues), encoding="utf-8")
            self._set(running=False, stage="done", pct=100, srt=str(srt), duration=round(plan.duration, 1),
                      seconds=int(time.time() - self.state["started"]))
        except Exception as e:                                  # noqa: BLE001
            msg = "cancelled" if self.cancelled else str(e)
            self._set(running=False, stage="error", error=msg)
            if out.exists() and (self.cancelled or self.state.get("stage") == "error"):
                try:
                    out.unlink()
                except OSError:
                    pass
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _rebuild(self, video: Path, info: VideoInfo, plan: Plan, work: Path) -> Path:
        """wait mode: cut the video into pieces, hold the last frame where the voice is longer, join."""
        fps = f"{info.fps:.3f}".rstrip("0").rstrip(".")
        total = sum((pc.b - pc.a) + pc.hold for pc in plan.pieces)
        done = 0.0
        files = []
        for k, pc in enumerate(plan.pieces):
            length = (pc.b - pc.a) + pc.hold
            f = work / f"piece_{k:04d}.mkv"
            vf = f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"
            if pc.hold > 0:
                vf += f",tpad=stop_mode=clone:stop_duration={pc.hold:.3f}"
            args = ["-y", "-ss", f"{pc.a:.3f}", "-to", f"{pc.b:.3f}", "-i", str(video)]
            if info.has_audio:
                args += ["-map", "0:v:0", "-map", "0:a:0", "-af", f"aresample=48000,apad=pad_dur={pc.hold + 0.1:.3f}",
                         "-c:a", "pcm_s16le", "-ac", "2"]
            else:
                args += ["-map", "0:v:0", "-an"]
            args += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                     "-t", f"{length:.3f}", str(f)]
            lo = 20 + 50 * done / total
            done += length
            self._ff(args, length, lo, 20 + 50 * done / total, "Making the video")
            files.append(f)
        lst = work / "pieces.txt"
        lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
        joined = work / "joined.mkv"
        self._ff(["-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)], 0, 70, 70,
                 "Joining the video")
        return joined

    def _mix(self, base: Path, info: VideoInfo, plan: Plan, project: Project, out: Path, copy_video: bool,
             lo: float) -> None:
        d = project.data
        bg = max(0.0, min(2.0, float(d.get("bg_volume", 0.25))))
        voice_vol = max(0.0, min(3.0, float(d.get("voice_volume", 1.0))))
        duck = bool(d.get("duck", True))
        args = ["-y", "-i", str(base)]
        for pl in plan.places:
            args += ["-i", str(pl.wav)]
        n = len(plan.places)
        f = []
        for k, pl in enumerate(plan.places, 1):
            ms = int(round(pl.start * 1000))
            f.append(f"[{k}:a]{tempo_chain(pl.tempo)}volume={voice_vol:.3f},adelay={ms}:all=1[v{k}]")
        vlabels = "".join(f"[v{k}]" for k in range(1, n + 1))
        f.append(f"{vlabels}amix=inputs={n}:normalize=0:duration=longest,"
                 f"aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur={plan.duration:.3f}[voice]")
        use_bg = info.has_audio and bg > 0.001
        if use_bg:
            f.append(f"[0:a:0]aresample=48000,aformat=channel_layouts=stereo,volume={bg:.3f}[bg0]")
            if duck:
                f.append("[voice]asplit=2[voice1][key]")
                f.append("[bg0][key]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=450[bg1]")
                f.append("[bg1][voice1]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[aout]")
            else:
                f.append("[bg0][voice]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[aout]")
        else:
            f.append("[voice]alimiter=limit=0.95[aout]")
        graph = project.folder / "export" / "_work" / "mix.txt"
        graph.write_text(";\n".join(f), encoding="utf-8")
        args += ["-/filter_complex", str(graph), "-map", "0:v:0", "-map", "[aout]"]
        if copy_video:
            args += ["-c:v", "copy"]
        else:
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        args += ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-t", f"{plan.duration:.3f}", "-movflags", "+faststart",
                 str(out)]
        self._ff(args, plan.duration, lo, 99, "Making the video")


def open_path(p: Path) -> None:
    """Show a file or folder in Windows Explorer / play a video."""
    if sys.platform == "win32":
        os.startfile(str(p))            # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])
