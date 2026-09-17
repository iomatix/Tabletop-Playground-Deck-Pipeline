# Tabletop Playground (TTPG) Deck Pipeline

Automated extraction, texture atlas compilation, and packaging pipeline for custom card decks and guidebooks in **Tabletop Playground** (Unreal Engine).

```text
   [ Source PDFs ]               _INPUT/<Package>/<Deck>.pdf
          │
          ▼  (deck_processor.py / PyMuPDF)
   [ Card Pairs & Metadata ]     _OUTPUT/<Package>/<Deck>/card_###_[front|back].png
          │                      _OUTPUT/<Package>/<Deck>/deck_meta.json (Contract)
          ▼  (ttpg_packager.py / Pillow)
   [ Texture Atlases ]           _PACKAGE/<Name>/Textures/*.png  (Max 8192x8192 px)
   [ Unified JSON Templates ]    _PACKAGE/<Name>/Templates/*Card.json (Multi-sheet)
          │
          ▼  (Direct Install / gui_app.py)
   [ Tabletop Playground ]       %LOCALAPPDATA%\TabletopPlayground\Packages\

```

> [!NOTE]
> In the extraction path `card_###_[front|back].png`, `###` denotes the **1-based sequential card index** within that specific deck folder (padded to a minimum of 3 digits, e.g., `card_001_front.png`, dynamically expanding to `card_1000_front.png` for decks $\ge 1000$ items), not a physical page number.

---

> [!IMPORTANT]
> **Key Architecture Highlights**
>
> * **Deterministic Physics (SoC):** Card dimensions (`Width`, `Height`) are calculated dynamically from pixel boundaries and DPI: $size_{cm} = \frac{pixels}{dpi} \times 2.54$. No hardcoded magic numbers.
> * **UV-Safe Partitioned Stacks:** Decks exceeding TTPG grid capacity (100 cards / $10 \times 10$ max cells) or GPU texture boundaries (8192 px) are automatically partitioned into numbered sub-stacks (Part 1, Part 2) with clean UV coordinates, ready to be stacked together in-game.
> * **Contract-Driven Pipeline (`deck_meta.json`):** Downstream tools receive exact classification (`card_deck` vs. `document`) directly from the extraction phase, eliminating brittle string heuristics.
> * **Context-Aware Naming & Tooltips:** In-game objects are prefixed with package hierarchy (`[Bridge Expansion Set] Lore Master's Deck Guidebook`), and cards held in hand display distinct hover labels (`Deck #001`, `Guidebook - Page 1`).
> * **Strict Allow-List:** Only PDFs explicitly matching rules in `config.json` are processed; print/assembly guides and alternate eco cuts are ignored by default.
> 
> 

---

## File Architecture

| File | Role | Execution |
| --- | --- | --- |
| `gui_app.py` | Desktop management interface (NiceGUI entry point, lifecycle & event loop patches). | `python gui_app.py` (or `run_app.bat`) |
| `app/state.py` | Global state, config persistence, and multi-language engine (`en` / `pl`). | Core module |
| `app/pdf_analyzer.py` | 1D differential cut analyzer, vector inspector & throttled SVG overlay generator. | Core module |
| `app/views/calibrator.py` | Visual grid calibrator with 2-Click calibration and conflict-free keyboard shortcuts. | View component |
| `app/views/wizard.py` | Asynchronous 4-step pipeline runner (Configuration → Extraction → Compilation → Install). | View component |
| `app/views/diagnostics.py` | Built-in test runner, Ruff static linter, and i18n parity sync view. | View component |
| `tests/` | Comprehensive test suite (unit, regression, PDF batch parsing, i18n parity, package install mock). | `pytest -v tests/` (or GUI) |
| `locales/*.json` | Internationalization bundles (`en.json`, `pl.json`). | Runtime asset |
| `deck_processor.py` | Vector extraction engine. Renders card pairs from PDF according to grid profiles and emits `deck_meta.json`. | `python deck_processor.py` |
| `ttpg_packager.py` | Compiles card pairs into atlases and generates unified TTPG `<GUID>Card.json` templates with per-card hover tooltips (`CardNames`) and stack names (`Name`). | `python ttpg_packager.py` |
| `inspect_deck.py` | Fast diagnostic CLI. Crops a single card pair to verify cut math, margins, and duplex alignment. | `python inspect_deck.py [optional_pdf]` |
| `config.json` | Declarative project schema: paths, DPI, allow-list match rules, and preset grid definitions. | Loaded at runtime |
| `deck_meta.json` | *(Generated)* Intermediate contract stored in each `_OUTPUT` subfolder detailing item classification (`card_deck` or `document`), grid dimensions, and item counts. | Emitted by processor |
| `deck.json` | *(Optional)* Local folder override for custom physics, metadata, or grid offsets. | Merged hierarchically |

---

## Quick Start

### Choose Your Distribution

#### Option A: Standalone Executable (Windows x64)

