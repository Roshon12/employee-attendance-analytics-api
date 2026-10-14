from datetime import datetime, timezone

from app.main import (
    compute_late_minutes,
    round_hours_half_up,
)


def test_work_hours_round_half_up():
    assert round_hours_half_up(14850) == 4.13


def test_late_within_grace_period():
    punch_in = datetime(
        2026, 10, 1, 4, 10, tzinfo=timezone.utc
    )
    assert compute_late_minutes(
        punch_in, "09:30", "2026-10-01"
    ) == 0


def test_late_after_grace_period():
    punch_in = datetime(
        2026, 10, 1, 4, 11, tzinfo=timezone.utc
    )
    assert compute_late_minutes(
        punch_in, "09:30", "2026-10-01"
    ) == 11

from app.main import compute_overtime, IST
from datetime import datetime


def test_overtime_below_30_minutes():
    punch_out = datetime(
        2026, 10, 1, 12, 55, tzinfo=IST
    )
    assert compute_overtime(
        punch_out, "18:30", "2026-10-01"
    ) == 0


def test_overtime_exactly_30_minutes():
    punch_out = datetime(
        2026, 10, 1, 19, 0, tzinfo=IST
    )
    assert compute_overtime(
        punch_out, "18:30", "2026-10-01"
    ) == 30

from fastapi.testclient import TestClient
from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
