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


async def test_list_daily_hrv(http):
    """daily-heart-rate-variability parser: full row, partial row, sparse row."""
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/daily-heart-rate-variability/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("daily_hrv.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_hrv(
            since=datetime.datetime(2026, 5, 1),
        )]
        assert len(rows) == 3
        by_date = {r.date: r for r in rows}

        # 1. Full row — every metric populated. nonRemHeartRateBeatsPerMinute
        #    arrives as a string<int64>; verify it's parsed to int.
        full = by_date[datetime.date(2026, 5, 18)]
        assert full.avg_hrv_ms == pytest.approx(64.7)
        assert full.deep_sleep_rmssd_ms == pytest.approx(56.25)
        assert full.non_rem_hr_bpm == 54
        assert isinstance(full.non_rem_hr_bpm, int)
        assert full.entropy == pytest.approx(3.142)
        assert full.source == "Pixel Watch 3"

        # 2. Partial — only avg + deep RMSSD reported.
        partial = by_date[datetime.date(2026, 5, 17)]
        assert partial.avg_hrv_ms == pytest.approx(48.0)
        assert partial.deep_sleep_rmssd_ms == pytest.approx(47.0)
        assert partial.non_rem_hr_bpm is None
        assert partial.entropy is None

        # 3. Sparse — only entropy. v4 schema says "at least one of {…} must be
        #    set" without specifying which, so we must accept any subset.
        sparse = by_date[datetime.date(2026, 5, 16)]
        assert sparse.entropy == pytest.approx(2.9)
        assert sparse.avg_hrv_ms is None
        assert sparse.deep_sleep_rmssd_ms is None
        assert sparse.non_rem_hr_bpm is None


async def test_list_daily_sleep_temperature(http):
    """daily-sleep-temperature-derivations parser: extracts the three temp
    fields, including the relativeNightlyStddev30dCelsius signal that flags
    'unusual' nights for the body-sim."""
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/daily-sleep-temperature-derivations/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("daily_sleep_temperature.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_sleep_temperature(
            since=datetime.datetime(2026, 5, 1),
        )]
        assert len(rows) == 2
        unusual = next(r for r in rows if r.date == datetime.date(2026, 5, 18))
        assert unusual.nightly_temp_c == pytest.approx(33.94)
        assert unusual.baseline_temp_c == pytest.approx(32.84)
        assert unusual.relative_stddev_30d_c == pytest.approx(0.857)
        assert unusual.source == "Pixel Watch 3"

        # A "normal" night — small deviation from baseline.
        normal = next(r for r in rows if r.date == datetime.date(2026, 5, 17))
        assert normal.relative_stddev_30d_c == pytest.approx(0.087)


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
        # The legacy fixture has type=STAGES but no metadata/summary — should
        # parse cleanly with None for the per-stage fields.
        assert rows[0].sleep_type == "STAGES"
        assert rows[0].deep_min is None
        assert rows[0].asleep_min is None


async def test_list_sleep_sessions_stages_summary(http):
    """STAGES session with metadata + summary fills every per-stage column;
    CLASSIC session populates only sleep_type; REJECTED_NAP session keeps the
    nap flag and stages_status but leaves stage minutes None."""
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/sleep/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("sleep_sessions_stages.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_sleep_sessions(
            since=datetime.datetime(2026, 4, 1),
        )]
        assert len(rows) == 3
        by_id = {r.external_id.split("/")[-1]: r for r in rows}

        # 1. Full STAGES session with summary
        stages = by_id["sleep-stages-2026-05-18"]
        assert stages.sleep_type == "STAGES"
        assert stages.nap is False
        assert stages.stages_status == "SUCCEEDED"
        assert stages.awake_min == 42
        assert stages.light_min == 245
        assert stages.deep_min == 101
        assert stages.rem_min == 59
        assert stages.restless_min is None  # not in stagesSummary for this night
        assert stages.asleep_min == 405
        assert stages.in_period_min == 447

        # 2. CLASSIC session — no metadata, no summary
        classic = by_id["sleep-classic-2026-04-26"]
        assert classic.sleep_type == "CLASSIC"
        assert classic.nap is None
        assert classic.stages_status is None
        assert classic.deep_min is None
        assert classic.asleep_min is None

        # 3. Rejected nap — has metadata but no summary
        rejected = by_id["sleep-nap-rejected-2026-05-10"]
        assert rejected.sleep_type == "STAGES"
        assert rejected.nap is True
        assert rejected.stages_status == "REJECTED_NAP"
        assert rejected.deep_min is None
        assert rejected.asleep_min is None


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


