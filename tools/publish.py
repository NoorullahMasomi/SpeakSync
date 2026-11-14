"""Publish a new version on GitHub Releases - every SpeakSync app then shows "New version ... Get it".

    .venv\\Scripts\\python tools\\publish.py            (after tools\\build.py)

It asks for a GitHub token in YOUR terminal (it is never saved and never shown). Make one at
https://github.com/settings/tokens?type=beta  ->  only this repository  ->  "Contents: Read and write".

What it does:
  1. checks that the code is committed and pushed (the release must match the public code)
  2. creates the release  v<VERSION>  with the text of that version from CHANGELOG.md
  3. uploads release/SpeakSync-<VERSION>-windows.zip (+ setup.exe and SHA256 file when they exist)
"""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from speaksync import APP_NAME, UPDATE_REPO, VERSION  # noqa: E402

API = f"https://api.github.com/repos/{UPDATE_REPO}"


def call(method: str, url: str, token: str, data: bytes | None = None, ctype: str = "application/json") -> dict:
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME}-publisher", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:            # noqa: S310 - fixed GitHub address
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"GitHub said {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from e


def notes() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(VERSION)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    body = m.group(1).strip() if m else "New version."
    return body + "\n\n**Download:** `SpeakSync-" + VERSION + "-windows.zip` - unzip it and double-click SpeakSync.exe."


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main() -> None:
    files = [ROOT / "release" / f"{APP_NAME}-{VERSION}-windows.zip"]
    if not files[0].exists():
        raise SystemExit(f"{files[0].name} is missing. Run tools\\build.py first.")
    for extra in (f"{APP_NAME}-{VERSION}-setup.exe", f"{APP_NAME}-{VERSION}-SHA256.txt"):
        if (ROOT / "release" / extra).exists():
            files.append(ROOT / "release" / extra)
    if git("status", "--porcelain"):
        raise SystemExit("There are changes that are not committed. Commit them first.")
    git("fetch", "--quiet")
    if git("rev-parse", "HEAD") != git("rev-parse", "@{u}"):
        raise SystemExit("Your commits are not pushed to GitHub yet. Run: git push")

    print(f"Publishing {APP_NAME} {VERSION} to https://github.com/{UPDATE_REPO}")
    for f in files:
        print(f"   {f.name}  {f.stat().st_size / 1e6:.1f} MB")
    raw = os.environ.get("SPEAKSYNC_GH_TOKEN") or getpass.getpass("GitHub token (hidden): ")
    # a paste can bring hidden characters (terminal paste marks, spaces, line ends) - a token has only these:
    token = re.sub(r"\x1b\[20[01]~", "", raw)
    token = re.sub(r"[^A-Za-z0-9_]", "", token)
    if not token:
        raise SystemExit("No token.")
    if not token.startswith(("ghp_", "github_pat_")):
        print("Note: GitHub tokens start with ghp_ or github_pat_ - check that you copied the whole token.")
    print(f"Token read: {len(token)} characters.")
    rel = call("POST", f"{API}/releases", token, json.dumps({
        "tag_name": f"v{VERSION}", "target_commitish": git("rev-parse", "HEAD"),
        "name": f"{APP_NAME} {VERSION}", "body": notes(), "draft": False, "prerelease": False}).encode("utf-8"))
    upload = rel["upload_url"].split("{")[0]
    for f in files:
        ctype = "application/zip" if f.suffix == ".zip" else "text/plain" if f.suffix == ".txt" else "application/octet-stream"
        print(f"uploading {f.name} ...", flush=True)
        call("POST", f"{upload}?name={f.name}", token, f.read_bytes(), ctype)
    print(f"\nDone: {rel['html_url']}\nEvery SpeakSync app will show 'New version {VERSION}' within 12 hours (or at its next start).")


if __name__ == "__main__":
    main()
