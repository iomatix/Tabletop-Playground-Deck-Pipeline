# Deck Processor & TTPG Mod Packager

An automated, config-driven Python pipeline designed to extract cards and guidebooks from multi-page print-and-play PDF sheets (*The Story Engine*, *Deck of Worlds*, and their expansions) and compile them directly into native mod packages for **Tabletop Playground (TTPG)**.

The project provides both headless CLI scripts for batch execution and a browser-based GUI built with NiceGUI featuring visual grid calibration and one-click deployment.

---

## Key Features & Architecture

* **Separation of Concerns (SoC) & Strict Whitelisting:** Execution logic is fully decoupled from card geometry and folder paths. Only PDFs matching declarative patterns in `config.json` are processed; unrelated helper sheets or loose files are safely skipped (`[IGNORE]`).
* **Vector-Accurate Clipping (PyMuPDF):** Point-exact coordinates (`pt`) are passed straight to PyMuPDF's underlying C++ engine (`page.get_pixmap(clip=...)`). This eliminates redundant raster allocations, guarantees sub-pixel sharpness, and cuts execution times.
* **Smart Page Classification & Dynamic Framing:** Real card decks enforce duplex page parity validation (Fail-Fast). Single-page documents and multi-page rulebooks dynamically adapt to portrait/landscape geometry with blank back-cover fallbacks for odd-numbered page sequences.
* **Atlas Generation & Unreal Engine Optimization:** `ttpg_packager.py` stitches card tiles into power-of-two card sheets (up to $10 \times 10$ matrices with an 8192 px ceiling). Generates native `<GUID>Card.json` templates with physical properties:
* Standard Cards: $7.62 \times 7.62\text{ cm}$, thickness $0.05\text{ cm}$, `"Rounded"` model.
* Guidebooks: $21.59 \times 27.94\text{ cm}$ (or dynamic aspect ratio), thickness $0.04\text{ cm}$, `"Square"` model.
* 1:1 Duplex Map: Configured with `"BackIndex": -3` for direct front-to-back index association.


* **Persistent Visual Web GUI:** Built-in NiceGUI frontend featuring:
* Non-blocking background workers with unified in-memory log streaming.
* Internationalization (`en` / `pl`).
* Interactive SVG grid calibrator with crop-mark auto-detection and preset loading.
* Direct one-click package installation into `%LOCALAPPDATA%\TabletopPlayground\Packages`.



---

## Directory Layout

```text
.
├── config.json                 # Global configuration: presets, rules, paths, TTPG manifest
├── deck_processor.py           # Backend: Vector extraction of cards and books from PDFs
├── ttpg_packager.py            # Backend: Card sheet atlas compilation and TTPG JSON generator
├── gui_app.py                  # Frontend: NiceGUI web interface and grid calibrator
├── locales/                    # External language files (en.json, pl.json)
│   ├── en.json
│   └── pl.json
├── .build_cache.json           # SHA-256 state tracking for incremental, idempotent builds
│
├── _INPUT/                     # Source PDF files and optional local deck configs
│   ├── Story Engine Deck/
│   │   └── Main Deck_HQ Cards.pdf
│   └── Deck of Worlds/
│
├── _OUTPUT/                    # Extracted raw card pairs (card_###_front.png, card_###_back.png)
│   └── Story Engine Deck/
│
└── _PACKAGE/                   # Compiled TTPG mod directory
    └── The Story Engine Universe/
        ├── Manifest.json       # Mod package header with generated package GUID
        ├── Textures/           # Compiled card sheets (*_front.png, *_back.png)
        └── Templates/          # TTPG physical card and deck templates (<GUID>Card.json)

```

---

## Configuration (`config.json`)

The configuration controls directories, target DPI, rule patterns, and grid presets:

```json
{
  "default_profile": "story_engine_standard",
  "dpi": 200,
  "export_format": "png",
  "dirs": {
    "input": "_INPUT",
    "output": "_OUTPUT",
    "diagnostics": "_DIAGNOSTICS"
  },
  "ttpg": {
    "package_name": "The Story Engine Universe",
    "output_dir": "_PACKAGE"
  },
  "rules": [
    {
      "pattern": "*_HQ Cards.pdf",
      "profile": "story_engine_standard",
      "strip_suffix": "_HQ Cards"
    },
    {
      "pattern": "*_Eco Cards.pdf",
      "profile": "story_engine_eco",
      "strip_suffix": "_Eco Cards"
    },
    {
      "pattern": "*Guidebook*.pdf",
      "profile": "full_page_duplex",
      "strip_suffix": ""
    }
  ],
  "profiles": {
    "story_engine_standard": {
      "description": "Standard US Letter 8.5x11, 2x3 cards (3x3 inches), HQ crop-mark margins",
      "duplex_flip": "horizontal",
      "grid": {
        "cols": 2,
        "rows": 3,
        "card_width_pt": 216.0,
        "card_height_pt": 216.0,
        "origin_x_pt": 80.95,
        "origin_y_pt": 54.0,
        "gutter_x_pt": 18.0,
        "gutter_y_pt": 18.0
      }
    },
    "story_engine_eco": {
      "description": "Eco US Letter 8.5x11, 3x4 cards (2.5x2.5 inches), zero-gutter layout",
      "duplex_flip": "horizontal",
      "grid": {
        "cols": 3,
        "rows": 4,
        "card_width_pt": 180.0,
        "card_height_pt": 180.0,
        "origin_x_pt": 36.0,
        "origin_y_pt": 36.0,
        "gutter_x_pt": 0.0,
        "gutter_y_pt": 0.0
      }
    },
    "full_page_duplex": {
      "description": "Full Page US Letter / A4 document (1x1 duplex)",
      "duplex_flip": "none",
      "grid": {
        "cols": 1,
        "rows": 1,
        "card_width_pt": 612.0,
        "card_height_pt": 792.0,
        "origin_x_pt": 0.0,
        "origin_y_pt": 0.0,
        "gutter_x_pt": 0.0,
        "gutter_y_pt": 0.0
      }
    }
  }
}

```

---

## Local Deck Overrides (`deck.json`)

To override global grid parameters for a specific expansion, place a `deck.json` file alongside its PDF inside `_INPUT/<Deck Name>/`:

```json
{
  "profile": "story_engine_standard",
  "duplex_flip": "vertical",
  "grid_overrides": {
    "origin_x_pt": 82.0
  }
}

```

Unspecified keys inherit from the globally defined base profile.

---

## Usage

### Method 1: Web Interface (Recommended)

1. Launch the NiceGUI dashboard:
```powershell
python gui_app.py

```


2. Navigate to `http://localhost:8080` in your browser.
3. Follow the 4-step workflow:
* **Step 1:** Verify directories and mod package name.
* **Step 2:** Run extraction (`deck_processor.py`).
* **Step 3:** Compile card sheets and templates (`ttpg_packager.py`).
* **Step 4:** Click **Install Directly to TTPG** to sync the package to your game installation.



### Method 2: Headless Command Line

```powershell
# 1. Install dependencies
pip install pymupdf pillow nicegui

# 2. Extract cards from _INPUT/ to _OUTPUT/
python deck_processor.py

# 3. Stitch atlases and compile TTPG mod into _PACKAGE/
python ttpg_packager.py

```

---

## Manual TTPG Installation

If not using the web GUI's direct installation button:

1. Locate the compiled mod folder in `_PACKAGE/<Package Name>/`.
2. Copy the entire folder into:
```text
%LOCALAPPDATA%\TabletopPlayground\Packages\

```


3. Start **Tabletop Playground**. The physical card decks and guidebook cards will appear in your in-game object library.