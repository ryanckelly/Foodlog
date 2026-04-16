import base64
import hashlib
import hmac
import re
import time
import urllib.parse
import uuid

import httpx

from foodlog.models.schemas import FoodSearchResult

FATSECRET_API_URL = "https://platform.fatsecret.com/rest/server.api"


def _oauth_sign(consumer_key: str, consumer_secret: str, params: dict) -> dict:
    """Add OAuth 1.0 two-legged signature to params."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth_params}

    sorted_encoded = "&".join(
        f"{urllib.parse.quote(k, safe='')}"
        f"={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = "&".join(
        urllib.parse.quote(s, safe="")
        for s in ["GET", FATSECRET_API_URL, sorted_encoded]
    )

    signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()

    all_params["oauth_signature"] = sig
    return all_params


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
        consumer_key: str,
        consumer_secret: str,
        http_client: httpx.AsyncClient,
    ):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.http = http_client

    async def search(
        self, query: str, max_results: int = 10
    ) -> list[FoodSearchResult]:
        params = _oauth_sign(
            self.consumer_key,
            self.consumer_secret,
            {
                "method": "foods.search",
                "search_expression": query,
                "format": "json",
                "max_results": str(max_results),
            },
        )
        resp = await self.http.get(FATSECRET_API_URL, params=params)
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
