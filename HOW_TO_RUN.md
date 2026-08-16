# RTS Monitoring Project — How to Run (Detail Guide)

> **Side project:** Postal Department — **Return to Sender (RTS)** parcel monitoring & automatic report generation.  
> **Not related to Railway work.**

---

## 1. Project kya karta hai? (Flow)

```
Physical RTS parcels receive
        ↓
Photo click (sequence me — parcel order maintain rakho)
        ↓
WhatsApp se images bhejo / folder me copy karo
        ↓
Images daalo →  Yet to be analysed images\
        ↓
Grok me is project directory se:  "start the program"
        ↓
AI VISION se har image analyse (OCR script NAHI)
        ↓
Details Excel report me fill + image hyperlink
        ↓
Processed images move →  Analysed Images\
        ↓
★ IT 2.0 online tracking (auto after Excel)
   Chrome fresh profile → login (.env) → OTP (you type, ~30s)
   → track each article → SO name + delivery remark → Excel update
```

**Extract hone wale fields (Excel format ke hisaab se):**

| Column | Meaning |
|--------|---------|
| SL NO. | **1st:** article top-corner handwritten no. (1,2,3…); **2nd:** WhatsApp-time order if no mark |
| Division | Default: **AGRA** (change if needed) |
| Office Name by which Article has been returned (**Col C**) | From IT 2.0 **Booking Details → Destination** (e.g. **SIKANDRA SO**) |
| Article No. | Speed Post / EMS — **must end with letters `IN`** (not `1N`) |
| Address | **TO address only** — Hindi **`सेवा में` / `सेवा मे`**; not sender/return-to |
| Addressee Mobile No. | TO side mobile |
| Whether remark on RTS found Genuine (Yes/No) | Phone verify ke baad |
| If No, Remark | Extra remark |
| **IT 2.0 remark** (Col I, next to H) | Portal Remarks e.g. **No such person in the address** (Item Returned to Sender) |
| **Source Image (Hyperlink)** | Photo link |
| AI Confidence | high / medium / low |
| Handwritten RTS Remark | Photo pe RTS reason (English/Hindi) |

---

## 2. Folder structure

```
RTS Monitoring project\
│
├── HOW_TO_RUN.md                 ← Ye guide
├── AGENTS.md                     ← Grok/CLI AI ke liye auto-rules ("start the program")
│
├── RTS Report Sample format.xlsx ← Blank official-style table
├── RTS 01.08.2026.xlsx           ← Manually filled sample (accuracy reference)
│
├── Sample Photos\                ← Practice / first test set (already used once)
├── Sample Video\                 ← IT 2.0 full navigation sample video (yahan daalo)
├── Yet to be analysed images\    ← ★ NAYI photos YAHAN daalo
├── Analysed Images\              ← ★ Process hone ke baad images YAHAN move
├── it20\                         ← India Post IT 2.0 Playwright automation
├── .env                          ← IT 2.0 username/password (private, gitignored)
│
└── Updated report\               ← Excel reports + extraction JSON
    ├── RTS_YYYY.MM.DD_Extracted.xlsx
    ├── run_*_extract.json
    └── build_excel_*.py
```

