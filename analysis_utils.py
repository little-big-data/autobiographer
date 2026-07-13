import glob
import hashlib
import json
import math
import os
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from localizer.plugins.google_timeline.parser import (  # noqa: F401
    _WHERE_WHEN_COLUMNS,
    _parse_latlng,
    load_google_timeline,
)


def _get_ruptures() -> Optional[Any]:
    """Lazily import ruptures (pulls in scipy) only when changepoint detection runs."""
    try:
        import ruptures as _r

        return _r
    except (ImportError, Exception):
        return None


def get_cache_key(
    lastfm_file: str,
    swarm_dir: Optional[str] = None,
    assumptions_file: Optional[str] = None,
    timeline_path: str = "",
) -> str:
    """Generate a unique cache key based on input files and their modification times."""
    if not os.path.exists(lastfm_file):
        return "none"

    lastfm_mtime = os.path.getmtime(lastfm_file)
    key_parts = [lastfm_file, str(lastfm_mtime)]

    if swarm_dir and os.path.isdir(swarm_dir):
        # Sort files to ensure deterministic key
        swarm_files = sorted(glob.glob(os.path.join(swarm_dir, "checkins*.json")))
        for f in swarm_files:
            key_parts.append(f)
            key_parts.append(str(os.path.getmtime(f)))

    if assumptions_file and os.path.exists(assumptions_file):
        key_parts.append(assumptions_file)
        key_parts.append(str(os.path.getmtime(assumptions_file)))

    if timeline_path and os.path.exists(timeline_path):
        key_parts.append(timeline_path)
        key_parts.append(str(os.path.getmtime(timeline_path)))

    # Include version to invalidate cache if logic changes
    key_parts.append("v1.6")

    return hashlib.md5("".join(key_parts).encode(), usedforsecurity=False).hexdigest()  # noqa: S324


def get_cached_data(cache_key: str, cache_dir: str = "data/cache") -> Optional[pd.DataFrame]:
    """Retrieve processed data from cache if it exists."""
    if cache_key == "none":
        return None

    cache_path = os.path.join(cache_dir, f"{cache_key}.csv.gz")
    if os.path.exists(cache_path):
        try:
            df = pd.read_csv(cache_path, compression="gzip")
            if "date_text" in df.columns:
                df["date_text"] = pd.to_datetime(df["date_text"])
            return df
        except Exception as e:
            print(f"Warning: failed to read cache at {cache_path}: {e}")
    return None


def save_to_cache(df: pd.DataFrame, cache_key: str, cache_dir: str = "data/cache") -> None:
    """Save processed data to cache."""
    if cache_key == "none":
        return

    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{cache_key}.csv.gz")
    try:
        df.to_csv(cache_path, index=False, compression="gzip")
    except Exception as e:
        print(f"Error saving to cache: {e}")


def load_assumptions(assumptions_file: Optional[str]) -> dict[str, Any]:
    """Load location assumptions from a JSON file."""
    default_data = {
        "defaults": {
            "city": "Reykjavik, IS",
            "state": "IS",
            "country": "Iceland",
            "lat": 64.1265,
            "lng": -21.8174,
            "timezone": "Atlantic/Reykjavik",
        },
        "holidays": [],
        "trips": [],
        "residency": [],
    }

    if not assumptions_file or not os.path.exists(assumptions_file):
        return default_data

    try:
        with open(assumptions_file) as f:
            user_data = json.load(f)
            # Merge with defaults to ensure all keys exist
            for key in default_data:
                if key not in user_data:
                    user_data[key] = default_data[key]
            return user_data  # type: ignore[no-any-return]
    except Exception as e:
        print(f"Error loading assumptions: {e}")
        return default_data


def load_listening_data(file_path: str) -> Optional[pd.DataFrame]:
    """Load and preprocess listening history from CSV."""
    if not os.path.exists(file_path):
        return None
    try:
        df = pd.read_csv(file_path)
        if "date_text" in df.columns:
            df["date_text"] = pd.to_datetime(df["date_text"])

        # Ensure we have a unix timestamp for lookup (Last.fm 'uts')
        if "timestamp" not in df.columns and "date_text" in df.columns:
            df["timestamp"] = df["date_text"].astype("int64") // 10**9

        return df
    except Exception:
        return None


