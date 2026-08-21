# -*- coding: utf-8 -*-
"""Playwright async automation for India Post IT 2.0 tracking (OTP / TOTP auth)."""

import asyncio
import logging
import re
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

import config

logger = logging.getLogger("IT20Tracker")
SPECIAL_OFFICES = ["AGRA HO", "FATEHABAD HO", "SANJAY PLACE", "SANJAY PLACE SO"]

OtpCallback = Callable[..., Coroutine[Any, Any, str]]
StatusCallback = Optional[Callable[[str], Coroutine[Any, Any, None]]]


async def check_portal_reachability(timeout_sec: float = 15.0) -> Dict[str, Any]:
    """HTTP preflight to India Post employee portal (no browser)."""
    url = config.IT20_BASE_URL
    result: Dict[str, Any] = {"ok": False, "url": url, "status": None, "error": "", "ms": 0}
    started = asyncio.get_event_loop().time()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_sec,
            follow_redirects=True,
            verify=False,
            headers={"User-Agent": config.CHROME_UA},
        ) as client:
            resp = await client.get(url)
            result["status"] = resp.status_code
            result["ok"] = resp.status_code < 500
            result["final_url"] = str(resp.url)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("IT 2.0 portal preflight failed: %s", result["error"])
    result["ms"] = int((asyncio.get_event_loop().time() - started) * 1000)
    logger.info(
        "IT 2.0 portal preflight ok=%s status=%s %sms error=%s",
        result["ok"],
        result["status"],
        result["ms"],
        result["error"] or "-",
    )
    return result


async def goto_with_retry(page: Page, url: str, attempts: Optional[int] = None) -> None:
    """Navigate with short timeouts and retries. US/EU datacenters often stall on this host."""
    attempts = attempts or config.IT20_NAV_RETRIES
    timeout_ms = config.IT20_NAV_TIMEOUT_MS
    last_err: Optional[Exception] = None
    for i in range(1, attempts + 1):
        try:
            await page.goto(url, wait_until="commit", timeout=timeout_ms)
            return
        except Exception as exc:
            last_err = exc
            logger.warning("goto attempt %s/%s failed for %s: %s", i, attempts, url, exc)
            await asyncio.sleep(1.2 * i)
    raise RuntimeError(
        f"India Post portal open nahi ho paya ({url}). "
        f"{attempts} attempts, {timeout_ms}ms each. Last error: {last_err}"
    )


async def _call_otp(otp_callback: OtpCallback, prompt: str) -> str:
    try:
        return await otp_callback(prompt)
    except TypeError:
        return await otp_callback()


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def is_destination_office(text: str) -> bool:
    """Identify if text represents destination delivery office (ending in SO or special HO)."""
    t = clean_text(text).upper()
    if not t or t in ("–", "-", "NONE", "NULL"):
        return False
    # Reject dates or timestamps
    if re.search(r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}", t):
        return False
    # Check special offices
    for spec in SPECIAL_OFFICES:
        if spec in t:
            return True
    # Check SO ending or token
    if re.search(r"\b[A-Z0-9 ./\-]+\s+SO\b", t) or t.endswith(" SO"):
        # Reject event phrases
        bad_words = ["ITEM", "BAG", "RETURNED", "RECEIVED", "DISPATCHED", "DELIVERED", "ENQUIRY"]
        if not any(w in t for w in bad_words):
            return True
    return False


def is_clean_rts_remark(text: str) -> bool:
    """Identify genuine RTS reason remark from tracking portal."""
    r = clean_text(text)
    if not r or r in ("–", "-", "Delivered", "delivered"):
        return False
    low = r.lower()
    known_reasons = (
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
        "lock",
        "absent",
    )
    if any(k in low for k in known_reasons):
        return True
    # If not containing event words and reasonably long
    if len(r) >= 8 and not any(w in low for w in ["item returned", "item dispatched", "item received", "bag"]):
        if not r.upper().endswith(" SO") and not r.upper().endswith(" HO"):
            return True
    return False


async def wait_loading_gone(page: Page, timeout_ms: int = 30000) -> None:
    """Wait for loading spinner to disappear."""
    deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000.0)
    while asyncio.get_event_loop().time() < deadline:
        try:
            spin = page.locator('img[alt="Loading.."], img.animate-spin, [class*="animate-spin"]')
            count = await spin.count()
            visible = False
            for i in range(min(count, 3)):
                if await spin.nth(i).is_visible():
                    visible = True
                    break
            if not visible:
                return
        except Exception:
            return
        await asyncio.sleep(0.3)


