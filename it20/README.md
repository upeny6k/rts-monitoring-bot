# IT 2.0 tracking module

Automates India Post **IT 2.0 / employee portal** login + article tracking for the RTS Excel report.

## Setup

1. Copy `.env.example` → `.env` (already created in project root) and set:
   - `IT20_USERNAME`
   - `IT20_PASSWORD`
2. Install deps:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

3. Put the navigation sample video in:

```
Sample Video\
```

## Commands

```powershell
# Test login + OTP only (Chrome/Chromium, fresh profile)
python -m it20.track_cli --smoke-login

# Track all rows in Excel (after Excel is generated)
python -m it20.track_cli --excel "Updated report\RTS_2026.08.04_Extracted.xlsx"
```

## TOTP — **manual in Chrome** (default)

Portal uses **APT TOTP app** (6-digit).

**Flow:**
1. Script fills Employee ID + password, opens TOTP page.
2. **You** type TOTP in the Chrome window → Enter / Verify & Login.
3. Script detects **home page** → then starts tracking automatically.

Chat/file OTP inject is **not** the default (was unreliable with 30s expiry).

## Excel fill-back (from Sample Video)

| Portal | Excel |
|--------|--------|
| Booking Details → **Destination** (e.g. SIKANDRA SO) | **Col C** |
| Event **Item Returned to Sender** → **Remarks** | **Col I — IT 2.0 remark** |

Runbook: `Sample Video\IT20_RUNBOOK.md`

## Article number hard rule

All India Post article / tracking numbers **end with the letters `IN`** (I + N).

- Correct: `JG832153662IN`
- Wrong vision misreads to fix: `…1N`, `…In`, spaces, asterisks

Helpers: `it20/article_utils.py` → `normalize_article_no`, `is_valid_article_no`.

## Wrong article handling

If IT 2.0 rejects an article number:

1. Re-open the row’s **source image** (vision)
2. Re-read article number (must end with `IN`)
3. Correct Excel cell
4. Retrack  
Max **2** retries per parcel (`IT20_MAX_RETRIES`).

## Status

| Piece | Status |
|-------|--------|
| `.env` credentials | Done |
| Fresh browser profile | Done |
| Login + OTP prompt | Scaffold ready (selectors may need video tuning) |
| Tracking page navigation | **Pending Sample Video** |
| Excel column mapping (SO + delivery remark) | **Pending your guide after automation works** |
| Auto-run after Excel | Documented in AGENTS.md; call `python -m it20.track_cli --excel …` |

## Security

- `.env` is gitignored — do not commit passwords.
- Prefer not pasting password in chat once `.env` exists.
