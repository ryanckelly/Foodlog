from fastapi import APIRouter, Query

from foodlog.api.dependencies import get_fatsecret_client, get_usda_client
from foodlog.models.schemas import FoodSearchResult
from foodlog.services.search import SearchService

router = APIRouter(prefix="/foods", tags=["foods"])


def get_search_service() -> SearchService:
    return SearchService(
        fatsecret=get_fatsecret_client(),
        usda=get_usda_client(),
    )


@router.get("/search", response_model=list[FoodSearchResult])
async def search_foods(
    q: str = Query(..., description="Food search query"),
):
    svc = get_search_service()
    return await svc.search(q)