async def perform_login(
    page: Page,
    otp_callback: OtpCallback,
    status_callback: StatusCallback = None
) -> None:
    """Credentials → Mobile OTP or TOTP → Verify & Login → home."""
    if status_callback:
        await status_callback("🌐 Opening India Post Login Portal...")

    await goto_with_retry(page, config.IT20_BASE_URL)
    await asyncio.sleep(2)
    await wait_loading_gone(page)

    if status_callback:
        await status_callback("🔑 Entering Employee ID and Password...")

    user_input = page.locator('input#username, input[name="username"], input[placeholder*="Employee" i]').first
    await user_input.wait_for(state="visible", timeout=30000)
    await user_input.fill(config.IT20_USERNAME)

    pass_input = page.locator('input#password, input[name="password"]').first
    await pass_input.fill(config.IT20_PASSWORD)

    sign_in_btn = page.locator('button:has-text("Sign In"), input#kc-login, button[type="submit"], input[type="submit"]').first
    await sign_in_btn.click()
    await asyncio.sleep(2)
    await wait_loading_gone(page)

    body_text = ""
    try:
        body_text = (await page.inner_text("body")).lower()
    except Exception:
        pass

    wants_totp = any(k in body_text for k in ("totp", "authenticator", "2-factor", "two-factor"))
    has_mobile_choice = "mobile otp" in body_text

    if has_mobile_choice and not wants_totp:
        if status_callback:
            await status_callback("📲 Selecting 'Mobile OTP' authentication method...")
        try:
            mobile_otp_radio = page.locator(
                'text=Mobile OTP, input[value*="mobile" i], input[value*="sms" i], label:has-text("Mobile OTP")'
            ).first
            if await mobile_otp_radio.count() > 0 and await mobile_otp_radio.is_visible():
                await mobile_otp_radio.click(force=True)
                await asyncio.sleep(0.8)
            else:
                mobile_label = page.get_by_text("Mobile OTP", exact=False).first
                if await mobile_label.count() > 0 and await mobile_label.is_visible():
                    await mobile_label.click(force=True)
                    await asyncio.sleep(0.8)

            continue_btn = page.locator('button:has-text("Continue"), input[value*="Continue" i]').first
            if await continue_btn.count() > 0 and await continue_btn.is_visible():
                await continue_btn.click()
                await asyncio.sleep(1.5)
                await wait_loading_gone(page)
        except Exception as e:
            logger.warning(f"Auth selection note: {e}")
        try:
            body_text = (await page.inner_text("body")).lower()
        except Exception:
            pass
        wants_totp = any(k in body_text for k in ("totp", "authenticator", "2-factor", "two-factor"))

    if wants_totp:
        otp_prompt = (
            "🔐 **IT 2.0 Login: APT TOTP Code Required!**\n\n"
            "APT TOTP app se **6-digit code** turant yahan reply karein.\n"
            "*(Window ~30 seconds — jaldi bhejein)*"
        )
        status_msg = "🔐 TOTP screen. APT app se 6-digit code chahiye..."
    else:
        otp_prompt = (
            "📱 **IT 2.0 Login: Mobile OTP Code Required!**\n\n"
            "Registered mobile number par aaya hua **6-digit OTP code** yahan reply karein.\n"
            f"*(Bot {config.IT20_OTP_TIMEOUT_SEC} second tak wait kar raha hai...)*"
        )
        status_msg = "📱 OTP screen. 6-digit Mobile OTP chahiye..."

    if status_callback:
        await status_callback(status_msg)

    otp_code = await _call_otp(otp_callback, otp_prompt)
    clean_otp = re.sub(r"\D", "", otp_code).strip()[:6]

    if len(clean_otp) != 6:
        raise ValueError(f"Invalid OTP code received: {otp_code}")

    if status_callback:
        await status_callback(f"⚡ Fast Injecting OTP ({clean_otp[:2]}****) into portal...")

    # Fill 6 digit boxes or single field instantly
    digit_boxes = page.locator('input[maxlength="1"]:visible')
    box_count = await digit_boxes.count()
    if box_count >= 6:
        await digit_boxes.nth(0).click()
        await page.keyboard.type(clean_otp, delay=20)
        # Fallback individual fill
        for i, ch in enumerate(clean_otp):
            try:
                await digit_boxes.nth(i).fill(ch)
            except Exception:
                pass
    else:
        single_input = page.locator('input[name*="otp" i], input[placeholder*="code" i], input[type="text"]:visible').first
        await single_input.fill(clean_otp)

    # Click Verify & Login button
    verify_btn = page.locator('button:has-text("Verify & Login"), button:has-text("Verify"), input[value*="Verify" i]').first
    if await verify_btn.count() > 0 and await verify_btn.is_visible():
        await verify_btn.click()
    else:
        await page.keyboard.press("Enter")

    # Wait for Home / Tracking navigation
    await asyncio.sleep(3)
    await wait_loading_gone(page)

    current_url = page.url.lower()
    if "employeeportal" in current_url or "tracking" in current_url:
        if status_callback:
            await status_callback("✅ Login Successful! Accessing Article Tracking...")
    else:
        # Check if error message is displayed
        err_msg = ""
        try:
            err_el = page.locator('.alert-danger, .error-message, text=Invalid code, text=expired').first
            if await err_el.count() > 0:
                err_msg = await err_el.inner_text()
        except Exception:
            pass
        if err_msg:
            raise RuntimeError(f"Login failed: {err_msg}")