def load_swarm_data(swarm_dir: str) -> pd.DataFrame:
    """Load and parse Swarm checkin data from JSON files."""
    all_checkins = []
    if not swarm_dir or not os.path.exists(swarm_dir):
        return pd.DataFrame(
            columns=[
                "timestamp",
                "offset",
                "city",
                "state",
                "country",
                "venue",
                "venue_category",
                "lat",
                "lng",
                "event_category",
                "shout",
            ]
        )

    json_files = glob.glob(os.path.join(swarm_dir, "checkins*.json"))
    for file_path in json_files:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                items = data.get("items", [])
                for item in items:
                    raw_created_at = item.get("createdAt")
                    if raw_created_at is None:
                        continue

                    try:
                        if isinstance(raw_created_at, (int, float)):
                            created_at = pd.to_datetime(raw_created_at, unit="s", utc=True)
                        else:
                            created_at = pd.to_datetime(raw_created_at, utc=True)
                        ts = int(created_at.timestamp())
                    except (ValueError, TypeError):
                        continue

                    offset = item.get("timeZoneOffset", 0)
                    venue = item.get("venue") or {}
                    location = venue.get("location") or {}

                    city = location.get("city")
                    state = location.get("state")
                    country = location.get("country")

                    # Track whether this item has no geographic text at all so
                    # we can batch-reverse-geocode from lat/lng after the loop.
                    needs_geocode = not (city or state or country)

                    if not city:
                        city = state or country or venue.get("name", "Unknown")
                    if not state:
                        state = country or "Unknown"
                    if not country:
                        country = "Unknown"

                    lat = item.get("lat") or location.get("lat")
                    lng = item.get("lng") or location.get("lng")

                    categories = venue.get("categories", [])
                    venue_category = categories[0].get("name", "") if categories else ""

                    event_cats = item.get("event", {}).get("categories", [])
                    event_category = event_cats[0].get("name", "") if event_cats else ""
                    shout = item.get("shout", "") or ""

                    all_checkins.append(
                        {
                            "timestamp": ts,
                            "offset": offset,
                            "city": city,
                            "state": state,
                            "country": country,
                            "venue": venue.get("name", "Unknown"),
                            "venue_category": venue_category,
                            "lat": lat,
                            "lng": lng,
                            "_needs_geocode": needs_geocode and lat is not None and lng is not None,
                            "event_category": event_category,
                            "shout": shout,
                        }
                    )
        except Exception as e:
            print(f"Error loading {file_path}: {e}")

    if not all_checkins:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "offset",
                "city",
                "state",
                "country",
                "venue",
                "venue_category",
                "lat",
                "lng",
                "event_category",
                "shout",
            ]
        )

    df = pd.DataFrame(all_checkins)

    # Reverse-geocode rows that had no city/state/country in the export but do
    # have coordinates (common in newer Foursquare GDPR exports which omit
    # venue.location entirely).
    geo_mask = df["_needs_geocode"].astype(bool)
    if geo_mask.any():
        try:
            import reverse_geocoder as rg  # optional dependency

            coords = list(zip(df.loc[geo_mask, "lat"], df.loc[geo_mask, "lng"]))
            results = rg.search(coords, verbose=False)
            df.loc[geo_mask, "city"] = [r["name"] for r in results]
            df.loc[geo_mask, "state"] = [r.get("admin1", r["cc"]) for r in results]
            df.loc[geo_mask, "country"] = [r["cc"] for r in results]
        except ImportError:
            pass  # degrade to venue-name / "Unknown" fallbacks already set

    df = df.drop(columns=["_needs_geocode"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp")
    return df


def infer_residency_periods(
    swarm_df: pd.DataFrame,
    radius_km: float = 48.0,
    min_months: int = 3,
) -> list[dict[str, str]]:
    """Infer home-base residency periods from Swarm check-in coordinates.

    Applies a five-step algorithm:
    1. Greedy haversine radius merge to cluster coordinates into metro areas.
    2. Monthly plurality vote to assign each calendar month to a cluster.
    3. Forward-fill sparse months (no back-fill for leading gaps).
    4. Stability filter: only keep runs of >= min_months consecutive months.
    5. Collapse qualifying runs into period dicts with city, start, end.

    Args:
        swarm_df: DataFrame with columns timestamp (int unix seconds),
            lat (float), lng (float), city (str).
        radius_km: Merge radius in kilometres for greedy clustering.
        min_months: Minimum consecutive months required to declare a residency.

    Returns:
        List of dicts with keys ``city``, ``start``, ``end`` (ISO date strings),
        sorted by start date.  Returns ``[]`` on edge-case inputs.
    """
    # --- Guard: required columns ---
    if swarm_df is None or swarm_df.empty:
        return []
    if "lat" not in swarm_df.columns or "lng" not in swarm_df.columns:
        return []

    # --- Drop rows with null lat/lng ---
    df = swarm_df.dropna(subset=["lat", "lng"]).copy()
    if df.empty:
        return []

    # Ensure city column exists; fill missing/None with empty string
    if "city" not in df.columns:
        df["city"] = ""
    df["city"] = df["city"].fillna("").astype(str)

    # --- Step 1: Greedy haversine radius merge ---
    # Collect unique (lat, lng) pairs and their city labels
    unique_coords = df[["lat", "lng", "city"]].copy()
    unique_coords["lat"] = unique_coords["lat"].astype(float)
    unique_coords["lng"] = unique_coords["lng"].astype(float)

    # cluster_centroids: list of [mean_lat, mean_lng, total_count]
    # cluster_city_counts: list of dict {city: count}
    cluster_centroids: list[list[float]] = []
    cluster_city_counts: list[dict[str, int]] = []
    # Maps row index to cluster index
    coord_cluster: list[int] = []

    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Return haversine distance in km between two coordinate pairs."""
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
        )
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    for _, row in unique_coords.iterrows():
        lat, lng, city = float(row["lat"]), float(row["lng"]), str(row["city"])
        best_idx = -1
        best_dist = float("inf")
        for ci, centroid in enumerate(cluster_centroids):
            d = _haversine(lat, lng, centroid[0], centroid[1])
            if d < best_dist:
                best_dist = d
                best_idx = ci

        if best_idx >= 0 and best_dist <= radius_km:
            # Assign to existing cluster and recompute centroid
            count = cluster_centroids[best_idx][2]
            cluster_centroids[best_idx][0] = (cluster_centroids[best_idx][0] * count + lat) / (
                count + 1
            )
            cluster_centroids[best_idx][1] = (cluster_centroids[best_idx][1] * count + lng) / (
                count + 1
            )
            cluster_centroids[best_idx][2] = count + 1
            coord_cluster.append(best_idx)
            if city:
                cluster_city_counts[best_idx][city] = cluster_city_counts[best_idx].get(city, 0) + 1
        else:
            # Start a new cluster
            new_idx = len(cluster_centroids)
            cluster_centroids.append([lat, lng, 1.0])
            city_counts: dict[str, int] = {}
            if city:
                city_counts[city] = 1
            cluster_city_counts.append(city_counts)
            coord_cluster.append(new_idx)

    # Label each cluster by most-frequent city name
    cluster_labels: list[str] = []
    for city_counts in cluster_city_counts:
        if city_counts:
            cluster_labels.append(max(city_counts, key=lambda k: city_counts[k]))
        else:
            cluster_labels.append("Unknown")

    # Assign cluster index to every row in df by matching (lat, lng)
    # Build a lookup: (lat, lng) -> cluster index
    coord_to_cluster: dict[tuple[float, float], int] = {}
    for i, row in enumerate(unique_coords.itertuples(index=False)):
        coord_to_cluster[(float(row.lat), float(row.lng))] = coord_cluster[i]

    df["_cluster"] = df.apply(
        lambda r: coord_to_cluster.get((float(r["lat"]), float(r["lng"])), 0), axis=1
    )
    df["_cluster_label"] = df["_cluster"].apply(lambda c: cluster_labels[c])

    # --- Step 2: Monthly plurality vote ---
    df["_month"] = pd.to_datetime(df["timestamp"], unit="s").dt.to_period("M")

    month_clusters = df.groupby(["_month", "_cluster"]).size().reset_index(name="count")
    # For each month, pick the cluster with the highest count (ties: lowest cluster index)
    idx = month_clusters.groupby("_month")["count"].idxmax()
    month_winner = month_clusters.loc[idx].set_index("_month")["_cluster"]
    # Convert cluster index to label
    month_label: pd.Series = month_winner.map(lambda c: cluster_labels[c])

    # --- Step 3: Forward-fill sparse months ---
    all_months = pd.period_range(month_label.index.min(), month_label.index.max(), freq="M")
    month_label = month_label.reindex(all_months)
    month_label = month_label.ffill()
    # Drop leading NaN (months before first check-in — no back-fill)
    month_label = month_label.dropna()

    if month_label.empty:
        return []

    # --- Step 4: Stability filter ---
    # Identify runs and mark months in runs of length >= min_months
    labels_list = month_label.tolist()
    months_list = month_label.index.tolist()
    n = len(labels_list)

    # Compute run lengths
    qualifying: list[bool] = [False] * n
    i = 0
    while i < n:
        j = i
        while j < n and labels_list[j] == labels_list[i]:
            j += 1
        run_len = j - i
        if run_len >= min_months:
            for k in range(i, j):
                qualifying[k] = True
        i = j

    # --- Step 5: Collapse qualifying months into period dicts ---
    # Build a list of (city_label, month_period) for qualifying months only,
    # then merge consecutive entries with the same label — even if there were
    # non-qualifying months between two same-label qualifying runs (blip eaten).
    qualifying_entries: list[tuple[str, Any]] = [
        (labels_list[k], months_list[k]) for k in range(n) if qualifying[k]
    ]

    periods: list[dict[str, str]] = []
    ei = 0
    while ei < len(qualifying_entries):
        city_label, run_start_period = qualifying_entries[ei]
        run_end_period = run_start_period
        ei += 1
        while ei < len(qualifying_entries) and qualifying_entries[ei][0] == city_label:
            run_end_period = qualifying_entries[ei][1]
            ei += 1
        start_str = run_start_period.to_timestamp("D", how="start").strftime("%Y-%m-%d")
        end_str = run_end_period.to_timestamp("D", how="end").strftime("%Y-%m-%d")
        periods.append({"city": city_label, "start": start_str, "end": end_str})

    return sorted(periods, key=lambda d: d["start"])


def get_assumption_location(ts: int, assumptions: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Get location and offset based on runtime assumptions (Issue #39).
    This is a non-vectorized version mainly used for tests and single lookups.
    """
    dt_utc = pd.to_datetime([ts], unit="s", utc=True)

    # Recurring holiday check — skip placeholder holidays (lat=0, lng=0) used
    # only for analytics, not for location assignment.
    for holiday in assumptions.get("holidays", []):
        if holiday.get("lat", 0) == 0 and holiday.get("lng", 0) == 0:
            continue
        tz = holiday.get("timezone", "UTC")
        local_time = dt_utc.tz_convert(tz)[0]
        month = holiday.get("month")
        day_range = holiday.get("day_range", [])
        if local_time.month == month and day_range[0] <= local_time.day <= day_range[1]:
            return {
                "offset": int(local_time.utcoffset().total_seconds() / 60),
                "city": holiday.get("city"),
                "state": holiday.get("state", holiday.get("city")),
                "country": holiday.get("country", "Unknown"),
                "lat": holiday.get("lat"),
                "lng": holiday.get("lng"),
            }

    # Trip check
    for trip in assumptions.get("trips", []):
        start = pd.to_datetime(trip.get("start")).date()
        end = pd.to_datetime(trip.get("end")).date()
        tz = trip.get("timezone", "UTC")
        local_time = dt_utc.tz_convert(tz)[0]
        if start <= local_time.date() <= end:
            return {
                "offset": int(local_time.utcoffset().total_seconds() / 60),
                "city": trip.get("city"),
                "state": trip.get("state", trip.get("city")),
                "country": trip.get("country", "Unknown"),
                "lat": trip.get("lat"),
                "lng": trip.get("lng"),
            }

    # Residency check
    dt_naive = dt_utc[0].replace(tzinfo=None)
    for res in assumptions.get("residency", []):
        start = pd.to_datetime(res.get("start")).replace(tzinfo=None)
        end = pd.to_datetime(res.get("end")).replace(tzinfo=None)
        if start <= dt_naive <= end:
            for rule in res.get("sub_rules", []):
                tz = rule.get("timezone", "UTC")
                local_time = dt_utc.tz_convert(tz)[0]
                cond = rule.get("condition")
                if cond == "work_hours":
                    if local_time.weekday() < 5 and (
                        (local_time.hour == 8 and local_time.minute >= 30)
                        or (9 <= local_time.hour < 16)
                        or (local_time.hour == 16 and local_time.minute <= 30)
                    ):
                        return {
                            "offset": int(local_time.utcoffset().total_seconds() / 60),
                            "city": rule.get("city"),
                            "state": rule.get("state", rule.get("city")),
                            "country": rule.get("country", "Unknown"),
                            "lat": rule.get("lat"),
                            "lng": rule.get("lng"),
                        }
                elif cond == "home_logic":
                    home_1_end = pd.to_datetime(rule.get("home_1_end")).replace(tzinfo=None)
                    use_home_1 = dt_naive <= home_1_end
                    return {
                        "offset": int(local_time.utcoffset().total_seconds() / 60),
                        "city": rule.get("city_1") if use_home_1 else rule.get("city_2"),
                        "state": (rule.get("state_1") if use_home_1 else rule.get("state_2"))
                        or (rule.get("city_1") if use_home_1 else rule.get("city_2")),
                        "country": rule.get("country", "Unknown"),
                        "lat": rule.get("lat_1") if use_home_1 else rule.get("lat_2"),
                        "lng": rule.get("lng_1") if use_home_1 else rule.get("lng_2"),
                    }
            return {
                "offset": 0,
                "city": res.get("city"),
                "state": res.get("state", res.get("city")),
                "country": res.get("country", "Unknown"),
                "lat": res.get("lat"),
                "lng": res.get("lng"),
            }
    return None


def apply_location_context(
    lastfm_df: pd.DataFrame,
    swarm_df: pd.DataFrame,
    assumptions: dict[str, Any],
    max_age_days: int = 30,
) -> pd.DataFrame:
    """
    Adjust Last.fm track timestamps and locations based on location-source checkins
    (Swarm, Google Location History, Google Timeline, etc. — any ``places``-shaped
    frame, regardless of ``source_id``) or runtime assumptions.
    Highly optimized vectorized implementation (Issue #39 optimization; renamed
    from ``apply_swarm_offsets`` in Issue #110 once it became source-agnostic).
    """
    if lastfm_df.empty:
        return lastfm_df

    df = lastfm_df.copy()
    defaults = assumptions.get("defaults", {})
    DEFAULT_CITY = defaults.get("city", "Reykjavik")
    DEFAULT_STATE = defaults.get("state", "IS")
    DEFAULT_COUNTRY = defaults.get("country", "Iceland")
    DEFAULT_LAT = defaults.get("lat", 64.1265)
    DEFAULT_LNG = defaults.get("lng", -21.8174)
    DEFAULT_TZ = defaults.get("timezone", "Atlantic/Reykjavik")

    # 1. Pre-calculate UTC timestamps and local variants for checks
    dt_utc = pd.to_datetime(df["timestamp"], unit="s", utc=True)

    # Initialize result columns with defaults
    df["tz_offset_min"] = 0
    df["city"] = DEFAULT_CITY
    df["state"] = DEFAULT_STATE
    df["country"] = DEFAULT_COUNTRY
    df["lat"] = DEFAULT_LAT
    df["lng"] = DEFAULT_LNG

    # Track which rows have been geocoded to avoid overwriting
    geocoded_mask: np.ndarray = np.zeros(len(df), dtype=bool)

    # 2. Try Swarm Data (Fastest Lookup)
    if not swarm_df.empty:
        swarm_ts = swarm_df["timestamp"].values
        max_age_sec = max_age_days * 24 * 60 * 60

        # Use binary search to find the most recent checkin for every track
        indices = np.searchsorted(swarm_ts, df["timestamp"].values, side="right") - 1

        # Filter indices that are within range and not too old
        valid_indices_mask = indices >= 0
        if valid_indices_mask.any():
            checkin_ts = swarm_ts[indices[valid_indices_mask]]
            age_mask = (df["timestamp"].values[valid_indices_mask] - checkin_ts) <= max_age_sec

            final_swarm_mask = valid_indices_mask.copy()
            final_swarm_mask[valid_indices_mask] = age_mask

            if final_swarm_mask.any():
                match_indices = indices[final_swarm_mask]
                df.loc[final_swarm_mask, "tz_offset_min"] = swarm_df["offset"].values[match_indices]
                df.loc[final_swarm_mask, "city"] = swarm_df["city"].values[match_indices]
                df.loc[final_swarm_mask, "state"] = swarm_df["state"].values[match_indices]
                df.loc[final_swarm_mask, "country"] = swarm_df["country"].values[match_indices]
                df.loc[final_swarm_mask, "lat"] = swarm_df["lat"].values[match_indices]
                df.loc[final_swarm_mask, "lng"] = swarm_df["lng"].values[match_indices]
                geocoded_mask[final_swarm_mask] = True

    # 3. Apply Runtime Assumptions (Residency, Trips, Holidays)
    remaining_mask = ~geocoded_mask
    if remaining_mask.any():
        # Pre-process trips and residency into datetime objects
        processed_trips = []
        for t in assumptions.get("trips", []):
            t_copy = t.copy()
            t_copy["_start"] = pd.to_datetime(t.get("start")).date()
            t_copy["_end"] = pd.to_datetime(t.get("end")).date()
            processed_trips.append(t_copy)

        processed_residency = []
        for r in assumptions.get("residency", []):
            r_copy = r.copy()
            r_copy["_start"] = pd.to_datetime(r.get("start")).replace(tzinfo=None)
            r_copy["_end"] = pd.to_datetime(r.get("end")).replace(tzinfo=None)
            processed_residency.append(r_copy)

        # For efficiency, compute local time once per unique timezone used in assumptions
        tz_to_local = {}

        # Apply Holidays (recurring) — skip placeholder entries (lat=0, lng=0)
        # that are used only for analytics, not for location assignment.
        for holiday in assumptions.get("holidays", []):
            if not remaining_mask.any():
                break
            if holiday.get("lat", 0) == 0 and holiday.get("lng", 0) == 0:
                continue
            tz = holiday.get("timezone", "UTC")
            if tz not in tz_to_local:
                tz_to_local[tz] = dt_utc.dt.tz_convert(tz)

            local_time = tz_to_local[tz]
            month = holiday.get("month")
            day_range = holiday.get("day_range", [])

            holiday_mask = (
                remaining_mask
                & (local_time.dt.month == month)
                & (local_time.dt.day >= day_range[0])
                & (local_time.dt.day <= day_range[1])
            )

            if holiday_mask.any():
                holiday_offsets = (
                    local_time[holiday_mask].dt.tz_localize(None)
                    - dt_utc[holiday_mask].dt.tz_localize(None)
                ).dt.total_seconds() / 60
                df.loc[holiday_mask, "tz_offset_min"] = holiday_offsets
                df.loc[holiday_mask, "city"] = holiday.get("city")
                df.loc[holiday_mask, "state"] = holiday.get("state", holiday.get("city"))
                df.loc[holiday_mask, "country"] = holiday.get("country", "Unknown")
                df.loc[holiday_mask, "lat"] = holiday.get("lat")
                df.loc[holiday_mask, "lng"] = holiday.get("lng")
                geocoded_mask[holiday_mask] = True
                remaining_mask = ~geocoded_mask

        # Apply Trips
        for trip in processed_trips:
            if not remaining_mask.any():
                break
            tz = trip.get("timezone", "UTC")
            if tz not in tz_to_local:
                tz_to_local[tz] = dt_utc.dt.tz_convert(tz)

            local_time = tz_to_local[tz]
            local_date = local_time.dt.date
            trip_mask = (
                remaining_mask & (local_date >= trip["_start"]) & (local_date <= trip["_end"])
            )

            if trip_mask.any():
                trip_offsets = (
                    local_time[trip_mask].dt.tz_localize(None)
                    - dt_utc[trip_mask].dt.tz_localize(None)
                ).dt.total_seconds() / 60
                df.loc[trip_mask, "tz_offset_min"] = trip_offsets
                df.loc[trip_mask, "city"] = trip.get("city")
                df.loc[trip_mask, "state"] = trip.get("state", trip.get("city"))
                df.loc[trip_mask, "country"] = trip.get("country", "Unknown")
                df.loc[trip_mask, "lat"] = trip.get("lat")
                df.loc[trip_mask, "lng"] = trip.get("lng")
                geocoded_mask[trip_mask] = True
                remaining_mask = ~geocoded_mask

        # Apply Residency (with sub-rules)
        dt_naive = dt_utc.dt.tz_localize(None)
        for res in processed_residency:
            if not remaining_mask.any():
                break
            res_mask = remaining_mask & (dt_naive >= res["_start"]) & (dt_naive <= res["_end"])

            if res_mask.any():
                # Apply sub-rules within this residency period
                res_remaining = res_mask.copy()
                for rule in res.get("sub_rules", []):
                    if not res_remaining.any():
                        break
                    tz = rule.get("timezone", "UTC")
                    if tz not in tz_to_local:
                        tz_to_local[tz] = dt_utc.dt.tz_convert(tz)

                    local_time = tz_to_local[tz]
                    cond = rule.get("condition")

                    if cond == "work_hours":
                        # Mon-Fri, 8:30 - 16:30
                        work_mask = (
                            res_remaining
                            & (local_time.dt.weekday < 5)
                            & (
                                ((local_time.dt.hour == 8) & (local_time.dt.minute >= 30))
                                | ((local_time.dt.hour >= 9) & (local_time.dt.hour < 16))
                                | ((local_time.dt.hour == 16) & (local_time.dt.minute <= 30))
                            )
                        )
                        if work_mask.any():
                            work_offsets = (
                                local_time[work_mask].dt.tz_localize(None)
                                - dt_utc[work_mask].dt.tz_localize(None)
                            ).dt.total_seconds() / 60
                            df.loc[work_mask, "tz_offset_min"] = work_offsets
                            df.loc[work_mask, "city"] = rule.get("city")
                            df.loc[work_mask, "state"] = rule.get("state", rule.get("city"))
                            df.loc[work_mask, "country"] = rule.get("country", "Unknown")
                            df.loc[work_mask, "lat"] = rule.get("lat")
                            df.loc[work_mask, "lng"] = rule.get("lng")
                            geocoded_mask[work_mask] = True
                            res_remaining &= ~work_mask

                    elif cond == "home_logic":
                        home_1_end = pd.to_datetime(rule.get("home_1_end")).replace(tzinfo=None)
                        h1_mask = res_remaining & (dt_naive <= home_1_end)
                        h2_mask = res_remaining & (dt_naive > home_1_end)

                        if h1_mask.any():
                            h1_offsets = (
                                local_time[h1_mask].dt.tz_localize(None)
                                - dt_utc[h1_mask].dt.tz_localize(None)
                            ).dt.total_seconds() / 60
                            df.loc[h1_mask, "tz_offset_min"] = h1_offsets
                            df.loc[h1_mask, "city"] = rule.get("city_1")
                            df.loc[h1_mask, "state"] = rule.get("state_1", rule.get("city_1"))
                            df.loc[h1_mask, "country"] = rule.get("country", "Unknown")
                            df.loc[h1_mask, "lat"] = rule.get("lat_1")
                            df.loc[h1_mask, "lng"] = rule.get("lng_1")
                            geocoded_mask[h1_mask] = True
                        if h2_mask.any():
                            h2_offsets = (
                                local_time[h2_mask].dt.tz_localize(None)
                                - dt_utc[h2_mask].dt.tz_localize(None)
                            ).dt.total_seconds() / 60
                            df.loc[h2_mask, "tz_offset_min"] = h2_offsets
                            df.loc[h2_mask, "city"] = rule.get("city_2")
                            df.loc[h2_mask, "state"] = rule.get("state_2", rule.get("city_2"))
                            df.loc[h2_mask, "country"] = rule.get("country", "Unknown")
                            df.loc[h2_mask, "lat"] = rule.get("lat_2")
                            df.loc[h2_mask, "lng"] = rule.get("lng_2")
                            geocoded_mask[h2_mask] = True
                        res_remaining &= ~(h1_mask | h2_mask)

                # Final fallback for residency if no sub-rules matched
                if res_remaining.any():
                    df.loc[res_remaining, "tz_offset_min"] = 0  # Default offset
                    df.loc[res_remaining, "city"] = res.get("city")
                    df.loc[res_remaining, "state"] = res.get("state", res.get("city"))
                    df.loc[res_remaining, "country"] = res.get("country", "Unknown")
                    df.loc[res_remaining, "lat"] = res.get("lat")
                    df.loc[res_remaining, "lng"] = res.get("lng")
                    geocoded_mask[res_remaining] = True

                remaining_mask = ~geocoded_mask

    # 4. Final Default (remaining tracks)
    remaining_mask = ~geocoded_mask
    if remaining_mask.any():
        # Compute default timezone once for all remaining
        default_local = dt_utc[remaining_mask].dt.tz_convert(DEFAULT_TZ)
        default_offsets = (
            default_local.dt.tz_localize(None) - dt_utc[remaining_mask].dt.tz_localize(None)
        ).dt.total_seconds() / 60
        df.loc[remaining_mask, "tz_offset_min"] = default_offsets
        df.loc[remaining_mask, "city"] = DEFAULT_CITY
        df.loc[remaining_mask, "state"] = DEFAULT_STATE
        df.loc[remaining_mask, "country"] = DEFAULT_COUNTRY
        df.loc[remaining_mask, "lat"] = DEFAULT_LAT
        df.loc[remaining_mask, "lng"] = DEFAULT_LNG

    # Apply the computed offsets to date_text
    df["local_date"] = pd.to_datetime(df["timestamp"], unit="s") + pd.to_timedelta(
        df["tz_offset_min"], unit="m"
    )
    df["original_date_text"] = df["date_text"]
    df["date_text"] = df["local_date"]

    return df


def get_top_entities(df: pd.DataFrame, entity: str = "artist", limit: int = 10) -> pd.DataFrame:
    """Get the top n most played entities (artist, album, track)."""
    if entity not in df.columns:
        return pd.DataFrame()
    top = df[entity].value_counts().head(limit).reset_index()
    top.columns = [entity, "Plays"]
    return top


def get_unique_entities(
    subset_df: pd.DataFrame, full_df: pd.DataFrame, entity: str = "artist", limit: int = 10
) -> pd.DataFrame:
    """
    Identify entities that are uniquely prominent in the subset compared to the full dataset.
    Uses a simple 'Over-representation' score: (Subset Frequency / Total Frequency).
    """
    if subset_df.empty or full_df.empty or entity not in full_df.columns:
        return pd.DataFrame()

    subset_counts = subset_df[entity].value_counts()
    full_counts = full_df[entity].value_counts()

    # Filter to only entities present in subset
    relevant_full = full_counts[subset_counts.index]

    # Score = (subset count) / (total count)
    # This favors entities that appear ONLY in this subset
    scores = subset_counts / relevant_full

    unique_data = (
        pd.DataFrame(
            {entity: scores.index, "Uniqueness": scores.values, "Plays": subset_counts.values}
        )
        .sort_values("Uniqueness", ascending=False)
        .head(limit)
    )

    return unique_data


def get_listening_intensity(df: pd.DataFrame, freq: str = "D") -> pd.DataFrame:
    """Calculate play counts per specified frequency ('D' for day, 'W' for week, 'ME' for month)."""
    if "date_text" not in df.columns or df.empty:
        return pd.DataFrame()
    # pandas Period uses 'M' for month-end; resample uses the newer 'ME' alias.
    period_freq = "M" if freq == "ME" else freq
    return (
        df.assign(date_group=df["date_text"].dt.to_period(period_freq).dt.to_timestamp())
        .groupby("date_group")
        .size()
        .reset_index(name="Plays")
        .rename(columns={"date_group": "date"})
    )


def get_milestones(df: pd.DataFrame, intervals: Optional[list[int]] = None) -> pd.DataFrame:
    """Find tracks that hit specific volume milestones."""
    if intervals is None:
        intervals = [1000, 5000, 10000, 50000]
    if df.empty:
        return pd.DataFrame()
    df_sorted = df.sort_values("date_text").reset_index(drop=True)
    milestones = []
    for interval in intervals:
        if len(df_sorted) >= interval:
            track = df_sorted.iloc[interval - 1]
            milestones.append(
                {
                    "Milestone": f"{interval:,} Tracks",
                    "Artist": track["artist"],
                    "Track": track["track"],
                    "Date": track["date_text"],
                }
            )
    return pd.DataFrame(milestones)


def get_listening_streaks(df: pd.DataFrame) -> dict:
    """Find the longest streak of consecutive days with at least one play."""
    if df.empty:
        return {"longest_streak": 0, "current_streak": 0}

    dates_series = pd.to_datetime(df["date_text"]).dt.normalize().drop_duplicates().sort_values()
    if dates_series.empty:
        return {"longest_streak": 0, "current_streak": 0}

    # Each gap > 1 day starts a new streak group.
    gap = dates_series.diff().dt.days.fillna(1)
    group_ids = (gap != 1).cumsum()
    streak_lengths = group_ids.value_counts()

    longest = int(streak_lengths.max())
    last_group = group_ids.iloc[-1]
    current = int(streak_lengths[last_group])
    if (pd.Timestamp.now().normalize() - dates_series.iloc[-1]).days > 1:
        current = 0

    return {
        "longest_streak": longest,
        "current_streak": current,
        "last_active": dates_series.iloc[-1].date(),
    }


def get_forgotten_favorites(
    df: pd.DataFrame, top_n: int = 10, months_threshold: int = 6
) -> pd.DataFrame:
    """Identify artists that were once favorites but haven't been heard recently."""
    if df.empty:
        return pd.DataFrame()

    latest_date = df["date_text"].max()
    threshold_date = latest_date - pd.DateOffset(months=months_threshold)

    past_df = df[df["date_text"] < threshold_date]
    recent_df = df[df["date_text"] >= threshold_date]

    if past_df.empty:
        return pd.DataFrame()

    past_top = past_df["artist"].value_counts().head(top_n * 2)
    recent_artists = recent_df["artist"].unique()
    forgotten_series = past_top[~past_top.index.isin(recent_artists)].head(top_n)
    return pd.DataFrame({"Artist": forgotten_series.index, "Past Plays": forgotten_series.values})


def get_cumulative_plays(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate cumulative plays over time."""
    if "date_text" not in df.columns or df.empty:
        return pd.DataFrame()
    df_copy = df.sort_values("date_text")
    df_copy["date"] = df_copy["date_text"].dt.date
    daily = df_copy.groupby("date").size().reset_index(name="DailyPlays")
    daily["CumulativePlays"] = daily["DailyPlays"].cumsum()
    return daily


def get_hourly_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate the distribution of plays throughout the hours of the day."""
    if "date_text" not in df.columns:
        return pd.DataFrame()
    return df.assign(hour=df["date_text"].dt.hour).groupby("hour").size().reset_index(name="Plays")


def get_day_hour_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    """Return a pivot table of play counts by day-of-week and hour of day.

    Args:
        df: Listening history with a ``date_text`` column.

    Returns:
        DataFrame indexed by day name (Monday–Sunday, ordered) with hour-of-day
        columns 0–23 and integer play counts as values.  Empty if no data.
    """
    if "date_text" not in df.columns or df.empty:
        return pd.DataFrame()
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    data = (
        df.assign(day_of_week=df["date_text"].dt.day_name(), hour=df["date_text"].dt.hour)
        .groupby(["day_of_week", "hour"])
        .size()
        .reset_index(name="Plays")
    )
    data["day_of_week"] = pd.Categorical(data["day_of_week"], categories=days_order, ordered=True)
    return data.pivot(index="day_of_week", columns="hour", values="Plays").fillna(0)


def get_genre_weekly(df: pd.DataFrame, n: int = 8) -> pd.DataFrame:
    """Return weekly scrobble counts for the top N artists.

    Because Last.fm exports do not include genre tags, artist name is used as
    the grouping dimension.  The column is named ``genre`` for compatibility
    with generic streamgraph rendering code.

    Args:
        df: Listening history with ``artist`` and ``date_text`` columns.
        n: Number of top artists (by total plays) to include.

    Returns:
        DataFrame with columns ``date`` (ISO-week Monday as Timestamp),
        ``genre`` (artist name), and ``scrobbles`` (int).
    """
    if df.empty or "artist" not in df.columns or "date_text" not in df.columns:
        return pd.DataFrame(columns=["date", "genre", "scrobbles"])

    top_artists = df["artist"].value_counts().head(n).index.tolist()
    subset = df[df["artist"].isin(top_artists)].copy()
    subset["date"] = subset["date_text"].dt.to_period("W").dt.start_time
    weekly = subset.groupby(["date", "artist"]).size().reset_index(name="scrobbles")
    return weekly.rename(columns={"artist": "genre"})


def get_first_plays(df: pd.DataFrame) -> pd.DataFrame:
    """Return the first play row for each artist, sorted chronologically.

    For each artist, finds the earliest scrobble — representing the moment
    that artist was "discovered."  The returned DataFrame retains all columns
    from the input so callers can join city/location context when available.

    Args:
        df: Listening history DataFrame with at minimum ``artist`` and
            ``timestamp`` columns.  A ``date_text`` column is expected for
            display purposes.

    Returns:
        DataFrame of first-play rows, one per artist, sorted by ``timestamp``
        ascending.  Empty DataFrame if input is empty or missing required
        columns.
    """
    required = {"artist", "timestamp"}
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame()

    return (
        df.sort_values("timestamp")
        .groupby("artist", as_index=False)
        .first()
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def detect_trip_periods(
    assumptions: dict[str, Any],
    swarm_df: Optional[pd.DataFrame] = None,
    home_city: Optional[str] = None,
    min_consecutive_days: int = 2,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Detect trip date ranges from assumptions and Swarm check-ins.

    Combines two sources:
    1. Explicit ``assumptions["trips"]`` date ranges.
    2. Swarm check-ins where the city differs from the home city for two or
       more consecutive days.

    Args:
        assumptions: Loaded assumptions dict (from :func:`load_assumptions`).
        swarm_df: Optional Swarm check-in DataFrame with ``timestamp`` and
            ``city`` columns.
        home_city: The city to treat as home.  Defaults to
            ``assumptions["defaults"]["city"]`` when not provided.
        min_consecutive_days: Minimum consecutive away-days to qualify as a
            trip when detected from Swarm data.  Defaults to 2.

    Returns:
        Sorted list of ``(start, end)`` ``pd.Timestamp`` pairs (date
        precision) representing trip date ranges.  Overlapping ranges from
        different sources are kept as-is; callers may merge if needed.
    """
    periods: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    for trip in assumptions.get("trips", []):
        try:
            start = pd.Timestamp(trip["start"]).normalize()
            end = pd.Timestamp(trip["end"]).normalize()
            if start <= end:
                periods.append((start, end))
        except (KeyError, ValueError, TypeError):
            continue

    if swarm_df is not None and not swarm_df.empty and "timestamp" in swarm_df.columns:
        resolved_home = home_city or assumptions.get("defaults", {}).get("city", "")

        sw = swarm_df.copy()
        sw["date"] = pd.to_datetime(sw["timestamp"], unit="s").dt.normalize()
        daily = sw.sort_values("timestamp").groupby("date")["city"].last().reset_index()

        if resolved_home:
            away = daily[daily["city"].str.lower() != resolved_home.lower()].copy()
        else:
            away = daily.copy()

        if not away.empty:
            away = away.sort_values("date").reset_index(drop=True)
            away["gap"] = away["date"].diff().dt.days.fillna(1)
            away["run"] = (away["gap"] > 1).cumsum()
            for _, run_df in away.groupby("run"):
                if len(run_df) >= min_consecutive_days:
                    periods.append((run_df["date"].min(), run_df["date"].max()))

    periods.sort(key=lambda t: t[0])
    return periods


def label_listening_context(
    lastfm_df: pd.DataFrame,
    trip_periods: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> pd.DataFrame:
    """Label each Last.fm row as ``'trip'`` or ``'home'`` based on trip periods.

    Args:
        lastfm_df: Listening history with a ``date_text`` column.
        trip_periods: Sorted list of ``(start, end)`` Timestamp pairs from
            :func:`detect_trip_periods`.

    Returns:
        Copy of ``lastfm_df`` with a new ``context`` column (``'home'`` or
        ``'trip'``).
    """
    if lastfm_df.empty:
        df = lastfm_df.copy()
        df["context"] = pd.Series(dtype="str")
        return df

    df = lastfm_df.copy()
    df["context"] = "home"

    if not trip_periods:
        return df

    dates = df["date_text"].dt.normalize()
    for start, end in trip_periods:
        mask = (dates >= start) & (dates <= end)
        df.loc[mask, "context"] = "trip"

    return df


def compute_vacation_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Compute per-context listening statistics for Home vs. Trip comparisons.

    Calculates the following metrics for each context group (``'home'`` and
    ``'trip'``): average daily scrobbles, unique artists per day, estimated
    listening hours, and top artist.

    Args:
        df: Listening history with ``date_text``, ``artist``, and ``context``
            columns (as produced by :func:`label_listening_context`).

    Returns:
        Dict keyed by context string (``'home'``, ``'trip'``), each value
        being a dict of metric name → value.  Missing contexts return an
        empty metric dict.
    """
    results: dict[str, Any] = {}

    if df.empty or "context" not in df.columns:
        return results

    for ctx in ("home", "trip"):
        sub = df[df["context"] == ctx]
        if sub.empty:
            results[ctx] = {}
            continue

        unique_days = sub["date_text"].dt.normalize().nunique()
        unique_days = max(unique_days, 1)
        total_plays = len(sub)
        avg_daily = round(total_plays / unique_days, 1)
        hours = round(total_plays * 3.5 / 60, 1)
        unique_artists_per_day = round(
            sub.groupby(sub["date_text"].dt.normalize())["artist"].nunique().mean(), 1
        )
        top_artist = sub["artist"].value_counts().index[0] if not sub.empty else "—"

        results[ctx] = {
            "avg_daily_scrobbles": avg_daily,
            "unique_artists_per_day": unique_artists_per_day,
            "listening_hours": hours,
            "top_artist": top_artist,
            "total_plays": total_plays,
            "unique_days": unique_days,
        }

    return results


def build_life_chapters(
    df: pd.DataFrame,
    assumptions: dict[str, Any],
    min_plays_exclusive: int = 5,
) -> list[dict[str, Any]]:
    """Build a chronological list of life chapters from residency and trip assumptions.

    Each chapter represents a distinct geographic period (residency segment or
    trip) with aggregated listening statistics.  Overlapping periods are
    resolved by giving trips priority over residency (matching the same
    precedence used in ``apply_location_context``).

    Args:
        df: Listening history DataFrame with ``date_text`` (datetime) and
            ``artist``, ``album`` columns.
        assumptions: Parsed assumptions dict from ``load_assumptions()``.
        min_plays_exclusive: Minimum number of plays in the chapter for an
            artist to qualify as "chapter-exclusive" (default 5).

    Returns:
        List of chapter dicts sorted by ``start`` date, each containing:

        - ``label`` (str): Human-readable chapter name.
        - ``location`` (str): City / country description.
        - ``start`` (pd.Timestamp): Chapter start date.
        - ``end`` (pd.Timestamp): Chapter end date.
        - ``total_plays`` (int): Number of scrobbles in the period.
        - ``top_artists`` (list[str]): Top-5 artists by play count.
        - ``top_album`` (str | None): Most-played album.
        - ``discovery_count`` (int): Artists first heard during this chapter.
        - ``exclusive_artists`` (list[str]): Artists whose listening is
          concentrated in this chapter (uniqueness score ≥ 0.8).
    """
    if df.empty or "date_text" not in df.columns:
        return []

    # --- 1. Collect raw periods from assumptions --------------------------------
    raw_periods: list[dict[str, Any]] = []

    for res in assumptions.get("residency", []):
        start_str = res.get("start")
        end_str = res.get("end")
        if not start_str or not end_str:
            continue
        city = res.get("city") or res.get("state") or "Unknown"
        country = res.get("country", "")
        location = f"{city}, {country}" if country else city
        raw_periods.append(
            {
                "label": city,
                "location": location,
                "start": pd.Timestamp(start_str),
                "end": pd.Timestamp(end_str),
                "kind": "residency",
                "lat": res.get("lat"),
                "lng": res.get("lng"),
            }
        )

    for trip in assumptions.get("trips", []):
        start_str = trip.get("start")
        end_str = trip.get("end")
        if not start_str or not end_str:
            continue
        city = trip.get("city") or trip.get("state") or "Unknown"
        country = trip.get("country", "")
        location = f"{city}, {country}" if country else city
        raw_periods.append(
            {
                "label": f"Trip to {city}",
                "location": location,
                "start": pd.Timestamp(start_str),
                "end": pd.Timestamp(end_str),
                "kind": "trip",
                "lat": trip.get("lat"),
                "lng": trip.get("lng"),
            }
        )

    if not raw_periods:
        return []

    # --- 2. Sort chronologically -----------------------------------------------
    raw_periods.sort(key=lambda p: p["start"])

    # --- 3. Compute stats for each period --------------------------------------
    df_sorted = df.copy()
    df_sorted["date_text"] = pd.to_datetime(df_sorted["date_text"])

    # Pre-compute first-heard date for every artist (across full history)
    if "artist" in df_sorted.columns:
        first_heard: pd.Series = df_sorted.groupby("artist")["date_text"].min()
    else:
        first_heard = pd.Series(dtype="datetime64[ns]")

    chapters: list[dict[str, Any]] = []
    for period in raw_periods:
        start_ts = period["start"]
        end_ts = period["end"]

        mask = (df_sorted["date_text"].dt.date >= start_ts.date()) & (
            df_sorted["date_text"].dt.date <= end_ts.date()
        )
        chapter_df = df_sorted[mask]

        total_plays = len(chapter_df)

        # Top-5 artists
        if "artist" in chapter_df.columns and not chapter_df.empty:
            top_artists = chapter_df["artist"].value_counts().head(5).index.tolist()
        else:
            top_artists = []

        # Top album
        top_album: Optional[str] = None
        if "album" in chapter_df.columns and not chapter_df.empty:
            album_counts = chapter_df["album"].value_counts()
            if not album_counts.empty:
                top_album = str(album_counts.index[0])

        # Discovery count: artists whose first-heard date falls in this chapter
        discovery_count = 0
        if not first_heard.empty and not chapter_df.empty and "artist" in chapter_df.columns:
            chapter_artists = chapter_df["artist"].dropna().unique()
            for artist in chapter_artists:
                if artist in first_heard.index:
                    fh = first_heard[artist]
                    if start_ts.date() <= fh.date() <= end_ts.date():
                        discovery_count += 1

        # Chapter-exclusive artists: uniqueness score ≥ 0.8 with min_plays_exclusive plays
        exclusive_artists: list[str] = []
        if not chapter_df.empty and "artist" in chapter_df.columns and total_plays > 0:
            chapter_counts = chapter_df["artist"].value_counts()
            full_counts = df_sorted["artist"].value_counts()
            qualified = chapter_counts[chapter_counts >= min_plays_exclusive]
            for artist, ch_count in qualified.items():
                full_count = full_counts.get(artist, ch_count)
                if full_count > 0 and (ch_count / full_count) >= 0.8:
                    exclusive_artists.append(str(artist))

        chapters.append(
            {
                "label": period["label"],
                "location": period["location"],
                "start": start_ts,
                "end": end_ts,
                "kind": period["kind"],
                "lat": period.get("lat"),
                "lng": period.get("lng"),
                "total_plays": total_plays,
                "top_artists": top_artists,
                "top_album": top_album,
                "discovery_count": discovery_count,
                "exclusive_artists": exclusive_artists,
            }
        )

    return chapters


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two WGS-84 points."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    cos1 = math.cos(math.radians(lat1))
    cos2 = math.cos(math.radians(lat2))
    a = math.sin(dlat / 2) ** 2 + cos1 * cos2 * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def detect_trips_from_swarm(
    swarm_df: pd.DataFrame,
    assumptions: dict[str, Any],
    radius_km: float = 80.0,
    gap_days: int = 2,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> list[dict[str, Any]]:
    """Detect trips from Swarm check-in data by clustering check-ins far from home.

    For each check-in, the home location is resolved via
    ``get_assumption_location`` using the active residency + trip rules at
    that point in time.  Check-ins beyond ``radius_km`` from home are
    collected, sorted chronologically, then split into trip clusters whenever
    the gap between consecutive check-ins exceeds ``gap_days``.

    Args:
        swarm_df: Swarm check-in DataFrame with at minimum ``timestamp``
            (Unix int), ``lat``, ``lng``, ``city``, and ``country`` columns.
        assumptions: Parsed assumptions dict from ``load_assumptions()``.
        radius_km: Minimum distance from home (km) to count as away (default 80).
        gap_days: Days gap between check-ins that starts a new trip cluster (default 2).
        progress_cb: Optional callable that receives progress strings for streaming UI.

    Returns:
        List of trip dicts, each containing: ``start``, ``end`` (ISO date
        strings), ``city``, ``country``, ``lat``, ``lng`` (centroid of the
        cluster), ``checkin_count`` (int).
    """
    if swarm_df.empty:
        return []

    required = {"lat", "lng", "timestamp"}
    if not required.issubset(swarm_df.columns):
        return []

    def log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    df = swarm_df.dropna(subset=["lat", "lng"]).copy()
    df = df[df["lat"] != 0].copy()
    log(f"Analysing {len(df):,} check-ins with location data…")

    away: list[dict[str, Any]] = []
    skipped = 0

    for _, row in df.iterrows():
        ts = int(row["timestamp"])
        home = get_assumption_location(ts, assumptions)
        if home is None or home.get("lat") is None or home.get("lng") is None:
            skipped += 1
            continue

        dist = _haversine_km(
            float(home["lat"]), float(home["lng"]), float(row["lat"]), float(row["lng"])
        )
        if dist >= radius_km:
            away.append(
                {
                    "timestamp": ts,
                    "lat": float(row["lat"]),
                    "lng": float(row["lng"]),
                    "city": str(row.get("city", "") or ""),
                    "country": str(row.get("country", "") or ""),
                }
            )

    log(
        f"Found {len(away):,} away-from-home check-ins (>{radius_km:.0f} km). "
        f"Skipped {skipped:,} without a home reference."
    )

    if not away:
        return []

    away.sort(key=lambda x: x["timestamp"])

    gap_seconds = gap_days * 86_400
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = [away[0]]
    for checkin in away[1:]:
        if checkin["timestamp"] - current[-1]["timestamp"] <= gap_seconds:
            current.append(checkin)
        else:
            clusters.append(current)
            current = [checkin]
    clusters.append(current)

    log(f"Clustered into {len(clusters)} trip(s) using a {gap_days}-day gap.")

    trips: list[dict[str, Any]] = []
    for cluster in clusters:
        start_dt = pd.to_datetime(cluster[0]["timestamp"], unit="s", utc=True)
        end_dt = pd.to_datetime(cluster[-1]["timestamp"], unit="s", utc=True)

        departure = cluster[0]
        furthest = max(
            cluster,
            key=lambda c: _haversine_km(departure["lat"], departure["lng"], c["lat"], c["lng"]),
        )
        top_city = furthest["city"] or "Unknown"
        top_country = furthest["country"] or ""
        if not top_country:
            countries = [c["country"] for c in cluster if c["country"]]
            top_country = max(set(countries), key=countries.count) if countries else ""

        mean_lat = sum(c["lat"] for c in cluster) / len(cluster)
        mean_lng = sum(c["lng"] for c in cluster) / len(cluster)

        trips.append(
            {
                "start": start_dt.strftime("%Y-%m-%d"),
                "end": end_dt.strftime("%Y-%m-%d"),
                "city": top_city,
                "country": top_country,
                "lat": round(mean_lat, 4),
                "lng": round(mean_lng, 4),
                "checkin_count": len(cluster),
            }
        )

    return trips


def get_artist_monthly_ranks(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return monthly rank positions for the top N artists overall.

    Ranks are computed per-month: rank 1 = most scrobbles in that month.
    Only the top ``n`` artists by all-time play count are tracked.

    Args:
        df: Listening history with ``artist`` and ``date_text`` columns.
        n: Number of top artists to track.

    Returns:
        DataFrame with columns ``month`` (first-day Timestamp), ``artist``
        (str), and ``rank`` (int, 1 = most played).
    """
    if df.empty or "artist" not in df.columns or "date_text" not in df.columns:
        return pd.DataFrame(columns=["month", "artist", "rank"])

    top_artists = df["artist"].value_counts().head(n).index.tolist()
    subset = df[df["artist"].isin(top_artists)].copy()
    subset["month"] = subset["date_text"].dt.to_period("M").dt.to_timestamp()

    monthly = subset.groupby(["month", "artist"]).size().reset_index(name="plays")
    monthly["rank"] = (
        monthly.groupby("month")["plays"].rank(method="min", ascending=False).astype(int)
    )
    return monthly[["month", "artist", "rank"]]


# ---------------------------------------------------------------------------
# Transit / airport analysis
# ---------------------------------------------------------------------------

#: Foursquare category substrings that indicate a transit hub.
TRANSIT_CATEGORY_KEYWORDS: list[str] = [
    "Airport",
    "Train Station",
    "Transit",
    "Bus Station",
    "Metro",
    "Subway",
    "Ferry",
    "Port",
    "Rail",
    "Rest Area",
    "Rest Stop",
    "Travel Plaza",
    "Service Plaza",
    "Turnpike",
    "Toll",
    "Gas Station",
    "Truck Stop",
]


def get_transit_days(swarm_df: pd.DataFrame) -> set[str]:
    """Return calendar date strings (YYYY-MM-DD) that contain a transit check-in.

    Args:
        swarm_df: Output of :func:`load_swarm_data`, which must include a
            ``venue_category`` column and a ``timestamp`` column (Unix seconds).

    Returns:
        Set of ISO date strings (e.g. ``{"2023-06-12", "2023-06-15"}``).
    """
    if swarm_df.empty or "venue_category" not in swarm_df.columns:
        return set()
    pattern = "|".join(TRANSIT_CATEGORY_KEYWORDS)
    transit_rows = swarm_df[
        swarm_df["venue_category"].str.contains(pattern, case=False, na=False)
    ].copy()
    if transit_rows.empty:
        return set()
    transit_rows["date"] = pd.to_datetime(transit_rows["timestamp"], unit="s").dt.strftime(
        "%Y-%m-%d"
    )
    return set(transit_rows["date"].unique())


def split_transit_listens(
    listens_df: pd.DataFrame, transit_days: set[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition a listening DataFrame into transit-day and non-transit-day rows.

    Args:
        listens_df: Listening history with a ``date_text`` datetime column.
        transit_days: Set of ISO date strings returned by :func:`get_transit_days`.

    Returns:
        Tuple ``(transit_df, non_transit_df)`` — both are subsets of ``listens_df``.
    """
    if listens_df.empty or "date_text" not in listens_df.columns:
        return listens_df.iloc[:0].copy(), listens_df.iloc[:0].copy()
    date_strs = listens_df["date_text"].dt.strftime("%Y-%m-%d")
    mask = date_strs.isin(transit_days)
    return listens_df[mask].copy(), listens_df[~mask].copy()


def get_avg_plays_per_day(df: pd.DataFrame) -> float:
    """Return the mean number of plays per calendar day.

    Args:
        df: Listening history with a ``date_text`` datetime column.

    Returns:
        Average plays per day, or 0.0 when the DataFrame is empty.
    """
    if df.empty or "date_text" not in df.columns:
        return 0.0
    unique_days = int(df["date_text"].dt.date.nunique())
    return float(len(df)) / unique_days if unique_days > 0 else 0.0


# ---------------------------------------------------------------------------
# Dining soundtrack analysis
# ---------------------------------------------------------------------------

_DINING_WINDOW_MINUTES: int = 30

#: Venue category buckets shown in the UI.
FOOD_DRINK_CATEGORIES: list[str] = [
    "Restaurants",
    "Bars & Nightlife",
    "Cafes",
    "Fast Food",
]

_CATEGORY_RULES: list[tuple[str, str]] = [
    ("fast food", "Fast Food"),
    ("burger", "Fast Food"),
    ("pizza", "Fast Food"),
    ("fried chicken", "Fast Food"),
    ("hot dog", "Fast Food"),
    ("sandwich", "Fast Food"),
    ("bar", "Bars & Nightlife"),
    ("nightclub", "Bars & Nightlife"),
    ("pub", "Bars & Nightlife"),
    ("brewery", "Bars & Nightlife"),
    ("wine", "Bars & Nightlife"),
    ("cocktail", "Bars & Nightlife"),
    ("lounge", "Bars & Nightlife"),
    ("club", "Bars & Nightlife"),
    ("cafe", "Cafes"),
    ("café", "Cafes"),
    ("coffee", "Cafes"),
    ("tea room", "Cafes"),
    ("bakery", "Cafes"),
    ("dessert", "Cafes"),
    ("ice cream", "Cafes"),
    ("juice bar", "Cafes"),
    ("restaurant", "Restaurants"),
    ("diner", "Restaurants"),
    ("food", "Restaurants"),
    ("sushi", "Restaurants"),
    ("ramen", "Restaurants"),
    ("noodle", "Restaurants"),
    ("steakhouse", "Restaurants"),
    ("bbq", "Restaurants"),
    ("seafood", "Restaurants"),
    ("bistro", "Restaurants"),
    ("brasserie", "Restaurants"),
    ("tapas", "Restaurants"),
    ("dim sum", "Restaurants"),
    ("buffet", "Restaurants"),
    ("grill", "Restaurants"),
    ("kitchen", "Restaurants"),
    ("eatery", "Restaurants"),
]


def _classify_venue_category(raw_category: str) -> Optional[str]:
    """Map a raw Foursquare category to one of the four display buckets.

    Args:
        raw_category: Raw category string from a Foursquare export.

    Returns:
        One of the four :data:`FOOD_DRINK_CATEGORIES` strings, or ``None``.
    """
    lower = raw_category.lower()
    for substring, bucket in _CATEGORY_RULES:
        if substring in lower:
            return bucket
    return None


def _listens_around_checkin(
    lastfm_df: pd.DataFrame,
    checkin_ts: int,
    window_minutes: int = _DINING_WINDOW_MINUTES,
) -> pd.DataFrame:
    """Return Last.fm listens within ±``window_minutes`` of *checkin_ts*.

    Args:
        lastfm_df: Listening history with a ``timestamp`` column.
        checkin_ts: Unix timestamp of the Swarm check-in.
        window_minutes: Symmetric window size in minutes.

    Returns:
        Subset of ``lastfm_df`` within the window; may be empty.
    """
    if lastfm_df.empty or "timestamp" not in lastfm_df.columns:
        return pd.DataFrame()
    window_sec = window_minutes * 60
    mask = (lastfm_df["timestamp"] >= checkin_ts - window_sec) & (
        lastfm_df["timestamp"] <= checkin_ts + window_sec
    )
    return lastfm_df[mask]


def get_dining_soundtrack_data(
    swarm_df: pd.DataFrame,
    lastfm_df: pd.DataFrame,
    top_n: int = 10,
) -> dict[str, dict[str, Any]]:
    """Aggregate Last.fm listens around food/drink check-ins by venue bucket.

    Uses a ±:data:`_DINING_WINDOW_MINUTES` window around each Swarm check-in.

    Args:
        swarm_df: Swarm DataFrame with ``timestamp`` and ``venue_category``.
        lastfm_df: Listening history with ``timestamp``, ``artist``, ``album``,
            ``date_text``.
        top_n: Maximum top artists/albums to return per bucket.

    Returns:
        Dict keyed by venue category bucket.  Each value has:
        ``top_artists`` (DataFrame), ``top_albums`` (DataFrame),
        ``checkin_count`` (int), ``listen_count`` (int), ``peak_hour`` (int | None).
    """
    if swarm_df.empty or lastfm_df.empty:
        return {}
    required = {"timestamp", "venue_category"}
    if not required.issubset(swarm_df.columns) or "timestamp" not in lastfm_df.columns:
        return {}

    bucket_listens: dict[str, list[pd.DataFrame]] = {c: [] for c in FOOD_DRINK_CATEGORIES}
    bucket_checkins: dict[str, int] = {c: 0 for c in FOOD_DRINK_CATEGORIES}

    for _, row in swarm_df.iterrows():
        bucket = _classify_venue_category(str(row.get("venue_category", "")))
        if bucket is None:
            continue
        nearby = _listens_around_checkin(lastfm_df, int(row["timestamp"]))
        if not nearby.empty:
            bucket_listens[bucket].append(nearby)
        bucket_checkins[bucket] += 1

    results: dict[str, dict[str, Any]] = {}
    for cat in FOOD_DRINK_CATEGORIES:
        if bucket_checkins[cat] == 0:
            continue
        frames = bucket_listens[cat]
        if not frames:
            continue
        combined = pd.concat(frames, ignore_index=True).drop_duplicates()
        top_artists = get_top_entities(combined, "artist", limit=top_n)
        top_albums = (
            get_top_entities(combined, "album", limit=top_n)
            if "album" in combined.columns
            else pd.DataFrame()
        )
        peak_hour: Optional[int] = None
        if "date_text" in combined.columns and not combined["date_text"].isna().all():
            hour_counts = combined["date_text"].dt.hour.value_counts()
            if not hour_counts.empty:
                peak_hour = int(hour_counts.idxmax())
        results[cat] = {
            "top_artists": top_artists,
            "top_albums": top_albums,
            "checkin_count": bucket_checkins[cat],
            "listen_count": len(combined),
            "peak_hour": peak_hour,
        }
    return results


# ---------------------------------------------------------------------------
# Swarm analysis cache persistence
# ---------------------------------------------------------------------------

DETECTED_TRIPS_CACHE: str = os.path.join("data", "cache", "detected_trips.json")
TRANSIT_DAYS_CACHE: str = os.path.join("data", "cache", "swarm_transit_days.json")
DINING_CACHE: str = os.path.join("data", "cache", "swarm_dining.json")


def load_detected_trips_cache(path: str = DETECTED_TRIPS_CACHE) -> list[dict[str, Any]]:
    """Load previously detected trips from the JSON cache file.

    Args:
        path: Path to the cache file.

    Returns:
        List of trip dicts, or an empty list if the file does not exist.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data: list[dict[str, Any]] = json.load(fh)
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_detected_trips_cache(
    trips: list[dict[str, Any]], path: str = DETECTED_TRIPS_CACHE
) -> None:
    """Persist detected trips to a JSON cache file.

    Args:
        trips: List of trip dicts from :func:`detect_trips_from_swarm`.
        path: Destination file path.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(trips, fh, indent=2)


def load_transit_days_cache(path: str = TRANSIT_DAYS_CACHE) -> set[str]:
    """Load cached transit days from disk.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Set of ISO date strings, or empty set if file is missing or invalid.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data: list[str] = json.load(fh)
            return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_transit_days_cache(days: set[str], path: str = TRANSIT_DAYS_CACHE) -> None:
    """Persist transit days to a JSON cache file.

    Args:
        days: Set of ISO date strings from :func:`get_transit_days`.
        path: Destination file path.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(sorted(days), fh)


def _dining_to_json(data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Serialise dining soundtrack data to a JSON-safe dict.

    DataFrames are stored as lists of records.
    """
    out: dict[str, Any] = {}
    for cat, stats in data.items():
        out[cat] = {
            "top_artists": stats["top_artists"].to_dict(orient="records")
            if isinstance(stats["top_artists"], pd.DataFrame)
            else [],
            "top_albums": stats["top_albums"].to_dict(orient="records")
            if isinstance(stats["top_albums"], pd.DataFrame)
            else [],
            "checkin_count": stats["checkin_count"],
            "listen_count": stats["listen_count"],
            "peak_hour": stats["peak_hour"],
        }
    return out


def _dining_from_json(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Reconstruct dining soundtrack data from a JSON-loaded dict.

    Converts record lists back to DataFrames.
    """
    out: dict[str, dict[str, Any]] = {}
    for cat, stats in data.items():
        out[cat] = {
            "top_artists": pd.DataFrame(stats.get("top_artists", [])),
            "top_albums": pd.DataFrame(stats.get("top_albums", [])),
            "checkin_count": stats.get("checkin_count", 0),
            "listen_count": stats.get("listen_count", 0),
            "peak_hour": stats.get("peak_hour"),
        }
    return out


def load_dining_cache(path: str = DINING_CACHE) -> dict[str, dict[str, Any]]:
    """Load cached dining soundtrack data from disk.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Dining dict with DataFrames reconstructed, or empty dict if missing.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)
            return _dining_from_json(raw)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_dining_cache(data: dict[str, dict[str, Any]], path: str = DINING_CACHE) -> None:
    """Persist dining soundtrack data to a JSON cache file.

    Args:
        data: Dining dict from :func:`get_dining_soundtrack_data`.
        path: Destination file path.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_dining_to_json(data), fh, indent=2)


# ---------------------------------------------------------------------------
# Deep analysis cache persistence
# ---------------------------------------------------------------------------

DEEP_SESSIONS_CACHE: str = os.path.join("data", "cache", "deep_sessions.json")
DEEP_PERSONALITY_CACHE: str = os.path.join("data", "cache", "deep_personality.json")
DEEP_ARCS_CACHE: str = os.path.join("data", "cache", "deep_arcs.json")
DEEP_SEASONAL_CACHE: str = os.path.join("data", "cache", "deep_seasonal.json")
DEEP_TASTE_DRIFT_CACHE: str = os.path.join("data", "cache", "deep_taste_drift.json")
DEEP_CITY_SOUNDTRACKS_CACHE: str = os.path.join("data", "cache", "deep_city_soundtracks.json")
DEEP_VENUE_PATTERNS_CACHE: str = os.path.join("data", "cache", "deep_venue_patterns.json")
DEEP_LIFE_EVENTS_CACHE: str = os.path.join("data", "cache", "deep_life_events.json")

_DEEP_CACHE_REGISTRY: dict[str, str] = {
    "sessions": DEEP_SESSIONS_CACHE,
    "personality": DEEP_PERSONALITY_CACHE,
    "arcs": DEEP_ARCS_CACHE,
    "seasonal": DEEP_SEASONAL_CACHE,
    "taste_drift": DEEP_TASTE_DRIFT_CACHE,
    "city_soundtracks": DEEP_CITY_SOUNDTRACKS_CACHE,
    "venue_patterns": DEEP_VENUE_PATTERNS_CACHE,
    "life_events": DEEP_LIFE_EVENTS_CACHE,
}


def _load_deep_cache(path: str) -> Any:
    """Load a deep analysis cache file, returning None if missing or corrupt.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data (dict or list), or None if the file is missing or invalid.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class _DeepCacheEncoder(json.JSONEncoder):
    """JSON encoder that handles pandas/numpy types produced by deep analyses."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if isinstance(obj, pd.Period):
            return str(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _save_deep_cache(data: Any, path: str) -> None:
    """Persist deep analysis data to a JSON cache file.

    Args:
        data: JSON-serialisable data to write.
        path: Destination file path.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, cls=_DeepCacheEncoder)


def load_deep_sessions_cache(path: str = DEEP_SESSIONS_CACHE) -> Any:
    """Load deep sessions analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_sessions_cache(data: Any, path: str = DEEP_SESSIONS_CACHE) -> None:
    """Persist deep sessions analysis data to cache.

    Args:
        data: JSON-serialisable sessions data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def load_deep_personality_cache(path: str = DEEP_PERSONALITY_CACHE) -> Any:
    """Load deep personality analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_personality_cache(data: Any, path: str = DEEP_PERSONALITY_CACHE) -> None:
    """Persist deep personality analysis data to cache.

    Args:
        data: JSON-serialisable personality data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def load_deep_arcs_cache(path: str = DEEP_ARCS_CACHE) -> Any:
    """Load deep arcs analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_arcs_cache(data: Any, path: str = DEEP_ARCS_CACHE) -> None:
    """Persist deep arcs analysis data to cache.

    Args:
        data: JSON-serialisable arcs data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def load_deep_seasonal_cache(path: str = DEEP_SEASONAL_CACHE) -> Any:
    """Load deep seasonal analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_seasonal_cache(data: Any, path: str = DEEP_SEASONAL_CACHE) -> None:
    """Persist deep seasonal analysis data to cache.

    Args:
        data: JSON-serialisable seasonal data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def load_deep_taste_drift_cache(path: str = DEEP_TASTE_DRIFT_CACHE) -> Any:
    """Load deep taste drift analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_taste_drift_cache(data: Any, path: str = DEEP_TASTE_DRIFT_CACHE) -> None:
    """Persist deep taste drift analysis data to cache.

    Args:
        data: JSON-serialisable taste drift data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def load_deep_city_soundtracks_cache(path: str = DEEP_CITY_SOUNDTRACKS_CACHE) -> Any:
    """Load deep city soundtracks analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_city_soundtracks_cache(data: Any, path: str = DEEP_CITY_SOUNDTRACKS_CACHE) -> None:
    """Persist deep city soundtracks analysis data to cache.

    Args:
        data: JSON-serialisable city soundtracks data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def load_deep_venue_patterns_cache(path: str = DEEP_VENUE_PATTERNS_CACHE) -> Any:
    """Load deep venue patterns analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_venue_patterns_cache(data: Any, path: str = DEEP_VENUE_PATTERNS_CACHE) -> None:
    """Persist deep venue patterns analysis data to cache.

    Args:
        data: JSON-serialisable venue patterns data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def load_deep_life_events_cache(path: str = DEEP_LIFE_EVENTS_CACHE) -> Any:
    """Load deep life events analysis cache.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Parsed JSON data or None if missing/corrupt.
    """
    return _load_deep_cache(path)


def save_deep_life_events_cache(data: Any, path: str = DEEP_LIFE_EVENTS_CACHE) -> None:
    """Persist deep life events analysis data to cache.

    Args:
        data: JSON-serialisable life events data.
        path: Destination file path.
    """
    _save_deep_cache(data, path)


def get_deep_analysis_status() -> dict[str, bool]:
    """Return presence/absence of each deep analysis cache file.

    Returns:
        Dict mapping cache name to True if the file exists, False otherwise.
    """
    return {name: os.path.exists(path) for name, path in _DEEP_CACHE_REGISTRY.items()}


# ---------------------------------------------------------------------------
# Life Chapters disk cache (issue #92)
# ---------------------------------------------------------------------------

LIFE_CHAPTERS_CACHE: str = os.path.join("data", "cache", "life_chapters.json")


def get_life_chapters_cache_key(
    broker_identity: Optional[tuple[Any, ...]],
    legacy_config: Optional[tuple[str, str, str, str]],
    merged_assumptions: dict[str, Any],
) -> str:
    """Compute a deterministic disk-cache key for Life in Chapters.

    Combines whichever data-loading identity is active this session
    (broker-mode ``_loaded_store_identity`` takes precedence over
    legacy-mode ``_loaded_config``) with a hash of ``merged_assumptions``
    (which can change independently of either identity, e.g. after the user
    rebuilds the Swarm Analysis Cache).

    Args:
        broker_identity: The broker-mode identity tuple (``store_path``,
            ``store_mtime``, ``assumptions_path``), or None if broker mode
            is not active this session.
        legacy_config: The legacy-mode 4-tuple (``file_path``, ``swarm_dir``,
            ``assumptions_path``, ``timeline_path``), or None if legacy mode
            is not active this session.
        merged_assumptions: The fully merged assumptions dict used to build
            Life in Chapters (folds in detected-trips overrides, etc.).

    Returns:
        A deterministic hex digest suitable as a cache key.
    """
    if broker_identity is not None:
        base = repr(broker_identity)
    elif legacy_config is not None:
        # Reuse the existing file-mtime-based cache key, but also fold in the
        # raw config tuple itself so the key remains sensitive to config
        # changes even when the referenced files don't exist on disk (e.g.
        # in tests using synthetic paths, where get_cache_key() alone would
        # collapse to its "none" sentinel for every non-existent path).
        base = f"{get_cache_key(*legacy_config)}|{legacy_config!r}"
    else:
        base = "none"

    assumptions_json = json.dumps(merged_assumptions, sort_keys=True, default=str)
    assumptions_hash = hashlib.md5(  # noqa: S324
        assumptions_json.encode(), usedforsecurity=False
    ).hexdigest()

    return hashlib.md5(  # noqa: S324
        f"{base}|{assumptions_hash}".encode(), usedforsecurity=False
    ).hexdigest()


def save_life_chapters_cache(
    cache_key: str,
    chapters: list[dict[str, Any]],
    trip_periods: list[tuple[pd.Timestamp, pd.Timestamp]],
    path: str = LIFE_CHAPTERS_CACHE,
) -> None:
    """Persist Life in Chapters' precomputed ``chapters``/``trip_periods`` to disk.

    Args:
        cache_key: The key from :func:`get_life_chapters_cache_key`, stored
            alongside the payload so a later load can detect staleness.
        chapters: Output of :func:`build_life_chapters`.
        trip_periods: Output of :func:`detect_trip_periods`.
        path: Destination file path.
    """
    payload = {
        "cache_key": cache_key,
        "chapters": chapters,
        "trip_periods": [[start, end] for start, end in trip_periods],
    }
    _save_deep_cache(payload, path)


def load_life_chapters_cache(
    cache_key: str, path: str = LIFE_CHAPTERS_CACHE
) -> Optional[tuple[list[dict[str, Any]], list[tuple[pd.Timestamp, pd.Timestamp]]]]:
    """Load Life in Chapters' precomputed ``chapters``/``trip_periods`` from disk.

    Args:
        cache_key: The key from :func:`get_life_chapters_cache_key`. If it
            does not match the stored key, the cache is treated as stale and
            this returns None (forced miss, never a stale hit).
        path: Path to the JSON cache file.

    Returns:
        ``(chapters, trip_periods)`` with ``pd.Timestamp`` objects
        reconstructed for every date field, or None if the file is missing,
        corrupt, or stale.
    """
    raw = _load_deep_cache(path)
    if raw is None or not isinstance(raw, dict):
        return None
    if raw.get("cache_key") != cache_key:
        return None

    chapters: list[dict[str, Any]] = []
    for chapter in raw.get("chapters", []):
        restored = dict(chapter)
        if restored.get("start") is not None:
            restored["start"] = pd.Timestamp(restored["start"])
        if restored.get("end") is not None:
            restored["end"] = pd.Timestamp(restored["end"])
        chapters.append(restored)

    trip_periods: list[tuple[pd.Timestamp, pd.Timestamp]] = [
        (pd.Timestamp(start), pd.Timestamp(end)) for start, end in raw.get("trip_periods", [])
    ]

    return chapters, trip_periods


# ---------------------------------------------------------------------------
# Listening session detection
# ---------------------------------------------------------------------------


def detect_listening_sessions(df: pd.DataFrame, gap_minutes: int = 30) -> pd.DataFrame:
    """Assign a session_id to each row based on listening gaps.

    Consecutive plays within ``gap_minutes`` of each other belong to the same
    session.  The DataFrame is sorted by ``timestamp`` ascending before
    processing; the returned copy preserves that order.

    Args:
        df: Last.fm-style DataFrame with at least a ``timestamp`` column
            containing Unix epoch seconds (int or float).
        gap_minutes: Minimum gap in minutes between plays that starts a new
            session.  Defaults to 30.

    Returns:
        A copy of ``df`` (sorted by ``timestamp``) with an integer
        ``session_id`` column added.  The first session has id 0.
    """
    if df.empty:
        result = df.copy()
        result["session_id"] = pd.array([], dtype="int64")
        return result

    result = df.sort_values("timestamp").copy()
    gap_seconds = gap_minutes * 60
    timestamps = result["timestamp"].to_numpy()
    session_ids = [0] * len(timestamps)
    current_id = 0
    for i in range(1, len(timestamps)):
        if (timestamps[i] - timestamps[i - 1]) > gap_seconds:
            current_id += 1
        session_ids[i] = current_id
    result["session_id"] = pd.array(session_ids, dtype="int64")
    return result


def get_session_stats(df_with_sessions: pd.DataFrame) -> pd.DataFrame:
    """Compute per-session statistics from a session-annotated DataFrame.

    Args:
        df_with_sessions: Output of :func:`detect_listening_sessions` — must
            have ``session_id``, ``timestamp``, ``date_text``, ``artist``, and
            ``track`` columns.

    Returns:
        One row per session with columns: ``session_start`` (datetime),
        ``session_end`` (datetime), ``track_count`` (int),
        ``duration_minutes`` (float), ``hour_of_day`` (int),
        ``day_of_week`` (str, e.g. "Monday"), ``opening_track`` (str),
        ``opening_artist`` (str).
    """
    rows = []
    for session_id, group in df_with_sessions.groupby("session_id", sort=True):
        group_sorted = group.sort_values("timestamp")
        first_row = group_sorted.iloc[0]
        last_row = group_sorted.iloc[-1]

        # Resolve session_start as a datetime
        if hasattr(first_row["date_text"], "tzinfo"):
            session_start = first_row["date_text"]
        else:
            session_start = pd.to_datetime(first_row["date_text"], utc=True)

        if hasattr(last_row["date_text"], "tzinfo"):
            session_end = last_row["date_text"]
        else:
            session_end = pd.to_datetime(last_row["date_text"], utc=True)

        duration_minutes = (last_row["timestamp"] - first_row["timestamp"]) / 60.0

        rows.append(
            {
                "session_id": int(session_id),
                "session_start": session_start,
                "session_end": session_end,
                "track_count": len(group_sorted),
                "duration_minutes": duration_minutes,
                "hour_of_day": int(session_start.hour),
                "day_of_week": session_start.strftime("%A"),
                "opening_track": str(first_row["track"]),
                "opening_artist": str(first_row["artist"]),
            }
        )

    return pd.DataFrame(rows)


def get_session_opening_tracks(session_stats: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Return the most frequent session-opening (artist, track) pairs.

    Args:
        session_stats: Output of :func:`get_session_stats`.
        top_n: Number of top entries to return.  Defaults to 10.

    Returns:
        DataFrame with columns ``opening_artist``, ``opening_track``, ``count``
        sorted by ``count`` descending.
    """
    if session_stats.empty:
        return pd.DataFrame(columns=["opening_artist", "opening_track", "count"])

    counts = (
        session_stats.groupby(["opening_artist", "opening_track"], sort=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    return counts


def get_session_time_distribution(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Count sessions by hour of day.

    Args:
        session_stats: Output of :func:`get_session_stats`.

    Returns:
        DataFrame with columns ``hour`` (int 0–23) and ``session_count`` (int),
        one row per hour that has at least one session.
    """
    if session_stats.empty:
        return pd.DataFrame(columns=["hour", "session_count"])

    dist = (
        session_stats.groupby("hour_of_day", sort=True)
        .size()
        .reset_index(name="session_count")
        .rename(columns={"hour_of_day": "hour"})
    )
    return dist


# ---------------------------------------------------------------------------
# Subtask 2 — Music Personality Metrics
# ---------------------------------------------------------------------------


def get_gini_coefficient(df: pd.DataFrame, entity: str = "artist") -> float:
    """Compute the Gini coefficient on the play-count distribution for an entity column.

    A Gini of 0.0 means perfectly equal plays across all entities; 1.0 means
    a single entity has all the plays.

    Args:
        df: Last.fm-style DataFrame containing the ``entity`` column.
        entity: Column name to aggregate play counts by.  Defaults to ``"artist"``.

    Returns:
        Gini coefficient in [0.0, 1.0].  Returns 0.0 for an empty DataFrame.
        Returns 1.0 when only one entity is present (perfect concentration).
    """
    if df.empty or entity not in df.columns:
        return 0.0

    counts = df[entity].value_counts().values.astype(float)
    n = len(counts)
    if n == 0:
        return 0.0

    counts.sort()
    total = counts.sum()
    if total == 0.0:
        return 0.0
    if n == 1:
        # Single entity holds all plays — perfect concentration
        return 1.0
    # Standard closed-form Gini: G = (2 * sum((i+1)*y_i) / (n * sum(y_i))) - (n+1)/n
    indices = np.arange(1, n + 1)
    gini = (2.0 * np.dot(indices, counts) / (n * total)) - (n + 1) / n
    return float(np.clip(gini, 0.0, 1.0))


def get_monthly_new_artist_rate(df: pd.DataFrame) -> pd.DataFrame:
    """Count artists heard for the first time in each calendar month.

    Args:
        df: Last.fm-style DataFrame with ``date_text`` (datetime) and ``artist`` columns.

    Returns:
        DataFrame with columns ``month`` (Timestamp, period start, UTC) and
        ``new_artists`` (int), sorted by ``month`` ascending.
    """
    if df.empty:
        return pd.DataFrame(columns=["month", "new_artists"])

    work = df[["date_text", "artist"]].copy()
    work["date_text"] = pd.to_datetime(work["date_text"], utc=True)
    # Month-period start for each play
    month_start = work["date_text"].dt.to_period("M").dt.to_timestamp(freq="D", how="start")
    work["month"] = month_start.dt.tz_localize("UTC")

    # First ever play month per artist
    first_month = work.groupby("artist")["month"].min().reset_index()
    first_month.columns = ["artist", "month"]

    # Count new artists per month
    rate = (
        first_month.groupby("month")
        .size()
        .reset_index(name="new_artists")
        .sort_values("month")
        .reset_index(drop=True)
    )
    rate["new_artists"] = rate["new_artists"].astype(int)
    return rate


def get_loyalty_score(df: pd.DataFrame, min_years_ago: int = 2) -> float:
    """Compute the loyalty score: fraction of old artists still in the all-time top 100.

    "Old" artists are those whose first play is at least ``min_years_ago`` years before
    the dataset's latest timestamp.  Among those old artists, the score is the fraction
    that also appear in the all-time top-100 by play count.

    Args:
        df: Last.fm-style DataFrame with ``date_text`` (datetime) and ``artist`` columns.
        min_years_ago: Minimum years before the latest play for an artist to be considered
            "old".  Defaults to 2.

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 when there are no old artists.
    """
    if df.empty or "artist" not in df.columns:
        return 0.0

    dates = pd.to_datetime(df["date_text"], utc=True)
    max_date = dates.max()
    cutoff = max_date - pd.DateOffset(years=min_years_ago)

    # First play date per artist
    first_plays = df.assign(_date=dates).groupby("artist")["_date"].min()
    old_artists = set(first_plays[first_plays <= cutoff].index)

    if not old_artists:
        return 0.0

    # Top 100 by play count using only RECENT plays (after the cutoff date).
    # This measures whether old artists are still actively listened to today.
    recent_df = df[dates > cutoff]
    if recent_df.empty:
        # No recent plays at all — no old artist is currently "active"
        return 0.0
    top_100 = set(recent_df["artist"].value_counts().head(100).index)

    loyal = old_artists & top_100
    return float(len(loyal) / len(old_artists))


def get_comfort_ratio(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the ratio of familiar to new plays per calendar month.

    For each month:
    - ``familiar_plays``: plays from artists whose first play was *before* that month.
    - ``new_plays``: plays from artists whose first play was *in* that month.
    - ``comfort_ratio``: familiar_plays / (familiar_plays + new_plays).

    Args:
        df: Last.fm-style DataFrame with ``date_text`` (datetime) and ``artist`` columns.

    Returns:
        DataFrame with columns ``month``, ``familiar_plays``, ``new_plays``,
        ``comfort_ratio``, sorted by ``month`` ascending.
    """
    cols = ["month", "familiar_plays", "new_plays", "comfort_ratio"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    work = df[["date_text", "artist"]].copy()
    work["date_text"] = pd.to_datetime(work["date_text"], utc=True)
    month_start = work["date_text"].dt.to_period("M").dt.to_timestamp(freq="D", how="start")
    work["month"] = month_start.dt.tz_localize("UTC")

    # First play month per artist
    first_month = work.groupby("artist")["month"].min().rename("first_month")
    work = work.join(first_month, on="artist")

    work["play_type"] = np.where(work["month"] == work["first_month"], "new", "familiar")

    pivot = work.groupby(["month", "play_type"]).size().unstack(fill_value=0).reset_index()
    if "familiar" not in pivot.columns:
        pivot["familiar"] = 0
    if "new" not in pivot.columns:
        pivot["new"] = 0

    pivot = pivot.rename(columns={"familiar": "familiar_plays", "new": "new_plays"})
    pivot = pivot.sort_values("month").reset_index(drop=True)
    total = pivot["familiar_plays"] + pivot["new_plays"]
    pivot["comfort_ratio"] = pivot["familiar_plays"] / total.where(total > 0, other=1.0)
    return pivot[cols]


def get_album_plays_by_familiarity(df: pd.DataFrame) -> pd.DataFrame:
    """Album play counts split by whether the artist was familiar or new that month.

    Uses the same familiar/new tagging as :func:`get_comfort_ratio`: an artist is
    "new" in the month of their first ever play, and "familiar" in all subsequent months.

    Args:
        df: Last.fm-style DataFrame with ``date_text`` (datetime), ``artist``, and
            ``album`` columns.

    Returns:
        DataFrame with columns ``month`` (UTC datetime), ``play_type``
        (``"familiar"`` or ``"new"``), ``artist``, ``album``, ``plays`` (int),
        sorted by ``month`` ascending then ``plays`` descending.
    """
    out_cols = ["month", "play_type", "artist", "album", "plays"]
    if df.empty or "album" not in df.columns:
        return pd.DataFrame(columns=out_cols)

    work = df[["date_text", "artist", "album"]].copy()
    work["date_text"] = pd.to_datetime(work["date_text"], utc=True)
    month_start = work["date_text"].dt.to_period("M").dt.to_timestamp(freq="D", how="start")
    work["month"] = month_start.dt.tz_localize("UTC")

    first_month = work.groupby("artist")["month"].min().rename("first_month")
    work = work.join(first_month, on="artist")
    work["play_type"] = np.where(work["month"] == work["first_month"], "new", "familiar")

    result = (
        work.groupby(["month", "play_type", "artist", "album"])
        .size()
        .reset_index(name="plays")
        .sort_values(["month", "plays"], ascending=[True, False])
        .reset_index(drop=True)
    )
    return result[out_cols]


def get_artist_lifecycle(df: pd.DataFrame, artist: str) -> dict[str, Any]:
    """Compute lifecycle statistics for a single artist.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds),
            ``artist``, ``track``, and ``album`` columns.
        artist: Artist name to analyse.

    Returns:
        Dict with keys:
        - ``discovery_date``: pd.Timestamp of first play.
        - ``peak_month``: pd.Period (freq="M") of month with most plays.
        - ``last_play``: pd.Timestamp of last play.
        - ``total_plays``: int total play count.
        - ``monthly_plays``: DataFrame with columns ``month`` (Period) and
          ``plays`` (int).
        - ``play_years``: sorted list of distinct calendar years.
    """
    artist_df = df[df["artist"] == artist].copy()
    artist_df = artist_df.sort_values("timestamp").reset_index(drop=True)

    timestamps = pd.to_datetime(artist_df["timestamp"], unit="s")
    discovery_date: pd.Timestamp = timestamps.iloc[0]
    last_play: pd.Timestamp = timestamps.iloc[-1]
    total_plays: int = len(artist_df)

    months = timestamps.dt.to_period("M")
    monthly_counts = months.value_counts().sort_index()
    monthly_plays = monthly_counts.reset_index()
    monthly_plays.columns = pd.Index(["month", "plays"])
    monthly_plays = monthly_plays.sort_values("month").reset_index(drop=True)

    peak_month: pd.Period = monthly_counts.idxmax()
    play_years: list[int] = sorted(timestamps.dt.year.unique().tolist())

    return {
        "discovery_date": discovery_date,
        "peak_month": peak_month,
        "last_play": last_play,
        "total_plays": total_plays,
        "monthly_plays": monthly_plays,
        "play_years": play_years,
    }


def get_all_artist_arcs(df: pd.DataFrame, min_plays: int = 20) -> pd.DataFrame:
    """Classify each artist's listening arc based on their play history.

    For every artist with at least ``min_plays`` total plays, computes lifecycle
    metrics and assigns one of the following arc types (evaluated in order):

    1. ``"one-hit"``   — active in ≤ 3 distinct months.
    2. ``"obsession"`` — peak month plays ≥ 3× median monthly plays **and**
       months from peak to last play ≥ 6.
    3. ``"rediscovery"`` — largest gap between consecutive active months ≥ 18.
    4. ``"perennial"`` — active in ≥ 75 % of calendar years since discovery.
    5. ``"other"``     — catch-all.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds) and
            ``artist`` column.
        min_plays: Minimum total plays required for an artist to be included.
            Defaults to 20.

    Returns:
        DataFrame with columns: ``artist``, ``discovery_date``, ``peak_month``,
        ``last_play``, ``total_plays``, ``arc_type``, ``peak_plays``,
        ``peak_ratio``.
    """
    cols = [
        "artist",
        "discovery_date",
        "peak_month",
        "last_play",
        "total_plays",
        "arc_type",
        "peak_plays",
        "peak_ratio",
    ]
    if df.empty:
        return pd.DataFrame(columns=cols)

    work = df[["timestamp", "artist"]].copy()
    work["ts"] = pd.to_datetime(work["timestamp"], unit="s")
    work["month"] = work["ts"].dt.to_period("M")
    work["year"] = work["ts"].dt.year

    total_plays_s = work.groupby("artist").size()
    qualified = total_plays_s[total_plays_s >= min_plays].index
    if qualified.empty:
        return pd.DataFrame(columns=cols)

    work = work[work["artist"].isin(qualified)]

    discovery = work.groupby("artist")["ts"].min().rename("discovery_date")
    last_play = work.groupby("artist")["ts"].max().rename("last_play")
    total_plays_q = work.groupby("artist").size().rename("total_plays")

    monthly = work.groupby(["artist", "month"]).size().rename("plays")
    peak_month_s = monthly.groupby("artist").idxmax()
    # idxmax returns (artist, month) tuples; extract just month
    peak_month_s = peak_month_s.map(lambda x: x[1]).rename("peak_month")
    peak_plays_s = monthly.groupby("artist").max().rename("peak_plays")
    median_plays_s = monthly.groupby("artist").median().rename("median_plays")
    mean_plays_s = monthly.groupby("artist").mean().rename("mean_plays")

    active_months_s = monthly.groupby("artist").count().rename("active_months")

    years_df = (
        work.groupby(["artist", "year"]).size().groupby("artist").count().rename("active_years")
    )
    discovery_year = work.groupby("artist")["year"].min().rename("discovery_year")
    last_year = work.groupby("artist")["year"].max().rename("last_year")

    arc_df = pd.concat(
        [
            discovery,
            last_play,
            total_plays_q,
            peak_month_s,
            peak_plays_s,
            median_plays_s,
            mean_plays_s,
            active_months_s,
            years_df,
            discovery_year,
            last_year,
        ],
        axis=1,
    ).reset_index()

    # peak_ratio = peak_plays / mean_monthly_plays
    arc_df["peak_ratio"] = arc_df["peak_plays"] / arc_df["mean_plays"].where(
        arc_df["mean_plays"] > 0, other=1.0
    )

    # Compute months_from_peak_to_last for obsession rule
    arc_df["peak_month_period"] = arc_df["peak_month"]
    arc_df["last_play_period"] = arc_df["last_play"].dt.to_period("M")
    arc_df["months_from_peak_to_last"] = arc_df["last_play_period"].apply(
        lambda p: p.ordinal
    ) - arc_df["peak_month_period"].apply(lambda p: p.ordinal)

    # Compute years_since_discovery
    arc_df["years_since_discovery"] = arc_df["last_year"] - arc_df["discovery_year"] + 1

    # Compute max consecutive month gap (for rediscovery rule) per artist
    def _max_month_gap(artist_name: str) -> int:
        artist_months = (
            monthly.loc[artist_name].index.sort_values()
            if artist_name in monthly.index.get_level_values(0)
            else pd.PeriodIndex([], freq="M")
        )
        if len(artist_months) < 2:
            return 0
        ordinals = pd.Series([p.ordinal for p in artist_months])
        gaps = ordinals.diff().dropna()
        return int(gaps.max())

    arc_df["max_gap"] = arc_df["artist"].apply(_max_month_gap)

    # Compute per-artist non-peak median (median of all months excluding peak month)
    def _nonpeak_median(artist_name: str, peak: pd.Period) -> float:
        if artist_name not in monthly.index.get_level_values(0):
            return 1.0
        m = monthly.loc[artist_name]
        non_peak = m[m.index != peak]
        if non_peak.empty:
            return 1.0
        return float(non_peak.median())

    arc_df["nonpeak_median"] = arc_df.apply(
        lambda r: _nonpeak_median(r["artist"], r["peak_month"]), axis=1
    )

    # Classify arc type (obsession checked before one-hit so a big spike with few
    # active months is correctly labelled obsession rather than one-hit)
    def _classify(row: Any) -> str:
        if row["peak_plays"] >= 3 * row["nonpeak_median"] and row["months_from_peak_to_last"] >= 6:
            return "obsession"
        if row["active_months"] <= 3:
            return "one-hit"
        if row["max_gap"] >= 18:
            return "rediscovery"
        years_ok = row["years_since_discovery"] > 0 and (
            row["active_years"] >= 0.75 * row["years_since_discovery"]
        )
        if years_ok:
            return "perennial"
        return "other"

    arc_df["arc_type"] = arc_df.apply(_classify, axis=1)

    return arc_df[cols].reset_index(drop=True)


def get_top_obsessions(arc_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Return the top obsession artists sorted by peak_ratio descending.

    Args:
        arc_df: DataFrame produced by :func:`get_all_artist_arcs`.
        top_n: Maximum number of rows to return. Defaults to 10.

    Returns:
        Filtered DataFrame of ``arc_type == "obsession"`` rows sorted by
        ``peak_ratio`` descending.  Returns an empty DataFrame (preserving
        all columns) if no obsession rows exist.
    """
    if arc_df.empty:
        return arc_df.iloc[0:0].copy()

    obsessions = arc_df[arc_df["arc_type"] == "obsession"].copy()
    if obsessions.empty:
        return obsessions

    return obsessions.sort_values("peak_ratio", ascending=False).head(top_n).reset_index(drop=True)


def get_album_sequence_depth(df: pd.DataFrame, min_sequence_length: int = 3) -> pd.DataFrame:
    """Detect consecutive runs of tracks from the same album and count deep listens.

    A "deep listen" is one continuous run of ``min_sequence_length`` or more
    consecutive tracks from the same ``(artist, album)`` pair (by timestamp order).

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int), ``artist``, and
            ``album`` columns.
        min_sequence_length: Minimum run length to qualify as a deep listen.
            Defaults to 3.

    Returns:
        DataFrame with columns ``artist``, ``album``, ``deep_listen_count``,
        one row per (artist, album) pair with at least one deep listen, sorted by
        ``deep_listen_count`` descending.
    """
    if df.empty:
        return pd.DataFrame(columns=["artist", "album", "deep_listen_count"])

    work = df[["timestamp", "artist", "album"]].copy()
    work = work.sort_values("timestamp").reset_index(drop=True)

    # Identify run boundaries: a new run starts where artist or album changes
    key = work["artist"] + "\x00" + work["album"]
    boundary = key != key.shift(1)
    run_id = boundary.cumsum()

    work["run_id"] = run_id
    run_lengths = work.groupby("run_id").size()
    # Keep only runs that qualify as deep listens
    deep_runs = run_lengths[run_lengths >= min_sequence_length].index
    cols = ["run_id", "artist", "album"]
    deep_work = work[work["run_id"].isin(deep_runs)][cols].drop_duplicates("run_id")

    if deep_work.empty:
        return pd.DataFrame(columns=["artist", "album", "deep_listen_count"])

    result = (
        deep_work.groupby(["artist", "album"])
        .size()
        .reset_index(name="deep_listen_count")
        .sort_values("deep_listen_count", ascending=False)
        .reset_index(drop=True)
    )
    return result


# ---------------------------------------------------------------------------
# Subtask 4 — Seasonal & Temporal Fingerprinting
# ---------------------------------------------------------------------------

_DEFAULT_SEASON_DEFINITIONS: dict[str, list[int]] = {
    "Winter": [12, 1, 2],
    "Spring": [3, 4, 5],
    "Summer": [6, 7, 8],
    "Fall": [9, 10, 11],
}


def get_seasonal_artist_affinity(
    df: pd.DataFrame,
    season_definitions: Optional[dict[str, list[int]]] = None,
) -> pd.DataFrame:
    """Compute seasonal affinity scores for the top-50 artists.

    For each (artist, season) pair the affinity score is:
        artist_season_fraction / overall_season_fraction

    A score > 1 means the artist is over-represented in that season relative
    to the season's share of total plays.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds),
            ``artist``, ``track``, and ``album`` columns.
        season_definitions: Mapping of season name → list of month numbers.
            Defaults to Winter/Spring/Summer/Fall.

    Returns:
        DataFrame with columns ``artist``, ``season``, ``affinity_score``,
        ``play_count``, one row per (artist, season) combination.  Returns an
        empty DataFrame when ``df`` is empty.
    """
    if df.empty:
        return pd.DataFrame(columns=["artist", "season", "affinity_score", "play_count"])

    seasons = season_definitions if season_definitions is not None else _DEFAULT_SEASON_DEFINITIONS

    work = df[["timestamp", "artist"]].copy()
    work["month"] = pd.to_datetime(work["timestamp"], unit="s").dt.month

    # Build month → season mapping
    month_to_season: dict[int, str] = {}
    for season, months in seasons.items():
        for m in months:
            month_to_season[m] = season
    work["season"] = work["month"].map(month_to_season)
    work = work.dropna(subset=["season"])

    total_plays = len(work)
    if total_plays == 0:
        return pd.DataFrame(columns=["artist", "season", "affinity_score", "play_count"])

    # Baseline fraction of plays per season — expected share based on equal-weight months.
    # Each season covers 3 months; a uniform baseline is 3/12 = 0.25.
    # Using month-count fractions (not observed-play fractions) ensures that an artist
    # with all plays in a single season scores substantially above 1.0.
    total_months = sum(len(months) for months in seasons.values())
    overall_season_frac: dict[str, float] = {
        season: len(months) / total_months for season, months in seasons.items()
    }

    # Top-50 artists by total play count
    top_artists = work.groupby("artist").size().nlargest(50).index.tolist()
    work = work[work["artist"].isin(top_artists)]

    # Per-artist total plays (used as denominator for artist_season_fraction)
    artist_totals = work.groupby("artist").size()

    # Per-artist, per-season play counts
    artist_season_counts = work.groupby(["artist", "season"]).size().reset_index(name="play_count")

    rows = []
    for _, row in artist_season_counts.iterrows():
        artist = row["artist"]
        season = row["season"]
        count = int(row["play_count"])
        artist_total = artist_totals[artist]
        artist_season_frac = count / artist_total if artist_total > 0 else 0.0
        baseline = overall_season_frac.get(season, 0.0)
        affinity = artist_season_frac / baseline if baseline > 0 else 0.0
        rows.append(
            {
                "artist": artist,
                "season": season,
                "affinity_score": affinity,
                "play_count": count,
            }
        )

    return pd.DataFrame(rows)


def get_morning_vs_night_artists(
    df: pd.DataFrame,
    top_n: int = 10,
) -> dict[str, pd.DataFrame]:
    """Return the top artists listened to in the morning and at night.

    Morning hours: 5–11 inclusive.
    Night hours: 21–23 and 0–3 inclusive.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds) and
            ``artist`` columns.
        top_n: Number of top artists to return per bucket.

    Returns:
        Dict with ``"morning"`` and ``"night"`` keys, each holding a DataFrame
        with columns ``artist`` and ``plays``, sorted by ``plays`` descending.
        Both DataFrames are empty when ``df`` is empty.
    """
    empty = pd.DataFrame(columns=["artist", "plays"])
    if df.empty:
        return {"morning": empty.copy(), "night": empty.copy()}

    work = df[["timestamp", "artist"]].copy()
    work["hour"] = pd.to_datetime(work["timestamp"], unit="s").dt.hour

    morning_mask = (work["hour"] >= 5) & (work["hour"] <= 11)
    night_mask = (work["hour"] >= 21) | (work["hour"] <= 3)

    def _top(mask: pd.Series) -> pd.DataFrame:
        subset = work[mask]
        if subset.empty:
            return empty.copy()
        counts = subset.groupby("artist").size().nlargest(top_n).reset_index(name="plays")
        return counts

    return {"morning": _top(morning_mask), "night": _top(night_mask)}


def get_day_of_week_personality(df: pd.DataFrame) -> pd.DataFrame:
    """Summarise listening behaviour by day of week.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds) and
            ``artist`` columns.

    Returns:
        DataFrame with columns ``day_of_week``, ``top_artist``, ``play_count``,
        ``unique_artists``, one row per day present in the data.
    """
    if df.empty:
        return pd.DataFrame(columns=["day_of_week", "top_artist", "play_count", "unique_artists"])

    work = df[["timestamp", "artist"]].copy()
    dt = pd.to_datetime(work["timestamp"], unit="s")
    work["day_of_week"] = dt.dt.day_name()

    rows = []
    for day, group in work.groupby("day_of_week"):
        top_artist_series = group.groupby("artist").size()
        top_artist = top_artist_series.idxmax()
        play_count = int(top_artist_series.max())
        unique_artists = int(top_artist_series.shape[0])
        rows.append(
            {
                "day_of_week": day,
                "top_artist": top_artist,
                "play_count": play_count,
                "unique_artists": unique_artists,
            }
        )

    return pd.DataFrame(rows)


def get_holiday_musical_identity(
    df: pd.DataFrame,
    assumptions: dict[str, Any],
    window_days: int = 3,
) -> pd.DataFrame:
    """Identify top artists and tracks listened to around each holiday.

    For every holiday defined in ``assumptions["holidays"]``, this function
    collects plays within ``window_days`` before or after each annual
    occurrence of that holiday and returns a summary row.

    Each holiday dict must have ``month`` and either ``day`` (int) or
    ``day_range`` ([start, end]).  An optional ``name`` field is used as the
    row label; otherwise a label is derived from month/day.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds),
            ``artist``, and ``track`` columns.
        assumptions: Dict containing ``"holidays"`` list.
        window_days: Number of days before/after the holiday centre to include.

    Returns:
        DataFrame with columns ``holiday_name``, ``top_artist``, ``top_track``,
        ``play_count``, one row per holiday.  Empty DataFrame if no holidays are
        defined or no matching plays exist.
    """
    holidays = assumptions.get("holidays", [])
    if not holidays or df.empty:
        return pd.DataFrame(columns=["holiday_name", "top_artist", "top_track", "play_count"])

    work = df[["timestamp", "artist", "track"]].copy()
    dt_series = pd.to_datetime(work["timestamp"], unit="s")
    work["date"] = dt_series.dt.normalize()

    # Determine the year range in the data
    years = dt_series.dt.year.unique().tolist()

    window_delta = pd.Timedelta(days=window_days)
    rows: list[dict[str, Any]] = []

    for holiday in holidays:
        month: int = int(holiday["month"])
        # Support both "day" (scalar) and "day_range" ([start, end])
        if "day" in holiday:
            day_center: int = int(holiday["day"])
        elif "day_range" in holiday:
            dr = holiday["day_range"]
            day_center = int((int(dr[0]) + int(dr[1])) // 2) or int(dr[0])
        else:
            continue

        name: str = holiday.get("name") or f"Holiday {month}/{day_center}"

        # Collect plays across all years
        matching_mask = pd.Series([False] * len(work), index=work.index)
        for year in years:
            try:
                center = pd.Timestamp(year=year, month=month, day=day_center)
            except ValueError:
                continue
            lower = center - window_delta
            upper = center + window_delta
            matching_mask |= (work["date"] >= lower) & (work["date"] <= upper)

        subset = work[matching_mask]
        if subset.empty:
            continue

        top_artist = subset.groupby("artist").size().idxmax()
        top_track = subset.groupby("track").size().idxmax()
        rows.append(
            {
                "holiday_name": name,
                "top_artist": top_artist,
                "top_track": top_track,
                "play_count": len(subset),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["holiday_name", "top_artist", "top_track", "play_count"])

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Subtask 5 — Geographic Taste Drift
# ---------------------------------------------------------------------------


def get_era_top_artists(
    df: pd.DataFrame,
    assumptions: dict[str, Any],
    top_n: int = 100,
) -> dict[str, pd.DataFrame]:
    """Return top-N artists per residency era, keyed by era label.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds) and
            ``artist`` columns.
        assumptions: Dict containing ``"residency"`` list.  Each entry must have
            ``start``, ``end``, and ``city`` keys (ISO date strings).
        top_n: Number of top artists to return per era.

    Returns:
        Dict mapping era label (e.g. ``"CityName (YYYY–YYYY)"``) to a DataFrame
        with columns ``artist`` and ``plays``, sorted by plays descending.
    """
    result: dict[str, pd.DataFrame] = {}

    for period in assumptions.get("residency", []):
        city = period.get("city", "Unknown")
        start_str = period.get("start", "")
        end_str = period.get("end", "")

        start_ts = int(pd.Timestamp(start_str).timestamp())
        end_ts = int(pd.Timestamp(end_str).timestamp())
        start_year = pd.Timestamp(start_str).year
        end_year = pd.Timestamp(end_str).year

        era_label = f"{city} ({start_year}–{end_year})"

        if df.empty:
            result[era_label] = pd.DataFrame(columns=["artist", "plays"])
            continue

        mask = (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
        era_df = df[mask]

        if era_df.empty:
            result[era_label] = pd.DataFrame(columns=["artist", "plays"])
        else:
            counts = era_df.groupby("artist").size().nlargest(top_n).reset_index(name="plays")
            result[era_label] = counts

    return result


def get_era_jaccard_similarity(
    era_tops: dict[str, pd.DataFrame],
    top_n: int = 100,
) -> pd.DataFrame:
    """Compute pairwise Jaccard similarity of artist sets across eras.

    Args:
        era_tops: Dict mapping era label to DataFrame with ``artist`` column,
            as returned by :func:`get_era_top_artists`.
        top_n: Number of top artists to use from each era for the comparison.

    Returns:
        Square DataFrame indexed and columned by era labels.  Diagonal
        entries are 1.0 (era vs itself).
    """
    labels = list(era_tops.keys())
    artist_sets: dict[str, set[str]] = {}
    for label, era_df in era_tops.items():
        if era_df.empty:
            artist_sets[label] = set()
        else:
            artist_sets[label] = set(era_df["artist"].head(top_n).tolist())

    data: dict[str, list[float]] = {label: [] for label in labels}

    for row_label in labels:
        for col_label in labels:
            set_a = artist_sets[row_label]
            set_b = artist_sets[col_label]
            if set_a == set_b:
                # Covers identical sets AND both-empty case (1.0 per spec)
                data[col_label].append(1.0)
            else:
                union = set_a | set_b
                intersection = set_a & set_b
                jaccard = len(intersection) / len(union) if union else 1.0
                data[col_label].append(jaccard)

    return pd.DataFrame(data, index=labels)


def get_era_defining_artists(
    df: pd.DataFrame,
    assumptions: dict[str, Any],
    exclusivity_threshold: float = 0.8,
    min_plays: int = 10,
) -> dict[str, list[str]]:
    """Identify artists whose plays are concentrated in one residency era.

    For each artist with ``>= min_plays`` total plays, compute the fraction
    of their plays in each era.  If that fraction meets
    ``exclusivity_threshold`` for one era, the artist is added to that era's
    defining list.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds) and
            ``artist`` columns.
        assumptions: Dict containing ``"residency"`` list.
        exclusivity_threshold: Fraction of plays required in one era to be
            considered defining for that era.  Defaults to 0.8.
        min_plays: Minimum total plays required across all eras.  Artists
            below this threshold are excluded.  Defaults to 10.

    Returns:
        Dict mapping era label to list of artist names.
    """
    residency = assumptions.get("residency", [])
    era_labels: list[str] = []
    era_ranges: list[tuple[int, int]] = []

    for period in residency:
        city = period.get("city", "Unknown")
        start_str = period.get("start", "")
        end_str = period.get("end", "")
        start_ts = int(pd.Timestamp(start_str).timestamp())
        end_ts = int(pd.Timestamp(end_str).timestamp())
        start_year = pd.Timestamp(start_str).year
        end_year = pd.Timestamp(end_str).year
        era_labels.append(f"{city} ({start_year}–{end_year})")
        era_ranges.append((start_ts, end_ts))

    result: dict[str, list[str]] = {label: [] for label in era_labels}

    if df.empty or not era_labels:
        return result

    # Total plays per artist
    total_plays = df.groupby("artist").size()
    qualified_artists = total_plays[total_plays >= min_plays].index

    for artist in qualified_artists:
        artist_df = df[df["artist"] == artist]
        total = len(artist_df)
        for label, (start_ts, end_ts) in zip(era_labels, era_ranges):
            ts = artist_df["timestamp"]
            era_count = ((ts >= start_ts) & (ts <= end_ts)).sum()
            fraction = era_count / total if total > 0 else 0.0
            if fraction >= exclusivity_threshold:
                result[label].append(artist)
                break  # assign to first qualifying era only

    return result


def get_taste_evolution_timeline(
    df: pd.DataFrame,
    assumptions: dict[str, Any],
    window_months: int = 6,
) -> pd.DataFrame:
    """Compute rolling top-10 artists for each calendar month.

    For each calendar month in the data's range, look back ``window_months``
    and compute the top-10 artists by play count.  Returns one row per
    (month, artist) pair with the artist's rank and play count.

    Args:
        df: Last.fm-style DataFrame with ``timestamp`` (int unix seconds) and
            ``artist`` columns.
        assumptions: Assumptions dict (currently unused; reserved for
            future era-scoping).
        window_months: Number of months to look back for each rolling window.
            Defaults to 6.

    Returns:
        DataFrame with columns ``month`` (Timestamp), ``artist``, ``rank``
        (1-based int), ``plays`` (int).  Returns an empty DataFrame when
        there is insufficient data.
    """
    if df.empty:
        return pd.DataFrame(columns=["month", "artist", "rank", "plays"])

    work = df[["timestamp", "artist"]].copy()
    dt_col = pd.to_datetime(work["timestamp"], unit="s")
    work["month"] = dt_col.dt.to_period("M")

    all_months = sorted(work["month"].unique())
    if len(all_months) < window_months:
        return pd.DataFrame(columns=["month", "artist", "rank", "plays"])

    rows: list[dict[str, Any]] = []

    for i, month in enumerate(all_months):
        # Look back window_months (inclusive of current month)
        start_idx = max(0, i - window_months + 1)
        window = all_months[start_idx : i + 1]
        mask = work["month"].isin(window)
        subset = work[mask]
        if subset.empty:
            continue
        top = subset.groupby("artist").size().nlargest(10).reset_index(name="plays")
        for rank_idx, row in enumerate(top.itertuples(index=False), start=1):
            rows.append(
                {
                    "month": month.to_timestamp(),
                    "artist": row.artist,
                    "rank": rank_idx,
                    "plays": int(row.plays),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["month", "artist", "rank", "plays"])

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Subtask 6 — Cross-Domain City Soundtracks
# ---------------------------------------------------------------------------


def get_city_soundtrack(
    lastfm_df: pd.DataFrame,
    city: str,
    city_start: pd.Timestamp,
    city_end: pd.Timestamp,
    window_days: int = 7,
    top_n: int = 10,
) -> dict[str, Any]:
    """Return the top artists and tracks listened to around a city visit.

    Filters ``lastfm_df`` to plays within the window
    ``[city_start - window_days, city_end + window_days]`` (inclusive).
    Timestamps in ``lastfm_df`` are unix integer seconds.

    Args:
        lastfm_df: DataFrame with columns ``timestamp`` (unix int seconds),
            ``artist``, ``track``, ``album``.
        city: City name (used as the ``"city"`` key in the result).
        city_start: Trip start date.
        city_end: Trip end date.
        window_days: Days before/after the trip dates to include.
        top_n: Number of top artists/tracks to return.

    Returns:
        Dict with keys ``city``, ``top_artists`` (DataFrame), ``top_tracks``
        (DataFrame), ``play_count`` (int), ``period_start`` (Timestamp),
        ``period_end`` (Timestamp).
    """
    import datetime

    period_start = city_start - datetime.timedelta(days=window_days)
    period_end = city_end + datetime.timedelta(days=window_days)

    start_ts = period_start.timestamp()
    end_ts = period_end.timestamp()

    if lastfm_df.empty:
        return {
            "city": city,
            "top_artists": pd.DataFrame(columns=["artist", "plays"]),
            "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
            "play_count": 0,
            "period_start": pd.Timestamp(period_start),
            "period_end": pd.Timestamp(period_end),
        }

    mask = (lastfm_df["timestamp"] >= start_ts) & (lastfm_df["timestamp"] <= end_ts)
    subset = lastfm_df[mask]

    top_artists = (
        subset.groupby("artist").size().nlargest(top_n).reset_index(name="plays")
        if not subset.empty
        else pd.DataFrame(columns=["artist", "plays"])
    )

    if not subset.empty and "track" in subset.columns:
        top_tracks = (
            subset.groupby(["track", "artist"]).size().nlargest(top_n).reset_index(name="plays")
        )
    else:
        top_tracks = pd.DataFrame(columns=["track", "artist", "plays"])

    return {
        "city": city,
        "top_artists": top_artists,
        "top_tracks": top_tracks,
        "play_count": int(len(subset)),
        "period_start": pd.Timestamp(period_start),
        "period_end": pd.Timestamp(period_end),
    }


def get_all_city_soundtracks(
    lastfm_df: pd.DataFrame,
    assumptions: dict[str, Any],
    swarm_df: Optional[pd.DataFrame] = None,
    window_days: int = 7,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Return per-city soundtrack dicts for all trips in assumptions.

    Iterates ``assumptions["trips"]``, deduplicates by city name (combining
    plays from all occurrences of the same city).  ``swarm_df`` is accepted
    but currently unused (reserved for future use).

    Args:
        lastfm_df: DataFrame with columns ``timestamp`` (unix int seconds),
            ``artist``, ``track``, ``album``.
        assumptions: Dict with a ``"trips"`` key whose value is a list of trip
            dicts each containing ``city``, ``start`` ("YYYY-MM-DD"), and
            ``end`` ("YYYY-MM-DD").
        swarm_df: Optional Swarm/Foursquare DataFrame (ignored for now).
        window_days: Days before/after each trip to include in the window.
        top_n: Number of top artists/tracks per city.

    Returns:
        List of soundtrack dicts (one per unique city), each as returned by
        :func:`get_city_soundtrack`.
    """
    trips = assumptions.get("trips", [])

    # Collect date ranges per city
    city_ranges: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for trip in trips:
        city = trip.get("city", "Unknown")
        start = pd.Timestamp(trip["start"])
        end = pd.Timestamp(trip["end"])
        city_ranges.setdefault(city, []).append((start, end))

    results: list[dict[str, Any]] = []
    for city, ranges in city_ranges.items():
        # Combine plays across all trips to this city
        import datetime as _dt

        combined_masks = pd.Series(False, index=lastfm_df.index) if not lastfm_df.empty else None
        overall_start = ranges[0][0]
        overall_end = ranges[0][1]

        for city_start, city_end in ranges:
            if city_start < overall_start:
                overall_start = city_start
            if city_end > overall_end:
                overall_end = city_end
            if combined_masks is not None:
                ps = (city_start - _dt.timedelta(days=window_days)).timestamp()
                pe = (city_end + _dt.timedelta(days=window_days)).timestamp()
                combined_masks |= (lastfm_df["timestamp"] >= ps) & (lastfm_df["timestamp"] <= pe)

        if combined_masks is not None:
            subset = lastfm_df[combined_masks]
        else:
            subset = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])

        top_artists = (
            subset.groupby("artist").size().nlargest(top_n).reset_index(name="plays")
            if not subset.empty
            else pd.DataFrame(columns=["artist", "plays"])
        )

        if not subset.empty and "track" in subset.columns:
            top_tracks = (
                subset.groupby(["track", "artist"]).size().nlargest(top_n).reset_index(name="plays")
            )
        else:
            top_tracks = pd.DataFrame(columns=["track", "artist", "plays"])

        results.append(
            {
                "city": city,
                "top_artists": top_artists,
                "top_tracks": top_tracks,
                "play_count": int(len(subset)),
                "period_start": pd.Timestamp(overall_start),
                "period_end": pd.Timestamp(overall_end),
            }
        )

    return results


def get_venue_loyalty_scores(
    swarm_df: pd.DataFrame,
    top_n: int = 20,
) -> pd.DataFrame:
    """Rank venues by visit count and compute a normalized loyalty score.

    Args:
        swarm_df: Swarm DataFrame with ``venue`` and ``venue_category`` columns.
        top_n: Maximum number of venues to return.

    Returns:
        DataFrame with columns ``venue``, ``venue_category``, ``visit_count``,
        ``loyalty_score`` (0–1, normalized by max visit count), sorted by
        ``visit_count`` descending.  Empty DataFrame (with correct columns)
        when input is empty.
    """
    _LOYALTY_COLS = ["venue", "venue_category", "visit_count", "loyalty_score"]
    if swarm_df.empty or "venue" not in swarm_df.columns:
        return pd.DataFrame(columns=_LOYALTY_COLS)

    counts = (
        swarm_df.groupby(["venue", "venue_category"], sort=False)
        .size()
        .reset_index(name="visit_count")
    )
    max_count = counts["visit_count"].max()
    counts["loyalty_score"] = counts["visit_count"] / max_count
    return counts.sort_values("visit_count", ascending=False).head(top_n).reset_index(drop=True)


def get_routine_venues(
    swarm_df: pd.DataFrame,
    min_occurrences: int = 3,
    day_of_week_threshold: float = 0.5,
) -> pd.DataFrame:
    """Identify venues visited routinely on the same day of the week.

    A venue is "routine" when:
    - ``visit_count >= min_occurrences``, AND
    - the fraction of visits on the most common day of week >=
      ``day_of_week_threshold``.

    Args:
        swarm_df: Swarm DataFrame with ``timestamp``, ``venue``,
            ``venue_category`` columns.
        min_occurrences: Minimum number of visits for a venue to qualify.
        day_of_week_threshold: Minimum fraction of visits on the dominant day
            of the week.

    Returns:
        DataFrame with columns ``venue``, ``venue_category``, ``dominant_day``
        (e.g. "Monday"), ``day_fraction``, ``visit_count``.
    """
    _ROUTINE_COLS = ["venue", "venue_category", "dominant_day", "day_fraction", "visit_count"]
    if swarm_df.empty or "venue" not in swarm_df.columns:
        return pd.DataFrame(columns=_ROUTINE_COLS)

    df = swarm_df.copy()
    df["_day"] = pd.to_datetime(df["timestamp"], unit="s").dt.day_name()

    records = []
    for (venue, cat), group in df.groupby(["venue", "venue_category"], sort=False):
        visit_count = len(group)
        if visit_count < min_occurrences:
            continue
        day_counts = group["_day"].value_counts()
        dominant_day = str(day_counts.idxmax())
        day_fraction = float(day_counts.iloc[0] / visit_count)
        if day_fraction >= day_of_week_threshold:
            records.append(
                {
                    "venue": venue,
                    "venue_category": cat,
                    "dominant_day": dominant_day,
                    "day_fraction": day_fraction,
                    "visit_count": visit_count,
                }
            )

    if not records:
        return pd.DataFrame(columns=_ROUTINE_COLS)
    return pd.DataFrame(records)


def get_venue_exploration_rate(swarm_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-month new venue count, revisits, and exploration ratio.

    For each calendar month:
    - ``new_venues``: count of venues appearing for the first time ever.
    - ``revisits``: visits to venues already seen in a prior month.
    - ``exploration_ratio``: new_venues / (new_venues + revisits), or 0.0
      when both are zero.

    Args:
        swarm_df: Swarm DataFrame with ``timestamp`` and ``venue`` columns.

    Returns:
        DataFrame sorted by ``month`` ascending, with columns ``month``
        (Timestamp, period start), ``new_venues`` (int), ``revisits`` (int),
        ``exploration_ratio`` (float).
    """
    _EXPL_COLS = ["month", "new_venues", "revisits", "exploration_ratio"]
    if swarm_df.empty or "venue" not in swarm_df.columns:
        return pd.DataFrame(columns=_EXPL_COLS)

    df = swarm_df.copy()
    df["_month"] = pd.to_datetime(df["timestamp"], unit="s").dt.to_period("M")
    df = df.sort_values("_month")

    seen_venues: set[str] = set()
    records = []
    for month_period, group in df.groupby("_month", sort=True):
        month_venues = group["venue"].values
        new = 0
        rev = 0
        for v in month_venues:
            if v in seen_venues:
                rev += 1
            else:
                new += 1
        # Update seen_venues with all unique venues first encountered this month
        for v in month_venues:
            seen_venues.add(v)
        total = new + rev
        ratio = new / total if total > 0 else 0.0
        records.append(
            {
                "month": month_period.to_timestamp(),
                "new_venues": new,
                "revisits": rev,
                "exploration_ratio": ratio,
            }
        )

    return pd.DataFrame(records)


def get_music_around_venue_type(
    swarm_df: pd.DataFrame,
    lastfm_df: pd.DataFrame,
    category_keywords: list[str],
    window_minutes: int = 60,
    top_n: int = 10,
) -> dict[str, Any]:
    """Find music played around check-ins at a given venue category type.

    Filters Swarm check-ins whose ``venue_category`` contains any of the
    ``category_keywords`` (case-insensitive), then aggregates Last.fm plays
    within ``window_minutes`` before or after each matching check-in.

    Delegates window logic to the existing :func:`_listens_around_checkin`
    helper.

    Args:
        swarm_df: Swarm DataFrame with ``timestamp`` and ``venue_category``.
        lastfm_df: Listening history with ``timestamp``, ``artist``, ``track``.
        category_keywords: List of sub-strings to match against
            ``venue_category`` (case-insensitive OR logic).
        window_minutes: Symmetric window in minutes around each check-in.
        top_n: Number of top artists / tracks to return.

    Returns:
        Dict with keys:
        - ``top_artists``: DataFrame(artist, plays)
        - ``top_tracks``: DataFrame(track, artist, plays)
        - ``checkin_count``: int
        - ``listen_count``: int
    """
    _empty: dict[str, Any] = {
        "top_artists": pd.DataFrame(columns=["artist", "plays"]),
        "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
        "checkin_count": 0,
        "listen_count": 0,
    }

    if swarm_df.empty or "venue_category" not in swarm_df.columns:
        return _empty

    lower_keywords = [kw.lower() for kw in category_keywords]

    def _matches(cat: str) -> bool:
        low = cat.lower()
        return any(kw in low for kw in lower_keywords)

    matching = swarm_df[swarm_df["venue_category"].apply(lambda c: _matches(str(c)))]
    checkin_count = len(matching)

    if checkin_count == 0:
        return {**_empty, "checkin_count": 0}

    frames: list[pd.DataFrame] = []
    for _, row in matching.iterrows():
        nearby = _listens_around_checkin(lastfm_df, int(row["timestamp"]), window_minutes)
        if not nearby.empty:
            frames.append(nearby)

    if not frames:
        return {
            "top_artists": pd.DataFrame(columns=["artist", "plays"]),
            "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
            "checkin_count": checkin_count,
            "listen_count": 0,
        }

    combined = pd.concat(frames, ignore_index=True).drop_duplicates()
    listen_count = len(combined)

    _raw_artists = get_top_entities(combined, "artist", limit=top_n)
    if not _raw_artists.empty and "Plays" in _raw_artists.columns:
        _raw_artists = _raw_artists.rename(columns={"Plays": "plays"})
    top_artists = _raw_artists
    # top_tracks: group by track + artist
    if "track" in combined.columns and "artist" in combined.columns:
        top_tracks = (
            combined.groupby(["track", "artist"], sort=False)
            .size()
            .reset_index(name="plays")
            .sort_values("plays", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
    else:
        top_tracks = pd.DataFrame(columns=["track", "artist", "plays"])

    return {
        "top_artists": top_artists,
        "top_tracks": top_tracks,
        "checkin_count": checkin_count,
        "listen_count": listen_count,
    }


def get_music_around_events(
    swarm_df: pd.DataFrame,
    lastfm_df: pd.DataFrame,
    window_hours: float = 2.0,
    top_n: int = 20,
) -> dict[str, pd.DataFrame]:
    """Find Last.fm plays near event check-ins grouped by event type.

    Matches ``event_category`` (case-insensitive substring) against three
    keyword buckets — Concert, Movie, Sports — then aggregates top artists
    within ``window_hours`` of each matching check-in.

    Args:
        swarm_df: Swarm DataFrame with ``timestamp`` and ``event_category``.
        lastfm_df: Listening history with ``timestamp`` and ``artist``.
        window_hours: Symmetric window in hours around each check-in.
        top_n: Maximum rows to return per bucket.

    Returns:
        Dict with keys ``"Concert"``, ``"Movie"``, ``"Sports"`` each mapping
        to a DataFrame with columns ``["artist", "plays"]`` sorted descending.
    """
    _empty_df = pd.DataFrame(columns=["artist", "plays"])
    result: dict[str, pd.DataFrame] = {
        "Concert": _empty_df.copy(),
        "Movie": _empty_df.copy(),
        "Sports": _empty_df.copy(),
    }

    if "event_category" not in swarm_df.columns or swarm_df.empty:
        return result

    window_minutes = int(window_hours * 60)

    buckets: dict[str, list[str]] = {
        "Concert": ["concert"],
        "Movie": ["movie"],
        "Sports": ["sport", "game"],
    }

    for bucket, keywords in buckets.items():
        _kws = keywords
        mask = swarm_df["event_category"].apply(
            lambda cat, _k=_kws: any(kw in str(cat).lower() for kw in _k)
        )
        matching = swarm_df[mask]
        if matching.empty:
            continue

        frames: list[pd.DataFrame] = []
        for _, row in matching.iterrows():
            nearby = _listens_around_checkin(lastfm_df, int(row["timestamp"]), window_minutes)
            if not nearby.empty:
                frames.append(nearby)

        if not frames:
            continue

        combined = pd.concat(frames, ignore_index=True)
        if "artist" not in combined.columns:
            continue

        artist_counts = (
            combined.groupby("artist", sort=False)
            .size()
            .reset_index(name="plays")
            .sort_values("plays", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
        result[bucket] = artist_counts

    return result


def get_city_artist_affinity_matrix(
    city_soundtracks: list[dict[str, Any]],
    top_artists_n: int = 20,
) -> pd.DataFrame:
    """Build an artist × city play count matrix.

    Index = artist names, columns = city names, values = play counts.
    Missing cells are filled with 0 (not NaN).

    Args:
        city_soundtracks: List of soundtrack dicts as returned by
            :func:`get_all_city_soundtracks`.
        top_artists_n: Maximum number of top artists to include per city
            (takes the top ``top_artists_n`` rows from each city's
            ``top_artists`` DataFrame).

    Returns:
        DataFrame with artists as the index, cities as columns, and play
        counts as values (0 where an artist has no plays in a city).
    """
    rows: list[dict[str, Any]] = []
    for soundtrack in city_soundtracks:
        city = soundtrack["city"]
        top_artists: pd.DataFrame = soundtrack["top_artists"]
        if top_artists.empty:
            continue
        for rec in top_artists.head(top_artists_n).itertuples(index=False):
            rows.append({"artist": rec.artist, "city": city, "plays": int(rec.plays)})

    if not rows:
        return pd.DataFrame()

    long_df = pd.DataFrame(rows)
    matrix = long_df.pivot_table(
        index="artist", columns="city", values="plays", aggfunc="sum", fill_value=0
    )
    # Remove column name label
    matrix.columns.name = None
    matrix.index.name = None
    return matrix


# ---------------------------------------------------------------------------
# Life Event Detection (Subtask 8)
# ---------------------------------------------------------------------------


def detect_listening_changepoints(
    df: pd.DataFrame,
    freq: str = "W",
    n_bkps: int = 10,
    model: str = "rbf",
) -> list[pd.Timestamp]:
    """Detect structural changepoints in listening intensity using ruptures.Pelt.

    Args:
        df: DataFrame with ``date_text`` column (datetime) and play rows.
        freq: Resampling frequency for intensity series (default ``"W"`` for weekly).
        n_bkps: Maximum number of breakpoints to detect.
        model: ruptures cost model (e.g. ``"rbf"``, ``"l2"``).

    Returns:
        List of ``pd.Timestamp`` changepoint dates, or ``[]`` if ruptures is
        unavailable, the DataFrame is empty, or segmentation fails.
    """
    ruptures = _get_ruptures()
    if ruptures is None:
        return []

    if df.empty or "date_text" not in df.columns:
        return []

    try:
        intensity = get_listening_intensity(df, freq=freq)
        if intensity.empty or len(intensity) < n_bkps + 2:
            return []

        signal = intensity["Plays"].values.reshape(-1, 1).astype(float)
        algo = ruptures.Pelt(model=model).fit(signal)
        breakpoints = algo.predict(n_bkps=n_bkps)

        # ruptures appends len(signal) as a sentinel — exclude it
        timestamps = []
        for idx in breakpoints[:-1]:
            if 0 <= idx < len(intensity):
                timestamps.append(pd.Timestamp(intensity["date"].iloc[idx]))
        return timestamps
    except Exception:  # noqa: BLE001
        return []


def detect_taste_shift_points(
    df: pd.DataFrame,
    window_months: int = 3,
    turnover_threshold: float = 0.4,
) -> list[dict[str, Any]]:
    """Detect months where listening taste shifts significantly.

    For each calendar month compares the top-10 artists in the current
    ``window_months``-wide window against the previous window using Jaccard
    similarity.  Flags periods where similarity is below
    ``1 - turnover_threshold``.

    Args:
        df: DataFrame with ``date_text`` (datetime) and ``artist`` columns.
        window_months: Number of months per rolling window.
        turnover_threshold: Fraction of artist turnover that qualifies as a
            shift (0.4 → flags when Jaccard < 0.6).

    Returns:
        List of dicts with keys ``date``, ``jaccard_similarity``,
        ``new_artists``, ``lost_artists``.  Returns ``[]`` when there is
        insufficient data for two windows.
    """
    if df.empty or "date_text" not in df.columns or "artist" not in df.columns:
        return []

    # Build monthly play counts per artist
    work = df.copy()
    work["month"] = work["date_text"].dt.to_period("M")
    all_months = sorted(work["month"].unique())

    if len(all_months) < window_months * 2:
        return []

    shifts: list[dict[str, Any]] = []
    jaccard_threshold = 1.0 - turnover_threshold

    for i in range(window_months, len(all_months)):
        cur_months = all_months[i - window_months : i]
        prev_months = all_months[max(0, i - window_months * 2) : i - window_months]

        if not prev_months:
            continue

        cur_plays = work[work["month"].isin(cur_months)]
        prev_plays = work[work["month"].isin(prev_months)]

        cur_top = set(cur_plays["artist"].value_counts().head(10).index)
        prev_top = set(prev_plays["artist"].value_counts().head(10).index)

        if not cur_top or not prev_top:
            continue

        intersection = cur_top & prev_top
        union = cur_top | prev_top
        jaccard = len(intersection) / len(union) if union else 1.0

        if jaccard < jaccard_threshold:
            shifts.append(
                {
                    "date": pd.Timestamp(all_months[i].to_timestamp()),
                    "jaccard_similarity": float(jaccard),
                    "new_artists": sorted(cur_top - prev_top),
                    "lost_artists": sorted(prev_top - cur_top),
                }
            )

    return shifts


def correlate_events_with_assumptions(
    changepoints: list[pd.Timestamp],
    taste_shifts: list[dict[str, Any]],
    assumptions: dict[str, Any],
    correlation_days: int = 30,
) -> list[dict[str, Any]]:
    """Merge changepoints and taste shifts into enriched event dicts.

    For each event, checks whether any trip start/end or residency transition
    falls within ``correlation_days`` and injects a human-readable ``context``
    string.

    Args:
        changepoints: List of ``pd.Timestamp`` from
            :func:`detect_listening_changepoints`.
        taste_shifts: List of dicts from :func:`detect_taste_shift_points`.
        assumptions: Assumptions dict with ``"trips"`` and ``"residency"`` keys.
        correlation_days: Window (in days) to consider an assumption
            "nearby" the event.

    Returns:
        List of event dicts sorted by date, each with keys ``date``,
        ``type``, and ``context``.
    """
    events: list[dict[str, Any]] = []

    for cp in changepoints:
        events.append({"date": cp, "type": "changepoint", "context": ""})

    for shift in taste_shifts:
        events.append(
            {
                "date": shift["date"],
                "type": "taste_shift",
                "context": "",
                "jaccard_similarity": shift.get("jaccard_similarity"),
                "new_artists": shift.get("new_artists", []),
                "lost_artists": shift.get("lost_artists", []),
            }
        )

    # Build reference dates from assumptions
    reference_points: list[tuple[pd.Timestamp, str]] = []

    for trip in assumptions.get("trips", []):
        city = trip.get("city", "")
        start_str = trip.get("start", "")
        end_str = trip.get("end", "")
        if start_str:
            try:
                reference_points.append((pd.Timestamp(start_str), f"Near start of trip to {city}"))
            except Exception:  # noqa: BLE001, S110
                pass
        if end_str:
            try:
                reference_points.append((pd.Timestamp(end_str), f"Near end of trip to {city}"))
            except Exception:  # noqa: BLE001, S110
                pass

    for res in assumptions.get("residency", []):
        city = res.get("city", "")
        end_str = res.get("end", "")
        if end_str:
            try:
                reference_points.append(
                    (pd.Timestamp(end_str), f"Near residency transition from {city}")
                )
            except Exception:  # noqa: BLE001, S110
                pass

    # Enrich each event with context
    window = pd.Timedelta(days=correlation_days)
    for event in events:
        event_date = event["date"]
        for ref_date, description in reference_points:
            if abs(event_date - ref_date) <= window:
                event["context"] = description
                break

    events.sort(key=lambda e: e["date"])
    return events
