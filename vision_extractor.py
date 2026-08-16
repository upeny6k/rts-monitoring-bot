# -*- coding: utf-8 -*-
"""Vision Extractor using OpenRouter API (GPT-5.6 Luna / Multimodal AI)."""

import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List
import httpx

import config

SYSTEM_PROMPT = """You are an expert postal data extraction AI specialized in Indian Postal Return-to-Sender (RTS) parcels and envelopes.

TASK:
Analyze the provided parcel/envelope photo and extract structured information into a JSON array of objects (one object per parcel in the photo).

CRITICAL RULES:
1. ARTICLE NUMBER:
   - Must always end with capital letters 'IN' (e.g., EU002821162IN, JG832153662IN).
   - Never use digit one '1N'. If it looks like '1N', 'In', or 'in', normalize it to 'IN'.
   - Strip spaces, asterisks, hyphens.

2. RECIPIENT (TO / ADDRESSEE) DETAILS ONLY:
   - ALWAYS extract the details of the person TO whom the parcel was sent (Addressee).
   - Markers for TO address: 'सेवा में', 'सेवा मे', 'सेवामें', 'To', 'To:', or destination window.
   - DO NOT extract Sender ('प्रेषक', 'From', 'If undelivered return to').
   - Accurately read Hindi (Devanagari) names and address lines.

3. MOBILE NUMBER:
   - Extract the mobile number of the recipient (TO side).
   - If not found or illegible, use '–'.

4. CORNER SERIAL NUMBER:
   - Look for a handwritten or circled serial number at the top corner or near the label (e.g., 1, 2, 3, 15, 39).
   - If present, output as integer. If not present, output null.

5. HANDWRITTEN RTS REMARK:
   - Look for handwritten reason notes on the cover (e.g., 'ताला बंद', 'लेने से मना किया', 'पता गलत', 'बार-बार जाने पर नहीं मिला', 'Door Locked', 'Refused', etc.).
   - Do NOT confuse the corner serial number with the RTS remark.

6. CONFIDENCE:
   - 'high', 'medium', or 'low' based on legibility of the article number and address.

OUTPUT FORMAT:
Return ONLY a valid JSON array of objects. Do not include extra conversational text.
Example:
[
  {
    "corner_serial": 1,
    "article_no": "EU002821162IN",
    "name": "राम कुमार",
    "address": "मकान नं. 12, सिकंदरा, आगरा",
    "mobile": "9876543210",
    "handwritten_remark": "ताला बंद",
    "confidence": "high"
  }
]
"""

def normalize_article_no(raw: str) -> str:
    """Normalize article tracking ID to strict format ending in IN."""
    if not raw:
        return "–"
    clean = re.sub(r"[^A-Za-z0-9]", "", str(raw)).upper()
    if clean.endswith("1N"):
        clean = clean[:-2] + "IN"
    if not clean.endswith("IN") and len(clean) >= 2:
        if clean[-2:] in ("IN", "LN", "TN", "1N"):
            clean = clean[:-2] + "IN"
    return clean if clean else "–"


def image_to_base64_data_uri(image_path: Path) -> str:
    """Read image file and convert to base64 data URI."""
    suffix = image_path.suffix.lower().lstrip(".")
    if suffix == "jpg":
        suffix = "jpeg"
    mime_type = f"image/{suffix}" if suffix in ("jpeg", "png", "webp") else "image/jpeg"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


async def extract_data_from_image(image_path: Path) -> List[Dict[str, Any]]:
    """Send image to OpenRouter Vision API and parse extracted parcel data."""
    if not config.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not set in .env")

    data_uri = image_to_base64_data_uri(image_path)
    
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://railway.app",
        "X-Title": "RTS Postal Monitoring",
        "Content-Type": "application/json"
    }

    payload = {
        "model": config.OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract all Return-to-Sender (RTS) parcel records from this photo according to the system rules. Return strict JSON array."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_uri
                        }
                    }
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 1500
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(config.OPENROUTER_BASE_URL, headers=headers, json=payload)
        response.raise_for_status()
        result_json = response.json()

    raw_text = result_json["choices"][0]["message"]["content"]
    
    # Clean code fences if returned
    clean_text = raw_text.strip()
    if clean_text.startswith("```"):
        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\s*```$", "", clean_text)
    
    try:
        data = json.loads(clean_text)
        if isinstance(data, dict):
            data = [data]
    except Exception as e:
        # Fallback regex extraction of JSON array
        match = re.search(r"\[.*\]", clean_text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
        else:
            raise ValueError(f"Failed to parse JSON from AI response: {raw_text}") from e

    # Post-process records
    records = []
    for item in data:
        art = normalize_article_no(item.get("article_no", ""))
        name = (item.get("name") or "").strip()
        address = (item.get("address") or "").strip()
        combined_address = f"{name}, {address}".strip(" ,-") if (name and address) else (name or address or "–")
        
        rec = {
            "corner_serial": item.get("corner_serial"),
            "article_no": art,
            "name": name or "–",
            "address": combined_address if combined_address else "–",
            "mobile": str(item.get("mobile") or "–").strip(),
            "handwritten_remark": item.get("handwritten_remark") or "–",
            "confidence": item.get("confidence") or "medium",
            "source_image": image_path.name
        }
        records.append(rec)

    return records
