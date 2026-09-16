# Tabletop Playground (TTPG) Deck Pipeline

Automated extraction, texture atlas compilation, and packaging pipeline for custom card decks and guidebooks in **Tabletop Playground** (Unreal Engine).

```
   [ Source PDFs ]               _INPUT/
          │
          ▼  (deck_processor.py / PyMuPDF)
   [ Card Pairs ]                _OUTPUT/<Universe>/<Deck>/card_###_[front|back].png
          │
          ▼  (ttpg_packager.py / Pillow)
   [ Texture Atlases ]           _PACKAGE/<Name>/Textures/*.png  (Max 8192x8192 px)
   [ Unified JSON Templates ]    _PACKAGE/<Name>/Templates/*Card.json (Multi-sheet)
          │
          ▼  (Direct Install / gui_app.py)
   [ Tabletop Playground ]       %LOCALAPPDATA%\TabletopPlayground\Packages\

```

---

## Key Features

* **Deterministic Physics (SoC):** Card dimensions (`Width`, `Height`) are calculated directly from pixel dimensions and configured DPI using $size_{cm} = \frac{pixels}{dpi} \times 2.54$. No hardcoded magic dimensions.
* **Native Multi-Sheet Decks:** Tallies exceeding texture boundaries (100 cards or 8192 px) are compiled into a single unified TTPG Card template using `ExtraFrontTextures` and `ExtraBackTextures`, preventing fragmented deck spawns in-game.
* **Vector-Accurate Extraction:** Direct PDF clipping via PyMuPDF matrix scaling without intermediate full-page rasterization.


* **Hierarchical Overrides:** Local `deck.json` files override global `config.json` rules seamlessly at any directory depth.
* **Fail-Fast Engineering:** Strict assertions enforce dimension consistency, duplex pairing, and page-count integrity before allocating textures.


* **Visual Calibrator UI:** Built-in NiceGUI dashboard with SVG alignment overlays, auto-detection of crop marks, and one-click package installation.



---

## File Architecture

| File | Role | Execution |
| --- | --- | --- |
| `gui_app.py` | Complete desktop dashboard with 4-step wizard and live visual calibration. | `python gui_app.py` (or `run_app.bat`) |
| `deck_processor.py` | Vector extraction engine. Renders card pairs from PDF according to grid profiles. | `python deck_processor.py` |
| `ttpg_packager.py` | Compiles card pairs into atlases and generates unified TTPG <GUID>Card.json templates. | `python ttpg_packager.py` |
| `inspect_deck.py` | Fast diagnostic CLI. Crops a single card pair to verify cut math and duplex alignment. | `python inspect_deck.py [optional_pdf]` |
| `config.json` | Declarative project schema: paths, DPI, match rules, and preset grid definitions. | Loaded at runtime |
| `deck.json` | *(Optional)* Local folder override for custom physics, metadata, or grid offsets. | Merged hierarchically |

---

## Quick Start

### 1. Requirements & Installation

Python 3.10+ is required. Install required dependencies:

```bash
pip install pymupdf pillow nicegui

```

(Or double-click `run_app.bat` on Windows to check and launch automatically).

### 2. Add Source PDFs

Place your PDF files inside the `_INPUT` directory:

```text
_INPUT/
└── Core/
    ├── Story_HQ Cards.pdf
    └── Instruction_Guidebook.pdf

```

### 3. Run Pipeline via GUI

```bash
python gui_app.py

```

Open `http://localhost:8080` in your browser. The interface guides you through:

1. **Configuration:** Set package name and export DPI.


2. **Extraction:** Run `deck_processor.py` with real-time log streaming.


3. **Packaging:** Run `ttpg_packager.py` to bake texture atlases and card templates.


4. **Installation:** Click **Install Directly to TTPG** to copy the mod to your local game directory.



---

## Configuration Reference (`config.json`)

The global configuration governs default paths, raster DPI, filename matching rules, and grid profiles.

