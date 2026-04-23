# FoodLog Dashboard

FoodLog includes a local web dashboard to view daily food logs, caloric intake, macronutrients, and trends.

## Access

The dashboard is accessible only from the local network (e.g., `http://192.168.1.40:3474/dashboard`). 

It is **intentionally restricted from public internet access**. The FastAPI application sits behind a Cloudflare Tunnel for its MCP and OAuth endpoints, but the `OAuthResourceMiddleware` (in `foodlog/api/auth.py`) actively blocks any requests to `/dashboard` that contain Cloudflare-specific headers (`cf-connecting-ip` or `cf-ray`). This ensures that even if someone guesses the URL, the dashboard remains inaccessible from the public internet.

To allow local network access, the Docker Compose configuration binds port `3474` to all interfaces (`"3474:3474"` instead of `"127.0.0.1:3474:3474"`).

## Architecture

The dashboard is built directly into the existing FastAPI backend using Server-Side Rendering (SSR) to prioritize simplicity and zero external build dependencies:

* **HTML Templating:** Jinja2 templates (`foodlog/templates/`) rendered on the server.
* **Interactivity:** HTMX for dynamic content updates (like changing date ranges) without full page reloads.
* **Styling:** Inline CSS in `base.html` driven by CSS custom properties, with Inter loaded from Google Fonts. The visual language is a Notion-inspired design system — full spec in `DESIGN.md` at the repo root. When changing palette, typography, or component patterns, update `DESIGN.md` alongside the templates so the spec stays authoritative.

## How it Accesses Data

The dashboard does not use a separate client-side API layer. Instead, the Jinja2 routes in `foodlog/api/routers/dashboard.py` directly instantiate the existing internal domain services (`EntryService` and `SummaryService`) from `foodlog/services/`, passing in the SQLAlchemy database session provided by FastAPI's dependency injection (`Depends(get_db)`).

1. **Routing:** A request hits `/dashboard/feed?date_range=today`.
2. **Service Call:** The router converts the `date_range` into `start_date` and `end_date` objects. It then calls `entry_svc.get_by_range(start_date, end_date)` and `summary_svc.range(start_date, end_date)`.
3. **Data Grouping:** The router groups the returned `FoodEntry` objects by meal type and time (consecutive items of the same meal logged within 5 minutes of each other).
4. **Template Rendering:** The router returns a `TemplateResponse` mapping to `dashboard/feed_partial.html`, passing the `grouped_entries` and `summary` data.
5. **Jinja2:** The template iterates over the grouped entries and renders the HTML, applying specific CSS classes to color-code meals (e.g., `.meal-breakfast`, `.meal-lunch`).

This architecture ensures the dashboard shares the exact same business logic and data persistence layer as the REST API and the MCP endpoint.
