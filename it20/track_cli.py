# -*- coding: utf-8 -*-
"""
CLI entry for IT 2.0 tracking.

Examples:
  python -m it20.track_cli --smoke-login
  python -m it20.track_cli --excel "Updated report\\RTS_2026.08.04_Extracted.xlsx"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from it20.article_utils import is_valid_article_no, normalize_article_no, looks_like_portal_invalid
from it20.browser import IT20Session, load_config, login_with_otp, open_article_tracking, smoke_login, start_session, track_article
from it20.excel_io import ensure_tracking_headers, load_parcel_rows, update_row_tracking


def run_tracking(excel_path: Path, headless: bool = False) -> int:
    excel_path = excel_path.resolve()
    if not excel_path.exists():
        print(f"Excel not found: {excel_path}")
        return 1

    cfg = load_config()
    max_retries = cfg["max_retries"]

    ensure_tracking_headers(excel_path)
    rows = load_parcel_rows(excel_path)
    if not rows:
        print("No parcel rows found in Excel.")
        return 1

    print(f"Loaded {len(rows)} parcel rows from {excel_path.name}")
    print("Starting IT 2.0 browser (fresh profile)…")
    print("Excel: Col C = Destination SO | Col 'IT 2.0 remark' = return/delivery remark")

    session: IT20Session | None = None
    try:
        session = start_session(headless=headless)
        login_with_otp(session)
        open_article_tracking(session)

        ok_n = fail_n = 0
        for i, row in enumerate(rows, start=1):
            article = normalize_article_no(row["article"])
            print(f"\n[{i}/{len(rows)}] SL={row['sl']}  Article={article}")

            if not is_valid_article_no(article):
                print("  SKIP: article does not end with IN / invalid format")
                update_row_tracking(
                    excel_path,
                    row["row"],
                    article=article,
                    status="invalid_format",
                    it20_remark="–",
                    tracked_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                )
                fail_n += 1
                continue

            attempt = 0
            result = None
            while attempt <= max_retries:
                attempt += 1
                result = track_article(session, article)
                if result.ok:
                    break
                if result.invalid_article or looks_like_portal_invalid(
                    (result.error or "") + (result.raw_text or "")
                ):
                    print(
                        f"  Portal rejected article (attempt {attempt}/{max_retries + 1}). "
                        "Re-read source image (vision) and fix article_no, then re-run."
                    )
                    update_row_tracking(
                        excel_path,
                        row["row"],
                        status=f"needs_reread_attempt_{attempt}",
                        it20_remark=result.error or "–",
                        tracked_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                    )
                    break
                print(f"  Track failed: {result.error}")
                break

            if result and result.ok:
                update_row_tracking(
                    excel_path,
                    row["row"],
                    office=result.office,
                    article=result.article,
                    it20_remark=result.it20_remark,
                    status=result.status,
                    tracked_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                )
                ok_n += 1
            else:
                fail_n += 1

        print(f"\nDone. ok={ok_n} fail/pending={fail_n}")
        print(f"Excel updated: {excel_path}")
        return 0
    finally:
        if session:
            session.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="India Post IT 2.0 tracking for RTS Excel")
    p.add_argument("--excel", type=str, help="Path to RTS extracted Excel")
    p.add_argument("--smoke-login", action="store_true", help="Test login + TOTP + open Track page")
    p.add_argument("--headless", action="store_true", help="Headless (not recommended for TOTP)")
    args = p.parse_args(argv)

    if args.smoke_login:
        smoke_login(headless=args.headless)
        return 0
    if not args.excel:
        p.print_help()
        print("\nProvide --excel or --smoke-login")
        return 2
    return run_tracking(Path(args.excel), headless=args.headless)


if __name__ == "__main__":
    raise SystemExit(main())
