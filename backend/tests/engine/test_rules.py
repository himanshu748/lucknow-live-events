from datetime import UTC, datetime, timedelta
from math import degrees

import pytest

from engine import rules
from engine.models import NormalizedEvent

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=1)
EVENT = NormalizedEvent(
    external_id="evt-1",
    title="GDG Lucknow meetup",
    start_at=NOW + timedelta(days=1),
    mode="offline",
    address="Lucknow",
    organizer_name="GDG Lucknow",
    canonical_url="https://example.test/events/evt-1",
    source_platform="bevy",
)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            return NOW.astimezone(tz)

    monkeypatch.setattr(rules, "datetime", Clock)


@pytest.mark.parametrize(
    "changes,reason",
    [({}, None), ({"title": ""}, "missing_title"), ({"title": "  "}, "missing_title")],
)
def test_has_title(changes, reason):
    # model_copy deliberately bypasses Pydantic to exercise defensive rule checks.
    assert rules.has_title(EVENT.model_copy(update=changes), {}) == reason


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({}, None),
        ({"start_at": None}, "invalid_dates"),
        ({"end_at": NOW}, "invalid_dates"),
        ({"end_at": EVENT.start_at}, None),
        ({"start_at": CUTOFF}, None),
        ({"start_at": CUTOFF - timedelta(microseconds=1)}, "event_ended"),
        ({"start_at": CUTOFF - timedelta(days=1), "end_at": NOW}, None),
        ({"start_at": CUTOFF - timedelta(days=1), "end_at": CUTOFF}, None),
        (
            {"start_at": CUTOFF - timedelta(days=1), "end_at": CUTOFF - timedelta(microseconds=1)},
            "event_ended",
        ),
    ],
)
def test_valid_dates(changes, reason):
    assert rules.valid_dates(EVENT.model_copy(update=changes), {}) == reason


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"lat": 26.8467, "lng": 80.9462}, None),
        ({"lat": 26.8467, "lng": 81.2462}, None),
        ({"lat": 26.8467, "lng": 81.4462}, "outside_lucknow"),
        ({"lat": 28.6139, "lng": 77.209}, "outside_lucknow"),
        ({"lat": 0, "lng": 0}, "outside_lucknow"),
        ({"address": "Gomti Nagar, lUcKnOw"}, None),
        ({"address": "Kanpur"}, "outside_lucknow"),
        ({"address": None}, "outside_lucknow"),
        ({"lat": 26.8467}, None),
        ({"mode": "online", "address": None}, None),
    ],
)
def test_in_lucknow(changes, reason):
    assert rules.in_lucknow(EVENT.model_copy(update=changes), {}) == reason


@pytest.mark.parametrize("km,reason", [(39.999, None), (40, None), (40.001, "outside_lucknow")])
def test_distance_boundary(km, reason):
    # Due north on a sphere: distance = radius * change in latitude (radians).
    event = EVENT.model_copy(update={"lat": 26.8467 + degrees(km / 6371), "lng": 80.9462})
    assert rules.in_lucknow(event, {}) == reason


@pytest.mark.parametrize(
    "config,organizer,reason",
    [
        ({}, "GDG Lucknow", "online_not_allowed"),
        ({"lucknow_community": True}, None, None),
        ({"lucknow_community": "true"}, "GDG Lucknow", "online_not_allowed"),
        ({"lucknow_community": 1}, "GDG Lucknow", "online_not_allowed"),
        ({"allowed_organizers": ["GDG Lucknow"]}, "GDG Lucknow", None),
        ({"allowed_organizers": ["Other"]}, "GDG Lucknow", "online_not_allowed"),
        ({"allowed_organizers": [None]}, None, "online_not_allowed"),
        ({"allowed_organizers": "GDG Lucknow"}, "GDG Lucknow", "online_not_allowed"),
        ({"allowed_organizers": None}, "GDG Lucknow", "online_not_allowed"),
    ],
)
def test_online_allowed(config, organizer, reason):
    event = EVENT.model_copy(update={"mode": "online", "organizer_name": organizer})
    assert rules.online_allowed(event, config) == reason


@pytest.mark.parametrize(
    "changes,config,result",
    [
        ({}, {}, (True, None)),
        ({"title": "", "start_at": None, "address": None}, {}, (False, "missing_title")),
        ({"start_at": None, "address": None}, {}, (False, "invalid_dates")),
        ({"address": "Delhi"}, {}, (False, "outside_lucknow")),
        ({"mode": "online"}, {}, (False, "online_not_allowed")),
        ({"mode": "online", "address": None}, {"lucknow_community": True}, (True, None)),
    ],
)
def test_check(changes, config, result):
    assert rules.check(EVENT.model_copy(update=changes), config) == result


def test_add_rule_and_stop_after_first_failure(monkeypatch):
    def extra_rule(event, config):
        assert event.title, "Later rules must not run after a rejection"
        return "extra_rule"

    monkeypatch.setattr(rules, "RULES", [*rules.RULES, extra_rule])
    assert rules.check(EVENT, {}) == (False, "extra_rule")
    assert rules.check(EVENT.model_copy(update={"title": ""}), {}) == (False, "missing_title")