| Folder | Use |
|--------|-----|
| `Yet to be analysed images\` | Pending inbox — nayi WhatsApp / camera photos yahan rakho |
| `Analysed Images\` | Done — successfully analysed photos yahan transfer |
| `Sample Photos\` | First demo set; daily work ke liye zaroori nahi |
| `Sample Video\` | IT 2.0 click-path sample video for automation training |
| `Updated report\` | Output Excel + intermediate JSON |
| `it20\` | Login + track + Excel write-back scripts |

---

## 3. Program kaise start karein (main method)

### Step A — Photos ready karo

1. Physical parcels ko **jis order me stack / tray me rakhe ho**, usi order me photo lo.  
2. Photos ko phone se PC pe lao (WhatsApp / cable / Drive).  
3. Saari pending images copy / move karo:

```
D:\Test Folder\RTS Monitoring project\Yet to be analysed images\
```

Supported: `.jpg` `.jpeg` `.png` `.webp` (aur common image types)

### Step B — Grok (ya similar CLI AI) is project folder me open karo

Workspace / working directory:

```
D:\Test Folder\RTS Monitoring project
```

### Step C — Sirf ye likho

```
start the program
```

Ya short variants (same meaning):

```
start
start analysis
analyse images
process RTS images
```

### Step D — Grok kya karega (automatic)

1. `Yet to be analysed images\` me images list karega  
2. Har image ko **AI Vision se** padhega — **OCR Python script nahi**  
3. Article pe **top corner serial** (1, 2, 3…) dhoondhega + article no., name, address, mobile  
4. Rows ko **final sequence** me sort karega (Section 5 — corner number pehle, phir WhatsApp time)  
5. Excel me **SL NO.** = corner serial (agar likha ho), warna WhatsApp-time order  
6. `RTS Report Sample format.xlsx` jaisa Excel banayega / update karega  
7. Har row pe **source image hyperlink**  
8. Successfully processed image ko  
   `Yet to be analysed images\` → `Analysed Images\` **move** karega  
9. Report save:

```
Updated report\RTS_YYYY.MM.DD_Extracted.xlsx
```

(Date report date / aaj ki date se)

### Step E — Aap check karo

1. Excel kholo → **AI Confidence = high** pehle verify  
2. Column **Source Image** pe click → photo open → details match?  
3. Galatiyan batao → next pass improve

---

## 4. CRITICAL RULE — AI Vision only (OCR nahi)

| Allowed | Not allowed (extraction ke liye) |
|---------|----------------------------------|
| Grok / multimodal AI **vision** (`read_file` on image) | `pytesseract`, EasyOCR, PaddleOCR, etc. as main extractor |
| Human-like reading of plastic, rotated, handwritten labels | Pure OCR script dump without vision understanding |
| Confidence tag (high/medium/low) | Silent wrong digits without review flags |

**Kyun?** RTS labels plastic, glare, upside-down, torn windows, Hindi handwriting — pure OCR galat digits deta hai. Vision context samajh kar padhta hai.

> Helper scripts (Excel merge, file move, sort order) Python se allowed hain.  
> **Text extraction from parcel photo = AI vision only.**

---

## 5. Photo sequence — corner number pehle, phir WhatsApp time

### Program sort order (UPDATED — ye follow hoga)

| Priority | Source | Rule |
|----------|--------|------|
| **1st** | **Article / photo top corner pe likha number** | Handwritten ya circled **1, 2, 3, 15…** — AI Vision se padho. **SL NO. isi number ko do.** |
| **2nd** | **WhatsApp filename timestamp** | Jab corner number **na ho**, ya same number / same photo pe tie-break. Pattern: `WhatsApp Image YYYY-MM-DD at HH.MM.SS` + `(1)/(2)` |
| 3rd | File modified time / filename | Fallback only |

```
Final row sort:
  1) corner_serial ascending   (articles jisme 1,2,3… likha hai)
  2) WhatsApp time             (bina number wale + tie-break)
  3) filename

Excel SL NO.:
  - Corner number dikha  →  SL NO. = wahi number (e.g. 7)
  - Corner number nahi   →  WhatsApp time order se free serial
