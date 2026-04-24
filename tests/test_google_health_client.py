import datetime
import json
from pathlib import Path

import httpx
import pytest
import respx

from foodlog.clients.google_health import GoogleHealthClient

FIXTURES = Path(__file__).parent / "fixtures" / "google_health"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def http():
    return httpx.AsyncClient()


async def test_list_daily_activity_returns_normalized_rows(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.post(url__regex=r".*/steps/dataPoints:dailyRollUp.*").mock(
            return_value=httpx.Response(200, json=_load("daily_activity.json"))
        )
        mock.post(url__regex=r".*/total-calories/dataPoints:dailyRollUp.*").mock(
            return_value=httpx.Response(200, json=_load("total_calories_rollup.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_activity(
            since=datetime.datetime(2026, 4, 20),
            until=datetime.datetime(2026, 4, 23),
        )]
        assert len(rows) == 1
        assert rows[0].date == datetime.date(2026, 4, 22)
        assert rows[0].steps == 8432
        assert rows[0].active_calories_kcal == pytest.approx(512.5)
        assert rows[0].source == "Pixel Watch 3"
        assert rows[0].external_id == "daily-activity|2026-04-22"


async def test_list_daily_activity_handles_calories_only(http):
    """Days with calories rollup but no steps rollup should still be yielded."""
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.post(url__regex=r".*/steps/dataPoints:dailyRollUp.*").mock(
            return_value=httpx.Response(200, json={"rollupDataPoints": []})
        )
        mock.post(url__regex=r".*/total-calories/dataPoints:dailyRollUp.*").mock(
            return_value=httpx.Response(200, json=_load("total_calories_rollup.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_activity(
            since=datetime.datetime(2026, 4, 20),
            until=datetime.datetime(2026, 4, 23),
        )]
        assert len(rows) == 1
        assert rows[0].steps == 0
        assert rows[0].active_calories_kcal == pytest.approx(512.5)


async def test_list_body_composition_returns_normalized_rows(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/weight/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("body_composition.json"))
        )
        mock.get(url__regex=r".*/body-fat/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("body_fat.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_body_composition(
            since=datetime.datetime(2026, 4, 1),
        )]
        assert len(rows) == 2
        weight_row = next(r for r in rows if r.weight_kg is not None)
        assert weight_row.weight_kg == pytest.approx(81.4)
        assert weight_row.source == "Renpho Scale"

        bf_row = next(r for r in rows if r.body_fat_pct is not None)
        assert bf_row.body_fat_pct == pytest.approx(22.4)


async def test_list_resting_heart_rate(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/daily-resting-heart-rate/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("resting_heart_rate.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_resting_heart_rate(
            since=datetime.datetime(2026, 4, 1),
        )]
        assert len(rows) == 1
        assert rows[0].bpm == 54
        assert rows[0].measured_at == datetime.datetime(2026, 4, 22)
        assert rows[0].source == "Pixel Watch 3"


async def test_list_sleep_sessions(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/sleep/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("sleep_sessions.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_sleep_sessions(
            since=datetime.datetime(2026, 4, 1),
        )]
        assert len(rows) == 1
        assert rows[0].duration_min == 435  # 7h15m
        assert rows[0].source == "Pixel Watch 3"
        assert rows[0].external_id.endswith("sleep-2026-04-22")


async def test_list_workouts(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/exercise/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("workouts.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_workouts(
            since=datetime.datetime(2026, 4, 1),
        )]
        assert len(rows) == 1
        w = rows[0]
        # Prefer displayName over exerciseType for UI presentation.
        assert w.activity_type == "Morning run"
        assert w.duration_min == 45
        assert w.calories_kcal == pytest.approx(412.5)
        assert w.distance_m == pytest.approx(6850.0)
        assert w.avg_hr == 152
        # max_hr is derived from HR samples by the sync service — the client
        # parser always returns None for it.
        assert w.max_hr is None
        assert w.source == "Pixel Watch 3"


async def test_list_workout_hr_samples(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/heart-rate/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("workout_hr_samples.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        samples = [s async for s in client.list_workout_hr_samples(
            workout_id="w-1",
            start_at=datetime.datetime(2026, 4, 22, 7, 30),
            end_at=datetime.datetime(2026, 4, 22, 8, 15),
        )]
        assert len(samples) == 5
        assert [s.bpm for s in samples] == [140, 152, 163, 158, 147]
        assert all(s.workout_id == "w-1" for s in samples)


async def test_list_handles_pagination(http):
    page1 = {
        "dataPoints": [{
            "name": "users/me/dataTypes/sleep/dataPoints/p1",
            "dataSource": {"device": {"displayName": "Pixel Watch 3"}, "platform": "FITBIT"},
            "sleep": {
                "interval": {
                    "startTime": "2026-04-20T22:00:00Z",
                    "endTime": "2026-04-21T06:00:00Z",
                }
            }
        }],
        "nextPageToken": "tok",
    }
    page2 = {
        "dataPoints": [{
            "name": "users/me/dataTypes/sleep/dataPoints/p2",
            "dataSource": {"device": {"displayName": "Pixel Watch 3"}, "platform": "FITBIT"},
            "sleep": {
                "interval": {
                    "startTime": "2026-04-21T22:00:00Z",
                    "endTime": "2026-04-22T06:00:00Z",
                }
            }
        }],
        "nextPageToken": "",
    }
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/sleep/dataPoints.*").mock(
            side_effect=[
                httpx.Response(200, json=page1),
                httpx.Response(200, json=page2),
            ]
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_sleep_sessions(
            since=datetime.datetime(2026, 4, 15),
        )]
        assert [r.external_id for r in rows] == [
            "users/me/dataTypes/sleep/dataPoints/p1",
            "users/me/dataTypes/sleep/dataPoints/p2",
        ]


async def test_429_raises_rate_limited_on_list(http):
    from foodlog.clients.google_health import RateLimited
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/sleep/dataPoints.*").mock(
            return_value=httpx.Response(429)
        )
        client = GoogleHealthClient(http, access_token="test")
        with pytest.raises(RateLimited):
            async for _ in client.list_sleep_sessions(
                since=datetime.datetime(2026, 4, 20),
            ):
                pass


