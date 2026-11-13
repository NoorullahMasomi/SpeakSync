# SpeakSync

**Your voice on any video.** Mark where you speak, read your script when the light is green, and get a finished video with subtitles.

Free and open source (MIT). Made by **Noorullah Masomi**.

[Download the newest version](https://github.com/Noorullahmasomi/SpeakSync/releases/latest) — Windows 10 / 11.

## How it works

1. **New project** — choose a video and paste your script. A blank line starts a new part.
   You can write the time in front of a part: `[0:01 - 0:03] Hello and welcome!`
2. **Mark** — play the video, press **M** where you start speaking and **M** again where you stop.
3. **Record** — press **Space**. 🔴 wait · 🟡 3-2-1 get ready · 🟢 read the bright text.
   A bar shows the time left. It stops by itself when you are quiet, and the next part comes.
   **R** = record that part again, **L** = listen.
4. **Make video** — choose where to save. You get an MP4 and an SRT subtitle file.

### Two timing modes
| | |
|---|---|
| **Voice fits the video** | The video does not change. Each recording starts at its mark; a too-long one is played up to 25% faster. For films, clips, ads. |
| **Video waits for me** | When you talk longer than the part, the picture stops at the end of the part until you finish. For lessons, slides, screen recordings. |

### Script format
```
[0:01 - 0:03] Hello and welcome.

[0:05 - 0:12] Today I show you how to ...

A part without a time gets its time when you mark it.
```
SRT subtitle files can be opened too, and every project can be saved back as `.txt` or `.srt`.

## Privacy
Everything stays on your computer. Nothing is uploaded. The only internet use is a daily
"is there a new version?" question to GitHub (it sends only the app version).

## Languages
The app screens are in English and Dari (right to left). To add a language, copy
`speaksync/web/i18n/en.json` to e.g. `ps.json`, translate the words, add it to the language list in
`index.html` and `app.js`, and send a pull request.

## For developers
```
py -3.13 -m venv .venv
.venv\Scripts\pip install pyinstaller imageio-ffmpeg pillow
.venv\Scripts\python SpeakSync.py                       # run from the source
.venv\Scripts\python -m unittest discover -s tests       # tests (makes small test videos)
.venv\Scripts\python tools\build.py                      # Windows app -> release\
```
How it is made: a small Python web server on `127.0.0.1` (a secret key per run, nothing reachable from
outside) + the page in `speaksync/web`, shown in a Microsoft Edge app window. FFmpeg does the video work.
See [RELEASING.md](RELEASING.md) for publishing a new version.

## License
MIT © 2026 Noorullah Masomi. FFmpeg is GPLv3 — see [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).
