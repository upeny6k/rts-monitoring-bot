# -*- coding: utf-8 -*-
"""Main Telegram Bot for RTS Parcel Monitoring & Automation (Mobile OTP Flow)."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional

IST = ZoneInfo("Asia/Kolkata")

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from excel_generator import build_rts_excel
from tracker import check_portal_reachability, run_it20_tracking
from vision_extractor import (
    OpenRouterQuotaError,
    check_openrouter_quota,
    extract_data_from_image,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("RTSBot")


class RTSWorkSession:
    def __init__(self):
        self.is_active: bool = False
        self.is_processing: bool = False
        self.image_paths: List[Path] = []
        self.session_dir: Optional[Path] = None
        self.otp_future: Optional[asyncio.Future] = None
        self.chat_id: Optional[int] = None

    def start_new(self, chat_id: int):
        self.is_active = True
        self.is_processing = False
        self.image_paths = []
        self.otp_future = None
        self.chat_id = chat_id
        timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        self.session_dir = config.DOWNLOADS_DIR / f"session_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def reset(self):
        self.is_active = False
        self.is_processing = False
        self.image_paths = []
        self.otp_future = None


# Global Session Instance
session = RTSWorkSession()


def is_authorized_chat(chat_id: int) -> bool:
    """Check if message is from the authorized group or testing environment."""
    if not config.TELEGRAM_GROUP_ID:
        return True
    try:
        cfg_id = int(config.TELEGRAM_GROUP_ID)
        return chat_id == cfg_id or str(chat_id).endswith(str(abs(cfg_id)))
    except Exception:
        return str(chat_id) == str(config.TELEGRAM_GROUP_ID)


def _plain_text(text: str) -> str:
    return re.sub(r"[*_`\[\]]", "", text or "")[:3900]


async def safe_send_message(
    bot,
    chat_id: int,
    text: str,
    parse_mode: Optional[str] = "Markdown",
) -> None:
    """Send a Telegram message; fall back to plain text if Markdown parsing fails."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        return
    except Exception as exc:
        logger.warning("Markdown send failed (%s); retrying plain text", exc)
    await bot.send_message(chat_id=chat_id, text=_plain_text(text))


async def send_excel_to_group(
    bot,
    chat_id: int,
    excel_path: Path,
    filename: str,
    caption: str,
) -> None:
    """Upload Excel. Caption Markdown is optional; file still goes if caption parse fails."""
    with open(excel_path, "rb") as doc_file:
        try:
            await bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                filename=filename,
                caption=caption,
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.warning("Excel caption Markdown failed (%s); sending file with plain caption", exc)
            doc_file.seek(0)
            await bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                filename=filename,
                caption=_plain_text(caption),
            )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "👋 **Namaste! RTS Parcel Monitoring Bot is online.**\n\n"
        "📌 **Kaise use karein:**\n"
        "1. Group me type karein: `start today work`\n"
        "2. Saari parcel photos bhejte jayein.\n"
        "3. Photos bhej lene ke baad type karein: `complete`\n"
        "4. Bot AI extraction aur IT 2.0 tracking karke final Excel report bhej dega!\n\n"
        "Commands:\n"
        "• `/status` - Current status check\n"
        "• `/portalcheck` - India Post portal server se reachable hai ya nahi\n"
        "• `/cancel` - Active session cancel karein",
        parse_mode="Markdown"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    if session.is_processing:
        st = "⚙️ Processing in progress (AI Vision / Tracking)..."
    elif session.is_active:
        st = f"🟢 Active session! Received {len(session.image_paths)} photos."
    else:
        st = "⚪ Idle (waiting for `start today work` message)."

    await update.message.reply_text(f"📊 **Bot Status:**\n{st}", parse_mode="Markdown")