```json
{
  "default_profile": "story_engine_standard",
  "dpi": 250,
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
      "pattern": "*Guidebook*.pdf",
      "profile": "full_page_duplex",
      "strip_suffix": ""
    }
  ],
  "profiles": {
    "story_engine_standard": {
      "description": "Standard US Letter (2x3, cards 3x3 inches, gutters 18pt)",
      "duplex_flip": "horizontal",
      "model": "Rounded",
      "thickness_cm": 0.05,
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
    }
  }
}

```

### Profiles Breakdown

* **`model`**: `"Rounded"` (standard playing card) or `"Square"` (tiles, manuals, square boards).
* **`thickness_cm`**: Card thickness in centimeters (default: `0.05` for cards, `0.03` for guidebooks).
* **`duplex_flip`**:
* `"horizontal"`: Back side columns are mirrored (`cols - 1 - col`) for standard short-edge landscape duplex or long-edge portrait duplex.


* `"vertical"`: Back side rows are mirrored (`rows - 1 - row`).


* `"none"`: Front and back use the exact same coordinates (for single-sided cards or manuals).




* **`grid`**: PDF coordinate geometry measured in PostScript points ($1\text{ pt} = \frac{1}{72}\text{ inch}$):


* `cols` / `rows`: Grid count per sheet.


* `card_width_pt` / `card_height_pt`: Card cut dimensions.


* `origin_x_pt` / `origin_y_pt`: Margin offsets from the bottom/top-left origin.


* `gutter_x_pt` / `gutter_y_pt`: Spacing between adjacent cards.





---

## Local Overrides (`deck.json`)

To override properties for an individual deck without modifying global rules, create a `deck.json` file inside the PDF's directory in `_INPUT`:

```text
_INPUT/
└── Expansions/
    └── MiniCards/
        ├── deck.json
        └── Cards.pdf

```

### Supported `deck.json` Schema

```json
{
  "profile": "story_engine_eco",
  "duplex_flip": "horizontal",
  "card_width_cm": 5.0,
  "card_height_cm": 5.0,
  "thickness_cm": 0.06,
  "model": "Square",
  "meta": {
    "universe": "Custom Expansion",
    "category": "Mini Cards",
    "deck_name": "Mini Deck",
    "description": "Custom mini square tokens."
  },
  "grid_overrides": {
    "origin_x_pt": 40.0,
    "origin_y_pt": 40.0
  }
}

```

*Any field omitted from `deck.json` automatically inherits from the resolved profile and image calculations.*

---

## Advanced Mechanics

### Multi-Sheet Unified Templates

When a deck contains more cards than fit onto a single $8192 \times 8192\text{ px}$ sheet (or exceeds the $10 \times 10$ cell limit), `ttpg_packager.py`:

1. Enforces uniform grid dimensions across all sheets (`cols` $\times$ `rows`).
2. Generates numbered atlas pairs: `<Deck>_01_front.png`, `<Deck>_01_back.png`, `<Deck>_02_front.png`...
3. Writes a **single** `<GUID>Card.json` linking `ExtraFrontTextures` and `ExtraBackTextures`.
4. Sets `BackIndex: -3` for 1:1 unique card back pairing across the entire index range ($0$ to $N - 1$).

### Fail-Fast Validations

The pipeline aborts immediately (`sys.exit(1)`) under the following error states:

* Odd page count in duplex card documents (indicates a missing back page or mismatched duplex pairing).


* Extracted card pixel dimensions mismatching within the same deck.
* Card pixel dimensions exceeding GPU limits ($> 8192\text{ px}$).
* Missing front/back companion pairs during packaging.

### Fast Calibration via CLI

To quickly preview margins and duplex alignment for a specific PDF before running batch extraction:

```bash
python inspect_deck.py "_INPUT/Core/Story_HQ Cards.pdf"

```

The script renders a single front/back pair into `_DIAGNOSTICS/precise_card_000_[front|back].png` and reports calculated physical dimensions in centimeters.