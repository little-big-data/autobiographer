# Autobiographer: Interactive Autobiographical Data Explorer

[![CI](https://github.com/jschloman/autobiographer/actions/workflows/ci.yml/badge.svg)](https://github.com/jschloman/autobiographer/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

<img src="assets/example%20screenshot%20map.png" style="width: 500">

Autobiographer is a Streamlit dashboard that turns your personal life data into an interactive autobiographical experience — top artists, listening patterns, milestones, travel history, and more. It reads from a local DuckDB file populated by **[localizer](packages/localizer/README.md)**, a standalone data-fetch layer that handles everything from Last.fm to Foursquare check-ins.

<img src="assets/example%20screenshot%20stats.png" style="width: 500">

## Architecture

```
localizer sync                   ← fetches data from all configured sources
        │
        ▼
~/.localizer/store.duckdb        ← single DuckDB file, your data stays local
        │
        ▼
streamlit run visualize.py       ← reads from DuckDB via LocalizerBroker
```

Data fetching and data display are completely decoupled. `localizer sync` populates the store; autobiographer reads it. You can run them on different schedules (e.g. sync via cron nightly, open the dashboard whenever you want).

## Features

- **Multi-source data platform**: Music (Last.fm), location check-ins (Foursquare/Swarm), films (Letterboxd), articles (Feedly, RSS), commits (GitHub) — all normalised into a single local DuckDB file by the `localizer` package.
- **Interactive Dashboard**: A multi-page Streamlit app with:
    - **Overview**: Top Artists, Albums, and Tracks plus a unified **Geo Explorer** with four views — 3D Globe (Pydeck), 2D scatter map, US States choropleth, and a paginated artist-city table.
    - **Music**: Listening timeline, top charts, and AI-powered insights.
    - **Places**: Check-in insights from Foursquare/Swarm data.
    - **Health**: Fitness activity from supported health plugins.
    - **Culture**: Films & Books and Beer logging.
- **Cinematic Fly-through**: Record smooth 3D globe videos of your listening locations, with optional US state border highlights.
- **Data Exploration**: Includes a Jupyter Notebook for custom data deep-dives.
- **Local-first**: All data is stored in `~/.localizer/store.duckdb` on your machine. No cloud account required.

<img src="assets/flythrough.gif" style="width: 500">

## Quickstart (Docker)

No Python knowledge required — just [Docker](https://www.docker.com/products/docker-desktop/).

```bash
git clone https://github.com/jschloman/autobiographer.git
cd autobiographer
docker compose up
```

Then open **http://localhost:8501** in your browser.

To populate data, run localizer sync from within the container:

```bash
cp .env.example .env           # fill in your credentials
docker compose run --rm dashboard localizer sync
docker compose up
```

---

## Manual Setup (Python)

### 1. Prerequisites

- Python 3.9 or higher
- A Last.fm API Key and Secret ([Obtain them here](https://www.last.fm/api/account/create))

### 2. Installation

```bash
git clone https://github.com/jschloman/autobiographer.git
cd autobiographer

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install localizer first (monorepo sub-package), then autobiographer
pip install -e packages/localizer/
pip install -e .
```

### 3. Configuration

#### API credentials (`.env` file)

Copy `.env.example` to `.env` and fill in your credentials. `localizer` loads this file automatically — no `export` needed.

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Last.fm — required for music data
# Get a key at: https://www.last.fm/api/account/create
AUTOBIO_LASTFM_API_KEY=your_api_key
AUTOBIO_LASTFM_API_SECRET=your_api_secret
AUTOBIO_LASTFM_USERNAME=your_username

# GitHub — optional, fetches commit history
LOCALIZER_GITHUB_TOKEN=ghp_...

# Feedly — optional, fetches reading list
LOCALIZER_FEEDLY_TOKEN=...
```

#### File-based sources (`localizer config set`)

Sources that require a local file export are configured via `localizer config`, which writes to `~/.localizer/config.toml`:

```bash
# Foursquare / Swarm — point at your unzipped Foursquare data export directory
localizer config set swarm_dir /path/to/foursquare-export/

# Letterboxd — point at the diary.csv from your Letterboxd data export
localizer config set csv_path /path/to/letterboxd/diary.csv

# Location assumptions — path to your default_assumptions.json file
# This tells the dashboard your home city, residency history, trips, and holidays
localizer config set assumptions_path /path/to/default_assumptions.json
```

To review what's currently configured:

```bash
localizer config show
```

#### RSS feeds

RSS/Atom feeds are configured through the Streamlit sidebar at runtime.

### 4. Fetch your data

```bash
localizer sync
```

This fetches all configured sources and writes records to `~/.localizer/store.duckdb`. Run this whenever you want fresh data. Subsequent runs are incremental — only new records are fetched.

To see what's stored:

```bash
localizer status
```

### 5. Launch the dashboard

```bash
streamlit run visualize.py
```

---

## Data Sources

All sources are managed by the `localizer` package. See [packages/localizer/README.md](packages/localizer/README.md) for full setup instructions per source.

| Source | Fetch mode | Output table | Description |
|---|---|---|---|
| Last.fm | API (automatic) | events | Complete listening history via Last.fm API |
| Foursquare / Swarm | Manual export | places | Check-in history from the Swarm app |
| GitHub | API (automatic) | events | Commit history across your repositories |
| Feedly | API (automatic) | content | Articles from your Feedly reading list |
| RSS / Atom | Local parse | content | Any RSS or Atom feed (including Goodreads) |
| Letterboxd | Manual export | events | Film diary from Letterboxd |

---

## Export a Static HTML Report

Generate a fully self-contained HTML report openable in any browser without a server.

<img src="assets/example%20web.png" style="width: 500">

```bash
python export_html.py data/tracks.csv
python export_html.py data/tracks.csv --swarm-dir data/swarm/
python export_html.py --from-settings
python export_html.py data/tracks.csv --output reports/my_report.html
```

| Section | Contents |
|---|---|
| **Overview** | Top 20 artists, tracks, albums |
| **Listening** | Monthly timeline and cumulative growth |
| **Insights** | Hour-of-day, day×hour heatmap, milestones, streaks |
| **Places** | World map, top cities, top countries (requires Swarm) |

---

## Fly-through Recording

Record a cinematic 3D fly-through video of your listening locations.

```bash
python record_flythrough.py path/to/lastfm_tracks.csv --output my_tour.mp4 --artist "Radiohead" --fps 30
python record_flythrough.py path/to/lastfm_tracks.csv --output tour.html --start_date 2023-01-01 --end_date 2023-12-31
```

| Argument | Description | Default |
|---|---|---|
| `csv` | Path to Last.fm tracks CSV (**required**) | — |
| `--output` | `.mp4` for video, `.html` for animation | `flythrough.mp4` |
| `--artist` | Filter to one artist | — |
| `--start_date` / `--end_date` | Date range (`YYYY-MM-DD`) | — |
| `--fps` | Frame rate | `30` |
| `--width` / `--height` | Resolution in pixels | `1920` / `1080` |
| `--highlight_states` | US states to outline (e.g. `IL,MD`) | — |

*Requires `playwright` and `ffmpeg`.*

---

## Project Structure

```
packages/
  localizer/                   # standalone data-fetch package (see its own README)
    src/localizer/
      cli.py                   # `localizer` CLI (sync, fetch, status, export, db, config)
      store/db.py              # LocalizerStore — DuckDB read/write
      plugins/                 # SourcePlugin ABC + all fetchers
        lastfm/, swarm/, feedly/, github/, rss/, letterboxd/

autobiographer.py              # legacy fetch CLI (deprecated — use `localizer` instead)
visualize.py                   # Streamlit dashboard entry point
export_html.py                 # static HTML report generator
record_flythrough.py           # cinematic 3D fly-through video generator
analysis_utils.py              # shared data processing and caching logic

core/
  broker.py                    # LocalizerBroker (reads DuckDB) + DataBroker (legacy shim)
  analysis_loader.py           # bridge: load_lastfm_history(), load_swarm_history()
  fetch_utils.py               # re-exports from localizer.fetch_utils

plugins/sources/               # autobiographer-specific plugin wrappers (thin shims)
  base.py                      # re-exports SourcePlugin, FetchMode, OutputTable from localizer
  lastfm/, swarm/, assumptions/

pages/                         # Streamlit page modules
  geo_explorer.py, music.py, insights.py, places.py, overview.py …

assets/                        # GeoJSON files for globe/map layers
tests/                         # pytest suite (70%+ coverage)
```

---

## Plugin Architecture

Autobiographer's data layer is built on two principles inherited from localizer.

### Data Sovereignty

Each `SourcePlugin` owns exactly one data source. It knows its own format and normalisation; it knows nothing about other sources. All cross-source logic (temporal joins, geographic enrichment) lives in `LocalizerBroker` — never in a plugin.

### Download-then-Display

Fetching and display are strictly separated phases. `localizer sync` (or `localizer fetch <source>`) downloads data and writes it to DuckDB. The Streamlit dashboard reads from DuckDB only — it makes zero outbound network calls at render time.

```
┌─────────────────────────────┐     ┌───────────────────────────────┐
│  FETCH  (localizer sync)    │     │  DISPLAY  (streamlit run)     │
│                             │     │                               │
│  credentials live here only │────▶│  LocalizerBroker reads DuckDB │
│  writes to store.duckdb     │     │  zero network calls           │
└─────────────────────────────┘     └───────────────────────────────┘
```

### Reading from DuckDB in Python

```python
from localizer.store.db import LocalizerStore

with LocalizerStore() as store:
    events = store.query_events(source_id="lastfm")   # → pd.DataFrame
    places = store.query_places(source_id="swarm")
```

### Adding a source plugin

See [packages/localizer/README.md#writing-a-plugin](packages/localizer/README.md#writing-a-plugin) for the full guide. In short:

1. Subclass `SourcePlugin` with `@register`.
2. Implement `fetch_records()` as a generator that yields one dict per record.
3. Add it to `load_builtin_plugins()` in `localizer/plugins/__init__.py`.
4. Add tests using mocked HTTP responses (no real network calls in tests).

---

## Exploratory Notebook

```bash
jupyter notebook notebooks/autobiographer_analysis.ipynb
```

---

## Contributing

Follow the engineering standards in `CLAUDE.md`:

1. Create a feature branch (`feat:`, `fix:`, etc.).
2. Install both packages before developing: `pip install -e packages/localizer/ && pip install -e .`
3. Run the quality gate before pushing: `ruff check . && ruff format --check . && mypy && pytest`
4. Submit a PR with a Conventional Commits title.

---

## License

GNU General Public License v3.0
