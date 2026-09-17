# -*- coding: utf-8 -*-
"""Vision Extractor using OpenRouter API (Gemini 3.7 Flash / Multimodal AI)."""

import asyncio
import base64
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from PIL import Image

import config

RETRYABLE_HTTP = {408, 429, 500, 502, 503, 520, 522, 524}
MAX_IMAGE_SIDE = 1600


class OpenRouterQuotaError(RuntimeError):
    """API key credit/spend cap exhausted — remaining photos will also fail."""

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
    """Read image, shrink for vision cost/speed, convert to JPEG data URI."""
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            longest = max(w, h)
            if longest > MAX_IMAGE_SIDE:
                scale = MAX_IMAGE_SIDE / longest
                im = im.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=80, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        suffix = image_path.suffix.lower().lstrip(".")
        if suffix == "jpg":
            suffix = "jpeg"
        mime_type = f"image/{suffix}" if suffix in ("jpeg", "png", "webp") else "image/jpeg"
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"


def _is_quota_error(status_code: int, body: str) -> bool:
    text = (body or "").lower()
    if status_code == 402:
        return True
    if status_code == 403 and any(
        token in text
        for token in ("limit exceeded", "credit", "quota", "insufficient")
    ):
        return True
    return False


async def check_openrouter_quota() -> Dict[str, Any]:
    """Return key spend cap info. remaining=None means unlimited."""
    info: Dict[str, Any] = {"ok": True, "limit": None, "remaining": None, "error": ""}
    if not config.OPENROUTER_API_KEY:
        info["ok"] = False
        info["error"] = "OPENROUTER_API_KEY is not set"
        return info
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            )
            payload = resp.json() if resp.content else {}
            data = payload.get("data") or payload
            remaining = data.get("limit_remaining")
            info["limit"] = data.get("limit")
            info["remaining"] = remaining
            if remaining is not None and float(remaining) <= 0:
                info["ok"] = False
                info["error"] = "OpenRouter API key credit limit exhausted"
    except Exception as exc:
        info["ok"] = False
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _strip_code_fences(raw_text: str) -> str:
    clean_text = (raw_text or "").strip()
    if clean_text.startswith("```"):
        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\s*```$", "", clean_text)
    return clean_text.strip()


def _close_truncated_json(text: str) -> str:
    """Best-effort close of truncated JSON arrays/objects from vision models."""
    s = (text or "").rstrip()
    in_str = False
    escaped = False
    for ch in s:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_str:
            escaped = True
            continue
        if ch == '"':
            in_str = not in_str
    if in_str:
        s += '"'
    s = s.rstrip()
    if s.endswith(","):
        s = s[:-1]
    s += "}" * max(0, s.count("{") - s.count("}"))
    s += "]" * max(0, s.count("[") - s.count("]"))
    return s


def _parse_records_json(raw_text: str) -> List[Any]:
    """Parse vision model JSON, including truncated / fenced replies."""
    clean_text = _strip_code_fences(raw_text)
    attempts = [clean_text]
    match = re.search(r"\[.*\]", clean_text, re.DOTALL)
    if match:
        attempts.append(match.group(0))
    repaired = _close_truncated_json(clean_text)
    if repaired not in attempts:
        attempts.append(repaired)

    data = None
    last_err: Optional[Exception] = None
    for cand in attempts:
        try:
            data = json.loads(cand)
            break
        except Exception as exc:
            last_err = exc

    if data is None:
        objs: List[Any] = []
        for m in re.finditer(r"\{[^{}]+\}", clean_text):
            try:
                obj = json.loads(m.group(0))
            except Exception:
                continue
            if isinstance(obj, dict):
                objs.append(obj)
        if objs:
            data = objs

    if data is None:
        raise ValueError(
            f"Failed to parse JSON from AI response: {raw_text[:800]}"
        ) from last_err

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError(f"AI JSON was not a list/object: {type(data)}")
    return data


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
        # 2500 was truncating longer Hindi addresses mid-JSON (mobile/address cut off).
        "max_tokens": 4096,
    }

    result_json: Optional[Dict[str, Any]] = None
    last_http_err = ""
    for attempt in range(1, 4):
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(config.OPENROUTER_BASE_URL, headers=headers, json=payload)
        body = (response.text or "")[:800]
        if _is_quota_error(response.status_code, body):
            raise OpenRouterQuotaError(
                f"OpenRouter HTTP {response.status_code} for model {config.OPENROUTER_MODEL}: {body}"
            )
        if response.status_code in RETRYABLE_HTTP:
            last_http_err = f"OpenRouter HTTP {response.status_code}: {body}"
            await asyncio.sleep(2 * attempt)
            continue
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenRouter HTTP {response.status_code} for model {config.OPENROUTER_MODEL}: {body}"
            )
        result_json = response.json()
        break

    if result_json is None:
        raise RuntimeError(last_http_err or "OpenRouter request failed after retries")

    choices = result_json.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {str(result_json)[:500]}")

    message = choices[0].get("message") or {}
    raw_text = message.get("content")
    if isinstance(raw_text, list):
        raw_text = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in raw_text
        )
    if not raw_text or not str(raw_text).strip():
        raise RuntimeError(
            f"OpenRouter returned empty content (finish={choices[0].get('finish_reason')}): {str(result_json)[:500]}"
        )
    raw_text = str(raw_text)
    data = _parse_records_json(raw_text)

    # Post-process records
    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
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
