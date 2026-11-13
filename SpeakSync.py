"""Start SpeakSync.   python SpeakSync.py   (the installed app runs this same file)"""
import sys

from speaksync.app import log, main

if __name__ == "__main__":
    try:
        main()
    except Exception:                       # noqa: BLE001 - write the reason where the user can send it to us
        import traceback
        log("CRASH " + traceback.format_exc())
        if not getattr(sys, "frozen", False):
            raise
