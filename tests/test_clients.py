import httpx
import pytest
import respx

from foodlog.clients.usda import USDAClient
from foodlog.models.schemas import FoodSearchResult

USDA_BASE = "https://api.nal.usda.gov/fdc/v1"


@respx.mock
@pytest.mark.asyncio
async def test_usda_search():
    respx.get(f"{USDA_BASE}/foods/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "foods": [
                    {
                        "fdcId": 171688,
                        "description": "Apple, raw",
                        "foodNutrients": [
                            {"nutrientName": "Energy", "value": 52.0, "unitName": "KCAL"},
                            {"nutrientName": "Protein", "value": 0.26, "unitName": "G"},
                            {
                                "nutrientName": "Carbohydrate, by difference",
                                "value": 13.81,
                                "unitName": "G",
                            },
                            {
                                "nutrientName": "Total lipid (fat)",
                                "value": 0.17,
                                "unitName": "G",
                            },
                        ],
                    }
                ]
            },
        )
    )

    async with httpx.AsyncClient() as http:
        client = USDAClient(api_key="test-key", http_client=http)
        results = await client.search("apple")

    assert len(results) == 1
    assert results[0].food_name == "Apple, raw"
    assert results[0].source == "usda"
    assert results[0].food_id == "171688"
    assert results[0].calories == 52.0
    assert results[0].protein_g == 0.26


@respx.mock
@pytest.mark.asyncio
async def test_usda_search_empty():
    respx.get(f"{USDA_BASE}/foods/search").mock(
        return_value=httpx.Response(200, json={"foods": []})
    )

    async with httpx.AsyncClient() as http:
        client = USDAClient(api_key="test-key", http_client=http)
        results = await client.search("xyznonexistent")

    assert results == []


# --- FatSecret Client Tests ---

from foodlog.clients.fatsecret import FatSecretClient


@respx.mock
@pytest.mark.asyncio
async def test_fatsecret_search():
    respx.post("https://oauth.fatsecret.com/connect/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "fake-token", "expires_in": 86400}
        )
    )
    respx.get("https://platform.fatsecret.com/rest/foods/search/v1").mock(
        return_value=httpx.Response(
            200,
            json={
                "foods": {
                    "food": [
                        {
                            "food_id": "33691",
                            "food_name": "Chicken Breast",
                            "food_type": "Generic",
                            "food_description": "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0.00g | Protein: 31.02g",
                        }
                    ]
                }
            },
        )
    )

    async with httpx.AsyncClient() as http:
        client = FatSecretClient(
            client_id="test-key",
            client_secret="test-secret",
            http_client=http,
        )
        results = await client.search("chicken breast")

    assert len(results) == 1
    assert results[0].food_name == "Chicken Breast"
    assert results[0].source == "fatsecret"
    assert results[0].food_id == "33691"
    assert results[0].calories == 165.0
    assert results[0].protein_g == 31.02


@respx.mock
@pytest.mark.asyncio
async def test_fatsecret_search_empty():
    respx.post("https://oauth.fatsecret.com/connect/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "fake-token", "expires_in": 86400}
        )
    )
    respx.get("https://platform.fatsecret.com/rest/foods/search/v1").mock(
        return_value=httpx.Response(200, json={"foods": {"total_results": "0"}})
    )

    async with httpx.AsyncClient() as http:
        client = FatSecretClient(
            client_id="test-key",
            client_secret="test-secret",
            http_client=http,
        )
        results = await client.search("xyznonexistent")

    assert results == []
