import httpx

from foodlog.models.schemas import FoodSearchResult

USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

NUTRIENT_MAP = {
    "Energy": "calories",
    "Protein": "protein_g",
    "Carbohydrate, by difference": "carbs_g",
    "Total lipid (fat)": "fat_g",
    "Fiber, total dietary": "fiber_g",
    "Sugars, Total": "sugar_g",
    "Sodium, Na": "sodium_mg",
}


class USDAClient:
    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        self.api_key = api_key
        self.http = http_client

    async def search(self, query: str, page_size: int = 10) -> list[FoodSearchResult]:
        resp = await self.http.get(
            f"{USDA_BASE_URL}/foods/search",
            params={
                "query": query,
                "api_key": self.api_key,
                "pageSize": page_size,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for food in data.get("foods", []):
            nutrients = self._extract_nutrients(food.get("foodNutrients", []))
            if nutrients.get("calories") is None:
                continue
            results.append(
                FoodSearchResult(
                    food_id=str(food["fdcId"]),
                    food_name=food["description"],
                    source="usda",
                    calories=nutrients.get("calories", 0),
                    protein_g=nutrients.get("protein_g", 0),
                    carbs_g=nutrients.get("carbs_g", 0),
                    fat_g=nutrients.get("fat_g", 0),
                    fiber_g=nutrients.get("fiber_g"),
                    sugar_g=nutrients.get("sugar_g"),
                    sodium_mg=nutrients.get("sodium_mg"),
                    serving_description="Per 100g",
                )
            )
        return results

    def _extract_nutrients(self, nutrients: list[dict]) -> dict:
        result = {}
        for n in nutrients:
            key = NUTRIENT_MAP.get(n.get("nutrientName"))
            if key:
                result[key] = n.get("value", 0)
        return result
