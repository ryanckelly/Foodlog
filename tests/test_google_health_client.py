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
        mock.get(url__regex=r".*/DAILY_STEPS/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("daily_activity.json"))
        )
        mock.get(url__regex=r".*/DAILY_ACTIVE_CALORIES/dataPoints.*").mock(
            return_value=httpx.Response(200, json={"dataPoints": [], "nextPageToken": ""})
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_activity(
            since=datetime.datetime(2026, 4, 20),
        )]
        assert len(rows) == 1
        assert rows[0].external_id.endswith("da-2026-04-22")
        assert rows[0].steps == 8432
        assert rows[0].source == "com.google.android.wearable.app"


async def test_list_body_composition_returns_normalized_rows(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/BODY_WEIGHT/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("body_composition.json"))
        )
        mock.get(url__regex=r".*/BODY_FAT_PERCENT/dataPoints.*").mock(
            return_value=httpx.Response(200, json={"dataPoints": [], "nextPageToken": ""})
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_body_composition(
            since=datetime.datetime(2026, 4, 1),
        )]
        assert len(rows) == 1
        assert rows[0].weight_kg == pytest.approx(81.4)
        assert rows[0].source == "com.renpho.fit"


async def test_list_handles_pagination(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        page1 = {
            "dataPoints": [{
                "name": "users/me/dataPoints/p1",
                "dataType": "DAILY_STEPS",
                "startTime": "2026-04-22T00:00:00Z",
                "endTime": "2026-04-23T00:00:00Z",
                "value": {"intValue": 100},
                "originDataSource": "src",
            }],
            "nextPageToken": "tok",
        }
        page2 = {
            "dataPoints": [{
                "name": "users/me/dataPoints/p2",
                "dataType": "DAILY_STEPS",
                "startTime": "2026-04-23T00:00:00Z",
                "endTime": "2026-04-24T00:00:00Z",
                "value": {"intValue": 200},
                "originDataSource": "src",
            }],
            "nextPageToken": "",
        }
        mock.get(url__regex=r".*/DAILY_STEPS/dataPoints.*").mock(
            side_effect=[
                httpx.Response(200, json=page1),
                httpx.Response(200, json=page2),
            ]
        )
        mock.get(url__regex=r".*/DAILY_ACTIVE_CALORIES/dataPoints.*").mock(
            return_value=httpx.Response(200, json={"dataPoints": [], "nextPageToken": ""})
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_activity(
            since=datetime.datetime(2026, 4, 20),
        )]
        assert [r.external_id for r in rows] == ["users/me/dataPoints/p1",
                                                  "users/me/dataPoints/p2"]


async def test_429_raises_rate_limited(http):
    from foodlog.clients.google_health import RateLimited
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/DAILY_STEPS/dataPoints.*").mock(
            return_value=httpx.Response(429)
        )
        client = GoogleHealthClient(http, access_token="test")
        with pytest.raises(RateLimited):
            async for _ in client.list_daily_activity(
                since=datetime.datetime(2026, 4, 20),
            ):
                pass
