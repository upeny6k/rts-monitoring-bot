# -*- coding: utf-8 -*-
"""Smoke login + track one article (for manual / agent runs)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from it20.browser import (  # noqa: E402
    open_article_tracking,
    start_session,
    login_with_otp,
    track_article,
)

STATUS_PATH = ROOT / "Updated report" / "smoke_status.txt"
RESULT_PATH = ROOT / "Updated report" / "smoke_track_one_result.json"


def main() -> int:
    article = "JO472221223IN"
    if len(sys.argv) > 1:
        article = sys.argv[1].strip().upper()

    STATUS_PATH.write_text("STARTING", encoding="utf-8")
    session = start_session(headless=False)
    try:
        # Manual TOTP in Chrome browser window
        login_with_otp(session, manual_totp=True, manual_timeout_sec=180)
        print("LOGIN_OK", session.page.url, flush=True)
        STATUS_PATH.write_text("LOGIN_OK " + session.page.url, encoding="utf-8")

        open_article_tracking(session)
        print("TRACK_PAGE_OK", session.page.url, flush=True)
        STATUS_PATH.write_text("TRACK_PAGE_OK " + session.page.url, encoding="utf-8")
        session.page.screenshot(
            path=str(ROOT / "Updated report" / "smoke_track_page.png"), full_page=True
        )

        print(f"Tracking article {article}…", flush=True)
        result = track_article(session, article)
        payload = {
            "article": result.article,
            "ok": result.ok,
            "office_col_c": result.office,
            "it20_remark": result.it20_remark,
            "status": result.status,
            "invalid_article": result.invalid_article,
            "error": result.error,
            "events_count": len(result.events),
            "events_sample": result.events[:8],
        }
        RESULT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print("RESULT", json.dumps(payload, indent=2, ensure_ascii=False), flush=True)
        session.page.screenshot(
            path=str(ROOT / "Updated report" / "smoke_article_result.png"), full_page=True
        )

        print("Keeping browser open 25s for visual check…", flush=True)
        session.page.wait_for_timeout(25000)
        STATUS_PATH.write_text("SMOKE_SUCCESS", encoding="utf-8")
        print("SMOKE_SUCCESS", flush=True)
        return 0 if result.ok else 2
    except Exception as e:
        STATUS_PATH.write_text("SMOKE_FAIL: " + str(e), encoding="utf-8")
        print("SMOKE_FAIL", e, flush=True)
        try:
            session.page.screenshot(
                path=str(ROOT / "Updated report" / "smoke_fail.png"), full_page=True
            )
        except Exception:
            pass
        raise
    finally:
        session.close()
        print("Browser closed.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