```

**Important:** Corner serial RTS remark nahi hai — alag field.  
Example: circled **15** on envelope → `corner_serial = 15` → Excel **SL NO. = 15**.

### Operator best practice (physical match)

1. **Best:** Har article / envelope pe top corner me clear **1, 2, 3…** likho (ya circle) — program isi ko first preference dega.  
2. **Second:** WhatsApp pe click/send order maintain rakho (filename time).  
3. Tray me parcels same serial order me rakho taaki Excel SL se physical parcel mil jaye.

### Q: WhatsApp se image bhejne ke baad EXIF data save rehta hai?

**Short answer: Almost no — useful EXIF usually nahi rehta.**

| Metadata | Original camera photo | WhatsApp ke baad (typical) |
|----------|----------------------|----------------------------|
| DateTimeOriginal | Haan | **Strip** |
| GPS / camera model | Kabhi-kabhi | **Strip** |

Isliye sequence ke liye **EXIF pe depend mat karo**.  
Is project me: **corner number (1st) + WhatsApp filename time (2nd)**.

---

## 6. Daily checklist (copy-paste)

```
[ ] Parcels sequence me tray pe
[ ] Har article top corner pe serial likho (1, 2, 3…) — first preference
[ ] Photos click (same sequence); WhatsApp send order maintain — second preference
[ ] Copy to: Yet to be analysed images\
[ ] Open Grok in: D:\Test Folder\RTS Monitoring project
[ ] Type: start the program
[ ] Wait for vision analysis + Excel
[ ] Check Updated report\*.xlsx
[ ] Confirm images moved to Analysed Images\
[ ] Accuracy review (high → medium → low)
```

---

## 7. Output kahan milta hai?

| Output | Location |
|--------|----------|
| Main Excel report | `Updated report\RTS_YYYY.MM.DD_Extracted.xlsx` |
| First sample run | `Updated report\RTS_Sample_Photos_Extracted_AI_Vision.xlsx` |
| Raw extractions (debug) | `Updated report\batch##_extract.json` |
| Merged JSON | `Updated report\all_parcels_merged.json` |
| Done photos | `Analysed Images\` |
| Blank template | `RTS Report Sample format.xlsx` |
| Manual reference | `RTS 01.08.2026.xlsx` |

Excel me **Source Image** column pe click karke photo open hogi.

---

## 8. Accuracy review kaise karein

1. Filter **AI Confidence = high** → 10 rows random check  
2. Hyperlink se photo kholo → Article No. / Mobile digit-by-digit  
3. Medium / Low pe jyada dhyan (glare, plastic, upside-down)  
4. Galat pattern note karke Grok ko batao, e.g.:  
   - “Article me JO ko JU padh raha hai”  
   - “Mobile me extra 9 aa raha hai”  
5. Col C (Office Name) aur Col G (Genuine Yes/No) aksar aapke operational knowledge / phone call se complete honge

**Dash rule:** Empty field = `–` (kabhi `N/A` nahi)

---

## 9. “start the program” — expected AI behaviour (for operators)

Jab user likhe **start the program** (ya equivalent), AI **must**:

1. Read `AGENTS.md` + this guide  
2. List images in `Yet to be analysed images\`  
3. If folder empty → user ko batao: photos daalo pehle  
4. Extract corner serial (1st) + sort; WhatsApp time (2nd) — Section 5  

5. Analyse **only with AI vision** (read images as images)  
6. Build / append Excel in official column format + image hyperlinks  
7. Move each successfully analysed image to `Analysed Images\`  
8. Give short summary: count, high/medium/low, output path  

Agar user **Sample Photos** se dubara practice chahe:

```
start the program using Sample Photos
```

---

## 10. Troubleshooting

| Problem | Fix |
|---------|-----|
| `Yet to be analysed images` empty | Photos copy karo us folder me |
| Hyperlink open nahi ho raha | Excel me path check; images move ke baad link `Analysed Images\` pe point hona chahiye |
| Sequence galat lag raha | Corner pe clear 1,2,3… likho; phir WhatsApp send order check karo |
| Article number doubt | Confidence = low/medium filter; photo zoom |
| OCR script suggestion aaye | Reject — vision only rule |
| Duplicate article 2 photos me | Merge one row; hyperlink best readable photo |

---

## 11. One-line summary

> **Photos daalo `Yet to be analysed images` me → project folder me Grok kholo → `start the program` likho → AI Vision se analyse + Excel + images `Analysed Images` me move.**  
> **Sequence: 1st = article top-corner number (1,2,3…) → 2nd = WhatsApp filename time. EXIF pe depend mat karo.**

---

*Last updated: 04.08.2026*
