# RTS Monitoring Project — Agent Rules (Grok / CLI AI)

> Load this file whenever working in this project directory.  
> Side project: **Postal RTS (Return to Sender)** parcel monitoring — **not Railway work**.

---

## Trigger: "start the program"

When the user says any of:

- `start the program`
- `start`
- `start analysis`
- `analyse images` / `analyze images`
- `process RTS images`
- `process pending images`

…run the **RTS vision pipeline** below immediately (do not wait for extra confirmation unless the inbox is empty or unsafe).

Optional variants:

- `start the program using Sample Photos` → input = `Sample Photos\` (do **not** move Sample Photos unless user asks)
- Default input = `Yet to be analysed images\`

---

## Hard rules

1. **AI Vision ONLY for reading parcel photos.**  
   - Use multimodal vision (e.g. `read_file` on image files).  
   - **Do NOT** write or run OCR scripts (pytesseract, EasyOCR, PaddleOCR, etc.) as the extractor.  
   - Python helpers for Excel build, file move, sorting, JSON merge are OK.

2. **Empty fields** → use dash `–`, never `N/A`.

3. **Article numbers ALWAYS end with letters `IN`** (I + N), never digit-one + N.  
   - Correct: `JG832153662IN`, `EU002821162IN`  
   - **Wrong (common vision mistake):** `…1N`, `…In`, `…in`, spaces, asterisks around barcode  
   - After reading each article number, **normalize**: strip spaces/dashes/`*`, uppercase, force suffix to **`IN`** if misread as `1N`.  
   - Prefer full India Post tracking IDs: typically **2 letters + 9 digits + `IN`**.  
   - Use helper: `it20/article_utils.py` → `normalize_article_no` / `is_valid_article_no`.

4. **To-address only (when two addresses on the cover)**  
   - Always take the **TO / addressee** block — name, address, mobile of the **recipient**, not the sender / return-to / “From”.  
   - **Hindi marker for TO:** **`सेवा में`** / **`सेवा मे`** / **`सेवामें`** (any spacing) = **To address**.  
     Also accept English **To** / **Addressee** / window address facing the barcode destination.  
   - **Do NOT** use “From”, “प्रेषक”, “If undelivered return to”, sender advocate/company return blocks as the main Address/Mobile.  
   - Read **Devanagari (Hindi) carefully** — do not skip or invent Hindi lines; slow down on handwritten Hindi RTS notes and address lines.

5. **Sequence matters** — physical parcel order. Sort / SL rules (see Sorting):
   - **1st preference:** handwritten serial on the **article / photo top corner** (1, 2, 3, … circled or plain).
   - **2nd preference:** **WhatsApp filename timestamp**.

6. After a photo is successfully extracted, **move** it:

   `Yet to be analysed images\` → `Analysed Images\`

   (Only for default inbox run. Do not move `Sample Photos\` unless user explicitly asks.)

7. Excel format must match `RTS Report Sample format.xlsx` columns, plus:

   - **Col C** — Office / SO name from IT 2.0 **Booking Details → Destination** (e.g. `SIKANDRA SO`)
   - **Col I — `IT 2.0 remark`** — portal Remarks on **Item Returned to Sender** (e.g. `No such person in the address`); sits **immediately after Col H**
   - Source Image (Hyperlink), AI Confidence, Handwritten RTS Remark
   - Optional: IT 2.0 Status, IT 2.0 Tracked At

8. Division default = **AGRA** unless photo clearly shows otherwise.

9. Column G (Genuine Yes/No) needs phone verification — leave `–` unless handwritten note clearly maps (switch off, no such person, refused, etc.).

---

## Folder map

| Path | Role |
|------|------|
| `Yet to be analysed images\` | **Inbox** — pending photos |
| `Analysed Images\` | **Done** — moved after success |
| `Sample Photos\` | Demo / practice set |
| `RTS Report Sample format.xlsx` | Blank template |
| `RTS 01.08.2026.xlsx` | Human-filled reference style |
| `Updated report\` | Outputs (xlsx, json) |
| `Sample Video\` | IT 2.0 navigation sample video (user-provided) |
| `it20\` | India Post IT 2.0 Playwright automation |
| `.env` | IT 2.0 username/password (gitignored — never commit) |
| `HOW_TO_RUN.md` | Human operator guide |

Project root (example):

```
D:\Test Folder\RTS Monitoring project
```

---

## Pipeline steps (execute in order)

### 1. List pending images

- Scan `Yet to be analysed images\` for image files (`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.heic` if readable).
- If **zero** files → stop and tell user to copy photos into that folder.
- Do not re-process files already only in `Analysed Images\` unless user asks re-run.

### 2. Provisional image order (before vision)

While scanning the folder, process images roughly by WhatsApp time so work is stable:

1. **WhatsApp filename timestamp**  
   Pattern: `WhatsApp Image YYYY-MM-DD at HH.MM.SS.jpeg`  
   then optional ` (1)`, ` (2)` suffix.
2. Else file **modified time**.
3. Else filename alphabetical.

This is only the *processing* order. **Final Excel / SL order is decided after vision** (step 3–3b).

**Note:** WhatsApp almost always strips EXIF — do not rely on EXIF for sequence.

### 3. Vision-analyse each image

For each image:

- Open with vision (`read_file` on the image path) — **AI vision only, no OCR scripts**.
- One photo may contain **multiple parcels** → emit one record per parcel.
- Skip pure printed list/report pages as parcel rows (optional: extract list rows only if user wants; default focus = physical labels).
- Extract:

  - **`corner_serial`** (CRITICAL) — handwritten / circled number on the **article or photo, usually top corner** (e.g. 1, 2, 3, 15, 39).  
    Look carefully at corners and near the label. If two parcels in one photo, each may have its own number.  
    If no number → set `corner_serial` to `null` / empty (not invent).
  - `article_no` (must end with letters **`IN`**)
  - `name` / `address` / `mobile` from **TO only** (`सेवा में` / `सेवा मे` / English To) — never sender-only block when both exist
  - `office_hint` (only if visible on photo)
  - `handwritten_remark` (RTS reason text in English **or Hindi**; do **not** confuse corner serial with RTS remark)
  - `confidence` (high / medium / low)
  - `source_image` (filename)
  - `whatsapp_time` (parsed from filename when possible)

- Rotate / plastic / glare: still try; mark confidence low if unsure.
- Prefer full tracking IDs ending in letters **`IN`** when visible (never `1N`).
- **Hindi:** read Devanagari slowly; common TO label is **`सेवा में`** (also written **`सेवा मे`**).

### 3b. Final sort + SL NO. assignment (MANDATORY)

After all parcels from the run are extracted, **sort rows** with this priority:

| Priority | Key | Rule |
|----------|-----|------|
| **1st** | **`corner_serial`** | Numeric ascending (1, 2, 3…). Rows **with** a corner number come first, ordered by that number. |
| **2nd** | **WhatsApp filename timestamp** | For rows **without** corner_serial, or as **tie-break** when two rows share the same corner_serial / same photo. Use `HH.MM.SS` + `(1)/(2)` suffix. |
| 3rd | filename | Alphabetical fallback |

**SL NO. in Excel:**

1. If parcel has **`corner_serial`** (e.g. 7) → **SL NO. = that number** (give the written serial priority).
2. If **no** corner serial → assign SL using WhatsApp time order among unmarked parcels, using free numbers that do not collide with used corner serials (or place them after the highest corner serial — be consistent and document in Notes).
3. Never invent a corner serial that is not visible on the photo.

**Multi-parcel photo:** each parcel is a separate row; each uses its own corner_serial if both are marked.

### 4. Save intermediate JSON

Write batch or full extract under:

```
Updated report\run_YYYYMMDD_HHMMSS_extract.json
```

### 5. Build Excel report

- Base columns from template `RTS Report Sample format.xlsx`.
- Title date: use report date or today `DD.MM.YYYY` style in title if known.
- Output:

```
Updated report\RTS_YYYY.MM.DD_Extracted.xlsx
```

- Address column = name + address combined (same style as reference `RTS 01.08.2026.xlsx`).
- Hyperlink each row to the **final** image path after move (`Analysed Images\filename`) when moved; if still pending mid-run, link current path then update.
- Deduplicate by `article_no` when same article appears on multiple photos (keep highest confidence; merge missing fields).

### 6. Move processed images

After successful extraction for an image file (all parcels on that photo recorded):

```
Move-Item / shutil.move
  from: Yet to be analysed images\<file>
  to:   Analysed Images\<file>
