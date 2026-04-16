import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_BASE_URL = "http://127.0.0.1:8042"


def create_mcp_server(base_url: str = DEFAULT_BASE_URL) -> FastMCP:
    mcp = FastMCP(
        "FoodLog",
        instructions=(
            "Food logging assistant. Use search_food to find nutrition data, "
            "then log_food to record meals. Use get_daily_summary to show totals. "
            "Always search before logging to get accurate nutrition values."
        ),
    )

    @mcp.tool()
    async def search_food(query: str) -> list[dict]:
        """Search the nutrition database for a food item.

        Returns matches with calories and macros per serving.
        Use this to find the right database match before logging.

        Args:
            query: Food name to search for (e.g. "chicken breast", "oat milk latte")
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base_url}/foods/search", params={"q": query}
            )
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def log_food(entries: list[dict]) -> list[dict]:
        """Log one or more food items to the diary.

        Use after searching to include accurate nutrition data.
        Include the original user description in raw_input.

        Args:
            entries: Array of food entry objects. Each must include:
                meal_type (breakfast/lunch/dinner/snack), food_name, quantity,
                unit, calories, protein_g, carbs_g, fat_g, source, raw_input.
                Optional: weight_g, source_id, fiber_g, sugar_g, sodium_mg.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{base_url}/entries", json=entries)
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def get_entries(date: str | None = None, meal_type: str | None = None) -> list[dict]:
        """Get food diary entries. Defaults to today.

        Use to show the user what they've logged or to check before adding duplicates.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
            meal_type: Filter by meal type (breakfast/lunch/dinner/snack)
        """
        params = {}
        if date:
            params["date"] = date
        if meal_type:
            params["meal_type"] = meal_type
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/entries", params=params)
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def edit_entry(entry_id: int, updates: dict) -> dict:
        """Update a previously logged entry.

        Fix quantity, swap to a better match, change meal type.

        Args:
            entry_id: ID of the entry to update
            updates: Fields to update (e.g. {"quantity": 2.0, "calories": 495.0})
        """
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{base_url}/entries/{entry_id}", json=updates
            )
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def delete_entry(entry_id: int) -> str:
        """Remove a food entry from the diary.

        Args:
            entry_id: ID of the entry to delete
        """
        async with httpx.AsyncClient() as client:
            resp = await client.delete(f"{base_url}/entries/{entry_id}")
            resp.raise_for_status()
            return f"Entry {entry_id} deleted"

    @mcp.tool()
    async def get_daily_summary(date: str | None = None) -> dict:
        """Get total calories, protein, carbs, and fat for a day, broken down by meal.

        Defaults to today.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
        """
        params = {}
        if date:
            params["date"] = date
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/summary/daily", params=params)
            resp.raise_for_status()
            return resp.json()

    return mcp


if __name__ == "__main__":
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