* Download `TTPG-Deck-Pipeline-Windows.zip` from [Releases](https://github.com/iomatix/Tabletop-Playground-Deck-Pipeline/releases/latest).
* Extract the archive and launch `TTPG-Deck-Pipeline.exe`.
* **Zero dependencies:** Bundles Python runtime, UI engine, and OS integrations out of the box.

#### Option B: Portable Source (Cross-Platform)

* Download `TTPG-Deck-Pipeline-Source.zip` (or clone this repository).
* Requires **Python 3.10+ (Standard Win32 / macOS / Linux)**.

> [!WARNING]
> **Windows Users:** Do NOT use the Microsoft Store version of Python (`PythonSoftwareFoundation`). Its UWP sandbox activates filesystem virtualization, redirecting writes away from `%LOCALAPPDATA%\TabletopPlayground`. Always use the official installer from [python.org](https://www.python.org/downloads/) or install via `winget install Python.Python.3.13`.

---

### 1. Requirements & Installation (Source Distribution)

Install production and diagnostic dependencies via `requirements.txt`:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

```

*(On Windows, you can also double-click `run_app.bat` to verify environment and launch automatically).*

### 2. Add Source PDFs

Place your PDF files inside the `_INPUT` directory:

```text
_INPUT/
└── Core/
    ├── Story_HQ Cards.pdf
    └── Instruction_Guidebook.pdf

```

### 3. Run Pipeline via GUI

Launch the desktop management interface:

```bash
python gui_app.py

```

Access the UI at [http://127.0.0.1:8080](http://127.0.0.1:8080).

The interface provides three dedicated modules:

#### Tab 1: Pipeline & Build (4-Step Wizard)

1. **Configuration:** Set package metadata, export DPI, and verify working directories.
2. **PDF Extraction:** Runs `deck_processor.py` asynchronously with real-time log streaming.
3. **TTPG Compilation:** Runs `ttpg_packager.py` to compile atlases and generate manifests. Includes **pre-flight package detection** to allow skipping re-compilation if valid assets exist.
4. **Installation:** Direct deployment into `%LOCALAPPDATA%\TabletopPlayground\Packages` with live diagnostic logging and Manifest integrity verification.

#### Tab 2: Visual Grid Calibrator (v1.1.0)

* **Auto-Detect Grid:** Runs 1D differential clustering directly on PDF vector cut lines.
* **2-Click Calibration:**
   * **Single Card #1:** Click Card #1 top-left, then bottom-right (calculates origin, width, height, and resets gutters to 0).
   * **Full Grid:** Click Card #1 top-left, then bottom-right of the last card in the grid (divides bounding box across cols and rows).


* **Direct Keyboard Nudge (Conflict-Free):**
   * **Origin (X/Y):** `Arrow Keys` (hold `Shift` for fine 0.1 pt micro-steps)
   * **Card Dimensions (W/H):** `W` / `A` / `S` / `D` (hold `Shift` for fine 0.1 pt micro-steps)
   * **Gutters (X/Y):** `J` / `L` / `I` / `K` (hold `Shift` for fine 0.1 pt micro-steps)
   * **Columns & Rows:** `[` / `]` (cols), `;` / `'` (rows)


* **Save Profile:** Writes calibrated presets straight to `config.json`.

#### Tab 3: Diagnostics & Regression Tests (v1.2.0)

* **Integrated Pytest Runner:** Run all tests or fast regression suites (`test_smoke`, `test_localization`, `test_pdf_analyzer`, `test_packager_install`) directly in the UI with live terminal output.
* **TTPG Installer Mock Test:** Verify package staging and manifest emission in an isolated sandbox.
* **Static Linter (Ruff):** Execute zero-configuration code analysis and fail-fast inspections from the browser.
* **i18n Locale Auto-Sync:** Validate key symmetry between `en.json` and `pl.json` and auto-inject missing translation stubs.

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

### Rules & Suffix Stripping

* **`strip_suffix`**: Trailing text removed from the PDF stem when naming the output folder.
* `"_HQ Cards"`: Converts `Deck_HQ Cards.pdf` into folder name `Deck`.
* `""` (empty string): **No suffix removal**; the output directory retains the clean PDF stem.

### Profiles Breakdown

* **`model`**: `"Rounded"` (playing cards) or `"Square"` (tiles, manuals, full-page sheets).
* **`thickness_cm`**: Physical card thickness in centimeters (default: `0.05` for cards, `0.03` for guidebooks).
* **`duplex_flip`**: Duplex binding transform, dependent on PDF page orientation (Portrait vs. Landscape):
   * `"horizontal"`: Back side columns are mirrored (`cols - 1 - col`). Standard for portrait pages flipped along the long edge, or landscape pages flipped along the short edge.
   * `"vertical"`: Back side rows are mirrored (`rows - 1 - row`). Standard for "calendar-style" flips along the opposing edge.
   * `"none"`: Front and back use the exact same grid coordinates (for single-sided cards or uniform multi-page manuals).


* **`grid`**: PDF coordinate geometry measured in standard PostScript points ($1\text{ pt} = \frac{1}{72}\text{ inch}$):
   * `cols` / `rows`: Grid cells per page.
   * `card_width_pt` / `card_height_pt`: Card cut boundaries.
   * `origin_x_pt` / `origin_y_pt`: Margin offsets from the origin.
   * `gutter_x_pt` / `gutter_y_pt`: Spacing between adjacent cards.



> [!WARNING]
> PostScript points are fixed at $72\text{ pt/inch}$ within PDF specifications. The actual raster resolution in pixels is governed by the top-level `"dpi"` setting. Ensure grid measurements match the authoring vector coordinates, not raster-downsampled values.

---

## Local Overrides (`deck.json`)

To override properties for an individual deck without modifying global rules, place a `deck.json` file inside the PDF's directory in `_INPUT`:

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

> [!TIP]
> Any omitted dimension property falls back to the active profile or pixel-to-DPI calculation. You can also explicitly pass the literal string `"card_width_cm": "auto"` to mandate automatic calculation.

---

## Advanced Mechanics

### Strict Allow-List Processing

`deck_processor.py` processes only files that match an entry in `rules` or have an adjacent `deck.json`. Unmatched files (e.g., `_Eco Cards.pdf`, print/assembly guides) are reported as `[IGNORE]` in the **CLI console log** and skipped, preventing asset collisions.

### Contract Architecture (`deck_meta.json`)

During extraction, `deck_processor.py` writes a structured contract into each deck's output folder:

```json
{
  "source_pdf": "Deck of Worlds Guidebook.pdf",
  "item_type": "document",
  "profile": "full_page_duplex",
  "total_items": 4
}

```

Supported values for `item_type`:

* `"card_deck"`: Standard multi-card grid. Applies rounded card physics and `#001` sequential naming.
* `"document"`: Single-sheet or booklet format ($1 \times 1$ grid). Applies square edges, thinner collision, and `Page X` naming.

### Context-Aware Naming & In-Game Tooltips

* **Stack Names (`Name`):** Prefixed with the package directory using bracket notation (`[Bridge Expansion Set] Lore Master's Deck Guidebook`). Square brackets are a **pipeline convention** to group and identify expansion components cleanly within the TTPG Object Spawner.
* **Individual Card Tooltips (`CardNames`):** When a card is drawn into a player's hand or inspected, its hover tooltip displays the deck title and original index: `Story-Lore Bridge Expansion #003`.
* **Document Pages:** Multi-page manuals and rulesheets display `[Title] - Page 1`, `[Title] - Page 2`, etc.

### Multi-Sheet Unified Templates & `BackIndex: -3`

When a deck exceeds single-sheet texture limits ($8192\text{ px}$ or 100 cards), `ttpg_packager.py`:

1. Enforces uniform grid dimensions across all sheets (`cols` $\times$ `rows`).
2. Generates numbered atlas pairs: `<Deck>_01_front.png`, `<Deck>_01_back.png`, `<Deck>_02_front.png`...
3. Writes a **single** `<GUID>Card.json` linking `ExtraFrontTextures` and `ExtraBackTextures`.
4. Sets `"BackIndex": -3`:
   * In TTPG, `BackIndex: -1` mirrors the front face on the reverse side.
   * `BackIndex: -3` is the native engine flag for **Unique Backs (1:1 slot mapping)**. It instructs TTPG to map slot index $i$ on the front atlas to the exact corresponding slot $i$ on the back atlas across all primary and extra sheets.



### Sub-Pixel Jitter & Dimension Normalization

Vector-to-raster clipping in PyMuPDF with fractional PostScript offsets ($80.95\text{ pt} \times \frac{250\text{ DPI}}{72} = 281.076\text{ px}$) inevitably introduces floating-point discretization jitter ($\pm 1\text{ to } 2\text{ px}$ across rows/columns).

1. **Statistical Canonical Dimension:** `ttpg_packager.py` evaluates all cards in a deck using statistical mode (`Counter.most_common(1)`) to establish canonical width and height.
2. **Strict Tolerance Boundary:** Deviations $\le 2\text{ px}$ (`MAX_JITTER_TOLERANCE_PX`) are automatically normalized to the canonical dimension using high-quality `LANCZOS` resampling during atlas baking.
3. **Fail-Fast Boundary:** Deviations exceeding $2\text{ px}$ immediately trigger `[FAIL-FAST]`, halting execution to protect against genuine aspect-ratio corruption or misaligned grid definitions.

> [!WARNING]
> **Fail-Fast Trigger Conditions
>
> The pipeline aborts execution (`sys.exit(1)`) when:
>
> * An odd page count is detected in double-sided card decks (`item_type: "card_deck"`). Single-page and full-page documents (`item_type: "document"`, $1 \times 1$ grid) are **exempt** from this check.
> * Individual card pixel sizes deviate beyond the $\pm 2\text{ px}$ jitter threshold.
> * Card dimensions exceed hardware texture limits ($> 8192\text{ px}$).
> * Duplex card backs are missing corresponding front cards.
> 
> 

### Fast Calibration via CLI

To preview margins and duplex alignment for a specific PDF before running batch extraction:

```bash
python inspect_deck.py "_INPUT/Core/Story_HQ Cards.pdf"

```

The script crops a single front/back pair into `_DIAGNOSTICS/precise_card_000_[front|back].png` and reports **raw vector-rasterized dimensions** in centimeters (before any packaging normalization) to verify crop accuracy.