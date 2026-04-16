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
