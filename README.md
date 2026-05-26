# Autobiographer: Interactive Autobiographical Data Explorer

[![CI](https://github.com/jschloman/autobiographer/actions/workflows/ci.yml/badge.svg)](https://github.com/jschloman/autobiographer/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

<img src="assets/example%20screenshot%20map.png" style="width: 500">

Autobiographer is a Python-based toolkit that lets you fetch, store, and explore your personal life data through a plugin system. Each plugin owns one data source — music listening (Last.fm), location check-ins (Foursquare/Swarm), and more — and exposes a unified fetch-and-display workflow. It transforms your data into an interactive autobiographical experience, highlighting your top artists, listening patterns, milestones, and travel history.


<img src="assets/example%20screenshot%20stats.png" style="width: 500">

## Features

- **Plugin-Based Data Fetching**: Each source plugin handles its own fetch workflow. Plugins that support automatic retrieval (e.g. Last.fm) download data with one command; plugins that require a manual export (e.g. Foursquare/Swarm) print step-by-step instructions. Run `python autobiographer.py list` to see every plugin's status and required configuration.
- **Interactive Dashboard**: A multi-page Streamlit dashboard with:
    - **Overview**: Top Artists, Albums, and Tracks plus a unified **Geo Explorer** with four views — 3D Globe (Pydeck), 2D scatter map, US States choropleth, and a paginated artist-city table.
    - **Music**: Listening timeline, top charts, and AI-powered insights.
    - **Places**: Check-in Insights from Foursquare/Swarm data.
    - **Health**: Fitness activity from supported health plugins.
    - **Culture**: Films & Books and Beer logging.
- **Cinematic Fly-through**: Record smooth 3D globe videos of your listening locations, with optional US state border highlights when filtered data spans specific states.
- **Data Exploration**: Includes a Jupyter Notebook for custom data deep-dives.
- **Secure Handling**: Credentials managed via environment variables.

<img src="assets/flythrough.gif" style="width: 500">

## Data Sources

Autobiographer is built around a plugin system. Each plugin owns a specific data source — its format, how to obtain it, and how it maps into the common schema. All path configuration happens in the sidebar; nothing is hardcoded.

| Plugin | Type | Description |
|--------|------|-------------|
| [Last.fm Music History](plugins/sources/lastfm/README.md) | what-when | Your complete listening history, fetched automatically via the Last.fm API. One click in the sidebar downloads everything. |
| [Foursquare / Swarm Check-ins](plugins/sources/swarm/README.md) | where-when | Your check-in history from the Swarm app. Requires a one-time manual data export request from Foursquare. |
| [Location Assumptions](plugins/sources/assumptions/README.md) | location-context | A user-authored JSON file that fills in your location for periods not covered by Swarm — trips, recurring holidays, and home residency rules. |

Each plugin has its own README with setup instructions, data format details, and schema documentation.

## Quickstart (Docker)

No Python knowledge required — just [Docker](https://www.docker.com/products/docker-desktop/).

```bash
git clone https://github.com/jschloman/autobiographer.git
cd autobiographer
docker compose up
```

Then open **http://localhost:8501** in your browser. The dashboard starts immediately.

Drop your Last.fm CSV into `data/` and it will appear automatically — no container restart needed. The `data/` directory is mounted as a volume: nothing is baked into the image, and your data stays on your machine.

### Fetching your data from within Docker

To download your listening history directly into the mounted data volume, pass your Last.fm credentials:

```bash
cp .env.example .env           # fill in your API key, secret, and username
docker compose run --rm dashboard \
    python autobiographer.py fetch lastfm
docker compose up
```

---

## Manual Setup (Python)

### 1. Prerequisites

- Python 3.9 or higher
- A Last.fm API Key and Secret ([Obtain them here](https://www.last.fm/api/account/create))

### 2. Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/jschloman/autobiographer.git
   cd autobiographer
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### 3. Configuration

Set your credentials as environment variables. Required for Last.fm fetching:
```bash
export AUTOBIO_LASTFM_API_KEY="your_api_key"
export AUTOBIO_LASTFM_API_SECRET="your_api_secret"
export AUTOBIO_LASTFM_USERNAME="your_username"
```

Get a Last.fm API key at: https://www.last.fm/api/account/create

### 4. Usage

#### Fetch Your Data

Start by listing available plugins to see what each one needs:

```bash
python autobiographer.py list
```

This prints every plugin with its fetch mode (auto or manual), required environment
variables with a ✓/✗ status for each, and the exact command to run.

The `fetch` command targets a specific plugin. Plugins that support automatic download
will retrieve your data; plugins that require a manual export will print step-by-step
instructions instead.

```bash
# Download Last.fm listening history (requires env vars above)
python autobiographer.py fetch lastfm

# Print Foursquare/Swarm manual export instructions
python autobiographer.py fetch swarm

# Limit to recent pages or a date range
python autobiographer.py fetch lastfm --pages 5
python autobiographer.py fetch lastfm --from-date 2024-01-01 --to-date 2024-12-31

# Save to a custom location
python autobiographer.py fetch lastfm --output data/my_tracks.csv
```

If a plugin is not yet configured the `fetch` command lists exactly which environment
variables are missing and what each one is for.

The app also exposes fetch directly: a **Fetch Latest Data** button appears for
plugins that support automatic retrieval, and step-by-step manual instructions are
shown for plugins that require a data export from the provider.

#### Launch the Streamlit Dashboard
Start the interactive Streamlit application:
```bash
streamlit run visualize.py
```

#### Export a Static HTML Report
Generate a fully self-contained HTML report that can be opened in any browser without a server or network connection.  All JavaScript is inlined — no external CDN calls are made during rendering.

<img src="assets/example%20web.png" style="width: 500">

```bash
# Listening data only
python export_html.py data/tracks.csv

# With Swarm check-ins — adds a Places tab with a world map
python export_html.py data/tracks.csv --swarm-dir data/swarm/

# Read both paths from local_settings.json (set once via the dashboard)
python export_html.py --from-settings

# Specify a custom output path
python export_html.py data/tracks.csv --output reports/my_report.html
```

The exported file contains tabbed sections:

| Section | Contents | Requires |
|---|---|---|
| **Overview** | Top 20 artists, tracks, and albums by play count | Last.fm CSV |
| **Listening** | Monthly activity timeline and cumulative growth | Last.fm CSV |
| **Insights** | Hour-of-day distribution, day×hour heatmap, milestones, and streaks | Last.fm CSV |
| **Places** | World map (natural-earth projection, no tiles), top cities, top countries | Swarm JSON export |

The report is a single `.html` file — share it by email, host it on any static file server, or keep it locally.  No server process needs to stay running.

**Advanced Usage with Environment Variables:**
You can pre-configure data paths and privacy settings using environment variables.

*Windows (PowerShell):*
```powershell
$env:AUTOBIO_LASTFM_DATA_DIR="C:\MyData\LastFM"; 
$env:AUTOBIO_SWARM_DIR="C:\MyData\Swarm";
$env:AUTOBIO_ASSUMPTIONS_FILE="C:\MyData\private_assumptions.json";
.\venv\Scripts\streamlit run visualize.py
```

*Linux/macOS:*
```bash
export AUTOBIO_LASTFM_DATA_DIR="/home/user/music_data"
export AUTOBIO_SWARM_DIR="/home/user/checkins"
export AUTOBIO_ASSUMPTIONS_FILE="/home/user/my_assumptions.json"
streamlit run visualize.py
```

#### Location Assumptions
To maintain privacy when sharing the codebase, identifying data like home residency and holiday trips are stored in a separate JSON file.
- **Template**: See `default_assumptions.json.example` for the structure.
- **Default**: If no file or Swarm data is provided, the app defaults to **Reykjavik, IS**.
- **Usage**: The app automatically looks for `default_assumptions.json` in the root, or you can specify a custom path via the `AUTOBIO_ASSUMPTIONS_FILE` environment variable.

#### Fly-through Recording
Generate a cinematic 3D fly-through video or HTML animation of your listening locations.

- **Script**: `record_flythrough.py`
- **Features**:
    - Smooth frame-by-frame interpolation using custom easing.
    - High-quality MP4 export using Playwright and MoviePy.
    - Automatically geocodes data if missing (using Swarm/Assumptions).
    - Configurable resolution, FPS, and filtering (artist, dates).
- **Video Generation (.mp4)**:
   ```bash
   python record_flythrough.py path/to/lastfm_tracks.csv --output my_tour.mp4 --artist "Radiohead" --marker_size 7 --fps 30
   ```
- **HTML Animation**:
   ```bash
   python record_flythrough.py path/to/lastfm_tracks.csv --output tour.html --start_date 2023-01-01 --end_date 2023-12-31
   ```

**Available Arguments:**

| Argument | Description | Default |
|---|---|---|
| `csv` | Path to Last.fm tracks CSV (**required**) | — |
| `--output` | Output path; `.mp4` for video, `.html` for interactive animation | `flythrough.mp4` |
| `--artist` | Filter to a single artist name | — |
| `--start_date` / `--end_date` | Inclusive date range filter (`YYYY-MM-DD`) | — |
| `--marker_size` | Marker size scaling — higher values produce smaller, more precise markers | `5.5` |
| `--highlight_states` | Comma-separated US state abbreviations to highlight with polygon borders (e.g. `IL,MD`) | — |
| `--fps` | Video frame rate | `30` |
| `--width` / `--height` | Video resolution in pixels | `1920` / `1080` |
| `--swarm_dir` | Path to Foursquare/Swarm export directory; used to geocode listening data when lat/lng is absent | — |
| `--assumptions` | Path to location assumptions JSON | `default_assumptions.json` |
| `--keep_frames` | Retain temporary per-frame PNG files after encoding | `false` |

*Note: Video generation requires `playwright` and `ffmpeg` (installed automatically during setup).*

#### Exploratory Notebook
Open the Jupyter notebook for custom analysis:
```bash
jupyter notebook notebooks/autobiographer_analysis.ipynb
```

## Tools

Additional utility scripts are available in the `tools/` directory:

- **`add_audio_to_video.py`**: A helper script to mux an audio track (e.g., a top artist's song) with a fly-through video using MoviePy.

## Project Structure

```
autobiographer.py           # Data-fetching CLI (`list`, `fetch <plugin>`) + Last.fm API client
visualize.py                # Streamlit dashboard (assembles views from plugins)
export_html.py              # Static HTML export — single self-contained report file
record_flythrough.py        # Cinematic 3D fly-through video generator (MP4 / HTML)
analysis_utils.py           # Shared data processing and caching logic
core/
  broker.py                 # DataBroker: loads plugins, merges what-when + where-when
pages/
  geo_explorer.py           # Unified Geo Explorer: 3D Globe, 2D Map, US States, Table
  music.py                  # Listening timeline and top charts
  insights.py               # AI-powered listening narrative and milestones
  places.py                 # Foursquare/Swarm check-in insights
  fitness.py                # Health & fitness data
  culture.py                # Films & books
  beer.py                   # Beer log
  overview.py               # Top-level summary stats
plugins/
  sources/
    base.py                 # SourcePlugin ABC + validate_schema()
    __init__.py             # REGISTRY + @register decorator + load_builtin_plugins()
    lastfm/loader.py        # Last.fm source plugin
    swarm/loader.py         # Foursquare/Swarm source plugin
    assumptions/loader.py   # Location assumptions plugin
assets/
  countries.geojson         # Country polygon GeoJSON for 3D globe overlay
  states.geojson            # US state border LineStrings for 3D globe overlay
  us-states-polygons.geojson  # US state polygon GeoJSON with abbreviation properties (highlight layer)
notebooks/                  # Jupyter notebooks for custom analysis
tools/                      # Utility scripts (audio muxing, etc.)
data/                       # Local data storage (CSVs, cache, Swarm JSON exports)
tests/                      # Pytest suite (70%+ coverage)
```

## Plugin Architecture

Autobiographer is built on two non-negotiable design principles that apply to every source plugin without exception.

### 1. Data Sovereignty

Each `SourcePlugin` is the sole authority over its own data. A plugin **knows**:

- Its own raw data format and where to read it from.
- How to normalise that data into the canonical schema.

A plugin **does not know**:

- That any other source exists.
- How its output will be filtered, joined, or merged with other sources.
- Any foreign column names, keys, or schemas.

All cross-source logic — temporal joins, geographic enrichment, correlation — lives exclusively in `DataBroker`. This makes every plugin independently testable, replaceable, and comprehensible in isolation.

```
┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│  LastFmPlugin        │   │  SwarmPlugin          │   │  LetterboxdPlugin    │
│  load() → DataFrame  │   │  load() → DataFrame   │   │  load() → DataFrame  │
│                      │   │                       │   │                      │
│  No knowledge of     │   │  No knowledge of      │   │  No knowledge of     │
│  other sources       │   │  other sources        │   │  other sources       │
└──────────┬───────────┘   └──────────┬────────────┘   └──────────┬───────────┘
           └──────────────────────────┼────────────────────────────┘
                                      ▼
                               ┌─────────────┐
                               │  DataBroker │  ← all joining & merging here
                               └─────────────┘
```

### 2. Download-then-Display

Every plugin operates in two strictly separate phases. **They must never be mixed.**

#### Phase 1 — Collection (download script)

A standalone CLI script fetches data from the external source and writes it to a local file under `data/`. This is the **only** place credentials, API keys, and HTTP calls exist in the codebase.

```bash
# Example: save your Letterboxd diary export locally
python -m autobiographer.sync letterboxd --export-path ~/Downloads/letterboxd.zip
```

The script runs once (or whenever the user wants to refresh their data) and produces a file the plugin can read indefinitely without a network connection.

#### Phase 2 — Display (plugin `load()`)

`SourcePlugin.load()` reads **only** from the previously downloaded local file. It makes **zero** outbound network calls, opens **no** sockets, and requires **no** credentials at runtime. If the local file is absent it raises `FileNotFoundError` with a clear message directing the user to run the download script — it never falls back to a live fetch.

```
┌─────────────────────────────────┐     ┌──────────────────────────────────┐
│  COLLECTION  (run once offline) │     │  DISPLAY  (Streamlit runtime)    │
│                                 │     │                                   │
│  python -m autobiographer.sync  │────▶│  LetterboxdPlugin.load()         │
│    letterboxd                   │     │    reads data/letterboxd.csv      │
│                                 │     │    — zero network calls           │
│  credentials live here only     │     │                                   │
└─────────────────────────────────┘     └──────────────────────────────────┘
```

### Adding a source plugin

Follow these four steps. The contract above applies to every plugin — no exceptions.

**1. Create the download script**, e.g. `autobiographer/sync/letterboxd.py`:

```python
"""Letterboxd: save diary export to data/letterboxd.csv (run once offline)."""
import argparse, zipfile, pathlib

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-path", required=True, help="Path to the Letterboxd ZIP")
    args = parser.parse_args()
    with zipfile.ZipFile(args.export_path) as zf:
        zf.extract("diary.csv", "data/")
    pathlib.Path("data/letterboxd.csv").rename(pathlib.Path("data/letterboxd_diary.csv"))
    print("Saved → data/letterboxd_diary.csv")

if __name__ == "__main__":
    main()
```

**2. Create the plugin file**, e.g. `plugins/sources/letterboxd/loader.py`:

```python
from __future__ import annotations
from typing import Any
import pandas as pd
from plugins.sources import register
from plugins.sources.base import SourcePlugin, validate_schema

@register
class LetterboxdPlugin(SourcePlugin):
    PLUGIN_TYPE = "what-when"
    PLUGIN_ID = "letterboxd"
    DISPLAY_NAME = "Letterboxd Film Diary"
    ICON = ":material/movie:"

    def get_config_fields(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "data_path",
                "label": "Letterboxd diary CSV",
                "type": "file_path",
                "file_types": [("CSV files", "*.csv"), ("All files", "*.*")],
            }
        ]

    def load(self, config: dict[str, Any]) -> pd.DataFrame:
        """Load previously downloaded Letterboxd diary from a local CSV.

        Zero network calls are made here. Raises FileNotFoundError if the
        export file has not been downloaded yet.
        """
        data_path: str = config["data_path"]
        if not data_path:
            return pd.DataFrame()
        # load() reads local data only — no REST calls, no credentials
        df = pd.read_csv(data_path)
        df = df.assign(
            label=df["Name"],
            sublabel=df["Name"],
            category=df["Year"].astype(str),
            source_id=self.PLUGIN_ID,
        )
        validate_schema(df, self.PLUGIN_TYPE)
        return df
```

**3. Register it** in `plugins/sources/__init__.py`:

```python
def load_builtin_plugins() -> None:
    import plugins.sources.lastfm.loader      # noqa: F401
    import plugins.sources.swarm.loader       # noqa: F401
    import plugins.sources.letterboxd.loader  # noqa: F401  ← add this
```

**4. Add tests** in `tests/test_source_plugins.py` following the `TestLastFmPlugin` pattern. Always mock the file-read call — tests must never touch the network or require local data files.

### Config field types

`get_config_fields()` returns field descriptors rendered as path selectors in the sidebar. Each plugin's selectors are grouped in their own collapsible section.

| `type` | Widget | Use for |
|---|---|---|
| `"file_path"` | Text input + file picker | Single export files (CSV, JSON, ZIP) |
| `"dir_path"` | Text input + folder picker | Export directories with multiple files |
| `"text"` | Plain text input | Non-path settings |
| `"toggle"` | Checkbox | Boolean options |

Add `"file_types": [("CSV files", "*.csv")]` to any `file_path` field to pre-filter the picker dialog.

Selected paths are persisted to `data/config.json` so they survive application restarts.

### Plugin schema

| `PLUGIN_TYPE` | Required columns |
|---|---|
| `what-when` | `timestamp`, `label`, `sublabel`, `category`, `source_id` |
| `where-when` | `timestamp`, `lat`, `lng`, `place_name`, `place_type`, `source_id` |
| `location-context` | No required columns — defines enrichment data, not a primary stream |

`validate_schema()` raises `ValueError` at load time if any required column is absent.

### Using the DataBroker directly

```python
from plugins.sources import load_builtin_plugins, REGISTRY
from core.broker import DataBroker

load_builtin_plugins()
broker = DataBroker()
broker.load(REGISTRY["lastfm"](), {"data_path": "data/tracks.csv"})
broker.load(REGISTRY["swarm"](), {"swarm_dir": "data/swarm"})

df = broker.get_merged_frame(assumptions=my_assumptions)  # temporally joined
broker.is_type_available("where-when")  # → True
```

## Contributing

Contributions are welcome! Please follow the engineering standards in `CLAUDE.md`:
1. Create a descriptive feature branch using [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `perf:`, etc.).
2. Implement your changes with test coverage (80% minimum).
3. Run the local quality gate before pushing: `ruff check . && ruff format --check . && mypy && pytest`
4. Submit a Pull Request — the PR title must also follow Conventional Commits format.

## License

GNU General Public License v3.0





