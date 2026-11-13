"""Build the Windows app:   .venv\\Scripts\\python tools\\build.py

Makes:
    dist/SpeakSync/                         the app folder (SpeakSync.exe + everything it needs)
    release/SpeakSync-<version>-windows.zip   what people download from GitHub Releases
    release/SpeakSync-<version>-setup.exe     installer, only when Inno Setup 6 is installed
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from speaksync import APP_NAME, AUTHOR, VERSION  # noqa: E402

BUILD = ROOT / "build"
DIST = ROOT / "dist"
REL = ROOT / "release"
BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0


def step(msg: str) -> None:
    print(f"\n== {msg}", flush=True)


def version_file() -> Path:
    nums = [int(x) for x in VERSION.split(".")] + [0] * 4
    tup = tuple(nums[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', '{AUTHOR}'),
    StringStruct('FileDescription', '{APP_NAME} - your voice on any video'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('InternalName', '{APP_NAME}'),
    StringStruct('LegalCopyright', 'Copyright (c) 2026 {AUTHOR}. MIT License.'),
    StringStruct('OriginalFilename', '{APP_NAME}.exe'),
    StringStruct('ProductName', '{APP_NAME}'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""
    f = BUILD / "version_info.txt"
    f.write_text(text, encoding="utf-8")
    return f


def main() -> None:
    BUILD.mkdir(exist_ok=True)
    REL.mkdir(exist_ok=True)

    step("icon")
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")], check=True)

    step("ffmpeg")
    import imageio_ffmpeg
    bin_dir = BUILD / "bin"
    bin_dir.mkdir(exist_ok=True)
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), bin_dir / "ffmpeg.exe")

    step(f"PyInstaller - {APP_NAME} {VERSION}")
    sep = ";" if os.name == "nt" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
           "--name", APP_NAME, "--icon", str(ROOT / "assets" / "icon.ico"),
           "--version-file", str(version_file()),
           "--add-data", f"{ROOT / 'speaksync' / 'web'}{sep}web",
           "--add-binary", f"{bin_dir / 'ffmpeg.exe'}{sep}bin",
           "--distpath", str(DIST), "--workpath", str(BUILD / "pyi"), "--specpath", str(BUILD),
           str(ROOT / "SpeakSync.py")]
    subprocess.run(cmd, check=True, cwd=ROOT, creationflags=BELOW_NORMAL)

    app = DIST / APP_NAME
    for f in ("LICENSE", "THIRD_PARTY_NOTICES.txt"):
        shutil.copy2(ROOT / f, app / f)
    shutil.copy2(ROOT / "docs" / "READ_ME_FIRST.txt", app / "READ_ME_FIRST.txt")

    step("zip")
    z = REL / f"{APP_NAME}-{VERSION}-windows.zip"
    if z.exists():
        z.unlink()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(app.rglob("*")):
            if p.is_file():
                zf.write(p, Path(APP_NAME) / p.relative_to(app))
    print(z, f"{z.stat().st_size / 1e6:.1f} MB")

    iscc = next((p for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                             Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
                             Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe")
                 if p.exists()), None)
    outs = [z]
    if iscc:
        step("installer")
        subprocess.run([str(iscc), f"/DMyVersion={VERSION}", f"/DMyRoot={ROOT}", str(ROOT / "installer" / "SpeakSync.iss")],
                       check=True, creationflags=BELOW_NORMAL)
        outs.append(REL / f"{APP_NAME}-{VERSION}-setup.exe")
    else:
        print("\n(Inno Setup 6 is not installed - only the zip was made. Install it from jrsoftware.org to also get setup.exe)")

    step("done")
    sums = REL / f"{APP_NAME}-{VERSION}-SHA256.txt"
    lines = []
    for f in outs:
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{h}  {f.name}")
        print(f"{f.name}  {f.stat().st_size / 1e6:.1f} MB  sha256 {h}")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
