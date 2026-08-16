# -*- coding: utf-8 -*-
"""Article number validation and repair helpers.

Hard rule: every India Post tracking / article number ends with the letters
``IN`` (I + N), never digit-one + N (``1N``), never ``In`` / ``in`` alone as suffix.
"""
from __future__ import annotations

import re

DASH = "–"

# Typical Speed Post / EMS: 2 letters + 9 digits + IN  (13 chars total)
# Some variants may differ slightly; we still require terminal "IN".
_ARTICLE_RE = re.compile(
    r"^([A-Z]{2})(\d{8,11})(IN)$",
    re.IGNORECASE,
)


def normalize_article_no(raw: str | None) -> str:
    """Clean and normalize a vision-read article number.

    Fixes common vision mistakes:
    - trailing ``1N`` → ``IN``
    - lowercase ``in`` → ``IN``
    - spaces / dashes / asterisks stripped
    - OCR letter/digit confusions near the suffix only when safe
    """
    if raw is None:
        return DASH
    s = str(raw).strip()
    if not s or s in ("-", "–", "N/A", "n/a", "NA"):
        return DASH

    # Remove spaces, hyphens, asterisks often seen around barcodes
    s = re.sub(r"[\s\-\*_]+", "", s)
    s = s.upper()

    # Common misread: ends with 1N instead of IN
    if s.endswith("1N") and not s.endswith("IN"):
        s = s[:-2] + "IN"
    # Double-fix: ...I1N / ...11N
    if s.endswith("I1N"):
        s = s[:-3] + "IN"
    if s.endswith("11N") and len(s) >= 4:
        # only if looks like tracking body + bad suffix
        body = s[:-3]
        if re.search(r"\d$", body):
            s = body + "IN"

    # Must end with IN
    if not s.endswith("IN"):
        # if ends with single N after digits, prepend I
        if re.search(r"\dN$", s):
            s = s[:-1] + "IN"
        elif re.search(r"\dI$", s):
            s = s + "N"

    return s


def is_valid_article_no(article: str | None) -> bool:
    """Return True if article looks trackable and ends with IN."""
    if not article or article == DASH:
        return False
    s = normalize_article_no(article)
    if s == DASH or not s.endswith("IN"):
        return False
    # Prefer strict pattern; fall back to len + IN
    if _ARTICLE_RE.match(s):
        return True
    # Allow slightly off length if clearly XX...IN with digits
    return bool(re.match(r"^[A-Z]{2}\d{7,12}IN$", s))


def looks_like_portal_invalid(message: str | None) -> bool:
    """Heuristic: portal response suggests wrong / invalid article number."""
    if not message:
        return False
    m = message.lower()
    keys = (
        "invalid",
        "not found",
        "no record",
        "does not exist",
        "incorrect",
        "wrong",
        "no data",
        "article not",
        "tracking number",
        "no information",
        "not available",
    )
    return any(k in m for k in keys)