async def cmd_portalcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ping India Post employee portal from this Railway replica."""
    await update.message.reply_text("🛰️ India Post portal check chal raha hai...")
    result = await check_portal_reachability()
    region = os.getenv("RAILWAY_REPLICA_REGION") or os.getenv("RAILWAY_REGION") or "unknown"
    if result["ok"]:
        text = (
            "✅ **Portal reachable** from this server.\n"
            f"HTTP `{result.get('status')}` in `{result.get('ms')}ms`\n"
            f"Region: `{region}`"
        )
    else:
        text = (
            "❌ **Portal NOT reachable** from this server — yahi wajah se online tracking fail ho rahi thi.\n"
            f"Error: `{result.get('error') or result.get('status')}`\n"
            f"Time: `{result.get('ms')}ms`\n"
            f"Region: `{region}`\n"
            "Server ko Singapore (asia-southeast1) pe hona chahiye, US East se India Post timeout hota hai."
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any running work session."""
    if session.is_active or session.is_processing:
        session.reset()
        await update.message.reply_text("🛑 Active session has been cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text("ℹ️ Koi active session nahi chal raha hai.", parse_mode="Markdown")


async def handle_photo_or_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect images when session is active."""
    chat_id = update.effective_chat.id
    if not is_authorized_chat(chat_id):
        return

    if not session.is_active:
        return

    if session.is_processing:
        await update.message.reply_text("⚠️ Processing already chal rahi hai, kripya wait karein.")
        return

    # Handle standard photo message
    file_obj = None
    file_name = None

    if update.message.photo:
        best_photo = update.message.photo[-1]
        file_obj = await context.bot.get_file(best_photo.file_id)
        idx = len(session.image_paths) + 1
        file_name = f"image_{idx:03d}_{best_photo.file_unique_id}.jpg"
    elif update.message.document:
        doc = update.message.document
        if doc.mime_type and doc.mime_type.startswith("image/"):
            file_obj = await context.bot.get_file(doc.file_id)
            idx = len(session.image_paths) + 1
            ext = Path(doc.file_name or "img.jpg").suffix or ".jpg"
            file_name = f"image_{idx:03d}_{doc.file_unique_id}{ext}"

    if file_obj and file_name:
        dest_path = session.session_dir / file_name
        await file_obj.download_to_drive(custom_path=dest_path)
        session.image_paths.append(dest_path)
        count = len(session.image_paths)
        if count % 5 == 0 or count == 1:
            await update.message.reply_text(f"📸 Photo #{count} received.")


async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle triggers ('start today work', 'complete', and Mobile OTP code)."""
    chat_id = update.effective_chat.id
    if not is_authorized_chat(chat_id):
        return

    raw_text = (update.message.text or "").strip()
    clean = re.sub(r"\s+", " ", raw_text).lower()

    # 1. Mobile OTP Response Check (if tracker is waiting for OTP)
    if session.otp_future and not session.otp_future.done():
        otp_match = re.search(r"\b\d{6}\b", raw_text)
        if otp_match:
            code = otp_match.group(0)
            session.otp_future.set_result(code)
            await update.message.reply_text(f"⚡ **Mobile OTP received ({code[:2]}****)!** Submitting to portal...", parse_mode="Markdown")
            return

    # 2. Trigger: "start today work"
    if clean in ("start today work", "start work", "start"):
        if session.is_processing:
            await update.message.reply_text("⚠️ Purana task abhi process ho raha hai, kripya complete hone dein.")
            return

        session.start_new(chat_id)
        await update.message.reply_text(
            "🚀 **RTS Work Session Started!**\n\n"
            "Ab aap 1-1 karke ya batch me saari parcel photos send karein.\n"
            "Jab saari photos bhej chuke ho, toh **`complete`** likh kar send karein.",
            parse_mode="Markdown"
        )
        return

    # 3. Trigger: "complete"
    if clean in ("complete", "done", "finish"):
        if not session.is_active:
            await update.message.reply_text("ℹ️ Koi session active nahi hai. Pehle `start today work` likhein.", parse_mode="Markdown")
            return

        if not session.image_paths:
            await update.message.reply_text("⚠️ Koi images receive nahi hui hain. Kripya pehle photos bhejein.", parse_mode="Markdown")
            return

        # Start Processing Pipeline
        session.is_processing = True
        total_imgs = len(session.image_paths)
        await update.message.reply_text(
            f"📥 **{total_imgs} photos received!**\n\n"
            f"🔍 **Step 1:** AI Vision data extraction shuru ho rahi hai (Model: `{config.OPENROUTER_MODEL}`)...\n"
            f"*(Kripya thoda intezaar karein)*",
            parse_mode="Markdown"
        )

        # Background processing task
        asyncio.create_task(run_full_pipeline(update, context))


async def run_full_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vision extract -> Excel to Telegram first -> optional IT 2.0 tracking."""
    chat_id = session.chat_id
    today_str = datetime.now(IST).strftime("%d.%m.%Y")
    bot = context.bot

    try:
        # Step 1: Vision Extraction
        all_records: List[Dict[str, Any]] = []
        vision_errors: List[str] = []
        quota_hit = False
        photos_ok = 0
        total_imgs = len(session.image_paths)

        quota = await check_openrouter_quota()
        if not quota.get("ok"):
            await safe_send_message(
                bot,
                chat_id,
                (
                    "OpenRouter API key credit/limit khatam hai, isliye photos analyse nahi ho sakti.\n"
                    f"{quota.get('error') or ''}\n"
                    "OpenRouter key pe spend cap badhao, phir `start today work` se dobara chalao."
                ),
                parse_mode=None,
            )
            return

        def failed_placeholder(img_path: Path, reason: str) -> Dict[str, Any]:
            return {
                "corner_serial": None,
                "article_no": "–",
                "name": "–",
                "address": "–",
                "mobile": "–",
                "handwritten_remark": reason[:120] or "–",
                "confidence": "low",
                "source_image": img_path.name,
            }

        for idx, img_path in enumerate(session.image_paths, 1):
            if idx == 1 or idx % 10 == 0 or idx == total_imgs:
                await safe_send_message(
                    bot,
                    chat_id,
                    f"🔍 Vision {idx}/{total_imgs} photos...",
                    parse_mode=None,
                )
            try:
                records = await extract_data_from_image(img_path)
                if records:
                    all_records.extend(records)
                    photos_ok += 1
                else:
                    vision_errors.append(f"{img_path.name}: empty extract")
                    all_records.append(failed_placeholder(img_path, "AI empty extract"))
            except OpenRouterQuotaError as e:
                quota_hit = True
                logger.error("OpenRouter quota hit at %s/%s: %s", idx, total_imgs, e)
                leftover = session.image_paths[idx - 1 :]
                for rest in leftover:
                    vision_errors.append(f"{rest.name}: OpenRouter key limit")
                    all_records.append(
                        failed_placeholder(rest, "OpenRouter key limit — not analysed")
                    )
                await safe_send_message(
                    bot,
                    chat_id,
                    (
                        f"OpenRouter credit/limit beech me khatam ho gaya.\n"
                        f"Analyse ho chuki: {photos_ok}/{total_imgs}\n"
                        f"Pending: {len(leftover)} photos Excel me low-confidence rows hain.\n"
                        "Key cap badhane ke baad yahi photos dobara bhejo."
                    ),
                    parse_mode=None,
                )
                break
            except Exception as e:
                logger.error(f"Error analyzing {img_path.name}: {e}")
                vision_errors.append(f"{img_path.name}: {e}")
                all_records.append(failed_placeholder(img_path, f"Vision failed: {e}"[:120]))

        extracted_ok = photos_ok
        total_records = len(all_records)
        if extracted_ok == 0:
            err_tail = ""
            if vision_errors:
                sample = " | ".join(vision_errors[:2])[:500]
                err_tail = f"\n\nLast error: {sample}"
            await safe_send_message(
                bot,
                chat_id,
                (
                    "AI kisi bhi photo se valid parcel data extract nahi kar paya. "
                    "Kripya clear photos dobara bhejein."
                    f"{err_tail}"
                ),
                parse_mode=None,
            )
            return

        if vision_errors and not quota_hit:
            await safe_send_message(
                bot,
                chat_id,
                (
                    f"⚠️ {len(vision_errors)} photo(s) fail hui, {extracted_ok}/{total_imgs} "
                    "photos se data aa gaya. Excel generate ho rahi hai."
                ),
            )

        status_word = "INCOMPLETE" if (quota_hit or vision_errors) else "Complete"
        await safe_send_message(
            bot,
            chat_id,
            (
                f"Step 1 {status_word}: {extracted_ok}/{total_imgs} photos analysed "
                f"({total_records} Excel rows).\n"
                "Ab Excel group me bhej raha hoon..."
            ),
            parse_mode=None,
        )

        # Step 2: Excel FIRST so tracking failures cannot block the daily report.
        output_excel_name = f"RTS_{today_str}_Extracted.xlsx"
        output_excel_path = config.REPORTS_DIR / output_excel_name
        build_rts_excel(all_records, output_excel_path, report_date=today_str)

        caption_status = (
            f"INCOMPLETE — {extracted_ok}/{total_imgs} photos analysed"
            if (quota_hit or vision_errors)
            else "Extraction complete"
        )
        await send_excel_to_group(
            bot,
            chat_id,
            output_excel_path,
            output_excel_name,
            (
                f"📄 **Postal RTS Monitoring Report — {today_str}**\n\n"
                f"📦 **Photos analysed:** {extracted_ok}/{total_imgs}\n"
                f"📦 **Excel rows:** {len(all_records)}\n"
                "⚠️ **IT 2.0 tracking pending** — Office / portal remark columns dash hain\n"
                f"🤖 **Status:** {caption_status}"
            ),
        )

        # Step 3: Optional IT 2.0 tracking. Never let this block the Excel already sent.
        async def otp_request_callback(prompt: str = "") -> str:
            loop = asyncio.get_running_loop()
            session.otp_future = loop.create_future()
            await safe_send_message(
                bot,
                chat_id,
                prompt or (
                    "📱 **IT 2.0 Login: 6-digit OTP/TOTP Required!**\n\n"
                    "APT TOTP app ya registered mobile OTP yahan reply karein."
                ),
            )
            try:
                otp_code = await asyncio.wait_for(
                    session.otp_future, timeout=config.IT20_OTP_TIMEOUT_SEC
                )
                return otp_code
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"OTP timeout ({config.IT20_OTP_TIMEOUT_SEC}s) - Mobile OTP receive nahi hua."
                )
            finally:
                session.otp_future = None

        async def status_update_callback(msg: str):
            try:
                await safe_send_message(bot, chat_id, msg, parse_mode=None)
            except Exception:
                pass

        if quota_hit:
            await safe_send_message(
                bot,
                chat_id,
                "IT 2.0 tracking skip — pehle saari photos ka extraction complete karo.",
                parse_mode=None,
            )
            return

        track_timeout = max(config.IT20_OTP_TIMEOUT_SEC + 90, 240)
        try:
            await safe_send_message(
                bot,
                chat_id,
                "🌐 **Step 3:** India Post IT 2.0 tracking try ho rahi hai "
                "(fail ho to pehle wali Excel hi final maano)...",
            )
            updated_records = await asyncio.wait_for(
                run_it20_tracking(
                    articles_data=all_records,
                    otp_callback=otp_request_callback,
                    status_callback=status_update_callback,
                ),
                timeout=track_timeout,
            )
            build_rts_excel(updated_records, output_excel_path, report_date=today_str)
            await send_excel_to_group(
                bot,
                chat_id,
                output_excel_path,
                output_excel_name,
                (
                    f"📄 **Postal RTS Monitoring Report — {today_str} (IT 2.0 updated)**\n\n"
                    f"📦 **Total Parcels Processed:** {len(updated_records)}\n"
                    "✅ **Destination SO & Remarks:** Updated via IT 2.0\n"
                    "🤖 **Status:** Extraction + tracking complete"
                ),
            )
        except Exception as track_err:
            logger.exception("IT 2.0 tracking failed; extracted Excel already sent")
            await safe_send_message(
                bot,
                chat_id,
                (
                    "⚠️ IT 2.0 online tracking fail / skip. "
                    "Extracted Excel already group me hai "
                    "(Office / IT 2.0 remark columns dash rahenge).\n"
                    f"{str(track_err)[:400]}"
                ),
                parse_mode=None,
            )

    except Exception as e:
        logger.exception("Error in pipeline execution")
        try:
            await safe_send_message(
                bot,
                chat_id,
                f"Error occurred during pipeline: {str(e)[:700]}",
                parse_mode=None,
            )
        except Exception:
            logger.exception("Failed to send pipeline error to Telegram")
    finally:
        session.reset()


def main():
    """Start Telegram Bot application with automatic reconnect on network/conflict issues."""
    import time
    if not config.TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
        return

    print("Starting RTS Telegram Bot (IT 2.0 tracking + OTP/TOTP)...")
    region = os.getenv("RAILWAY_REPLICA_REGION") or os.getenv("RAILWAY_REGION") or "local"
    print(f"Runtime region: {region}")
    while True:
        try:
            app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

            # Register Handlers
            app.add_handler(CommandHandler("start", cmd_start))
            app.add_handler(CommandHandler("status", cmd_status))
            app.add_handler(CommandHandler("cancel", cmd_cancel))
            app.add_handler(CommandHandler("portalcheck", cmd_portalcheck))
            
            app.add_handler(MessageHandler(filters.PHOTO | (filters.Document.IMAGE), handle_photo_or_doc))
            app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_messages))

            print("Bot is polling and ready for commands!")
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            err = str(e)
            # Conflict = another process is already polling this token.
            # Wait longer so we do not start a second overlapping poller.
            delay = 45 if "Conflict" in err else 15
            logger.error(
                "Bot polling encountered error: %s. Retrying cleanly in %s seconds...",
                e,
                delay,
            )
            time.sleep(delay)


if __name__ == "__main__":
    main()
