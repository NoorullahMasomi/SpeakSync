"""'Is there a new version?' - asks GitHub Releases. Sends nothing about the user, only the app version."""
from __future__ import annotations

import json
import re
import time
import urllib.request

from . import APP_NAME, UPDATE_REPO, VERSION

CHECK_EVERY = 12 * 3600


def _ver(tag: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def is_newer(latest: str, current: str = VERSION) -> bool:
    return _ver(latest) > _ver(current)


def fetch(timeout: float = 6.0) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
        headers={"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:          # noqa: S310 - fixed https address
        rel = json.loads(r.read().decode("utf-8"))
    tag = rel.get("tag_name") or ""
    assets = rel.get("assets") or []
    pick = next((a for a in assets if a.get("name", "").lower().endswith((".exe", ".zip"))), None)
    return {
        "latest": tag.lstrip("vV"),
        "newer": is_newer(tag),
        "page": rel.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases/latest",
        "download": pick.get("browser_download_url") if pick else "",
        "notes": (rel.get("body") or "")[:3000],
        "published": rel.get("published_at") or "",
    }


def check(settings: dict, force: bool = False) -> dict:
    """Uses the saved answer when it is fresh. Never raises: no internet = no message."""
    cached = settings.get("update") or {}
    if not force and cached and time.time() - cached.get("checked", 0) < CHECK_EVERY:
        cached["newer"] = is_newer(cached.get("latest", ""))           # the app may have been updated
        return cached
    try:
        info = fetch()
        info["checked"] = time.time()
        info["ok"] = True
    except Exception as e:                                              # noqa: BLE001
        info = {**cached, "ok": False, "error": str(e)[:200], "checked": time.time() if force else cached.get("checked", 0)}
        info["newer"] = is_newer(info.get("latest", ""))
    settings["update"] = info
    return info
