# -*- coding: utf-8 -*-
"""
Playwright browser session for India Post IT 2.0.

Flow (Sample Video runbook):
  employeeportal → Employee ID + Password → Sign In
  → Enter TOTP Code (6-digit APT TOTP app) → Verify & Login
  → Home → Track and Trace → Article Tracking
  → enter article → Track
  → Col C = Booking Details.Destination (e.g. SIKANDRA SO)
  → Col "IT 2.0 remark" = Remarks on "Item Returned to Sender"
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

TRACK_URL = "https://app.indiapost.gov.in/tracking/track/article"
HOME_URL = "https://app.indiapost.gov.in/employeeportal/home"

SELECTORS = {
    "username": 'input#username, input[name="username"]',
    "password": 'input#password, input[name="password"]',
    "submit": 'input#kc-login, input[name="login"], button[type="submit"], input[type="submit"]',
}


@dataclass
class TrackResult:
    article: str
    ok: bool
    office: str = "–"  # Destination SO → Excel Col C
    it20_remark: str = "–"  # delivery/return remarks → "IT 2.0 remark"
    status: str = "–"
    raw_text: str = ""
    error: str = ""
    invalid_article: bool = False
    events: list[dict[str, str]] = field(default_factory=list)


@dataclass
class IT20Session:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    username: str
    password: str
    base_url: str
    otp_timeout_sec: int = 30
    logged_in: bool = False
    notes: list[str] = field(default_factory=list)

    def close(self) -> None:
        for closer in (self.context.close, self.browser.close, self.playwright.stop):
            try:
                closer()
            except Exception:
                pass


def load_config() -> dict[str, Any]:
    load_dotenv(ENV_PATH)
    user = os.getenv("IT20_USERNAME", "").strip()
    pwd = os.getenv("IT20_PASSWORD", "").strip()
    base = os.getenv("IT20_BASE_URL", "https://app.indiapost.gov.in/employeeportal/").strip()
    otp_timeout = int(os.getenv("IT20_OTP_TIMEOUT_SEC", "30"))
    max_retries = int(os.getenv("IT20_MAX_RETRIES", "2"))
    if not user or not pwd:
        raise RuntimeError(
            f"Missing IT20_USERNAME / IT20_PASSWORD in {ENV_PATH}. "
            "Copy .env.example → .env and fill credentials."
        )
    return {
        "username": user,
        "password": pwd,
        "base_url": base,
        "otp_timeout_sec": otp_timeout,
        "max_retries": max_retries,
    }


def prompt_totp_fast(timeout_sec: int = 30) -> str:
    """Block for 6-digit TOTP from APT app. Must be fast (~30s).

    Agent rule: when this runs, do NOTHING else until code is submitted
    (no parallel tools / Excel / vision). Fill within 4–5s of receiving digits.
    """
    print()
    print("=" * 60)
    print("  IT 2.0 TOTP REQUIRED (APT TOTP app) — ~{}s window!".format(timeout_sec))
    print("  Type / paste the 6-digit code and press Enter IMMEDIATELY.")
    print("  AGENT: stop all other tasks until Verify & Login completes.")
    print("=" * 60)
    sys.stdout.flush()
    sys.stderr.flush()
    start = time.time()
    code = input("TOTP > ").strip().replace(" ", "")
    elapsed = time.time() - start
    print(f"  TOTP received in {elapsed:.1f}s — submitting NOW…", flush=True)
    if not code:
        raise RuntimeError("Empty TOTP received.")
    if not re.fullmatch(r"\d{6}", code):
        print(f"  WARNING: expected 6 digits, got {len(code)} chars: {code!r}")
    if elapsed > timeout_sec:
        print(f"  WARNING: took {elapsed:.1f}s — code may be expired.")
    return code


def wait_totp_from_file(
    totp_path: Path | None = None,
    status_path: Path | None = None,
    poll_sec: float = 0.15,
    max_wait_sec: float = 90.0,
) -> str:
    """Poll a small file for 6-digit TOTP; return the instant it appears.

    Used by agent runs: user/agent writes digits to file; we submit ASAP.
    Poll interval is short so submit happens within ~1s of file write.
    """
    totp_path = totp_path or (ROOT / "Updated report" / "totp_code.txt")
    status_path = status_path or (ROOT / "Updated report" / "smoke_status.txt")
    if totp_path.exists():
        try:
            totp_path.unlink()
        except Exception:
            pass
    status_path.write_text("WAITING_TOTP", encoding="utf-8")
    print("=== WAITING_TOTP === send 6 digits NOW (file or chat)", flush=True)
    print("AGENT: only job until login OK = inject TOTP in 4–5s", flush=True)
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        if totp_path.exists():
            try:
                raw = totp_path.read_text(encoding="utf-8")
            except Exception:
                time.sleep(poll_sec)
                continue
            code = re.sub(r"\D", "", raw.lstrip("\ufeff"))
            if len(code) >= 6:
                try:
                    totp_path.unlink()
                except Exception:
                    pass
                print(f"TOTP file read — submitting immediately ({code[:2]}****)", flush=True)
                return code[:6]
        time.sleep(poll_sec)
    raise RuntimeError("TOTP timeout — no code file")


def start_session(headless: bool = False) -> IT20Session:
    cfg = load_config()
    pw = sync_playwright().start()
    browser = None
    last_err: Exception | None = None
    for channel in ("chrome", None):
        try:
            launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            }
            if channel:
                launch_kwargs["channel"] = channel
            browser = pw.chromium.launch(**launch_kwargs)
            print(f"Browser launched (channel={channel or 'chromium'})")
            break
        except Exception as e:
            last_err = e
    if browser is None:
        pw.stop()
        raise RuntimeError(f"Could not launch Chrome/Chromium: {last_err}")

    context = browser.new_context(
        viewport={"width": 1400, "height": 900},
        locale="en-IN",
        ignore_https_errors=True,
    )
    page = context.new_page()
    page.set_default_timeout(25000)

    return IT20Session(
        playwright=pw,
        browser=browser,
        context=context,
        page=page,
        username=cfg["username"],
        password=cfg["password"],
        base_url=cfg["base_url"],
        otp_timeout_sec=cfg["otp_timeout_sec"],
    )


def _first_visible(page: Page, selector: str, timeout: float = 8000):
    parts = [s.strip() for s in selector.split(",")]
    deadline = time.time() + timeout / 1000.0
    last_err = None
    while time.time() < deadline:
        for part in parts:
            loc = page.locator(part).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception as e:
                last_err = e
        page.wait_for_timeout(150)
    raise RuntimeError(f"No visible element for: {selector} ({last_err})")


def _click_continue_if_present(page: Page, rounds: int = 3) -> bool:
    """Click Continue / Next if shown between password and TOTP (or multi-step login)."""
    clicked_any = False
    for _ in range(rounds):
        # If TOTP already visible, stop
        if _totp_ui_visible(page):
            return clicked_any
        clicked = False
        for pattern in (
            r"^continue$",
            r"^next$",
            r"continue\s*&?\s*next",
            r"^proceed$",
        ):
            try:
                btn = page.get_by_role("button", name=re.compile(pattern, re.I))
                if btn.count() and btn.first.is_visible():
                    print(f"Clicking button: {btn.first.inner_text()!r}")
                    btn.first.click()
                    page.wait_for_timeout(1200)
                    clicked = True
                    clicked_any = True
                    break
            except Exception:
                pass
        if not clicked:
            try:
                # Keycloak sometimes uses input submit with value Continue
                sub = page.locator(
                    'input[type="submit"][value*="Continue" i], '
                    'input[type="submit"][value*="Next" i], '
                    'button:has-text("Continue"), button:has-text("Next")'
                )
                if sub.count() and sub.first.is_visible():
                    print("Clicking Continue/Next submit…")
                    sub.first.click()
                    page.wait_for_timeout(1200)
                    clicked = True
                    clicked_any = True
            except Exception:
                pass
        if not clicked:
            break
    return clicked_any


def _totp_ui_visible(page: Page) -> bool:
    """True only on the real TOTP entry page (not login news mentioning TOTP)."""
    # Strong signals: heading / button from sample video
    try:
        if page.get_by_role("heading", name=re.compile(r"enter\s+totp", re.I)).count():
            if page.get_by_role("heading", name=re.compile(r"enter\s+totp", re.I)).first.is_visible():
                return True
    except Exception:
        pass
    try:
        if page.get_by_text(re.compile(r"^\s*Enter TOTP Code\s*$", re.I)).count():
            loc = page.get_by_text(re.compile(r"Enter TOTP Code", re.I)).first
            if loc.is_visible():
                return True
    except Exception:
        pass
    try:
        v = page.get_by_role("button", name=re.compile(r"verify\s*&?\s*login", re.I))
        if v.count() and v.first.is_visible():
            return True
    except Exception:
        pass
    # 6 single-digit boxes (and password field gone)
    try:
        boxes = page.locator('input[maxlength="1"]:visible')
        if boxes.count() >= 6:
            pwd = page.locator('input#password, input[type="password"]')
            if pwd.count() == 0 or not pwd.first.is_visible():
                return True
    except Exception:
        pass
    return False


def _wait_for_totp_screen(page: Page, timeout_ms: int = 20000) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        # Intermediate Continue may appear while waiting
        if not _totp_ui_visible(page):
            _click_continue_if_present(page, rounds=1)
        if _totp_ui_visible(page):
            return True
        page.wait_for_timeout(400)
    return _totp_ui_visible(page)


def _fill_totp_boxes(page: Page, code: str) -> None:
    """Fill 6-digit TOTP (separate boxes or single field)."""
    code = re.sub(r"\D", "", code)[:6]
    if len(code) != 6:
        raise RuntimeError(f"TOTP must be 6 digits, got {code!r}")

    # Collect visible inputs that look like digit boxes
    candidates = page.locator("input:visible")
    digit_boxes = []
    single = None
    try:
        n = candidates.count()
    except Exception:
        n = 0
    for i in range(n):
        el = candidates.nth(i)
        try:
            t = (el.get_attribute("type") or "text").lower()
            if t in ("hidden", "submit", "password", "checkbox", "radio", "button"):
                continue
            ml = el.get_attribute("maxlength") or ""
            name = (el.get_attribute("name") or "").lower()
            autocomplete = (el.get_attribute("autocomplete") or "").lower()
            if ml == "1":
                digit_boxes.append(el)
            elif "otp" in name or "totp" in name or "one-time" in autocomplete:
                single = el
            elif t in ("tel", "number", "text") and ml in ("6", "8", ""):
                # possible single 6-digit field
                if single is None and ml == "6":
                    single = el
        except Exception:
            continue

    print(f"  TOTP UI: digit_boxes={len(digit_boxes)} single={'yes' if single else 'no'}", flush=True)

    if len(digit_boxes) >= 6:
        # Click first box then type all digits (auto-advance common in Keycloak/React)
        digit_boxes[0].click()
        page.keyboard.type(code, delay=40)
        # Also force each box if keyboard auto-advance failed
        for i, ch in enumerate(code):
            try:
                digit_boxes[i].fill(ch)
            except Exception:
                pass
        return

    if single is not None:
        single.click()
        single.fill("")
        single.fill(code)
        return

    # Last resort: click anywhere in OTP area and type
    try:
        page.get_by_text(re.compile(r"TOTP|2-Factor|one.time", re.I)).first.click(timeout=2000)
    except Exception:
        pass
    page.keyboard.type(code, delay=40)


def _is_logged_in_home(page: Page) -> bool:
    """True when IT 2.0 employee home (or tracking) is visible after successful login."""
    url = (page.url or "").lower()
    if "idam" in url or "login-actions" in url or "openid-connect/auth" in url:
        return False
    if re.search(r"employeeportal/(home)?/?$", url) or "/employeeportal/home" in url:
        return True
    if "/tracking/" in url:
        return True
    # UI signals on home
    try:
        if page.get_by_text(re.compile(r"Track and Trace", re.I)).count():
            if page.get_by_text(re.compile(r"Welcome", re.I)).count() or "employeeportal" in url:
                return True
    except Exception:
        pass
    try:
        if page.get_by_role("link", name=re.compile(r"Track and Trace", re.I)).count():
            if "employeeportal" in url:
                return True
    except Exception:
        pass
    return False


def _wait_for_manual_login_home(page: Page, status_path: Path | None = None, timeout_sec: int = 180) -> None:
    """User fills TOTP manually; we only wait until home/tracking is reached."""
    status_path = status_path or (ROOT / "Updated report" / "smoke_status.txt")
    status_path.write_text("WAITING_MANUAL_TOTP", encoding="utf-8")
    print()
    print("=" * 64, flush=True)
    print("  MANUAL TOTP — program will NOT type the code", flush=True)
    print("  1) APT app se 6-digit TOTP Chrome window me type karein", flush=True)
    print("  2) Enter / Verify & Login dabayein", flush=True)
    print("  3) Home page aate hi tracking auto-start hogi", flush=True)
    print(f"  Waiting up to {timeout_sec}s for employeeportal home…", flush=True)
    print("=" * 64, flush=True)

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        # Continue may appear again after partial steps
        if not _totp_ui_visible(page) and not _is_logged_in_home(page):
            _click_continue_if_present(page, rounds=1)
        if _is_logged_in_home(page):
            status_path.write_text("LOGIN_OK " + page.url, encoding="utf-8")
            print(f"Home/login success detected: {page.url}", flush=True)
            return
        # Also accept URL change via wait
        try:
            if re.search(r"employeeportal|tracking", page.url or "", re.I):
                if "idam" not in (page.url or "").lower():
                    # Confirm not still on intermediate login
                    if _is_logged_in_home(page) or "/tracking/" in page.url:
                        status_path.write_text("LOGIN_OK " + page.url, encoding="utf-8")
                        print(f"Login success by URL: {page.url}", flush=True)
                        return
        except Exception:
            pass
        page.wait_for_timeout(400)

    raise RuntimeError(
        f"Manual TOTP timeout ({timeout_sec}s) — home page not detected. URL={page.url}"
    )


def login_with_otp(
    session: IT20Session,
    otp_provider: Callable[[], str] | None = None,
    manual_totp: bool = True,
    manual_timeout_sec: int = 180,
) -> None:
    """Login with Employee ID + password from .env.

    Default: **manual TOTP** — user types OTP in Chrome and presses Enter/Verify.
    Program waits until employeeportal home is detected, then continues.

    Set manual_totp=False and pass otp_provider only for automated experiments.
    """
    page = session.page
    print(f"Opening: {session.base_url}")
    try:
        page.goto(session.base_url, wait_until="domcontentloaded", timeout=90000)
    except Exception as e:
        print(f"goto warn: {e} — retry once…")
        page.goto(session.base_url, wait_until="load", timeout=90000)
    page.wait_for_timeout(2000)

    # Intermediate Sign in / welcome (if present)
    for label in ("Sign in", "Sign In", "Login", "Log in"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() and btn.first.is_visible():
                # If username already on page, don't re-click
                try:
                    _first_visible(page, SELECTORS["username"], timeout=1200)
                    break
                except Exception:
                    print(f"Clicking: {label}")
                    btn.first.click(force=True)
                    page.wait_for_timeout(1500)
                    break
        except Exception:
            pass
        try:
            link = page.get_by_role("link", name=label)
            if link.count() and link.first.is_visible():
                try:
                    _first_visible(page, SELECTORS["username"], timeout=1200)
                    break
                except Exception:
                    print(f"Clicking link: {label}")
                    link.first.click(force=True)
                    page.wait_for_timeout(1500)
                    break
        except Exception:
            pass

    # Wait for username field (portal can be slow)
    print("Waiting for Employee ID field…")
    try:
        page.wait_for_selector(
            "input#username, input[name='username'], input[placeholder*='Employee' i]",
            timeout=45000,
            state="visible",
        )
    except Exception:
        print(f"  selector wait failed; URL={page.url}")
        try:
            page.screenshot(path=str(ROOT / "Updated report" / "smoke_login_no_username.png"))
        except Exception:
            pass

    print("Filling Employee ID…")
    user_box = _first_visible(
        page,
        'input#username, input[name="username"], input[placeholder*="Employee" i], input[placeholder*="Employee ID" i]',
        timeout=20000,
    )
    try:
        user_box.click(timeout=5000, force=True)
    except Exception:
        pass
    user_box.fill(session.username)

    print("Filling password…")
    pass_box = _first_visible(page, SELECTORS["password"], timeout=15000)
    try:
        pass_box.click(timeout=5000, force=True)
    except Exception:
        pass
    pass_box.fill(session.password)

    print("Clicking Sign In…")
    try:
        sign = page.get_by_role("button", name=re.compile(r"sign\s*in", re.I))
        if sign.count() and sign.first.is_visible():
            sign.first.click(force=True, timeout=10000)
        else:
            _first_visible(page, SELECTORS["submit"], timeout=4000).click(force=True)
    except Exception:
        try:
            pass_box.press("Enter")
        except Exception:
            page.keyboard.press("Enter")

    page.wait_for_timeout(1200)

    # Continue before TOTP (if shown)
    print("Looking for Continue (before TOTP)…")
    if _click_continue_if_present(page, rounds=4):
        print("Continue clicked.")
    else:
        print("No Continue button found (may already be on next step).")

    # Already home? (rare)
    if _is_logged_in_home(page):
        print("Already on home after Sign In.")
    else:
        print("Waiting for TOTP screen (or home)…")
        totp_needed = _wait_for_totp_screen(page, timeout_ms=20000)

        if manual_totp or otp_provider is None:
            # --- MANUAL TOTP (default) ---
            if totp_needed:
                print("TOTP page ready — fill code MANUALLY in Chrome.", flush=True)
            else:
                print(
                    "TOTP UI not clearly detected — still waiting for home after your login.",
                    flush=True,
                )
            _wait_for_manual_login_home(
                page,
                status_path=ROOT / "Updated report" / "smoke_status.txt",
                timeout_sec=manual_timeout_sec,
            )
        else:
            # --- Optional automated TOTP (not default) ---
            print("Automated TOTP path (otp_provider)…", flush=True)
            code = otp_provider()
            _fill_totp_boxes(page, code)
            try:
                verify = page.get_by_role(
                    "button", name=re.compile(r"verify\s*&?\s*login|verify", re.I)
                )
                if verify.count() and verify.first.is_visible():
                    verify.first.click(force=True)
                else:
                    page.keyboard.press("Enter")
            except Exception:
                page.keyboard.press("Enter")
            _wait_for_manual_login_home(page, timeout_sec=60)

    session.logged_in = True
    session.notes.append(f"After login URL: {page.url}")
    print(f"Login finished. URL: {page.url}", flush=True)
    if not _is_logged_in_home(page):
        if "idam" in page.url or "login-actions" in page.url or "authenticate" in page.url:
            try:
                page.screenshot(path=str(ROOT / "Updated report" / "smoke_still_on_login.png"))
            except Exception:
                pass
            raise RuntimeError(
                f"Still on login page after wait — login not completed. URL={page.url}"
            )


def open_article_tracking(session: IT20Session) -> None:
    """Navigate to Article Tracking page."""
    page = session.page
    print(f"Opening Article Tracking: {TRACK_URL}")
    page.goto(TRACK_URL, wait_until="domcontentloaded", timeout=60000)
    _wait_loading_gone(page, timeout_ms=30000)
    page.wait_for_timeout(500)

    if "idam" in page.url or "login-actions" in page.url:
        raise RuntimeError("Session not authenticated — still on login/IdAM page.")

    if "track" not in page.url.lower():
        print("Direct URL failed; clicking Track and Trace from home…")
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)
        link = page.get_by_role("link", name=re.compile(r"track\s*and\s*trace", re.I))
        if link.count():
            link.first.click()
        else:
            page.get_by_text(re.compile(r"track\s*and\s*trace", re.I)).first.click()
        _wait_loading_gone(page, timeout_ms=30000)
        page.wait_for_timeout(500)

    try:
        page.get_by_text("Article Tracking", exact=False).first.wait_for(timeout=10000)
    except Exception:
        pass
    print(f"On tracking page: {page.url}")


def _wait_loading_gone(page: Page, timeout_ms: int = 30000) -> None:
    """Wait for IT 2.0 loading spinner to disappear."""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        try:
            spin = page.locator(
                'img[alt="Loading.."], img.animate-spin, [class*="animate-spin"]'
            )
            n = spin.count()
            visible = False
            for i in range(min(n, 5)):
                if spin.nth(i).is_visible():
                    visible = True
                    break
            if not visible:
                return
        except Exception:
            return
        page.wait_for_timeout(200)


def _article_number_input(page: Page):
    """Locate the Article Number field — never the Favourites/Search box."""
    # 1) Accessible label
    loc = page.get_by_label(re.compile(r"article\s*number", re.I))
    if loc.count():
        return loc.first

    # 2) Placeholder
    for sel in (
        'input[placeholder*="Article" i]',
        'input[placeholder*="article number" i]',
        'input[aria-label*="Article" i]',
    ):
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            return loc.first

    # 3) Input near "Article Number" text (same form card)
    try:
        near = page.locator("text=Article Number").locator(
            "xpath=ancestor::div[1]//input[@type='text' or not(@type)]"
        )
        for i in range(min(near.count(), 5)):
            el = near.nth(i)
            if not el.is_visible():
                continue
            ph = (el.get_attribute("placeholder") or "").lower()
            al = (el.get_attribute("aria-label") or "").lower()
            if "search" in ph or "favourites" in ph or "search" in al:
                continue
            return el
    except Exception:
        pass

    # 4) First visible text input that is NOT search/favourites
    inputs = page.locator('input[type="text"], input:not([type])')
    for i in range(min(inputs.count(), 20)):
        el = inputs.nth(i)
        try:
            if not el.is_visible():
                continue
            ph = (el.get_attribute("placeholder") or "").lower()
            al = (el.get_attribute("aria-label") or "").lower()
            name = (el.get_attribute("name") or "").lower()
            if any(x in ph + al + name for x in ("search", "favourites", "menu")):
                continue
            return el
        except Exception:
            continue
    raise RuntimeError("Article Number input not found")


def _looks_like_date(text: str) -> bool:
    """True for values like 03/08/2026, 3-8-26, 03.08.2026 (must never go in Col C)."""
    t = (text or "").strip()
    if not t:
        return False
    if re.fullmatch(r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}", t):
        return True
    if re.fullmatch(r"\d{4}[./\-]\d{1,2}[./\-]\d{1,2}", t):
        return True
    # date with time prefix fragment
    if re.match(r"^\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}\b", t):
        return True
    return False


def _is_delivery_so_name(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or t in ("–", "-", "None", "null"):
        return False
    # Never accept dates / pure numbers as SO
    if _looks_like_date(t):
        return False
    if re.fullmatch(r"\d+", t):
        return False
    if re.fullmatch(r"[\d./\-: ]+", t):  # numeric/date-ish only
        return False
    # Never accept tracking event phrases as office
    low = t.lower()
    bad_phrases = (
        "item returned",
        "item received",
        "item dispatched",
        "item bagged",
        "item delivered",
        "item booked",
        "item kept",
        "taken out",
        "bag received",
        "for enquiry",
        "returned to sender",
        "received at destination",
    )
    if any(p in low for p in bad_phrases):
        return False
    # Typical India Post office names for delivery destination
    if re.search(r"\b(SO|HO|BO|PO|NSH|TMO|RMS)\b", t, re.I):
        # Reject if office token is just a date + SO somehow
        if _looks_like_date(re.sub(r"\b(SO|HO|BO|PO|NSH|TMO|RMS)\b", "", t, flags=re.I).strip()):
            return False
        return True
    # Some destinations are plain place names in booking (still valid SO area)
    # Require at least one letter and no event verbs; short place names only
    if 2 <= len(t) <= 40 and re.match(r"^[A-Za-z][A-Za-z0-9 ./\-]*$", t):
        if not re.search(r"\d{5,}", t) and " " not in t or re.match(
            r"^[A-Za-z][A-Za-z .]{1,35}$", t
        ):
            # Allow multi-word place names like "Fatehpur Sikri" but not long sentences
            words = t.split()
            if 1 <= len(words) <= 4 and not any(
                w.lower() in ("item", "returned", "sender", "delivered", "address")
                for w in words
            ):
                return True
    return False


def _is_clean_rts_remark(text: str) -> bool:
    """Reject office-name fragments mis-read as remarks (BRIDGE SO, Mandi BO)."""
    r = re.sub(r"\s+", " ", (text or "").strip())
    if not r or r in ("–", "-", "Delivered", "delivered"):
        return False
    low = r.lower()
    # Event names are not remarks
    if any(
        p in low
        for p in (
            "item returned",
            "item received",
            "item dispatched",
            "item bagged",
            "item delivered",
            "item booked",
            "item kept",
            "taken out",
            "bag received",
            "for enquiry",
        )
    ):
        # Allow only if it also has a real reason phrase after event noise
        pass
    if re.match(r"^item\s+", low) or re.match(r"^bag\s+", low) or re.match(r"^taken\s+out", low):
        # strip leading event then re-check — if whole string is event, reject
        if not any(
            k in low
            for k in (
                "no such",
                "insufficient",
                "incomplete",
                "refused",
                "left without",
                "not known",
                "unclaimed",
                "shifted",
                "deceased",
                "door locked",
            )
        ):
            return False
    # Pure office-like short tokens are NOT remarks
    if re.fullmatch(
        r"[A-Za-z0-9 ./\-]{0,40}\b(SO|HO|BO|PO|NSH|TMO)\b",
        r,
        re.I,
    ):
        return False
    if r.upper() in ("BRIDGE SO", "MANDI BO", "YAMUNA BRIDGE SO"):
        return False
    # Prefer known RTS phrases
    keys = (
        "no such",
        "insufficient",
        "incomplete",
        "refused",
        "left without",
        "not known",
        "unclaimed",
        "shifted",
        "deceased",
        "door locked",
        "not available",
        "wrong address",
        "no such person",
        "addressee left",
        "insufficient address",
    )
    if any(k in low for k in keys):
        return True
    # Free text remark (not office-shaped, not event-shaped)
    if len(r) >= 10 and not re.search(r"\b(SO|HO|BO|NSH|TMO)\s*$", r, re.I):
        if "item " not in low and "bag " not in low:
            return True
    return False


def _extract_delivery_destination_so(body_text: str, events: list[dict]) -> str:
    """
    Col C rule: SO where article was TO BE DELIVERED.
    1) Booking Details column Destination
    2) Fallback: Office on event 'Item received at Destination'
    """
    office = "–"

    # Isolate booking block (before event timeline)
    booking = body_text
    m_split = re.search(
        r"Booking Details of[^\n]*\n(.*?)(?:Article Tracking of|\bEvent Date\b)",
        body_text,
        re.I | re.S,
    )
    if m_split:
        booking = m_split.group(0)

    # Header tokens in fixed order used by IT 2.0 booking strip
    header_re = re.compile(
        r"(Booked At|Booked On|Dest\.?\s*Pincode|Tariff|Article Type|"
        r"Destination|Dest\.?\s*City|Dest\.?\s*Country)",
        re.I,
    )
    headers = header_re.findall(booking)
    # Normalize header names
    headers_n = [re.sub(r"\s+", " ", h).strip().lower() for h in headers]
    dest_idx = None
    for i, h in enumerate(headers_n):
        if h == "destination":
            dest_idx = i
            break

    if dest_idx is not None:
        # Value row: after last header line, first substantial data line
        # Find line with Article Type value pattern (SP_ / EM / etc.) or pincode
        lines = [ln.strip() for ln in booking.splitlines() if ln.strip()]
        value_line = None
        for ln in lines:
            if header_re.search(ln) and "Booked At" in ln:
                continue
            if re.search(r"\bSP_|EM_|INLAND|DOC\b", ln, re.I) or re.search(
                r"\b\d{6}\b", ln
            ):
                if "Booking Details" in ln:
                    continue
                value_line = ln
                break
        if value_line:
            # Split values — prefer multi-space, else heuristic after Article Type code
            parts = re.split(r"\s{2,}|\t", value_line)
            if len(parts) <= dest_idx:
                # Single-spaced row: capture Destination as token before Dest. City-like region
                m = re.search(
                    r"\b(?:SP_[A-Z0-9_]+|EM_[A-Z0-9_]+|[A-Z]{2}_[A-Z0-9_]+)\s+"
                    r"([A-Za-z0-9][A-Za-z0-9 ./\-]{1,40}?)"
                    r"(?=\s+(?:[A-Z][A-Za-z]+(?:,|\s)+[A-Z]|INDIA|AGRA|UTTAR|DELHI|MADHYA|RAJASTHAN|HARYANA)\b)",
                    value_line,
                    re.I,
                )
                if m and _is_delivery_so_name(m.group(1)):
                    office = re.sub(r"\s+", " ", m.group(1)).strip()
            else:
                cand = parts[dest_idx].strip()
                if _is_delivery_so_name(cand):
                    office = cand

    # Explicit "Destination <value>" when laid out with newline
    if office == "–":
        m = re.search(
            r"(?m)^Destination\s*\n\s*([A-Za-z0-9][A-Za-z0-9 ./\-]{1,50})",
            booking,
            re.I,
        )
        if m and _is_delivery_so_name(m.group(1)):
            office = re.sub(r"\s+", " ", m.group(1)).strip()

    # Token after Article Type code ending with SO/HO/BO
    if office == "–":
        m = re.search(
            r"\b(?:SP_[A-Z0-9_]+|EM_[A-Z0-9_]+)\s+([A-Za-z0-9][A-Za-z0-9 ./\-]*\b(?:SO|HO|BO|PO|NSH))\b",
            booking,
            re.I,
        )
        if m:
            office = re.sub(r"\s+", " ", m.group(1)).strip()

    # Fallback: Item received at Destination → Office column
    if office == "–" or not _is_delivery_so_name(office):
        office = "–"
        for ev in events:
            if "received at destination" in (ev.get("event") or "").lower():
                cand = (ev.get("office") or "").strip()
                if _is_delivery_so_name(cand):
                    office = cand
                    break
        if office == "–":
            m = re.search(
                r"Item received at Destination\s+([A-Za-z][A-Za-z0-9 ./\-]*\b(?:SO|HO|BO|PO|NSH)?)",
                body_text,
                re.I,
            )
            if m and _is_delivery_so_name(m.group(1)):
                office = re.sub(r"\s+", " ", m.group(1)).strip()

    # Final sanitize — never write date into Col C
    if not _is_delivery_so_name(office):
        return "–"
    return office


def _parse_events_from_body(body_text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    # Standard row: date time event office [remark]
    row_re = re.compile(
        r"(?m)^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+"
        r"(Item [A-Za-z()]+(?:\s+[A-Za-z()]+)*|Bag [A-Za-z()]+(?:\s+[A-Za-z()]+)*|"
        r"Taken out for delivery|Item Returned to Sender|Item received at Destination|"
        r"Item Delivered(?:\([^)]*\))?|Item Booked|Item Invoiced to BO|"
        r"Item bagged|Item Dispatched|Item Received)\s+"
        r"([A-Za-z0-9][A-Za-z0-9 ./\-]*)"
        r"(?:\s{2,}|\t)?"
        r"(.*)?$"
    )
    for m in row_re.finditer(body_text):
        events.append(
            {
                "date": m.group(1),
                "time": m.group(2),
                "event": m.group(3).strip(),
                "office": m.group(4).strip(),
                "remarks": (m.group(5) or "").strip(),
            }
        )

    # Also HTML/table cells if present
    return events


def _parse_tracking_page(page: Page, article: str) -> TrackResult:
    """Col C = deliver-to SO (Booking Destination); IT 2.0 remark = RTS remarks only."""
    try:
        page.get_by_text(re.compile(r"Booking Details of", re.I)).first.wait_for(
            timeout=25000
        )
    except Exception:
        body_low = ""
        try:
            body_low = page.inner_text("body").lower()
        except Exception:
            pass
        if re.search(
            r"\binvalid article\b|\bno record found\b|\barticle not found\b|\bno data found\b",
            body_low,
        ):
            return TrackResult(
                article=article,
                ok=False,
                invalid_article=True,
                error="Portal rejected article / no data",
                raw_text=page.inner_text("body")[:2000],
            )
        return TrackResult(
            article=article,
            ok=False,
            error="No Booking Details section appeared",
            raw_text=page.inner_text("body")[:2000],
        )

    _wait_loading_gone(page, timeout_ms=10000)
    page.wait_for_timeout(400)
    body_text = page.inner_text("body")

    # --- Events first (needed for destination fallback + remarks) ---
    events = _parse_events_from_body(body_text)

    # DOM tables / react rows (extra)
    try:
        tables = page.locator("table")
        for ti in range(min(tables.count(), 8)):
            table = tables.nth(ti)
            ttext = table.inner_text()
            if "Event Date" not in ttext and "Item Returned" not in ttext:
                continue
            rows = table.locator("tr")
            for ri in range(rows.count()):
                cells = [c.inner_text().strip() for c in rows.nth(ri).locator("th, td").all()]
                if len(cells) < 4 or cells[0].lower().startswith("event"):
                    continue
                events.append(
                    {
                        "date": cells[0],
                        "time": cells[1] if len(cells) > 1 else "",
                        "event": cells[2] if len(cells) > 2 else "",
                        "office": cells[3] if len(cells) > 3 else "",
                        "remarks": cells[4] if len(cells) > 4 else "",
                    }
                )
    except Exception as e:
        print(f"  Events table parse warn: {e}")

    # Also react-data-table cells: scan text lines for Item Returned
    if not any("returned to sender" in (e.get("event") or "").lower() for e in events):
        m_ret = re.search(
            r"Item Returned to Sender\s+([A-Za-z0-9][A-Za-z0-9 ./\-]*)\s+"
            r"(No such person[^\n]*|Insufficient[^\n]*|Incomplete[^\n]*|"
            r"Addressee[^\n]*|Refused[^\n]*|Unclaimed[^\n]*|[A-Za-z][^\n]{5,100})",
            body_text,
            re.I,
        )
        if m_ret:
            events.append(
                {
                    "event": "Item Returned to Sender",
                    "office": m_ret.group(1).strip(),
                    "remarks": m_ret.group(2).strip(),
                }
            )

    # --- Col C: deliver-to SO only ---
    office = _extract_delivery_destination_so(body_text, events)

    # --- IT 2.0 remark: clean RTS remarks only ---
    it20_remark = "–"
    status = "–"
    for ev in events:
        if "returned to sender" in (ev.get("event") or "").lower():
            status = ev.get("event") or "Item Returned to Sender"
            rem = (ev.get("remarks") or "").strip()
            if _is_clean_rts_remark(rem):
                it20_remark = re.sub(r"\s+", " ", rem)
                break

    if it20_remark == "–":
        for ev in events:
            rem = (ev.get("remarks") or "").strip()
            if _is_clean_rts_remark(rem):
                it20_remark = re.sub(r"\s+", " ", rem)
                status = ev.get("event") or status
                break

    if status == "–" and events:
        # Prefer most recent RTS-ish event name
        for ev in events:
            en = (ev.get("event") or "").lower()
            if "return" in en or "undeliver" in en:
                status = ev.get("event") or status
                break
        if status == "–":
            status = events[0].get("event") or "–"

    ok = office != "–" or it20_remark != "–"
    invalid = False
    if not ok and re.search(
        r"\binvalid article\b|\bno record found\b|\barticle not found\b",
        body_text.lower(),
    ):
        invalid = True

    return TrackResult(
        article=article,
        ok=ok,
        office=office if office else "–",
        it20_remark=it20_remark if it20_remark else "–",
        status=status if status else "–",
        raw_text=body_text[:4000],
        error="" if ok else "Could not parse delivery SO / remark",
        invalid_article=invalid,
        events=events,
    )


def track_article(session: IT20Session, article: str) -> TrackResult:
    """Track one article: Col C = deliver-to Destination SO; IT 2.0 remark = RTS remark."""
    page = session.page
    article = article.strip().upper()

    if "track/article" not in page.url:
        open_article_tracking(session)

    _wait_loading_gone(page, timeout_ms=20000)

    # Fill Article Number (not search box)
    try:
        inp = _article_number_input(page)
        inp.click(timeout=10000)
        inp.fill("")
        inp.fill(article)
        # Ensure value stuck
        page.wait_for_timeout(150)
    except Exception as e:
        # Recover: re-open tracking page once
        try:
            open_article_tracking(session)
            _wait_loading_gone(page, timeout_ms=20000)
            inp = _article_number_input(page)
            inp.click(timeout=10000)
            inp.fill("")
            inp.fill(article)
        except Exception as e2:
            return TrackResult(
                article=article,
                ok=False,
                error=f"Could not fill article input: {e2}",
            )

    # Click Track
    try:
        btn = page.get_by_role("button", name=re.compile(r"^track$", re.I))
        if btn.count() and btn.first.is_visible():
            btn.first.click()
        else:
            page.locator("button:has-text('Track')").first.click()
    except Exception as e:
        return TrackResult(
            article=article,
            ok=False,
            error=f"Could not click Track: {e}",
        )

    _wait_loading_gone(page, timeout_ms=35000)

    # Wait for this article's booking header
    try:
        page.get_by_text(
            re.compile(rf"Booking Details of\s*{re.escape(article)}", re.I)
        ).first.wait_for(timeout=25000)
    except Exception:
        try:
            page.get_by_text(re.compile(r"Booking Details of", re.I)).first.wait_for(
                timeout=10000
            )
        except Exception:
            page.wait_for_timeout(1500)

    result = _parse_tracking_page(page, article)
    print(
        f"  → deliverSO(Col C)={result.office!r} | IT 2.0 remark={result.it20_remark!r} | "
        f"status={result.status!r} ok={result.ok}"
    )
    return result


def smoke_login(headless: bool = False) -> None:
    session = start_session(headless=headless)
    try:
        login_with_otp(session)
        open_article_tracking(session)
        print("\nSmoke login + Track page OK. Browser open 15s…")
        session.page.wait_for_timeout(15000)
    finally:
        session.close()
        print("Browser closed.")