async def test_429_raises_rate_limited_on_rollup(http):
    from foodlog.clients.google_health import RateLimited
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.post(url__regex=r".*/steps/dataPoints:dailyRollUp.*").mock(
            return_value=httpx.Response(429)
        )
        client = GoogleHealthClient(http, access_token="test")
        with pytest.raises(RateLimited):
            async for _ in client.list_daily_activity(
                since=datetime.datetime(2026, 4, 20),
            ):
                pass


async def test_400_on_list_returns_empty_iterator(http):
    """A per-type 4xx from the list endpoint must not crash sync."""
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/exercise/dataPoints.*").mock(
            return_value=httpx.Response(400, json={"error": {"message": "nope"}})
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_workouts(
            since=datetime.datetime(2026, 4, 20),
        )]
        assert rows == []


async def test_malformed_point_is_skipped_not_raised(http):
    """If Google returns a dataPoint missing our expected envelope, log + skip."""
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/exercise/dataPoints.*").mock(
            return_value=httpx.Response(200, json={
                "dataPoints": [
                    {"name": "broken", "dataSource": {}},  # no exercise envelope
                    {
                        "name": "good",
                        "dataSource": {"device": {"displayName": "X"}},
                        "exercise": {
                            "interval": {
                                "startTime": "2026-04-22T07:30:00Z",
                                "endTime": "2026-04-22T08:00:00Z",
                            },
                            "exerciseType": "WALKING",
                        },
                    },
                ],
                "nextPageToken": "",
            })
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_workouts(
            since=datetime.datetime(2026, 4, 20),
        )]
        assert [r.external_id for r in rows] == ["good"]


async def test_synthesises_external_id_when_name_missing(http):
    """heart-rate samples don't have a top-level name; sleep does, but test
    that the code tolerates missing name on session types."""
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/sleep/dataPoints.*").mock(
            return_value=httpx.Response(200, json={
                "dataPoints": [{
                    "dataSource": {"device": {"displayName": "Pixel Watch 3"}},
                    "sleep": {
                        "interval": {
                            "startTime": "2026-04-22T02:09:00Z",
                            "endTime": "2026-04-22T10:57:30Z",
                        }
                    }
                }],
                "nextPageToken": "",
            })
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_sleep_sessions(
            since=datetime.datetime(2026, 4, 20),
        )]
        assert len(rows) == 1
        assert rows[0].external_id.startswith("sleep|")
        assert "Pixel Watch 3" in rows[0].external_id
