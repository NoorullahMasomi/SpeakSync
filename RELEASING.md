# Publishing SpeakSync

Every SpeakSync app asks GitHub (`UPDATE_REPO` in `speaksync/__init__.py`) once every 12 hours,
and at each start, whether a newer **Release** exists. If yes, a green **"New version … Get it"**
box shows at the top; "Get it" opens the download page. So: **a new GitHub Release = everyone is told.**

## One time only

1. Sign in at https://github.com. Check your user name (top right). If it is **not** `Noorullahmasomi`,
   change `UPDATE_REPO` in `speaksync/__init__.py` (and the links in `README.md`, `docs/READ_ME_FIRST.txt`,
   `installer/SpeakSync.iss`) before you build.
2. Make the repository: https://github.com/new → name **SpeakSync** → **Public** → do not add a README
   (we have one) → *Create repository*.
3. Send the code (in a terminal in `D:\SpeakSync`):
   ```
   git remote add origin https://github.com/Noorullahmasomi/SpeakSync.git
   git push -u origin main
   ```
4. Make a token for publishing: https://github.com/settings/tokens?type=beta → *Generate new token* →
   *Only select repositories* → **SpeakSync** → *Repository permissions* → **Contents: Read and write** →
   *Generate*. Keep it in your password manager. Never put it in a file or a chat.
5. (Optional, nicer for users) install **Inno Setup 6** (free, https://jrsoftware.org/isdl.php).
   Then the build also makes `SpeakSync-<version>-setup.exe` with Start-menu and desktop shortcuts.

## Every new version

1. Change the number in `speaksync/__init__.py` → `VERSION = "1.0.1"`.
2. Write what is new at the top of `CHANGELOG.md` under `## 1.0.1`.
3. Test: `.venv\Scripts\python -m unittest discover -s tests`
4. Build: `.venv\Scripts\python tools\build.py` → files in `release\`.
   Try `dist\SpeakSync\SpeakSync.exe` once.
5. Save and send the code:
   ```
   git commit -am "Release 1.0.1"
   git push
   ```
6. Publish: `.venv\Scripts\python tools\publish.py` → paste your token when it asks (it stays hidden).

   Or by hand: on GitHub → *Releases* → *Draft a new release* → tag `v1.0.1` → title `SpeakSync 1.0.1`
   → paste the CHANGELOG text → drag the files from `release\` → *Publish release*.

Version numbers: `1.0.1` small fix · `1.1.0` new feature · `2.0.0` big change. The tag must start with `v`.

## Windows "protected your PC" message
New free apps are not yet known to Windows SmartScreen, so people see "Windows protected your PC" →
*More info* → *Run anyway*. The message goes away as more people download the app. A code-signing
certificate removes it at once (it costs money each year); you can add one later without changing anything else.
