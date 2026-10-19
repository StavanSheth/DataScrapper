"""
Test Platform Directory Scout Agent Live & Print Scraped Data.
Executes the Platform Agent worker pipeline with a real browser session,
scrapes directory cards, normalizes brand identities, persists to SQLite,
and prints the resulting dataset cleanly to the console.
"""
import asyncio
import os
import sys
import json

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
sys.path.insert(0, BASE_DIR)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.async_api import async_playwright

import importlib.util
agent_path = os.path.join(BASE_DIR, "agents/agents/directory-discovery/agent.py")
spec = importlib.util.spec_from_file_location("directory_discovery_agent", agent_path)
dir_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dir_agent)
platform_area_search_worker = dir_agent.platform_area_search_worker

from packages.database.src.adapters.sqlite.connection import get_connection, DEFAULT_DB_PATH
from packages.database.src.repositories.platform_repository import get_platform_listings, get_cached_census_total

async def run_live_test(platform="Fresha", category="Salon", location="London", max_results=5):
    print("=" * 80)
    print(f"🚀 TESTING PLATFORM DIRECTORY AGENT")
    print(f"Target Platform : {platform}")
    print(f"Category        : {category}")
    print(f"Location        : {location}")
    print(f"Max Results     : {max_results}")
    print(f"Database Path   : {DEFAULT_DB_PATH}")
    print("=" * 80)

    # Record logs emitted by the agent
    def console_emit(event_type: str, data):
        if event_type == "log":
            print(f"[AGENT LOG] {data}")
        elif event_type == "status":
            print(f"[AGENT STATUS] {data}")
        elif event_type == "platform_listing_saved":
            print(f"  ✨ [SAVED LISTING] #{data.get('id')} {data.get('title')} ({data.get('url')})")

    async with async_playwright() as p:
        print("\n🌐 Launching Chromium browser session...")
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        print("⚡ Executing Platform Area Worker Pipeline...")
        # Hook into page evaluate to print extracted card data directly
        total_saved = await platform_area_search_worker(
            context=context,
            platform_page=page,
            selected_platforms=[platform],
            category=category,
            location_name=location,
            max_results=max_results,
            emit_event_fn=console_emit,
            db_path=DEFAULT_DB_PATH
        )

        from connectors.directories.connector import extract_platform_listing_cards
        scraped_cards = await extract_platform_listing_cards(page, platform)
        print(f"\n📋 LIVE SCRAPED CARDS DIRECTLY FROM BROWSER VIEWPORT ({len(scraped_cards)} items):")
        print(f"{'#':<3} | {'Title':<30} | {'Rating':<6} | {'Reviews':<8} | {'Price':<6} | {'Direct Booking URL'}")
        print("-" * 115)
        for idx, c in enumerate(scraped_cards[:10], 1):
            t = c.get('title', '')[:30]
            r = str(c.get('rating', '0.0'))
            rev = str(c.get('reviews_count', '0'))
            p = str(c.get('price_info', 'N/A') or 'N/A')[:6]
            u = c.get('url', '')[:55]
            print(f"{idx:<3} | {t:<30} | {r:<6} | {rev:<8} | {p:<6} | {u}")
        print("-" * 115)

        await browser.close()
        print(f"\n✅ Scrape Worker Finished. Total listings saved in this run: {total_saved}")

    # Inspect SQLite database records
    print("\n" + "=" * 80)
    print("📊 INSPECTING SCRAPED DATA SAVED IN SQLITE (platform_listings)")
    print("=" * 80)

    rows = get_platform_listings(platform=platform, limit=10, db_path=DEFAULT_DB_PATH)
    if not rows:
        print(f"No records found for platform '{platform}'. Showing recent records across all platforms:")
        rows = get_platform_listings(limit=10, db_path=DEFAULT_DB_PATH)

    print(f"Found {len(rows)} records in database:\n")
    print(f"{'ID':<6} | {'Platform':<10} | {'Clean Brand':<24} | {'Rating':<6} | {'Reviews':<7} | {'Price':<6} | {'Title'}")
    print("-" * 95)
    for r in rows:
        r_id = str(r.get("id", ""))
        plat = str(r.get("platform", ""))[:10]
        brand = str(r.get("clean_brand", ""))[:24]
        rating = f"{r.get('rating', 0.0):.1f}"
        revs = str(r.get("reviews_count", 0))
        price = str(r.get("price_info", "") or "N/A")[:6]
        title = str(r.get("title", ""))[:30]
        print(f"{r_id:<6} | {plat:<10} | {brand:<24} | {rating:<6} | {revs:<7} | {price:<6} | {title}")

    print("-" * 95)
    print("\n📋 Detailed First Record Sample (JSON):")
    if rows:
        sample = dict(rows[0])
        print(json.dumps(sample, indent=2))
    print("=" * 80)

if __name__ == "__main__":
    plat = sys.argv[1] if len(sys.argv) > 1 else "Fresha"
    cat = sys.argv[2] if len(sys.argv) > 2 else "Salon"
    loc = sys.argv[3] if len(sys.argv) > 3 else "London"
    asyncio.run(run_live_test(plat, cat, loc, max_results=5))
