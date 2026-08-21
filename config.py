# -*- coding: utf-8 -*-
"""Configuration module for RTS Monitoring Bot & Automation."""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

# Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID", "").strip()
# Supergroup IDs are -100xxxxxxxxxx. Accept both -3974060856 and -1003974060856.

# OpenRouter Settings
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3.7-flash").strip()
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# India Post IT 2.0 Portal Settings
IT20_USERNAME = os.getenv("IT20_USERNAME", "").strip()
IT20_PASSWORD = os.getenv("IT20_PASSWORD", "").strip()
IT20_BASE_URL = os.getenv(
    "IT20_BASE_URL",
    "https://app.indiapost.gov.in/employeeportal/home"
).strip()
IT20_TRACK_URL = os.getenv(
    "IT20_TRACK_URL",
    "https://app.indiapost.gov.in/tracking/track/article"
).strip()
IT20_OTP_TIMEOUT_SEC = int(os.getenv("IT20_OTP_TIMEOUT_SEC", "180"))
IT20_NAV_TIMEOUT_MS = int(os.getenv("IT20_NAV_TIMEOUT_MS", "25000"))
IT20_NAV_RETRIES = int(os.getenv("IT20_NAV_RETRIES", "3"))
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Directories
DOWNLOADS_DIR = BASE_DIR / "temp_downloads"
REPORTS_DIR = BASE_DIR / "Updated report"
DOWNLOADS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