```

If name collision in destination, add suffix `_2`, `_3`, etc. — do not overwrite.

### 7. User summary (after Excel)

Report:

- How many images processed / remaining
- How many parcel rows
- High / medium / low counts
- Excel path
- Remind user to verify medium/low + Col G phone check

### 8. IT 2.0 online tracking (MANDATORY after Excel)

**Runs automatically after the Excel file is generated** for **all rows** in that Excel.

Credentials: project root `.env` (`IT20_USERNAME`, `IT20_PASSWORD`).  
Entry URL: `IT20_BASE_URL` (employee portal).  
Auth is **TOTP** (APT TOTP app, 6 digits) — **not** SMS OTP. Code window ~**30 seconds**.

### ⚠️ TOTP / LOGIN (MANUAL OTP — default)

Chat se OTP bhejkar program-fill **use mat karo** (timeout / expire issues).

1. Program fills **Employee ID + password** from `.env`, clicks Sign In / Continue.
2. **TOTP page** aate hi user **Chrome me manually** 6-digit code type karke **Enter / Verify & Login** kare.
3. Program **home page** detect kare (`employeeportal/home` / Track and Trace visible) — status `WAITING_MANUAL_TOTP` → `LOGIN_OK`.
4. Login OK ke **baad hi** Article Tracking + Excel fill auto start.
5. Jab tak user manual login complete na kare, agent tracking start na kare; user ko clear message: *Chrome me TOTP daalo*.

**Runbook (from sample video):** `Sample Video\IT20_RUNBOOK.md`

Flow:

1. Launch **fresh** Chrome/Chromium profile via Playwright.
2. Login: Employee ID + password → **Sign In** → **Enter TOTP Code** → **Verify & Login**.
3. Go to **Track and Trace** → `https://app.indiapost.gov.in/tracking/track/article`.
4. For **each** Excel article:
   - Enter article → **Track**
   - **Col C** ← **SO where article was to be delivered**  
     = Booking Details **Destination** (e.g. `SIKANDRA SO`);  
     fallback = Office on event **Item received at Destination**
   - **Col I `IT 2.0 remark`** ← clean Remarks on **Item Returned to Sender** only  
     (e.g. `No such person in the address`) — never office-name fragments
