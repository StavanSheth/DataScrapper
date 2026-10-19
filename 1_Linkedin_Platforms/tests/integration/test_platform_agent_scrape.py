"""
Integration Test for Platform Directory Agent Scraping Pipeline.
Verifies end-to-end execution of Census Probing, Card Extraction,
Brand Normalization, and SQLite Persistence.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock

import importlib.util

agent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../agents/agents/directory-discovery/agent.py"))
spec = importlib.util.spec_from_file_location("directory_discovery_agent", agent_path)
dir_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dir_agent)
platform_area_search_worker = dir_agent.platform_area_search_worker

from packages.database.src.adapters.sqlite.connection import get_connection
from packages.database.src.repositories.platform_repository import (
    get_platform_listings,
    get_cached_census_total
)

@pytest.fixture
def temp_test_db(tmp_path):
    db_file = os.path.join(tmp_path, "test_leads.db")
    schema_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../database/migrations/sqlite/001_initial_schema.sql"))
    with open(schema_path, "r", encoding="utf-8") as f:
        ddl = f.read()
    with get_connection(db_file) as conn:
        conn.executescript(ddl)
        conn.commit()
    return db_file

def test_platform_agent_scrapes_and_saves_data(temp_test_db):
    async def _run():
        # Mock Playwright Page
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock()

        async def evaluate_side_effect(script, *args):
            if "results-counter" in script or "pagination-results-count" in script or "venues?" in script:
                return 120  # Mocked 120 businesses found
            elif "window.scrollBy" in script:
                return None
            elif "data-testid=\"card-container\"" in script or "cardElements" in script:
                return [
                    {
                        "title": "Enrich Salon & Spa - Powai",
                        "url": "https://www.fresha.com/a/enrich-salon-powai-12345",
                        "rating": 4.8,
                        "reviews_count": 215,
                        "price_info": "₹₹"
                    },
                    {
                        "title": "BBlunt Hair Studio Pvt Ltd",
                        "url": "https://www.fresha.com/a/bblunt-powai-67890",
                        "rating": 4.6,
                        "reviews_count": 98,
                        "price_info": "₹₹₹"
                    },
                    {
                        "title": "Truefitt & Hill Barber Co",
                        "url": "https://www.fresha.com/a/truefitt-powai-11223",
                        "rating": 4.9,
                        "reviews_count": 340,
                        "price_info": "₹₹₹₹"
                    }
                ]
            return None

        mock_page.evaluate.side_effect = evaluate_side_effect

        events_emitted = []
        def record_event(evt_type, data):
            events_emitted.append((evt_type, data))

        # Run the platform agent worker
        total_saved = await platform_area_search_worker(
            context=None,
            platform_page=mock_page,
            selected_platforms=["Fresha"],
            category="Salon",
            location_name="Powai Mumbai",
            max_results=5,
            emit_event_fn=record_event,
            db_path=temp_test_db
        )

        # 1. Verify saved count
        assert total_saved == 3, f"Expected 3 listings saved, got {total_saved}"

        # 2. Verify census cache was stored
        cached_census = get_cached_census_total("Fresha", "Salon", "Powai Mumbai", db_path=temp_test_db)
        assert cached_census == 120

        # 3. Verify SQLite platform_listings table content
        saved_rows = get_platform_listings(platform="Fresha", db_path=temp_test_db)
        assert len(saved_rows) == 3

        # Check first row data and brand normalization
        first = next(r for r in saved_rows if "Enrich" in r["title"])
        assert first["platform"] == "Fresha"
        assert first["clean_brand"] == "Enrich Salon & Spa"  # '- Powai' branch stripped by brand_cleaner
        assert first["rating"] == 4.8
        assert first["reviews_count"] == 215
        assert first["price_info"] == "₹₹"
        assert "fresha.com" in first["url"]

        # 4. Check events emitted
        saved_events = [e for e in events_emitted if e[0] == "platform_listing_saved"]
        assert len(saved_events) == 3

    asyncio.run(_run())
