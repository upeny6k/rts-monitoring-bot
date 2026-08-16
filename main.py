# -*- coding: utf-8 -*-
"""Main Telegram Bot for RTS Parcel Monitoring & Automation (Mobile OTP Flow)."""

import asyncio
from datetime import datetime
import logging
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional

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
from tracker import run_it20_tracking
from vision_extractor import extract_data_from_image

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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    """Execute AI Vision extraction -> Playwright tracking via Mobile OTP -> Excel upload."""
    chat_id = session.chat_id
    today_str = datetime.now().strftime("%d.%m.%Y")
    
    try:
        # Step 1: Vision Extraction
        all_records: List[Dict[str, Any]] = []
        vision_errors: List[str] = []
        for idx, img_path in enumerate(session.image_paths, 1):
            try:
                records = await extract_data_from_image(img_path)
                all_records.extend(records)
            except Exception as e:
                logger.error(f"Error analyzing {img_path.name}: {e}")
                vision_errors.append(f"{img_path.name}: {e}")

        total_records = len(all_records)
        if total_records == 0:
            err_tail = ""
            if vision_errors:
                sample = "\n".join(vision_errors[:3])
                err_tail = f"\n\nLast error(s):\n`{sample}`"
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ AI kisi bhi photo se valid parcel data extract nahi kar paya. "
                    "Kripya clear photos dobara bhejein."
                    f"{err_tail}"
                ),
                parse_mode="Markdown",
            )
            session.reset()
            return

        if vision_errors:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ {len(vision_errors)} photo(s) fail hui, baaki se data aa gaya.\n"
                    f"`{vision_errors[0][:400]}`"
                ),
                parse_mode="Markdown",
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ **Step 1 Complete:** Total **{total_records}** parcel records extract ho gaye!\n\n"
                 f"🌐 **Step 2:** India Post IT 2.0 portal par login (Mobile OTP) & tracking start ho rahi hai...",
            parse_mode="Markdown"
        )

        # Step 2: IT 2.0 Browser Tracking with Mobile OTP Callback
        async def otp_request_callback() -> str:
            """Prompt Telegram group for Mobile OTP and wait for response."""
            loop = asyncio.get_running_loop()
            session.otp_future = loop.create_future()
            
            await context.bot.send_message(
                chat_id=chat_id,
                text="📱 **IT 2.0 Login: Mobile OTP Code Required!**\n\n"
                     "Registered mobile number par aaya hua **6-digit OTP code** yahan reply karein.\n"
                     "*(Bot 3 minute tak wait kar raha hai...)*",
                parse_mode="Markdown"
            )

            try:
                otp_code = await asyncio.wait_for(session.otp_future, timeout=config.IT20_OTP_TIMEOUT_SEC)
                return otp_code
            except asyncio.TimeoutError:
                raise RuntimeError(f"OTP timeout ({config.IT20_OTP_TIMEOUT_SEC}s) - Mobile OTP receive nahi hua.")
            finally:
                session.otp_future = None

        async def status_update_callback(msg: str):
            """Send status updates during tracking."""
            try:
                await context.bot.send_message(chat_id=chat_id, text=msg)
            except Exception:
                pass

        # Run IT 2.0 Tracking. If browser/login fails, still send Excel with extracted rows.
        tracking_ok = True
        tracking_error = ""
        updated_records = all_records
        try:
            updated_records = await run_it20_tracking(
                articles_data=all_records,
                otp_callback=otp_request_callback,
                status_callback=status_update_callback
            )
        except Exception as track_err:
            tracking_ok = False
            tracking_error = str(track_err)
            logger.exception("IT 2.0 tracking failed; sending extracted Excel only")
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ **IT 2.0 tracking fail ho gayi.** Extracted data se Excel bhej raha hoon "
                    "(Office / IT 2.0 remark columns dash rahenge).\n\n"
                    f"`{tracking_error[:600]}`"
                ),
                parse_mode="Markdown",
            )

        # Step 3: Excel Report Build
        output_excel_name = f"RTS_{today_str}_Extracted.xlsx"
        output_excel_path = config.REPORTS_DIR / output_excel_name
        build_rts_excel(updated_records, output_excel_path, report_date=today_str)

        # Step 4: Upload Excel to Telegram Group
        await context.bot.send_message(
            chat_id=chat_id,
            text="📊 **Step 3 Complete:** Excel Report generate ho gayi hai! Group me upload ki ja rahi hai..."
        )

        status_line = (
            "✅ **Destination SO & Remarks:** Updated via IT 2.0"
            if tracking_ok
            else "⚠️ **IT 2.0 tracking incomplete** — Office / portal remark columns pending"
        )
        with open(output_excel_path, "rb") as doc_file:
            await context.bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                filename=output_excel_name,
                caption=(
                    f"📄 **Postal RTS Monitoring Report — {today_str}**\n\n"
                    f"📦 **Total Parcels Processed:** {len(updated_records)}\n"
                    f"{status_line}\n"
                    f"🤖 **Status:** Extraction complete"
                    + ("" if tracking_ok else " (tracking retry later)")
                ),
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.exception("Error in pipeline execution")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ **Error occurred during pipeline:**\n`{str(e)}`",
            parse_mode="Markdown"
        )
    finally:
        session.reset()


def main():
    """Start Telegram Bot application with automatic reconnect on network/conflict issues."""
    import time
    if not config.TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
        return

    print("Starting RTS Telegram Bot (Mobile OTP Mode)...")
    while True:
        try:
            app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

            # Register Handlers
            app.add_handler(CommandHandler("start", cmd_start))
            app.add_handler(CommandHandler("status", cmd_status))
            app.add_handler(CommandHandler("cancel", cmd_cancel))
            
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
