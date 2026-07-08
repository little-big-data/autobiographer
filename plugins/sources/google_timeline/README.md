# Google Maps Timeline

## What it is

Google Maps Timeline is Google's personal location history. When Timeline is enabled, your phone records where you spent time (**visits** to places such as home, work, shops, and restaurants) and how you moved between them (**activities** such as walking, driving, or taking the subway), each with coordinates and timestamps. Over months and years this becomes a detailed location diary.

Autobiographer imports this history so you can map where you have been, analyse travel patterns, and cross-reference locations against your music listening activity — the same way it uses Foursquare/Swarm check-ins.

## How the data is obtained

Timeline data now lives on your device, so **it must be exported manually**. This is a one-time step: once you have the exported `Timeline.json` you can keep it on disk and re-point the plugin at it whenever needed. The plugin never contacts Google — it only reads the file you export.

Autobiographer supports the **new on-device export format** (a single `Timeline.json` containing a `semanticSegments` array). The older Takeout "Semantic Location History" / `Records.json` format is not supported.

## Setup

### 1. Export your Timeline

**Option A — from your phone (recommended):**

1. Open **Settings** on your Android phone.
2. Go to **Location → Location Services → Timeline**.
3. Tap **Export Timeline data** and save the file.
4. Copy the exported `Timeline.json` to your computer.

**Option B — Google Takeout:**

1. Visit [takeout.google.com](https://takeout.google.com).
2. Deselect all, then select only **Location History (Timeline)**.
3. Create the export and download the archive.
4. Unzip it and locate the `Timeline.json` file.

### 2. Point the plugin at the file

In the Autobiographer sidebar, expand **Google Maps Timeline** and click **…** next to **Google Timeline JSON file**. Navigate to your exported `Timeline.json` and select it.

## Data produced

| Column | Description |
|--------|-------------|
| `timestamp` | Unix timestamp of the visit or activity start (UTC) |
| `lat` | Latitude (WGS84) |
| `lng` | Longitude (WGS84) |
| `place_name` | Frequent-place label, or a humanized visit/activity type |
| `place_type` | Semantic visit type (e.g. `"home"`, `"work"`) or `"activity:<type>"` |
| `source_id` | Always `"google_timeline"` |

Visits are named from your Google "frequent places" labels when available, otherwise from the semantic type (Home, Work, …). City / state / country are filled in offline from the coordinates — no network requests are made. Precise venue names are not resolved, as that would require an online geocoding API.
