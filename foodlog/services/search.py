from foodlog.clients.fatsecret import FatSecretClient
from foodlog.clients.usda import USDAClient
from foodlog.models.schemas import FoodSearchResult


class SearchService:
    def __init__(
        self,
        fatsecret: FatSecretClient | None = None,
        usda: USDAClient | None = None,
    ):
        self.fatsecret = fatsecret
        self.usda = usda

    async def search(self, query: str) -> list[FoodSearchResult]:
        if self.fatsecret:
            results = await self.fatsecret.search(query)
            if results:
                return results

        if self.usda:
            results = await self.usda.search(query)
            if results:
                return results

        if not self.fatsecret and not self.usda:
            raise RuntimeError(
                "No food database APIs configured. "
                "Set FATSECRET_CONSUMER_KEY/SECRET or USDA_API_KEY in .env"
            )

        return []
