import datetime

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from foodlog.api.dependencies import (
    get_fatsecret_client,
    get_session_factory_cached,
    get_usda_client,
)
from foodlog.models.schemas import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodEntryUpdate,
)
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService
from foodlog.services.search import SearchService


def _default_transport_security() -> TransportSecuritySettings:
    """Allow localhost and Tailscale MagicDNS hostnames."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "foodlog",
            "foodlog:*",
            "foodlog.tailf67313.ts.net",
            "foodlog.tailf67313.ts.net:*",
            "testserver",  # for pytest TestClient
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "https://foodlog.tailf67313.ts.net:*",
        ],
    )


def create_mcp_server() -> FastMCP:
    """Create the MCP server with tools that call services directly.

    Uses streamable_http_path='/' so when mounted at /mcp on FastAPI,
    the endpoint URL is /mcp (not /mcp/mcp).
    """
    mcp = FastMCP(
        "FoodLog",
        instructions=(
            "Food logging assistant. Use search_food to find nutrition data, "
            "then log_food to record meals. Use get_daily_summary to show totals. "
            "Always search before logging to get accurate nutrition values."
        ),
        streamable_http_path="/",
        transport_security=_default_transport_security(),
    )

    @mcp.tool()
    async def search_food(query: str) -> list[dict]:
        """Search the nutrition database for a food item.

        Returns matches with calories and macros per serving.
        Use this to find the right database match before logging.

        Args:
            query: Food name to search for (e.g. "chicken breast", "oat milk latte")
        """
        svc = SearchService(
            fatsecret=get_fatsecret_client(),
            usda=get_usda_client(),
        )
        results = await svc.search(query)
        return [r.model_dump() for r in results]

    @mcp.tool()
    def log_food(entries: list[dict]) -> list[dict]:
        """Log one or more food items to the diary.

        Use after searching to include accurate nutrition data.
        Include the original user description in raw_input.

        Args:
            entries: Array of food entry objects. Each must include:
                meal_type (breakfast/lunch/dinner/snack), food_name, quantity,
                unit, calories, protein_g, carbs_g, fat_g, source, raw_input.
                Optional: weight_g, source_id, fiber_g, sugar_g, sodium_mg.
        """
        session_factory = get_session_factory_cached()
        models = [FoodEntryCreate.model_validate(e) for e in entries]
        with session_factory() as session:
            svc = EntryService(session)
            results = svc.create_many(models)
            return [
                FoodEntryResponse.model_validate(r).model_dump(mode="json")
                for r in results
            ]

    @mcp.tool()
    def get_entries(
        date: str | None = None, meal_type: str | None = None
    ) -> list[dict]:
        """Get food diary entries. Defaults to today.

        Use to show the user what they've logged or to check before adding duplicates.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
            meal_type: Filter by meal type (breakfast/lunch/dinner/snack)
        """
        target_date = (
            datetime.date.fromisoformat(date) if date else datetime.date.today()
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            results = svc.get_by_date(target_date, meal_type=meal_type)
            return [
                FoodEntryResponse.model_validate(r).model_dump(mode="json")
                for r in results
            ]

    @mcp.tool()
    def edit_entry(entry_id: int, updates: dict) -> dict:
        """Update a previously logged entry.

        Fix quantity, swap to a better match, change meal type.

        Args:
            entry_id: ID of the entry to update
            updates: Fields to update (e.g. {"quantity": 2.0, "calories": 495.0})
        """
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            update_model = FoodEntryUpdate.model_validate(updates)
            result = svc.update(entry_id, update_model)
            if result is None:
                raise ValueError(f"Entry {entry_id} not found")
            return FoodEntryResponse.model_validate(result).model_dump(mode="json")

    @mcp.tool()
    def delete_entry(entry_id: int) -> str:
        """Remove a food entry from the diary.

        Args:
            entry_id: ID of the entry to delete
        """
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            if not svc.delete(entry_id):
                raise ValueError(f"Entry {entry_id} not found")
            return f"Entry {entry_id} deleted"

    @mcp.tool()
    def get_daily_summary(date: str | None = None) -> dict:
        """Get total calories, protein, carbs, and fat for a day, broken down by meal.

        Defaults to today.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
        """
        target_date = (
            datetime.date.fromisoformat(date) if date else datetime.date.today()
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = SummaryService(session)
            result = svc.daily(target_date)
            return result.model_dump(mode="json")

    return mcp


if __name__ == "__main__":
    # Kept for legacy compatibility — running as stdio no longer used in production
    # (MCP is mounted on FastAPI). This path remains for ad-hoc debugging.
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