5. **Wrong article handling** (max **2** retries):
   - Portal rejects → re-vision source image → fix article (must end **`IN`**) → retrack
6. CLI:

```
python -m it20.track_cli --smoke-login
python -m it20.track_cli --excel "Updated report\RTS_YYYY.MM.DD_Extracted.xlsx"
```

**Do not** hardcode password in code/git. Do not commit `.env`.

---

## Sorting helper (conceptual)

```
# Final parcel row sort (after vision):
sort key =
  (
    0 if corner_serial is present else 1,   # numbered articles first
    corner_serial or 0,                     # 1st preference: top-corner mark 1,2,3...
    whatsapp_filename_datetime,             # 2nd preference
    whatsapp_suffix_number or 0,
    filename
  )

# SL NO. =
#   corner_serial  if present
#   else next free serial by WhatsApp time among unmarked
```

WhatsApp name parse example:

- `WhatsApp Image 2026-08-01 at 22.04.44.jpeg` → 2026-08-01 22:04:44, suffix 0  
- `WhatsApp Image 2026-08-01 at 22.04.44 (1).jpeg` → same second, suffix 1  

Corner serial examples (vision):

- Circled **15** on envelope top/side → `corner_serial = 15`, SL NO. = 15  
- Handwritten **3** at top corner → `corner_serial = 3`, SL NO. = 3  
- No mark → `corner_serial` empty → order by WhatsApp time (2nd preference)  

---

## Anti-patterns (do not do)

- Do not invent article numbers when unreadable — use `–` and low confidence.
- Do not write article suffix as **`1N`** (digit one + N) — always letters **`IN`**.
- Do not use OCR libraries as primary reader.
- Do not empty `Sample Photos` unless asked.
- Do not put Category letters or Railway letter format in this project.
- Do not claim phone “YES genuine” without evidence on photo or user verification.
- Do not commit `.env` or paste IT 2.0 passwords into git-tracked files.
- Do not reuse a saved Chrome profile for IT 2.0 — always **fresh** profile.

---

## Reference docs

- Human guide: `HOW_TO_RUN.md`
- Template: `RTS Report Sample format.xlsx`
- Style sample: `RTS 01.08.2026.xlsx`
