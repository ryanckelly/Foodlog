import re

import httpx

from foodlog.models.schemas import FoodSearchResult

FATSECRET_TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
FATSECRET_API_URL = "https://platform.fatsecret.com/rest/foods/search/v1"


def _parse_description(desc: str) -> dict:
    """Parse FatSecret food_description string into numeric values.

    Example: "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0.00g | Protein: 31.02g"
    """
    result = {}
    cal_match = re.search(r"Calories:\s*([\d.]+)", desc)
    fat_match = re.search(r"Fat:\s*([\d.]+)", desc)
    carb_match = re.search(r"Carbs:\s*([\d.]+)", desc)
    protein_match = re.search(r"Protein:\s*([\d.]+)", desc)
    serving_match = re.search(r"^(.*?)\s*-\s*Calories", desc)

    result["calories"] = float(cal_match.group(1)) if cal_match else 0.0
    result["fat_g"] = float(fat_match.group(1)) if fat_match else 0.0
    result["carbs_g"] = float(carb_match.group(1)) if carb_match else 0.0
    result["protein_g"] = float(protein_match.group(1)) if protein_match else 0.0
    result["serving_description"] = (
        serving_match.group(1).strip() if serving_match else "Per serving"
    )
    return result


class FatSecretClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        http_client: httpx.AsyncClient,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = http_client
        self._access_token: str | None = None

    async def _get_token(self) -> str:
        """Get an OAuth 2.0 access token using client credentials grant."""
        if self._access_token:
            return self._access_token

        resp = await self.http.post(
            FATSECRET_TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": "basic"},
            auth=(self.client_id, self.client_secret),
        )
        resp.raise_for_status()
        self._access_token = resp.json()["access_token"]
        return self._access_token

    async def search(
        self, query: str, max_results: int = 10
    ) -> list[FoodSearchResult]:
        token = await self._get_token()
        resp = await self.http.get(
            FATSECRET_API_URL,
            params={
                "search_expression": query,
                "format": "json",
                "max_results": max_results,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        # If token expired, refresh and retry once
        if resp.status_code == 401:
            self._access_token = None
            token = await self._get_token()
            resp = await self.http.get(
                FATSECRET_API_URL,
                params={
                    "search_expression": query,
                    "format": "json",
                    "max_results": max_results,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        resp.raise_for_status()
        data = resp.json()

        foods_data = data.get("foods", {})
        food_list = foods_data.get("food", [])
        if not isinstance(food_list, list):
            food_list = [food_list] if food_list else []

        results = []
        for food in food_list:
            desc = food.get("food_description", "")
            parsed = _parse_description(desc)
            results.append(
                FoodSearchResult(
                    food_id=food["food_id"],
                    food_name=food["food_name"],
                    source="fatsecret",
                    calories=parsed["calories"],
                    protein_g=parsed["protein_g"],
                    carbs_g=parsed["carbs_g"],
                    fat_g=parsed["fat_g"],
                    serving_description=parsed["serving_description"],
                )
            )
        return results