@pytest.mark.asyncio
async def test_rollup_posts_correct_body_and_returns_points():
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            route = mock.post(
                url__regex=r".*/heart-rate/dataPoints:rollUp.*"
            ).mock(
                return_value=httpx.Response(200, json=_load("hr_rollup.json"))
            )
            client = GoogleHealthClient(http, access_token="test")
            since = datetime.datetime(2026, 4, 12, 11, 50, 0)
            until = datetime.datetime(2026, 4, 12, 12, 50, 0)
            points = await client._rollup("heart-rate", since, until, window_size_s=900)

    assert len(points) == 4
    sent = json.loads(route.calls.last.request.content)
    assert sent["range"]["startTime"] == "2026-04-12T11:50:00Z"
    assert sent["range"]["endTime"]   == "2026-04-12T12:50:00Z"
    assert sent["windowSize"] == "900s"


@pytest.mark.asyncio
async def test_list_azm_intervals_parses_zone_breakdown():
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            mock.post(url__regex=r".*/active-zone-minutes/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_load("azm_rollup.json"))
            )
            client = GoogleHealthClient(http, access_token="test")
            since = datetime.datetime(2026, 4, 12, 11, 50, 0)
            until = datetime.datetime(2026, 4, 12, 13, 30, 0)
            rows = [r async for r in client.list_azm_intervals(since=since, until=until)]

    # 5 windows in fixture; 5th is empty {}
    assert len(rows) == 4
    first = rows[0]
    assert first.fat_burn_min == 3
    assert first.cardio_min is None
    assert first.peak_min is None
    fourth = rows[3]
    assert fourth.fat_burn_min == 12
    assert fourth.cardio_min == 2
    assert fourth.peak_min is None


@pytest.mark.asyncio
async def test_list_activity_intervals_zips_three_endpoints_and_skips_empty():
    activity_fix = _load("activity_rollup.json")
    # Synthesize per-endpoint responses by stripping the others.
    def _only(field: str) -> dict:
        return {
            "rollupDataPoints": [
                {"startTime": p["startTime"], "endTime": p["endTime"], field: p.get(field, {})}
                for p in activity_fix["rollupDataPoints"]
            ]
        }
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            r_steps = mock.post(url__regex=r".*/steps/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_only("steps"))
            )
            r_dist = mock.post(url__regex=r".*/distance/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_only("distance"))
            )
            r_floors = mock.post(url__regex=r".*/floors/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_only("floors"))
            )
            client = GoogleHealthClient(http, access_token="test")
            since = datetime.datetime(2026, 4, 12, 11, 50, 0)
            until = datetime.datetime(2026, 4, 12, 13, 30, 0)
            rows = [r async for r in client.list_activity_intervals(since=since, until=until)]

    assert r_steps.called and r_dist.called and r_floors.called
    # 5 windows; 5th (13:00) has all-empty across all three -> dropped
    assert len(rows) == 4
    by_time = {r.start_at: r for r in rows}
    first = by_time[datetime.datetime(2026, 4, 12, 11, 50, 0)]
    assert first.steps == 649
    assert abs(first.distance_m - 420.268) < 1e-6
    assert first.floors is None


@pytest.mark.asyncio
async def test_list_hr_intervals_chunks_into_14_day_slices():
    async with httpx.AsyncClient() as http:
        with respx.mock(base_url="https://health.googleapis.com") as mock:
            route = mock.post(url__regex=r".*/heart-rate/dataPoints:rollUp.*").mock(
                return_value=httpx.Response(200, json=_load("hr_rollup.json"))
            )
            client = GoogleHealthClient(http, access_token="test")
            # 30-day range -> expect three chunks: [0..14], [14..28], [28..30]
            since = datetime.datetime(2026, 3, 15, 0, 0, 0)
            until = datetime.datetime(2026, 4, 14, 0, 0, 0)
            rows = [r async for r in client.list_hr_intervals(since=since, until=until)]

    assert route.call_count == 3
    # each chunk returns the same 4-row fixture, so total rows = 12
    assert len(rows) == 12
    first = rows[0]
    assert first.bpm_avg == 102  # rounded from 102.3
    assert first.bpm_min == 88
    assert first.bpm_max == 121
    assert first.source == ""  # fixture has no dataSource
    assert first.start_at == datetime.datetime(2026, 4, 12, 11, 50, 0)


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