async def track_article(page: Page, article_no: str) -> Dict[str, str]:
    """Search a single article and extract destination SO and RTS remarks."""
    result = {"office": "–", "it20_remark": "–"}
    if not article_no or article_no == "–":
        return result

    # Find Article Number input
    art_input = page.locator('input[placeholder*="Article" i], input#articleNumber, input[name*="article" i]').first
    await art_input.wait_for(state="visible", timeout=15000)
    await art_input.fill("")
    await art_input.fill(article_no)

    # Click Track button
    track_btn = page.locator('button:has-text("Track"), button[type="submit"]:has-text("Track")').first
    await track_btn.click()

    await asyncio.sleep(1)
    await wait_loading_gone(page, timeout_ms=25000)

    # Extract Page Content / Tables
    body_text = await page.inner_text("body")

    # 1. Extract Office Name (SO Destination)
    # A: Check Booking Details block for Destination
    dest_match = re.search(r"Destination\s*:\s*([A-Za-z0-9 ./\-]+)", body_text, re.I)
    if dest_match:
        cand = clean_text(dest_match.group(1))
        if is_destination_office(cand):
            result["office"] = cand

    # B: If not found, look for table rows with SO or special offices
    if result["office"] == "–":
        for spec in SPECIAL_OFFICES:
            if spec in body_text.upper():
                result["office"] = spec
                break

    if result["office"] == "–":
        so_matches = re.findall(r"\b([A-Za-z0-9 ./\-]+\s+SO)\b", body_text, re.I)
        for m in so_matches:
            if is_destination_office(m):
                result["office"] = clean_text(m).upper()
                break

    # 2. Extract First Remark (RTS / Event Remark)
    lines = [clean_text(l) for l in body_text.split("\n") if clean_text(l)]
    for line in lines:
        if is_clean_rts_remark(line):
            result["it20_remark"] = line
            break

    return result


async def run_it20_tracking(
    articles_data: List[Dict[str, Any]],
    otp_callback: OtpCallback,
    status_callback: StatusCallback = None
) -> List[Dict[str, Any]]:
    """Complete tracking pipeline: Launch browser -> Login via OTP/TOTP -> Track each article -> Return updated data."""
    if status_callback:
        await status_callback("🛰️ India Post portal connectivity check ho rahi hai...")

    preflight = await check_portal_reachability()
    if not preflight["ok"]:
        err = preflight.get("error") or f"HTTP {preflight.get('status')}"
        raise RuntimeError(
            "India Post employee portal Railway server se open nahi ho raha "
            f"({preflight.get('url')}, {preflight.get('ms')}ms). {err}\n"
            "Server ko Asia (Singapore) region pe hona chahiye — US East se portal timeout hota hai."
        )

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu",
            ],
        )
        context: BrowserContext = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=config.CHROME_UA,
            ignore_https_errors=True,
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page: Page = await context.new_page()
        page.set_default_timeout(30000)

        try:
            await perform_login(page, otp_callback, status_callback)

            if status_callback:
                await status_callback("🔍 Navigating to Article Tracking Page...")

            await goto_with_retry(page, config.IT20_TRACK_URL)
            await wait_loading_gone(page)
            await asyncio.sleep(1)

            # Track Each Article
            total = len(articles_data)
            for idx, item in enumerate(articles_data, 1):
                art_no = item.get("article_no", "–")
                if status_callback and art_no != "–":
                    await status_callback(f"📍 Tracking [{idx}/{total}]: {art_no}")

                track_res = await track_article(page, art_no)
                item["office"] = track_res["office"]
                item["it20_remark"] = track_res["it20_remark"]
                await asyncio.sleep(0.5)

            if status_callback:
                await status_callback(f"🎉 Tracking completed for all {total} articles!")

        finally:
            await context.close()
            await browser.close()

    return articles_data
