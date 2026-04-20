# FoodLog Dashboard Design

## Overview
A local-only dashboard to view daily food logs, caloric intake, macronutrients, and trends. The dashboard is designed as a single-page application integrated directly into the existing FastAPI backend, prioritizing simplicity, zero external build dependencies, and secure local access.

## Architecture

**Frontend Approach: Server-Side Rendered (Jinja2 + HTMX)**
Since this dashboard is intended strictly for local network access and security is a priority, adding a heavy Node.js build process or a separate SPA frontend introduces unnecessary complexity and potential supply-chain surface area. 

Instead, the dashboard will be served directly by the existing Python FastAPI backend:
* **HTML Templating:** Jinja2 templates rendered on the server.
* **Interactivity:** HTMX for dynamic content updates without full page reloads.
* **Styling:** Minimal custom CSS or a classless CSS framework (e.g., Pico.css) to keep the footprint tiny while looking modern.
* **Charts:** A lightweight, dependency-free JavaScript charting library (e.g., Chart.js or uPlot) included via CDN or local static file.

By rendering on the server, the backend retains full control over data access and session state, ensuring secure access over the local network.

## User Interface & Layout

The dashboard will follow a **Timeline-led (Chronological)** layout. 

### Core Components

1. **Global Navigation / Time Selector (Top/Sidebar)**
   * A primary control to select the date range: "Today", "Yesterday", "This Week", "This Month", "Custom Range".
   * Changing this range uses HTMX to swap out the content below without a page reload.

2. **Summary Header / Sidebar**
   * Displays aggregate data for the selected time range.
   * Total Calories, Protein, Carbs, and Fat.
   * If a range > 1 day is selected, it shows daily averages alongside the totals.

3. **The Feed (Main Content Area)**
   * A chronological list of food entries for the selected time period.
   * Entries use the **Detailed Macros** design:
     * Food Name and Quantity
     * Total Calories
     * Time Logged
     * Specific Macro Breakdown (P: Xg, C: Yg, F: Zg)

4. **Trends Section (Below Feed or Separate Tab)**
   * Visual representations of the data over the selected range.
   * A line or bar chart showing caloric intake vs. a defined goal over the selected days.
   * A breakdown (pie/doughnut chart) of average macronutrient distribution.

## API Integration

The dashboard will interact with the existing FoodLog backend endpoints. It appears from the models that the necessary data structures (`DailySummary`, `RangeSummary`, `FoodEntryResponse`) are already supported by the API.

The Jinja2 routes will likely need to:
1. Fetch the user's entries or summaries for the selected date range using the existing internal services or API logic.
2. Pass this data into the templates.
3. Serve the rendered HTML.

## Security Considerations

* **Local Access Only:** The dashboard will be served on the local network (e.g., `192.168.1.40:3474` based on the current port setup). It should not be exposed via the Cloudflare Tunnel unless explicitly configured to do so with proper authentication.
* **Authentication:** If the FastAPI backend currently requires authentication (OAuth), the dashboard routes must be protected by the same session or token-based authentication mechanism. If accessed purely locally on a trusted network, a simplified or bypassed auth mechanism might be desired, but standardizing on the existing auth is preferred.

## Next Steps for Implementation
1. Set up FastAPI to serve static files (`/static`) and render Jinja2 templates (`/templates`).
2. Create the base HTML layout including HTMX and charting library scripts.
3. Build the backend routes to render the dashboard views and HTMX partials.
4. Implement the Timeline feed and Summary components.
5. Add the charting components for trends.