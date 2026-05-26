import glob
import hashlib
import json
import math
import os
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd


def get_cache_key(
    lastfm_file: str, swarm_dir: Optional[str] = None, assumptions_file: Optional[str] = None
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


def apply_swarm_offsets(
    lastfm_df: pd.DataFrame,
    swarm_df: pd.DataFrame,
    assumptions: dict[str, Any],
    max_age_days: int = 30,
) -> pd.DataFrame:
    """
    Adjust Last.fm track timestamps and locations based on Swarm checkins or runtime assumptions.
    Highly optimized vectorized implementation (Issue #39 optimization).
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
    precedence used in ``apply_swarm_offsets``).

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
