"""
Cross-Platform Directory Discovery Agent (Agent 4).
Performs area/proximity census discovery, listing card extraction, and detail enrichment
across Fresha, Airbnb, Yelp, TripAdvisor, Treatwell, and Justdial.
"""
import asyncio
import logging
import math
from typing import Dict, Any, List, Optional

from connectors.directories.connector import (
    extract_platform_total_count,
    extract_platform_listing_cards
)
from packages.database.src.repositories.platform_repository import (
    save_platform_listing,
    get_cached_census_total,
    set_cached_census_total,
    is_platform_listing_already_scraped
)
from backend.src.datascrapper.modules.source_registry.platform_profiles import (
    PLATFORM_PROFILES,
    build_platform_area_url
)
from backend.src.datascrapper.modules.normalization.brand_cleaner import clean_brand_tokens

logger = logging.getLogger("directory_discovery_agent")

async def platform_area_search_worker(
    context,
    platform_page,
    selected_platforms: List[str],
    category: str,
    location_name: str,
    max_results: int = 15,
    custom_url_pattern: str = "",
    emit_event_fn=None,
    db_path: Optional[str] = None
) -> int:
    """
    Dedicated Proximity & Area Worker for Tab 4 (Multi-Source Platform Directory Scout).
    Phase 1: Discovers total businesses across all enabled platforms (Census).
    Phase 2: Navigates, scrolls, and extracts directory listings into the database.
    """
    def emit(event_type: str, data: Any):
        if emit_event_fn:
            emit_event_fn(event_type, data)
        else:
            logger.info(f"[{event_type}] {data}")

    if not selected_platforms:
        selected_platforms = ["Fresha"]

    active_clean_platforms = [p.strip() for p in selected_platforms if p.strip()]
    emit("log", f"🟣 [Agent 4: Platform] Target platforms active ({len(active_clean_platforms)}): {', '.join(active_clean_platforms)}")

    # =========================================================================
    # PHASE 1: PROXIMITY CENSUS
    # =========================================================================
    platform_totals = {}
    for p_name in active_clean_platforms:
        target_url = build_platform_area_url(p_name, category, location_name, custom_url_pattern)
        emit("status", f"Census: Probing {p_name} volume for '{category}' in '{location_name}'...")
        emit("log", f"🎯 [Agent 4: Platform] Probing {p_name} available volume in '{location_name}'...")
        emit("platform_navigated", {"url": target_url, "title": f"{p_name} Proximity Census", "platform": p_name})

        cached_tot = get_cached_census_total(p_name, category, location_name, db_path=db_path)
        if cached_tot and cached_tot > 0:
            final_plat_total = cached_tot
            emit("log", f"⚡ [Agent 4: Platform] Reusing verified census count for {p_name} in '{location_name}': ~{final_plat_total} businesses.")
        else:
            detected_total = 0
            try:
                await platform_page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                await platform_page.wait_for_timeout(1000)
                detected_total = await extract_platform_total_count(platform_page, p_name)
            except Exception as ce:
                emit("log", f"⚠️ [Proximity Census] {p_name} probe delayed: {ce}")

            final_plat_total = max(detected_total, max_results if max_results > 0 else 15)
            set_cached_census_total(p_name, category, location_name, final_plat_total, db_path=db_path)

        platform_totals[p_name] = final_plat_total

    emit("log", f"📊 [Proximity Census] Verified totals across directory platforms: {platform_totals}")

    # =========================================================================
    # PHASE 2: AREA DIRECTORY SEARCH & SCRAPE
    # =========================================================================
    total_saved_all_platforms = 0
    for p_name in active_clean_platforms:
        target_url = build_platform_area_url(p_name, category, location_name, custom_url_pattern)
        emit("status", f"Searching {p_name} for '{category}' in '{location_name}'...")
        emit("log", f"🔍 [Agent 4: Platform] Searching {p_name}: '{category}' in '{location_name}'")
        emit("platform_navigated", {"url": target_url, "title": f"{p_name} Directory Search", "platform": p_name})

        try:
            saved_on_platform = 0
            page_num = 1
            max_pages = max(4, math.ceil(max_results / 15))
            consecutive_zero_new = 0

            while page_num <= max_pages and saved_on_platform < max_results:
                current_url = target_url
                if page_num > 1:
                    sep = "&" if "?" in target_url else "?"
                    if "airbnb" in p_name.lower():
                        offset = (page_num - 1) * 18
                        current_url = f"{target_url}{sep}pagination_search=true&items_offset={offset}"
                    else:
                        current_url = f"{target_url}{sep}page={page_num}"

                emit("log", f"🌐 [Agent 4: Platform] Accessing {p_name} Page {page_num}: {current_url}")
                await platform_page.goto(current_url, wait_until="domcontentloaded", timeout=15000)
                await platform_page.wait_for_timeout(1200)

                # Smooth scroll to trigger listing loading
                for _ in range(4):
                    await platform_page.evaluate("window.scrollBy(0, 1000)")
                    await platform_page.wait_for_timeout(600)

                cards = await extract_platform_listing_cards(platform_page, p_name)
                emit("log", f"📋 [Agent 4: Platform] Discovered {len(cards)} listings on {p_name} (Page {page_num}).")

                new_on_page = 0
                for card in cards:
                    title = card.get("title", "").strip()
                    url = card.get("url", "").strip()
                    if not title or not url:
                        continue

                    if is_platform_listing_already_scraped(p_name, title, url, db_path=db_path):
                        continue

                    clean_brand = clean_brand_tokens(title)
                    listing_data = {
                        "platform": p_name,
                        "title": title,
                        "clean_brand": clean_brand,
                        "category": category,
                        "url": url,
                        "booking_url": url,
                        "rating": card.get("rating", 0.0),
                        "reviews_count": card.get("reviews_count", 0),
                        "price_info": card.get("price_info", ""),
                        "address": location_name,
                        "website_status": "captured"
                    }

                    listing_id = save_platform_listing(listing_data, db_path=db_path)
                    if listing_id:
                        saved_on_platform += 1
                        new_on_page += 1
                        total_saved_all_platforms += 1
                        emit("platform_listing_saved", {
                            "id": listing_id,
                            "platform": p_name,
                            "title": title,
                            "clean_brand": clean_brand,
                            "url": url
                        })

                    if max_results and saved_on_platform >= max_results:
                        break

                emit("log", f"📄 [Agent 4: Platform] Page {page_num} on {p_name}: {new_on_page} new saved (Total for platform: {saved_on_platform}/{max_results}).")
                if len(cards) == 0:
                    break
                if new_on_page == 0:
                    consecutive_zero_new += 1
                    if consecutive_zero_new >= 2:
                        emit("log", f"🏁 [Agent 4: Platform] No new listings on {p_name} across 2 consecutive pages. Platform crawl complete.")
                        break
                else:
                    consecutive_zero_new = 0

                page_num += 1

            emit("log", f"✅ [Agent 4: Platform] Completed {p_name} extraction: {saved_on_platform} new listings saved.")

        except Exception as pe:
            emit("log", f"❌ [Agent 4: Platform] Error extracting {p_name}: {pe}")

    return total_saved_all_platforms
