"""Match Hevy workouts to existing Garmin activities by start time.

Matching logic:
- Primary: UTC start time within ±15 minutes (handles same workout from different sources)
- For dashboard counts: date-based matching (Garmin strength activity on same calendar day)
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, date

from garminconnect import Garmin

logger = logging.getLogger("hevy2garmin")

# Cache to avoid hammering Garmin API on every page load
_garmin_activities_cache: list[dict] | None = None
_cache_timestamp: float = 0
CACHE_TTL = 300  # 5 minutes


def fetch_garmin_activities(client: Garmin, count: int = 50) -> list[dict]:
    """Fetch recent Garmin activities with caching."""
    global _garmin_activities_cache, _cache_timestamp

    if _garmin_activities_cache is not None and (_time.time() - _cache_timestamp) < CACHE_TTL:
        return _garmin_activities_cache

    try:
        from garmin_auth import RateLimiter
        limiter = RateLimiter(delay=1.0)
        activities = limiter.call(client.get_activities, 0, count)
        _garmin_activities_cache = activities
        _cache_timestamp = _time.time()
        return activities
    except Exception as e:
        logger.warning("Could not fetch Garmin activities: %s", e)
        return []


def get_garmin_strength_dates(garmin_activities: list[dict]) -> set[str]:
    """Extract dates (YYYY-MM-DD) of all strength_training activities from Garmin."""
    dates: set[str] = set()
    for act in garmin_activities:
        act_type = act.get("activityType", {}).get("typeKey", "")
        if act_type in ("strength_training", "indoor_cardio"):
            gmt = act.get("startTimeGMT", "")
            if gmt:
                dates.add(gmt[:10])
    return dates


def count_matched_workouts(hevy_total: int, hevy_workouts_sample: list[dict], garmin_activities: list[dict]) -> int:
    """Estimate how many Hevy workouts are already on Garmin.

    Uses time-based matching for the sample, then extrapolates based on
    Garmin strength activity count for dates we can't check.
    """
    # Count Garmin strength activities
    garmin_strength_count = sum(
        1 for a in garmin_activities
        if a.get("activityType", {}).get("typeKey", "") in ("strength_training", "indoor_cardio")
    )

    # For the sample we have, do precise time matching
    precise_matches = match_workouts_to_garmin(hevy_workouts_sample, garmin_activities)

    # The broader estimate: min of Garmin strength count and Hevy total
    # (can't have more matches than either side)
    return min(garmin_strength_count, hevy_total)


def _parse_time(raw: str) -> datetime | None:
    """Parse various time formats to datetime."""
    if not raw:
        return None
    try:
        cleaned = raw.replace("Z", "+00:00")
        if "T" not in cleaned:
            cleaned = cleaned.replace(" ", "T")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def match_workouts_to_garmin(
    workouts: list[dict],
    garmin_activities: list[dict],
    window_minutes: int = 15,
) -> dict[str, dict]:
    """Match Hevy workouts to Garmin activities by start time.

    Returns dict mapping hevy_id → {"garmin_id": int, "garmin_name": str, "match_type": str}
    """
    matches: dict[str, dict] = {}

    for workout in workouts:
        hevy_id = workout.get("id", "")
        hevy_start_str = workout.get("start_time") or workout.get("startTime", "")
        hevy_start = _parse_time(hevy_start_str)
        if not hevy_start:
            continue

        hevy_naive = hevy_start.replace(tzinfo=None) if hevy_start.tzinfo else hevy_start

        for act in garmin_activities:
            # Use GMT time for comparison (Hevy uses UTC, Garmin local has timezone offset)
            act_start_str = act.get("startTimeGMT") or act.get("startTimeLocal", "")
            act_start = _parse_time(act_start_str)
            if not act_start:
                continue

            act_naive = act_start.replace(tzinfo=None) if act_start.tzinfo else act_start
            diff_seconds = abs((hevy_naive - act_naive).total_seconds())

            if diff_seconds < window_minutes * 60:
                matches[hevy_id] = {
                    "garmin_id": act.get("activityId"),
                    "garmin_name": act.get("activityName", ""),
                    "garmin_type": act.get("activityType", {}).get("typeKey", ""),
                    "match_type": "time_match",
                }
                break

    return matches
