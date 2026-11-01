"""Ordered event filters; config is the source's config_json, not the source row.

Return stable rejection codes for the runner's ingest_runs counters. Adding a
rule requires one function and one RULES entry; check stops at the first failure.
"""

from datetime import UTC, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

from engine.models import NormalizedEvent


def has_title(event: NormalizedEvent, config: dict[str, Any]) -> str | None:
    return "missing_title" if not event.title or not event.title.strip() else None


def valid_dates(event: NormalizedEvent, config: dict[str, Any]) -> str | None:
    start = event.start_at
    end = event.end_at or start  # Without an end, use the start as the expiry reference.
    if start is None or end < start:
        return "invalid_dates"
    if end < datetime.now(UTC) - timedelta(days=1):
        return "event_ended"
    return None


def in_lucknow(event: NormalizedEvent, config: dict[str, Any]) -> str | None:
    if event.mode == "online":
        return None
    if event.lat is None or event.lng is None:
        # NormalizedEvent carries location text in address; it has no city field.
        return None if "lucknow" in (event.address or "").casefold() else "outside_lucknow"
    home_lat, home_lng = map(radians, (26.8467, 80.9462))
    lat, lng = map(radians, (event.lat, event.lng))
    a = sin((lat - home_lat) / 2) ** 2 + cos(home_lat) * cos(lat) * sin((lng - home_lng) / 2) ** 2
    distance_km = 2 * 6371 * asin(min(1, sqrt(a)))
    # Allow floating-point roundoff at the inclusive 40 km edge.
    return "outside_lucknow" if distance_km > 40 + 1e-9 else None


def online_allowed(event: NormalizedEvent, config: dict[str, Any]) -> str | None:
    if event.mode != "online" or config.get("lucknow_community") is True:
        return None
    allowed = config.get("allowed_organizers", [])
    if event.organizer_name and isinstance(allowed, list) and event.organizer_name in allowed:
        return None
    return "online_not_allowed"


RULES = [has_title, valid_dates, in_lucknow, online_allowed]


def check(event: NormalizedEvent, config: dict[str, Any]) -> tuple[bool, str | None]:
    """Apply all rules in order, returning (accepted, first rejection reason)."""
    for rule in RULES:
        reason = rule(event, config)
        if reason is not None:
            return False, reason
    return True, None
