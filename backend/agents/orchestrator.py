"""
Multi-Agent Orchestrator Pipeline.
Coordinates Google Maps Harvester, Website Intelligence, LinkedIn Workforce Scout,
and Cross-Platform Directory Agents.
"""
import argparse
import asyncio
import base64
import datetime
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import async_playwright

from backend.config import STATIC_DIR, SCREENSHOTS_DIR
from backend.database import (
    save_lead,
    save_employees_batch,
    classify_seniority,
    clean_domain,
    is_lead_in_db,
    save_platform_listing,
    normalize_all_platform_listings,
    get_tables_split_data,
    extract_core_brand_name,
    load_proximity_dedup_cache,
    is_place_already_scraped,
    is_platform_listing_already_scraped,
    get_pending_resume_leads,
    get_cached_census_total,
    set_cached_census_total,
    update_lead_website_data,
    clean_email_string,
    get_connection,
)
from scrapers.antibot import (
    decode_cloudflare_email,
    detect_and_handle_cookies,
    attempt_turnstile_solve,
    detect_anti_bot_protection,
)
from backend.agents.event_bus import emit_event, emit_log, event_bus
from backend.agents.utils import (
    calculate_haversine_distance_km,
    radius_to_zoom,
    is_valid_email,
    clean_phone_number,
    clean_linkedin_url,
    clean_text,
    get_screen_dimensions,
    force_foreground_window,
    extract_emails_from_text,
    clean_social_url,
    extract_brand_from_domain,
    extract_city_from_address,
    verify_company_name_match,
    is_person_relevant_to_brand,
    extract_socials_from_text,
    parse_search_query_and_location,
    build_platform_area_url,
)
from backend.agents.web_inspector.agent import website_worker
from backend.agents.linkedin.agent import linkedin_worker, extract_single_linkedin_profile
from backend.agents.platform_scout.agent import platform_area_search_worker, extract_platform_total_count, PLATFORM_PROFILES
from backend.scrapers.screencast import frame_streamer_loop, clear_fixed_viewport, stop_stream_event

logger = logging.getLogger("Orchestrator")


async def run_scraper(
    query: str,
    max_results: int = 15,
    scrape_all: bool = False,
    visible_browser: bool = True,
    extract_emails: bool = True,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    zoom: int = 14,
    radius_km: float = 5.0,
    enable_maps: bool = True,
    enable_website: bool = True,
    enable_linkedin: bool = True,
    enable_platform: bool = False,
    platform_name: str = "Fresha",
    platforms: Optional[str] = None,
    platform_custom_url: Optional[str] = None,
    dedup_area: bool = True,
    skip_existing_db: bool = False,
    standalone_companies: Optional[str] = None,
    standalone_websites: Optional[str] = None,
    extension_active: bool = False,
):
    cleaned_query = query.strip() if query else ""
    if not cleaned_query or cleaned_query.lower() in ["all", "all businesses", "all shops", "all shops in area", "*", "shop", "shops", "places"]:
        cleaned_query = "businesses"

    search_category, search_location = parse_search_query_and_location(cleaned_query, lat=lat, lon=lon)
    selected_platforms_list = [p.strip() for p in (platforms or platform_name).split(",") if p.strip()] if enable_platform else []

    emit_event("status", "Launching Google Chrome on your screen...")
    emit_event("log", f"Starting Desktop Chrome (Visible: {visible_browser})...")

    async with async_playwright() as p:
        profile_dir = os.path.expandvars(r"%LOCALAPPDATA%\DataScrapper\BrowserProfile")
        try:
            os.makedirs(profile_dir, exist_ok=True)
        except Exception:
            pass
        screen_w, screen_h = get_screen_dimensions()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--disk-cache-size=33554432",
            "--media-cache-size=16777216",
            "--disable-dev-shm-usage",
            "--js-flags=--max-old-space-size=512",
            "--disable-gpu-shader-disk-cache",
        ]

        # Load Custom Mavon Scraper Chrome Extension
        ext_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "extension"))
        if os.path.exists(ext_path):
            launch_args.extend([
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
            ])

        cdp_connected = False
        browser = None
        context = None

        def get_chrome_executable_path() -> Optional[str]:
            for env_var in ["CHROME_BIN", "CHROME_PATH", "BROWSER_PATH"]:
                p = os.environ.get(env_var)
                if p and os.path.exists(p):
                    return p
            candidates = [
                # Standard Google Chrome
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                # Chrome Canary / Beta / Dev
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome SxS\Application\chrome.exe"),
                r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
                r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe",
                # Microsoft Edge
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                # Brave Browser
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
            return None

        async def ensure_chrome_running() -> bool:
            import urllib.request
            def is_port_open() -> bool:
                for target_url in ["http://127.0.0.1:9222/json/version", "http://localhost:9222/json/version"]:
                    try:
                        with urllib.request.urlopen(target_url, timeout=1.2) as resp:
                            if resp.status == 200:
                                return True
                    except Exception:
                        pass
                return False

            if is_port_open():
                return True

            chrome_exe = get_chrome_executable_path()
            src_user_data = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
            dest_user_data = profile_dir

            # Check if Chrome is already running on the desktop
            chrome_running = False
            try:
                chk = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"], capture_output=True, text=True, timeout=2.0)
                if "chrome.exe" in (chk.stdout or "").lower():
                    chrome_running = True
            except Exception:
                pass

            if chrome_running:
                emit_event("log", "⚠️ Chrome is running without Port 9222. Click '⚡ Use This Chrome (Port 9222)' in the dashboard header so all tabs open in this window!")
            
            # Always launch dedicated automation profile to isolate from personal browser
            target_profile_dir = dest_user_data
            emit_event("log", "🚀 Launching Chrome on Port 9222 (Profile: Dedicated Automation)...")

            if chrome_exe:
                cmd_args = [
                    chrome_exe,
                    f'--user-data-dir={target_profile_dir}',
                    '--remote-debugging-port=9222',
                    '--remote-allow-origins=*',
                    '--start-maximized',
                    'about:blank'
                ]
                subprocess.Popen(cmd_args)
                emit_event("log", "Launched Chrome with Port 9222 enabled.")

            # Wait up to 8 seconds for port 9222 to become ready
            for _ in range(20):
                await asyncio.sleep(0.4)
                if is_port_open():
                    emit_event("log", "✅ Google Chrome Port 9222 is active and ready.")
                    return True

            return is_port_open()

        if visible_browser:
            emit_event("log", "🔗 Checking for active Google Chrome with Remote Debugging (Port 9222)...")
            ready = await ensure_chrome_running()
            if ready:
                try:
                    browser = await p.chromium.connect_over_cdp("http://localhost:9222", timeout=15000)
                    context = browser.contexts[0] if browser.contexts else await browser.new_context(no_viewport=True)
                    cdp_connected = True
                    emit_event("log", "✅ Attached directly to your active Google Chrome window (Port 9222)! All accounts and tabs preserved.")
                    force_foreground_window()
                except Exception as cdp_err:
                    logger.warning(f"CDP connect error: {cdp_err}")

            if not context:
                emit_event("log", "Launching Chrome with persistent automation profile...")
                try:
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        channel="chrome",
                        headless=False,
                        args=launch_args,
                        no_viewport=True,
                        locale="en-US"
                    )
                    if context:
                        force_foreground_window()
                except Exception as e:
                    logger.warning(f"Native Chrome launch fallback: {e}")

        # Headless fallback if toggle is OFF
        if not context:
            stale_sessions = os.path.join(profile_dir, "Default", "Sessions")
            if os.path.exists(stale_sessions):
                try:
                    shutil.rmtree(stale_sessions, ignore_errors=True)
                except Exception:
                    pass

            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=not visible_browser,
                args=launch_args,
                no_viewport=True,
                locale="en-US"
            )

        # Close any leftover extra tabs from prior sessions if running persistent context
        if not cdp_connected and context and len(context.pages) > 1:
            for extra_p in list(context.pages)[1:]:
                try:
                    await extra_p.close()
                except Exception:
                    pass

        # Inject Synced LinkedIn Session Cookies (from active Chrome session via Extension)
        cookies_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "linkedin_cookies.json"))
        if os.path.exists(cookies_file) and not cdp_connected and context:
            try:
                with open(cookies_file, "r", encoding="utf-8") as f:
                    saved_cookies = json.load(f)
                if saved_cookies:
                    pw_cookies = []
                    for c in saved_cookies:
                        item = {
                            "name": str(c["name"]),
                            "value": str(c["value"]),
                            "domain": str(c["domain"]),
                            "path": str(c.get("path", "/")),
                            "httpOnly": bool(c.get("httpOnly", False)),
                            "secure": bool(c.get("secure", False)),
                        }
                        same_site = str(c.get("sameSite", "Lax")).capitalize()
                        if same_site in ("Strict", "Lax", "None"):
                            item["sameSite"] = same_site
                        else:
                            item["sameSite"] = "Lax"
                        if "expires" in c and c["expires"] > 0:
                            item["expires"] = float(c["expires"])
                        pw_cookies.append(item)
                    await context.add_cookies(pw_cookies)
                    emit_event("log", f"🔐 Injected {len(pw_cookies)} authenticated LinkedIn session cookies from your active Chrome.")
            except Exception as e:
                logger.warning(f"Cookie injection notice: {e}")

        # Inject Mavon Scraper Extension Bridge into all tabs
        bridge_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "extension", "injected_bridge.js"))
        if os.path.exists(bridge_file):
            try:
                await context.add_init_script(path=bridge_file)
                emit_event("log", "🧩 Mavon Scraper Extension Bridge active in Chrome tabs.")
            except Exception:
                pass

        # =============================================================
        # STANDALONE ENTERPRISE / COMPANY SEARCH MODE
        # (Direct LinkedIn Intelligence without Google Maps)
        # =============================================================
        if standalone_companies or (not enable_maps and enable_linkedin and not enable_platform and not enable_website):
            if standalone_companies:
                comp_list = [c.strip() for c in standalone_companies.split(",") if c.strip()]
            elif cleaned_query and cleaned_query not in ["shops", "places", "businesses"]:
                comp_list = [c.strip() for c in cleaned_query.split(",") if c.strip()]
            else:
                from database import get_all_leads
                db_leads = get_all_leads()
                comp_list = [l["name"] for l in db_leads if l.get("name")][:15]
                if not comp_list:
                    comp_list = ["Google", "Microsoft", "Amazon"]

            emit_event("status", f"Scanning {len(comp_list)} companies on LinkedIn...")
            emit_event("log", f"🏢 Starting Standalone LinkedIn Org Intelligence for: {', '.join(comp_list)}")

            linkedin_page = await context.new_page() if cdp_connected else (context.pages[0] if context.pages else await context.new_page())
            await clear_fixed_viewport(linkedin_page)

            stop_stream_event.clear()
            stream_task = asyncio.create_task(frame_streamer_loop(pages_dict={"linkedin": linkedin_page}))

            linkedin_queue = asyncio.Queue()
            done_event = asyncio.Event()

            linkedin_task = asyncio.create_task(linkedin_worker(linkedin_page, linkedin_queue, done_event))

            for idx, cname in enumerate(comp_list, start=1):
                save_lead({
                    "name": cname,
                    "category": "Enterprise",
                    "address": "N/A",
                    "website": "N/A",
                    "bot_protection": "N/A",
                    "cookie_status": "None"
                })
                emit_event("place_scraped", {
                    "name": cname,
                    "category": "Enterprise",
                    "address": "N/A",
                    "website": "N/A",
                    "phone": "N/A",
                    "email": "N/A",
                    "bot_protection": "N/A",
                    "cookie_status": "None"
                })

                linkedin_queue.put_nowait({
                    "index": idx,
                    "name": cname,
                    "website": "",
                    "linkedin_url": ""
                })

            done_event.set()
            await linkedin_queue.join()
            if linkedin_task:
                linkedin_task.cancel()

            stop_stream_event.set()
            if stream_task:
                try: await stream_task
                except Exception: pass

            if cdp_connected:
                try: await linkedin_page.close()
                except Exception: pass
            else:
                await context.close()

            emit_event("status", "Finished")
            emit_event("log", "🏁 Finished Standalone LinkedIn Org Intelligence.")
            emit_event("completed", {"count": len(comp_list), "places": []})
            return

        # =============================================================
        # STANDALONE WEBSITE AGENT (Agent 2 - Tab 2)
        # =============================================================
        if standalone_websites or (not enable_maps and enable_website and not enable_linkedin and not enable_platform):
            if standalone_websites:
                site_list = [w.strip() for w in standalone_websites.split(",") if w.strip()]
            else:
                from database import get_all_leads
                db_leads = get_all_leads()
                # Prioritize unexplored leads (pending status or missing emails/screenshots)
                site_list = [
                    l["website"] for l in db_leads
                    if l.get("website") and l["website"].startswith("http") and (
                        not l.get("website_status")
                        or l.get("website_status") in ["pending", "None", "", "failed"]
                        or not l.get("screenshot")
                        or l.get("email") in ["N/A", "", None]
                    )
                ][:25]
                if not site_list:
                    site_list = [l["website"] for l in db_leads if l.get("website") and l["website"].startswith("http")][:10]
                if not site_list:
                    site_list = ["https://grind.co.uk"]

            emit_event("status", f"Scanning {len(site_list)} websites...")
            emit_event("log", f"🌐 [Agent 2: Website] Starting Standalone Website Inspector for: {', '.join(site_list)}")

            website_page = await context.new_page() if cdp_connected else (context.pages[0] if context.pages else await context.new_page())
            await clear_fixed_viewport(website_page)

            stop_stream_event.clear()
            stream_task = asyncio.create_task(frame_streamer_loop(pages_dict={"website": website_page}))

            website_queue = asyncio.Queue()
            done_event = asyncio.Event()

            worker_task = asyncio.create_task(website_worker(context, website_queue, done_event, website_page=website_page, cdp_connected=cdp_connected))

            for idx, site_url in enumerate(site_list, start=1):
                clean_host = site_url.split("//")[-1].split("/")[0]
                website_queue.put_nowait({
                    "index": idx,
                    "name": clean_host,
                    "address": "N/A",
                    "website": site_url
                })

            done_event.set()
            await website_queue.join()
            if worker_task:
                worker_task.cancel()

            stop_stream_event.set()
            if stream_task:
                try: await stream_task
                except Exception: pass

            if cdp_connected:
                try: await website_page.close()
                except Exception: pass
            else:
                await context.close()

            emit_event("status", "Finished")
            emit_event("log", "🏁 Finished Standalone Website Inspector.")
            emit_event("completed", {"count": len(site_list), "places": []})
            return

        # =============================================================
        # MULTI-TAB PARALLEL SCRAPER:
        # Tab 1: Google Maps Master Tab
        # Tab 2: Dedicated Shop Website Tab
        # Tab 3: Dedicated LinkedIn Org Intelligence Tab
        # =============================================================
        # By default, open ONLY 2 tabs on startup: Tab 1 (Maps) and Tab 2 (LinkedIn)
        # Tab 3 (Shop Website) opens dynamically based on shop website
        # Dedicated 4-Agent Tab Architecture:
        # Tab 1: maps_page (Agent 1 - Google Maps)
        # Tab 2: website_page (Agent 2 - Shop Website, Anti-bot, Cookies, Emails)
        # Tab 3: linkedin_page (Agent 3 - LinkedIn Corporate & People Extraction)
        # Tab 4: platform_page (Agent 4 - Platform Directory Scout: Fresha, Airbnb, Yelp, TripAdvisor)
        pages_dict = {"maps": None, "website": None, "linkedin": None, "platform": None}
        maps_page = None
        website_page = None
        linkedin_page = None
        platform_page = None

        if cdp_connected:
            def is_maps_tab(p):
                u = p.url.lower()
                return "/maps" in u or "maps.google" in u

            def is_blank_tab(p):
                u = p.url.lower()
                return u in ["about:blank", "chrome://newtab/", "chrome://new-tab-page/", "chrome://newtab"]

            existing_maps = [p for p in context.pages if is_maps_tab(p)]
            existing_li = [p for p in context.pages if "linkedin.com" in p.url.lower()]
            known_plat_domains = ["fresha.com", "airbnb.com", "yelp.com", "tripadvisor.com", "booking.com", "zomato.com", "justdial.com", "treatwell", "opentable.com", "yellowpages.com"]
            if platform_name and "." in platform_name:
                known_plat_domains.append(platform_name.lower())
            if platform_custom_url and "http" in platform_custom_url:
                try:
                    host = urllib.parse.urlparse(platform_custom_url).hostname
                    if host:
                        known_plat_domains.append(host.lower())
                except Exception:
                    pass
            existing_plat = [p for p in context.pages if any(d in p.url.lower() for d in known_plat_domains)]
            
            # Close any existing tabs for agents that the user explicitly disabled
            if not enable_maps:
                for p in existing_maps:
                    try: await p.close()
                    except Exception: pass
                existing_maps = []
            if not enable_linkedin:
                for p in existing_li:
                    try: await p.close()
                    except Exception: pass
                existing_li = []
            if not enable_platform:
                for p in existing_plat:
                    try: await p.close()
                    except Exception: pass
                existing_plat = []

            used_tabs = set(existing_maps + existing_li + existing_plat)
            blank_tabs = [p for p in context.pages if is_blank_tab(p) and p not in used_tabs]

            if enable_maps and existing_maps:
                maps_page = existing_maps[-1]
                for extra_m in existing_maps[:-1]:
                    try: await extra_m.close()
                    except Exception: pass
            elif enable_maps:
                maps_page = blank_tabs.pop(0) if blank_tabs else await context.new_page()
            else:
                maps_page = None

            if enable_linkedin and existing_li:
                linkedin_page = existing_li[-1]
                for extra_li in existing_li[:-1]:
                    try: await extra_li.close()
                    except Exception: pass
            elif enable_linkedin:
                linkedin_page = blank_tabs.pop(0) if blank_tabs else await context.new_page()
            else:
                linkedin_page = None

            if enable_platform and existing_plat:
                platform_page = existing_plat[-1]
                for extra_plat in existing_plat[:-1]:
                    try: await extra_plat.close()
                    except Exception: pass
            elif enable_platform:
                platform_page = blank_tabs.pop(0) if blank_tabs else await context.new_page()
            else:
                platform_page = None

            website_page = (blank_tabs.pop(0) if blank_tabs else await context.new_page()) if (enable_website and extract_emails) else None
        else:
            pages_avail = list(context.pages)
            maps_page = pages_avail.pop(0) if (enable_maps and pages_avail) else (await context.new_page() if enable_maps else None)
            website_page = pages_avail.pop(0) if (enable_website and extract_emails and pages_avail) else (await context.new_page() if (enable_website and extract_emails) else None)
            linkedin_page = pages_avail.pop(0) if (enable_linkedin and pages_avail) else (await context.new_page() if enable_linkedin else None)
            platform_page = pages_avail.pop(0) if (enable_platform and pages_avail) else (await context.new_page() if enable_platform else None)
            # Close any leftover stray tabs
            for stray in pages_avail:
                try:
                    await stray.close()
                except Exception:
                    pass

        if maps_page:
            pages_dict["maps"] = maps_page
            await clear_fixed_viewport(maps_page)
        if website_page:
            pages_dict["website"] = website_page
            await clear_fixed_viewport(website_page)
        if linkedin_page:
            pages_dict["linkedin"] = linkedin_page
            await clear_fixed_viewport(linkedin_page)
        if platform_page:
            pages_dict["platform"] = platform_page
            await clear_fixed_viewport(platform_page)
            p_target = (platform_name or "Fresha").lower().strip()
            if "airbnb" in p_target:
                p_home = "https://www.airbnb.com/"
            elif "yelp" in p_target:
                p_home = "https://www.yelp.com/"
            elif "tripadvisor" in p_target:
                p_home = "https://www.tripadvisor.com/"
            elif "booking" in p_target:
                p_home = "https://www.booking.com/"
            elif "zomato" in p_target:
                p_home = "https://www.zomato.com/"
            elif "justdial" in p_target:
                p_home = "https://www.justdial.com/"
            elif "treatwell" in p_target:
                p_home = "https://www.treatwell.com/"
            elif "yellowpages" in p_target:
                p_home = "https://www.yellowpages.com/"
            elif "opentable" in p_target:
                p_home = "https://www.opentable.com/"
            elif platform_custom_url and "http" in platform_custom_url:
                p_home = platform_custom_url.split("?")[0]
            elif "." in p_target and " " not in p_target:
                p_home = f"https://www.{p_target.replace('www.', '')}" if not p_target.startswith("http") else p_target
            else:
                p_home = "https://www.fresha.com/"
            emit_event("log", f"Navigating Tab 4 ({platform_name}): {p_home}")
            emit_event("platform_navigated", {"url": p_home, "title": f"Directory: {platform_name}", "platform": platform_name})
            try:
                await platform_page.goto(p_home, wait_until="domcontentloaded", timeout=14000)
                await platform_page.evaluate(f"() => window.MavonScraper && window.MavonScraper.showHUD('Platform Scout: {platform_name}', 'Tab 4 Live on Chrome', '#a855f7')")
            except Exception:
                pass

    
        if visible_browser:
            if maps_page and not maps_page.is_closed():
                try: await maps_page.bring_to_front()
                except Exception: pass
            elif platform_page and not platform_page.is_closed():
                try: await platform_page.bring_to_front()
                except Exception: pass
            elif linkedin_page and not linkedin_page.is_closed():
                try: await linkedin_page.bring_to_front()
                except Exception: pass

        # Navigate Tab 2 (LinkedIn) on startup so both Maps and LinkedIn tabs are open by default
        if linkedin_page:
            try:
                emit_event("log", "Navigating Tab (LinkedIn): https://www.linkedin.com/")
                await linkedin_page.goto("https://www.linkedin.com/", wait_until="domcontentloaded")
            except Exception:
                pass

        # Initialize Tab (Website) on startup so all active tabs are visible and ready
        if website_page:
            try:
                emit_event("log", "Initializing Tab (Website Agent): Live domain & anti-bot observer ready.")
                await website_page.set_content("""
                    <!DOCTYPE html>
                    <html>
                    <head><title>Shop Website Intelligence Agent (Live)</title></head>
                    <body style="margin:0;font-family:Segoe UI,sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;background:#0f172a;color:#f8fafc;text-align:center;">
                        <div style="font-size:48px;margin-bottom:12px;">🌐</div>
                        <h2 style="font-size:22px;margin:0 0 8px 0;font-weight:700;">Shop Website Intelligence Agent</h2>
                        <p style="font-size:14px;color:#94a3b8;max-width:440px;line-height:1.5;margin:0 0 16px 0;">Live in your Chrome browser. As Google Maps extracts shops with websites, domains will load, test anti-bot protection, handle cookie banners, and harvest emails here live.</p>
                        <span style="display:inline-block;padding:6px 16px;border-radius:9999px;background:#1e293b;border:1px solid #334155;color:#38bdf8;font-size:12px;font-weight:600;">Status: Live on Screen</span>
                    </body>
                    </html>
                """)
            except Exception:
                pass

        # Setup Parallel Asynchronous Queues for Tab 2, Tab 3, and Tab 4
        website_queue = asyncio.Queue() if enable_website else None
        linkedin_queue = asyncio.Queue() if linkedin_page else None

        # RESUME CAPABILITY: Only resume old incomplete leads if Maps is disabled (dedicated background worker mode)
        # When Google Maps is running, prioritize the live harvested stream from Maps without old-queue lag!
        if not enable_maps:
            pending_web, pending_li = get_pending_resume_leads()
            if pending_web and website_queue:
                emit_event("log", f"🔄 [Resume Pipeline] Continuing {len(pending_web)} website inspections left incomplete from previous session...")
                for pw in pending_web:
                    website_queue.put_nowait(pw)
            if pending_li and linkedin_queue:
                emit_event("log", f"🔄 [Resume Pipeline] Continuing {len(pending_li)} LinkedIn org inspections left incomplete from previous session...")
                for pl in pending_li:
                    linkedin_queue.put_nowait(pl)
        platform_queue = asyncio.Queue() if enable_platform else None
        website_done_event = asyncio.Event()
        linkedin_done_event = asyncio.Event()
        platform_done_event = asyncio.Event()

        worker_task = None
        if website_queue:
            worker_task = asyncio.create_task(website_worker(context, website_queue, website_done_event, website_page=website_page, maps_page=maps_page, linkedin_queue=linkedin_queue, pages_dict=pages_dict, cdp_connected=cdp_connected))

        linkedin_task = None
        if linkedin_page and linkedin_queue:
            linkedin_task = asyncio.create_task(linkedin_worker(linkedin_page, linkedin_queue, linkedin_done_event))

        scraped_places = []
        skipped_count = 0
        dedup_cache = load_proximity_dedup_cache(search_location)

        platform_task = None
        if enable_platform and platform_page:
            platform_task = asyncio.create_task(platform_area_search_worker(
                context=context,
                platform_page=platform_page,
                selected_platforms=selected_platforms_list,
                category=search_category,
                location_name=search_location,
                radius_km=radius_km,
                max_results=max_results,
                scrape_all=scrape_all,
                custom_url_pattern=platform_custom_url or "",
                visible_browser=visible_browser,
                dedup_cache=dedup_cache
            ))
        proximity_total_estimated = max_results if not scrape_all else 120
        emit_event("proximity_total", {"platform": "Google Maps", "query": cleaned_query, "location": search_location, "total": proximity_total_estimated})
        emit_event("log", f"⚡ Loaded proximity deduplication cache ({dedup_cache['total_existing_leads']} leads, {dedup_cache['total_existing_listings']} directory listings in DB).")

        # Start live screen streaming across all active agent viewports
        stop_stream_event.clear()
        stream_task = asyncio.create_task(frame_streamer_loop(pages_dict=pages_dict))

        if enable_maps and maps_page:
            # Dynamic zoom from radius_km
            effective_zoom = radius_to_zoom(radius_km) if radius_km else zoom
            encoded_query = urllib.parse.quote_plus(cleaned_query)
            if lat is not None and lon is not None:
                search_url = f"https://www.google.com/maps/search/{encoded_query}/@{lat},{lon},{effective_zoom}z?hl=en"
            else:
                search_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"

            emit_event("log", f"🗺️ [Agent 1: Maps] Navigating to: {search_url}")
            emit_event("status", f"Searching Google Maps: {cleaned_query}")
            emit_event("maps_navigated", {"url": search_url, "query": cleaned_query})
            await maps_page.goto(search_url, wait_until="domcontentloaded")
            try:
                await maps_page.bring_to_front()
            except Exception:
                pass
            force_foreground_window()

            # Handle Cookie Consent on Google Maps
            try:
                consent_btn = maps_page.locator('button:has-text("Reject all"), button:has-text("Accept all"), form[action*="consent"] button').first
                if await consent_btn.is_visible(timeout=2000):
                    emit_event("log", "🍪 [Agent 1: Maps] Auto-accepting Google Maps cookie consent...")
                    await consent_btn.click()
                    await maps_page.wait_for_timeout(1000)
            except Exception:
                pass

            # Wait for results feed
            feed_selector = 'div[role="feed"]'
            try:
                await maps_page.wait_for_selector(feed_selector, timeout=12000)
                emit_event("log", "🗺️ [Agent 1: Maps] Google Maps results feed loaded. Scanning area businesses...")
            except Exception:
                emit_event("log", "🗺️ [Agent 1: Maps] Results feed container detected.")

            await maps_page.wait_for_timeout(1000)
        seen_titles = set()
        seen_signatures = set()
        seen_phones = set()
        seen_domains = set()
        seen_names = set()
        scroll_attempts = 0
        is_infinite = (scrape_all or max_results >= 9999)
        target_max = 999999 if is_infinite else max_results
        max_scroll_attempts = 99999 if is_infinite else max(30, (max_results * 2) + 20)
        consecutive_no_new = 0

        emit_event("status", "Extracting places from feed...")

        while (enable_maps and maps_page) and len(scraped_places) < target_max and scroll_attempts < max_scroll_attempts:
            links = maps_page.locator('div[role="feed"] a.hfpxzc, div[role="feed"] a[href*="/maps/place/"]')
            count = await links.count()
            if count == 0:
                links = maps_page.locator('a.hfpxzc, div[role="article"] a')
                count = await links.count()

            new_found_this_scroll = 0

            for i in range(count):
                if len(scraped_places) >= target_max:
                    break

                try:
                    elem = links.nth(i)
                    raw_title = await elem.get_attribute("aria-label") or ""
                    title = clean_text(raw_title)
                    # Strip 'Visited link' or 'visited' suffix added by Google Maps
                    title = re.sub(r'\s*[·•\-]\s*visited\s*link.*$', '', title, flags=re.I).strip()
                    title = re.sub(r'\s+visited\s*link.*$', '', title, flags=re.I).strip()

                    if not title or title in seen_titles:
                        continue

                    seen_titles.add(title)
                    new_found_this_scroll += 1

                    # PRE-CLICK FAST DEDUPLICATION CHECK (Bypasses click & crawl if in DB)
                    preview_text = ""
                    try:
                        parent_el = elem.locator("xpath=..")
                        preview_text = clean_text(await parent_el.inner_text())
                    except Exception:
                        pass

                    if is_place_already_scraped(title, preview_text, dedup_cache):
                        skipped_count += 1
                        time_saved = skipped_count * 3.5
                        emit_event("lead_skipped", {
                            "name": title,
                            "address": preview_text[:60] if preview_text else "In Database",
                            "reason": "Already exists in database",
                            "scraped": len(scraped_places),
                            "skipped": skipped_count,
                            "total": proximity_total_estimated,
                            "time_saved_sec": round(time_saved, 1)
                        })
                        emit_event("proximity_progress", {
                            "scraped": len(scraped_places),
                            "skipped": skipped_count,
                            "total": proximity_total_estimated,
                            "percent": min(100, round(((len(scraped_places) + skipped_count) / max(1, proximity_total_estimated)) * 100))
                        })
                        emit_event("log", f"⏭️ [Agent 1: Maps] Skipped '{title}' (already verified in database).")
                        try:
                            await elem.evaluate("el => window.MavonScraper && window.MavonScraper.highlight(el, 'Skipped (In DB)', '#f59e0b')")
                        except Exception:
                            pass
                        continue

                    idx = len(scraped_places) + 1

                    emit_event("log", f"👉 [Agent 1: Maps] [{idx}] Inspecting place card: '{title}'")
                    emit_event("status", f"Scraping #{idx}: {title}")

                    # Highlight place card visually using extension bridge
                    try:
                        await elem.evaluate(f"el => window.MavonScraper && window.MavonScraper.highlight(el, 'Inspecting #{idx}')")
                    except Exception:
                        pass

                    # Extract feed card data directly (prevents detail pane mismatches)
                    card_data = {}
                    try:
                        card_data = await elem.evaluate(r"""(el) => {
                            const card = el.closest('div.Nv2PK, div[role="article"]') || el.parentElement;
                            if (!card) return {};
                            const webA = card.querySelector('a[data-value="Website"], a[aria-label*="website" i]');
                            return {
                                cardWeb: webA ? webA.href : '',
                                cardText: card.innerText || ''
                            };
                        }""")
                    except Exception:
                        pass

                    # FAST RELIABLE DOM CLICK & SYNCHRONIZED DETAIL PANE EXTRACTION
                    try:
                        await elem.evaluate("el => { el.scrollIntoView({ block: 'center' }); el.click(); }")
                    except Exception:
                        await elem.click(force=True)

                    # Synchronize with Google Maps network loading: wait until detail header matches this place AND buttons hydrate
                    clean_target = re.sub(r'[^a-zA-Z0-9]', '', title).lower()[:15]
                    try:
                        await maps_page.wait_for_function(
                            """(target) => {
                                const h1 = document.querySelector('h1.DUwDvf');
                                if (!h1) return false;
                                const hClean = (h1.innerText || '').toLowerCase().replace(/[^a-z0-9]/g, '');
                                const isMatch = !target || hClean.includes(target) || target.includes(hClean);
                                if (!isMatch) return false;

                                const pane = h1.closest('div.dS8AEf, div.m6QErb.DxyBCb, div.m6QErb.kA9KIf') || h1.closest('div[role="main"]');
                                if (!pane) return false;
                                const hasDetail = !!pane.querySelector(
                                    'button[data-item-id="address"], button[aria-label*="Address:"], button[data-item-id*="phone:"], a[data-item-id="authority"], div[data-item-id*="oh"]'
                                );
                                return hasDetail;
                            }""",
                            arg=clean_target,
                            timeout=3500
                        )
                    except Exception:
                        await maps_page.wait_for_timeout(350)

                    # Scroll the opened place card detail pane to reveal below-the-fold contact info
                    try:
                        await maps_page.evaluate("""() => {
                            const h1 = document.querySelector('h1.DUwDvf');
                            const detailPane = h1 ? (h1.closest('div.dS8AEf, div.m6QErb.DxyBCb, div.m6QErb.kA9KIf') || h1.closest('div[role="main"]')) : null;
                            if (detailPane) {
                                detailPane.scrollTop = 450;
                            }
                        }""")
                        await maps_page.wait_for_timeout(150)
                    except Exception:
                        pass

                    # Single ultra-fast evaluation in browser V8 (Extracts all details in <10ms)
                    detail_data = {}
                    try:
                        detail_data = await maps_page.evaluate(r'''() => {
                            const d = {
                                title: '',
                                category: '',
                                rating: '',
                                reviews: '',
                                address: '',
                                phone: '',
                                website: '',
                                hours: '',
                                price: '',
                                plus_code: '',
                                email: '',
                                ig: '',
                                fb: '',
                                li: '',
                                tw: '',
                                yt: '',
                                tt: '',
                                lat: null,
                                lon: null
                            };

                            // Helper to unwrap Google redirection URLs (e.g. google.com/url?q=...)
                            const unwrapUrl = (href) => {
                                if (!href) return '';
                                try {
                                    if (href.includes('google.com/url?') || href.includes('/url?q=')) {
                                        const m = href.match(/[?&]q=([^&]+)/);
                                        if (m) return decodeURIComponent(m[1]).split('?')[0].replace(/\/+$/, '');
                                    }
                                } catch (_) {}
                                return href.split('?')[0].replace(/\/+$/, '');
                            };

                            // Title & Scoped Detail Pane Root
                            const h1 = document.querySelector('h1.DUwDvf');
                            if (h1) d.title = h1.innerText.trim();
                            const pane = h1 ? (h1.closest('div.dS8AEf, div.m6QErb.DxyBCb, div.m6QErb.kA9KIf') || h1.closest('div[role="main"]')) : null;
                            const root = pane || document;

                            // Category
                            const catBtn = root.querySelector('button.DkEaL, button[jsaction*="category"], div.fontBodyMedium button, span.YhemCb');
                            if (catBtn) {
                                const cText = catBtn.innerText.trim();
                                const ignore = ["learn more", "see more", "read more", "claim this business", "suggest an edit", "save", "nearby", "send to phone", "share", "reviews", "photos", "overview", "about", "directions", "copy", "update results when map moves", "update results", "search this area"];
                                if (cText && !ignore.some(x => cText.toLowerCase().includes(x))) {
                                    d.category = cText;
                                }
                            }

                            // Rating
                            const ratingEl = root.querySelector('div.F7nice span[aria-hidden="true"], span.ceNzKf, div.fontDisplayLarge, span[aria-label*="stars"], span.MW4etd');
                            if (ratingEl) {
                                const text = ratingEl.innerText || ratingEl.getAttribute('aria-label') || '';
                                const m = text.match(/\b([0-5]\.\d+)\b/);
                                if (m) d.rating = m[1];
                            }

                            // Reviews
                            const revEl = root.querySelector('div.F7nice span[aria-label*="reviews"], span.mgr77e, button[aria-label*="reviews"], span[aria-label*="reviews"], span.UY7F9, div.F7nice button');
                            if (revEl) {
                                const text = revEl.getAttribute('aria-label') || revEl.innerText || '';
                                const digits = text.match(/[\d,]+/);
                                if (digits && digits[0] !== '0') d.reviews = digits[0].replace(/,/g, '');
                            }

                            // Address
                            const addrEl = root.querySelector('button[data-item-id="address"], button[aria-label*="Address:"], div[data-item-id="address"], button[data-tooltip*="Copy address"], [data-item-id*="address"]');
                            if (addrEl) {
                                const text = addrEl.getAttribute('aria-label') || addrEl.innerText || '';
                                d.address = text.replace(/^Address:\s*/i, '').replace(/[\uE000-\uF8FF]/g, '').trim();
                            }

                            // Phone
                            const phoneEl = root.querySelector('button[data-item-id*="phone:"], button[aria-label*="Phone:"], button[data-tooltip*="Copy phone"], a[href^="tel:"]');
                            if (phoneEl) {
                                const text = phoneEl.getAttribute('aria-label') || phoneEl.innerText || '';
                                d.phone = text.replace(/^Phone:\s*/i, '').replace(/[\uE000-\uF8FF]/g, '').trim();
                            }

                            // Website: STRICTLY inside detail pane authority button (NEVER global feed buttons)
                            if (pane) {
                                const webEl = pane.querySelector('a[data-item-id="authority"], a[data-tooltip*="Open website"]');
                                if (webEl && webEl.href) {
                                    d.website = unwrapUrl(webEl.href);
                                }
                            }

                            // Email extraction from Google Maps detail pane
                            let mapsEmail = '';
                            const mailLink = root.querySelector('a[href^="mailto:"]');
                            if (mailLink && mailLink.href) {
                                mapsEmail = mailLink.href.replace(/^mailto:/i, '').split('?')[0].trim();
                            }
                            if (!mapsEmail) {
                                const emailEl = root.querySelector('button[data-item-id*="email"], a[data-item-id*="email"], [aria-label*="Email:" i], button[data-tooltip*="email" i]');
                                if (emailEl) {
                                    const txt = emailEl.getAttribute('aria-label') || emailEl.innerText || '';
                                    const m = txt.match(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/);
                                    if (m) mapsEmail = m[0];
                                }
                            }
                            if (!mapsEmail && pane && pane.innerText) {
                                const m = pane.innerText.match(/\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b/);
                                if (m) {
                                    const potential = m[0].trim();
                                    if (!potential.match(/\.(png|jpg|jpeg|svg|webp|gif|js|css)$/i)) {
                                        mapsEmail = potential;
                                    }
                                }
                            }
                            d.email = mapsEmail;

                            // Hours
                            const hoursEl = root.querySelector('button[data-item-id*="oh"], div[data-item-id*="oh"], button[aria-label*="Hours"], div[aria-label*="Hours"]');
                            if (hoursEl) {
                                d.hours = (hoursEl.innerText || '').split('\n')[0].trim();
                            }

                            // Price
                            const priceEl = root.querySelector('span[aria-label*="per person"], span[aria-label*="Price"], button[data-item-id*="price"], div[aria-label*="£"], div[aria-label*="$"]');
                            if (priceEl) {
                                d.price = priceEl.innerText.trim();
                            }

                            // Plus code
                            const pcEl = root.querySelector('button[data-item-id="oloc"], button[aria-label*="Plus code"]');
                            if (pcEl) {
                                d.plus_code = pcEl.innerText.trim();
                            }

                            // Socials strictly inside detail pane and overview profiles
                            if (pane) {
                                const allLinks = pane.querySelectorAll('a[href]');
                                allLinks.forEach(a => {
                                    const rawHref = a.getAttribute('href') || a.href || '';
                                    const cleanHref = unwrapUrl(rawHref);
                                    const lower = cleanHref.toLowerCase();
                                    if (lower.includes('instagram.com/') && !d.ig && !lower.includes('/p/')) {
                                        d.ig = cleanHref;
                                    } else if ((lower.includes('facebook.com/') || lower.includes('fb.me/')) && !d.fb && !lower.includes('sharer')) {
                                        d.fb = cleanHref;
                                    } else if (lower.includes('linkedin.com/') && !d.li) {
                                        d.li = cleanHref;
                                    } else if ((lower.includes('twitter.com/') || lower.includes('x.com/')) && !d.tw && !lower.includes('/intent/')) {
                                        d.tw = cleanHref;
                                    } else if ((lower.includes('youtube.com/') || lower.includes('youtu.be/')) && !d.yt && !lower.includes('/watch')) {
                                        d.yt = cleanHref;
                                    } else if (lower.includes('tiktok.com/') && !d.tt) {
                                        d.tt = cleanHref;
                                    } else if ((lower.includes('wa.me/') || lower.includes('api.whatsapp.com/send') || lower.includes('whatsapp://')) && !d.whatsapp) {
                                        const mWa = cleanHref.match(/(?:wa\.me\/|phone=|\b)(\+?[0-9]{7,15})\b/);
                                        if (mWa) d.whatsapp = mWa[1].replace(/[^0-9]/g, '');
                                    }
                                });
                            }

                            // Platform Booking & Table Reservation
                            let bUrl = '';
                            let bPlat = '';
                            const bookEl = root.querySelector('a[data-tooltip*="reservation" i], a[data-tooltip*="booking" i], a[data-tooltip*="table" i], a[aria-label*="table" i], a[aria-label*="reserve" i], a[aria-label*="book" i], a[href*="zoma.to"], a[href*="zomato.com"], a[href*="opentable.com"], a[href*="resy.com"], a[href*="fresha.com"], a[href*="booksy.com"], a[href*="practo.com"], a[data-item-id*="action:1"], a[data-item-id="reserve"]');
                            if (bookEl && (bookEl.href || bookEl.getAttribute('href'))) {
                                bUrl = unwrapUrl(bookEl.getAttribute('href') || bookEl.href);
                                const bLower = bUrl.toLowerCase();
                                const tLower = (bookEl.innerText || '').toLowerCase();
                                if (bLower.includes('zoma.to') || bLower.includes('zomato') || tLower.includes('zoma')) bPlat = 'Zomato';
                                else if (bLower.includes('swiggy') || tLower.includes('swiggy')) bPlat = 'Swiggy';
                                else if (bLower.includes('opentable') || tLower.includes('opentable')) bPlat = 'OpenTable';
                                else if (bLower.includes('resy') || tLower.includes('resy')) bPlat = 'Resy';
                                else if (bLower.includes('fresha') || tLower.includes('fresha')) bPlat = 'Fresha';
                                else if (bLower.includes('booksy') || tLower.includes('booksy')) bPlat = 'Booksy';
                                else if (bLower.includes('practo') || tLower.includes('practo')) bPlat = 'Practo';
                                else if (bLower.includes('eazydiner')) bPlat = 'EazyDiner';
                                else if (bLower.includes('dineout')) bPlat = 'Dineout';
                                else bPlat = 'Reservation';
                            }
                            d.booking_url = bUrl;
                            d.platform_name = bPlat;

                            // Order Online Link
                            let oUrl = '';
                            const orderEl = root.querySelector('a[aria-label*="Order online" i], button[aria-label*="Order online" i], a.A1zNzb, a[href*="searchviewer"][href*="order"]');
                            if (orderEl && (orderEl.href || orderEl.getAttribute('href'))) {
                                oUrl = unwrapUrl(orderEl.getAttribute('href') || orderEl.href);
                            }
                            d.order_url = oUrl;

                            // Formulate Structured Notes (Price, Services, Highlights, Location info)
                            const noteItems = [];
                            if (d.price) {
                                noteItems.push(`💰 ${d.price}`);
                            }

                            const allSpans = Array.from(root.querySelectorAll('div, span')).filter(el => {
                                const t = el.innerText || '';
                                return (t.includes('Dine-in') || t.includes('Takeaway') || t.includes('Delivery') || t.includes('Curbside pickup')) && t.length < 80;
                            });
                            if (allSpans.length > 0) {
                                const cleanServices = allSpans[0].innerText.replace(/[\ue000-\uf8ff\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
                                const parts = ['Dine-in', 'Takeaway', 'Delivery', 'No-contact delivery', 'Curbside pickup'].filter(s => cleanServices.includes(s));
                                if (parts.length > 0) {
                                    noteItems.push(`🍽️ ${parts.join(' · ')}`);
                                }
                            }

                            const attrEls = Array.from(root.querySelectorAll('div, button, span')).filter(el => {
                                const t = el.innerText || '';
                                return (t.includes('women-owned') || t.includes('Identifies as') || t.includes('LGBTQ') || t.includes('Veteran')) && t.length < 60;
                            });
                            if (attrEls.length > 0) {
                                const attrText = attrEls[0].innerText.replace(/[\ue000-\uf8ff\r\n]+/g, ' ').trim();
                                if (attrText) noteItems.push(`💜 ${attrText}`);
                            }

                            if (pane) {
                                const secAddrEl = pane.querySelector('button[data-item-id*="address"] ~ button, div.rogA2c ~ div.rogA2c');
                                if (secAddrEl) {
                                    const secText = secAddrEl.innerText.replace(/[\ue000-\uf8ff\r\n]+/g, ' ').trim();
                                    if (secText && (secText.toLowerCase().includes('floor') || secText.toLowerCase().includes('mall') || secText.toLowerCase().includes('complex'))) {
                                        noteItems.push(`📍 ${secText}`);
                                    }
                                }
                            }

                            d.notes = noteItems.join(' | ');

                            // If primary website was a social media profile, set it accordingly
                            if (d.website) {
                                const wLower = d.website.toLowerCase();
                                if (wLower.includes('instagram.com/') && !d.ig) d.ig = d.website;
                                else if ((wLower.includes('facebook.com/') || wLower.includes('fb.me/')) && !d.fb) d.fb = d.website;
                                else if (wLower.includes('linkedin.com/') && !d.li) d.li = d.website;
                                else if ((wLower.includes('twitter.com/') || wLower.includes('x.com/')) && !d.tw) d.tw = d.website;
                                else if ((wLower.includes('youtube.com/') || wLower.includes('youtu.be/')) && !d.yt) d.yt = d.website;
                                else if (wLower.includes('tiktok.com/') && !d.tt) d.tt = d.website;
                            }

                            // DOM Coordinates
                            const dirLink = document.querySelector('a[href*="destination="], a[data-value="Directions"], a[href*="maps/dir/"]');
                            if (dirLink && dirLink.href) {
                                const m = dirLink.href.match(/destination=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)/i);
                                if (m) { d.lat = parseFloat(m[1]); d.lon = parseFloat(m[2]); }
                            }
                            if (d.lat === null) {
                                const anyCoord = document.querySelector('a[href*="!3d"]');
                                if (anyCoord && anyCoord.href) {
                                    const m = anyCoord.href.match(/!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/);
                                    if (m) { d.lat = parseFloat(m[1]); d.lon = parseFloat(m[2]); }
                                }
                            }

                            return d;
                        }''')
                    except Exception:
                        pass

                    place_title = clean_text(detail_data.get("title") or title)
                    category = detail_data.get("category") or ""
                    rating = detail_data.get("rating") or ""
                    reviews = detail_data.get("reviews") or ""
                    address = detail_data.get("address") or ""
                    phone = detail_data.get("phone") or ""
                    website = detail_data.get("website") or ""

                    # Card-level fallback: If website was not in detail pane, check the clicked card's direct website button
                    if not website and card_data.get("cardWeb"):
                        u = card_data["cardWeb"]
                        if "google.com/url?q=" in u:
                            m = re.search(r'[?&]q=([^&]+)', u)
                            if m:
                                u = urllib.parse.unquote(m.group(1))
                        website = u

                    # Secondary deep-scroll fallback: If website is not found, scroll further down in detail pane and check authority link
                    if not website:
                        try:
                            await maps_page.evaluate("""() => {
                                const h1 = document.querySelector('h1.DUwDvf');
                                const detailPane = h1 ? (h1.closest('div.TIHn2, div.m6QErb:not([role="feed"]), div[role="main"]') || h1.parentElement?.parentElement) : null;
                                if (detailPane) {
                                    detailPane.scrollTop = 900;
                                }
                            }""")
                            deep_web = await maps_page.wait_for_function(
                                """() => {
                                    const h1 = document.querySelector('h1.DUwDvf');
                                    const pane = h1 ? (h1.closest('div.TIHn2, div.m6QErb:not([role="feed"]), div[role="main"]') || h1.parentElement?.parentElement) : null;
                                    const webEl = pane ? pane.querySelector('a[data-item-id="authority"], a[data-tooltip*="Open website"]') : null;
                                    if (webEl && webEl.href) {
                                        let u = webEl.href;
                                        if (u.includes('google.com/url?q=')) {
                                            const match = u.match(/[?&]q=([^&]+)/);
                                            if (match) u = decodeURIComponent(match[1]);
                                        }
                                        return u;
                                    }
                                    return false;
                                }""",
                                timeout=500
                            )
                            if deep_web:
                                website = await deep_web.json_value()
                        except Exception:
                            pass
                    hours = detail_data.get("hours") or ""
                    price = detail_data.get("price") or ""
                    plus_code = detail_data.get("plus_code") or ""
                    maps_email = clean_email_string(detail_data.get("email") or "")
                    maps_ig = detail_data.get("ig") or ""
                    maps_fb = detail_data.get("fb") or ""
                    maps_li = detail_data.get("li") or ""
                    maps_tw = detail_data.get("tw") or "" 
                    maps_yt = detail_data.get("yt") or ""
                    maps_tt = detail_data.get("tt") or ""
                    maps_b_url = detail_data.get("booking_url") or ""
                    maps_b_plat = detail_data.get("platform_name") or ""
                    maps_o_url = detail_data.get("order_url") or ""
                    maps_notes = detail_data.get("notes") or (f"💰 {price}" if price else "")

                    # FALLBACK: If right-side detail pane had missing address or phone, extract from small feed card preview_text
                    if preview_text:
                        if not address or address == "N/A":
                            dot_parts = [p.strip() for p in preview_text.split("·") if p.strip()]
                            for dp in dot_parts[1:]:
                                if not any(x in dp.lower() for x in ["closed", "open", "reviews", "stars", "delivery"]):
                                    address = dp
                                    break
                        if not phone or phone == "N/A":
                            ph_match = re.search(r'\b(?:\+?\d{1,4}[ -]?)?(?:\d{5}[ -]?\d{5}|\d{3,5}[ -]?\d{6,8})\b', preview_text)
                            if ph_match:
                                phone = ph_match.group(0).strip()
                        if not rating or rating == "N/A":
                            r_match = re.search(r'\b([1-5]\.\d)\b', preview_text)
                            if r_match:
                                rating = r_match.group(1) 

                    if website:
                        w_low = website.lower()
                        if "instagram.com/" in w_low and not maps_ig: maps_ig = website
                        elif ("facebook.com/" in w_low or "fb.me/" in w_low) and not maps_fb: maps_fb = website
                        elif "linkedin.com/" in w_low and not maps_li: maps_li = website
                        elif ("twitter.com/" in w_low or "x.com/" in w_low) and not maps_tw: maps_tw = website
                        elif ("youtube.com/" in w_low or "youtu.be/" in w_low) and not maps_yt: maps_yt = website
                        elif "tiktok.com/" in w_low and not maps_tt: maps_tt = website

                    # Extract Exact GPS Coordinates (Lat, Lon) of the Place
                    lat_val = detail_data.get("lat")
                    lon_val = detail_data.get("lon")
                    cur_maps_url = maps_page.url or ""
                    
                    if lat_val is None or lon_val is None:
                        d_match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", cur_maps_url)
                        if d_match:
                            lat_val = float(d_match.group(1))
                            lon_val = float(d_match.group(2))

                    # 3. Fallback to /place/ URL @lat,lon (only if viewing a single place, not search view)
                    if (lat_val is None or lon_val is None) and "/place/" in cur_maps_url:
                        url_match = re.search(r"/place/[^/]+/@(-?\d+\.\d+),(-?\d+\.\d+)", cur_maps_url)
                        if url_match:
                            lat_val = float(url_match.group(1))
                            lon_val = float(url_match.group(2))

                    # --- RADIUS FILTERING (Strict Haversine Distance Check) ---
                    if lat is not None and lon is not None and radius_km is not None and lat_val is not None and lon_val is not None:
                        dist_km = calculate_haversine_distance_km(lat, lon, lat_val, lon_val)
                        if dist_km > (radius_km * 1.5):
                            emit_event("log", f"⚠️ [Radius Filter] Skipped '{place_title}' ({dist_km:.2f}km away > {radius_km}km limit).")
                            continue

                    # --- DEDUPLICATION AVOIDANCE ---
                    norm_name = place_title.strip().lower()
                    norm_addr = address.strip().lower() if address and address != "N/A" else ""
                    phone_digits = re.sub(r"\D", "", phone) if phone and phone != "N/A" else ""
                    dom = clean_domain(website) if website and website != "N/A" else ""

                    if dedup_area:
                        if (norm_name, norm_addr) in seen_signatures:
                            emit_event("log", f"🔄 [Area Dedup] Skipped '{place_title}' (already harvested in this area).")
                            continue
                        if phone_digits and len(phone_digits) >= 8 and phone_digits in seen_phones:
                            emit_event("log", f"🔄 [Area Dedup] Skipped '{place_title}' (phone matches existing shop).")
                            continue
                        if dom and dom in seen_domains and norm_name in seen_names:
                            emit_event("log", f"🔄 [Area Dedup] Skipped '{place_title}' (matches existing shop name & domain).")
                            continue

                    if skip_existing_db:
                        if is_lead_in_db(place_title, address):
                            emit_event("log", f"🏢 [DB Dedup] Skipped '{place_title}' (already saved in database).")
                            continue

                    seen_signatures.add((norm_name, norm_addr))
                    seen_names.add(norm_name)
                    if phone_digits and len(phone_digits) >= 8:
                        seen_phones.add(phone_digits)
                    if dom:
                        seen_domains.add(dom)

                    is_social_site = bool(website and any(s in website.lower() for s in [
                        "instagram.com", "facebook.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com"
                    ]))

                    place_info = {
                        "index": idx,
                        "name": place_title,
                        "category": category or "Business",
                        "address": address or "N/A",
                        "phone": clean_phone_number(phone),
                        "hours": hours or "N/A",
                        "price": price or "N/A",
                        "plus_code": plus_code or "N/A",
                        "emails": [maps_email] if maps_email else [],
                        "email": maps_email or "N/A",
                        "instagram": maps_ig,
                        "facebook": maps_fb,
                        "linkedin": maps_li,
                        "twitter": maps_tw,
                        "youtube": maps_yt,
                        "tiktok": maps_tt,
                        "booking_url": maps_b_url,
                        "platform_name": maps_b_plat,
                        "order_url": maps_o_url,
                        "notes": maps_notes,
                        "whatsapp": detail_data.get("whatsapp", ""),
                        "screenshot": "",
                        "bot_protection": "Social Profile" if is_social_site else ("Inspecting..." if (enable_website and extract_emails and website and not is_social_site) else "N/A"),
                        "cookie_status": "None" if is_social_site else ("Inspecting..." if (enable_website and extract_emails and website and not is_social_site) else "None"),
                        "rating": rating or "N/A",
                        "reviews": reviews or "0",
                        "website": website or "N/A",
                        "maps_url": maps_page.url,
                        "lat": lat_val,
                        "lon": lon_val,
                        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }

                    lead_db_id = save_lead(place_info)
                    if lead_db_id:
                        place_info["id"] = lead_db_id

                    scraped_places.append(place_info)
                    emit_event("place_scraped", place_info)
                    soc_tags = []
                    if maps_email: soc_tags.append(f"✉️ {maps_email}")
                    if maps_ig: soc_tags.append(f"📸 IG: {maps_ig}")
                    if maps_fb: soc_tags.append(f"👥 FB: {maps_fb}")
                    if maps_li: soc_tags.append(f"💼 LI: {maps_li}")
                    if maps_tw: soc_tags.append(f"🐦 X: {maps_tw}")
                    if maps_yt: soc_tags.append(f"▶️ YT: {maps_yt}")
                    if maps_tt: soc_tags.append(f"🎵 TT: {maps_tt}")
                    soc_str = (" | " + " ".join(soc_tags)) if soc_tags else ""

                    extra_tags = []
                    if maps_b_plat or maps_b_url: extra_tags.append(f"📅 {maps_b_plat or 'Booking'}")
                    if maps_o_url: extra_tags.append("🛍️ Order Online")
                    if maps_notes: extra_tags.append(f"📝 {maps_notes}")
                    extra_str = (" | " + " ".join(extra_tags)) if extra_tags else ""

                    emit_event("log", f"✅ [Agent 1: Maps] Saved #{idx}: '{place_title}' | 🏷️ {category or 'Business'} | 📞 {place_info['phone']} | 🌐 {website or 'N/A'}{soc_str}{extra_str} | ⭐ {rating or 'N/A'}")
                    dedup_cache["leads_names"].add(place_title.lower().strip())
                    if address and address != 'N/A':
                        dedup_cache["leads_name_addr"].add((place_title.lower().strip(), address.lower().strip()))
                    emit_event("proximity_progress", {
                        "scraped": len(scraped_places),
                        "skipped": skipped_count,
                        "total": proximity_total_estimated,
                        "percent": min(100, round(((len(scraped_places) + skipped_count) / max(1, proximity_total_estimated)) * 100)),
                        "time_saved_sec": round(skipped_count * 3.5, 1)
                    })

                    # -----------------------------------------------------------------
                    # PARALLEL PIPELINE: Send website job to Tab 2 simultaneously!
                    # Tab 1 DOES NOT STOP! It immediately moves to the next place!
                    # -----------------------------------------------------------------
                    if enable_website and website and website.startswith("http") and website_queue:
                        emit_event("log", f"➡️ [Agent 1: Maps] Dispatched #{idx} '{place_title}' to [Agent 2: Website] for contact discovery")
                        website_queue.put_nowait({
                            "index": idx,
                            "lead_id": place_info.get("id") or lead_db_id,
                            "name": place_title,
                            "address": address or "N/A",
                            "website": website,
                        })
                    elif enable_linkedin and linkedin_queue:
                        emit_event("log", f"➡️ [Agent 1: Maps] Dispatched #{idx} '{place_title}' to [Agent 3: LinkedIn] for org intelligence")
                        linkedin_queue.put_nowait({
                            "index": idx,
                            "lead_id": place_info.get("id") or lead_db_id,
                            "name": place_title,
                            "address": address or "N/A",
                            "website": website if (website and website != "N/A") else "",
                            "linkedin_url": "",
                        })

                    # Platform area search operates independently by location & proximity

                except Exception as e:
                    emit_event("log", f"⚠️ Card error: {type(e).__name__} - {e}")
                    continue

            if len(scraped_places) >= target_max:
                break

            # Check if Google Maps feed reached the end
            end_reached = False
            try:
                end_banner = maps_page.locator('div:has-text("You\'ve reached the end of the list"), div.W275Fa, div.HlvSq').first
                if await end_banner.is_visible(timeout=500):
                    end_reached = True
                    proximity_total_estimated = max(1, len(scraped_places) + skipped_count)
                    emit_event("proximity_total", {"platform": "Google Maps", "query": cleaned_query, "location": search_location, "total": proximity_total_estimated, "is_final": True})
                    emit_event("log", f"🏁 Reached the end of Google Maps results! Total shops in proximity: {proximity_total_estimated}")
            except Exception:
                pass

            if end_reached:
                break

            scroll_attempts += 1
            if new_found_this_scroll == 0:
                consecutive_no_new += 1
            else:
                consecutive_no_new = 0

            # Check if Google Maps has a "Search this area" button to expand boundaries
            if consecutive_no_new in [3, 6, 10]:
                try:
                    search_area_btn = maps_page.locator('button:has-text("Search this area"), button[aria-label*="Search this area"], button.DgHppc').first
                    if await search_area_btn.is_visible(timeout=600):
                        emit_event("log", "🗺️ Clicking 'Search this area' to reload surrounding area shops...")
                        await search_area_btn.click()
                        await maps_page.wait_for_timeout(2000)
                        consecutive_no_new = 0
                except Exception:
                    pass

            is_continuous = (scrape_all or max_results >= 9999)
            stagnant_limit = 24 if is_continuous else 14
            if consecutive_no_new >= stagnant_limit:
                emit_event("log", f"No new places loaded after {stagnant_limit} scrolls. All area shops captured.")
                break

            emit_event("log", f"📜 Scrolling Tab 1 feed down to load more shops (Pass {scroll_attempts})...")
            try:
                feed = maps_page.locator('div[role="feed"]').first
                if await feed.is_visible(timeout=1000):
                    try:
                        await feed.focus()
                        await maps_page.keyboard.press("PageDown")
                    except Exception:
                        pass
                    await feed.evaluate("el => { el.scrollBy(0, 3500); el.dispatchEvent(new Event('scroll', { bubbles: true })); }")
                    if count > 0:
                        try:
                            await links.last.scroll_into_view_if_needed(timeout=800)
                        except Exception:
                            pass
                    await maps_page.wait_for_timeout(600)
            except Exception:
                await maps_page.mouse.wheel(0, 2500)
                await maps_page.wait_for_timeout(600)

        if enable_maps and maps_page:
            emit_event("status", "Google Maps harvesting complete. Finalizing website & LinkedIn org inspections...")
        else:
            emit_event("status", f"Platform & Intelligence harvesting in progress ({', '.join(selected_platforms_list)})...")

        # Signal website worker that no more places will be added from Maps
        website_done_event.set()
        if worker_task and website_queue:
            try:
                remaining_web = website_queue.qsize()
                if remaining_web > 0:
                    emit_event("status", f"Processing {remaining_web} website email & anti-bot inspections...")
                web_timeout = max(300.0, max(len(scraped_places), remaining_web) * 20.0)
                await asyncio.wait_for(website_queue.join(), timeout=web_timeout)
            except Exception:
                pass
            worker_task.cancel()

        # Signal LinkedIn worker that all companies have been pushed and wait for org intelligence to complete
        linkedin_done_event.set()
        if linkedin_task and linkedin_queue:
            try:
                remaining_li = linkedin_queue.qsize()
                if remaining_li > 0:
                    emit_event("status", f"Processing {remaining_li} LinkedIn org intelligence inspections...")
                li_timeout = max(600.0, max(len(scraped_places), remaining_li) * 35.0)
                await asyncio.wait_for(linkedin_queue.join(), timeout=li_timeout)
            except Exception:
                pass
            linkedin_task.cancel()

        # Wait for Platform Scout Area & Proximity Harvester to finish
        if platform_task:
            try:
                plat_timeout = max(600.0, len(selected_platforms_list) * 240.0) if is_infinite else max(240.0, len(selected_platforms_list) * 90.0)
                await asyncio.wait_for(platform_task, timeout=plat_timeout)
            except Exception as e:
                emit_event("log", f"⚠️ Platform Harvester finished/timed out: {e}")

        # -------------------------------------------------------------
        # STEP 5: CROSS-PLATFORM ENTITY NORMALIZATION
        # Matches Google Maps leads against harvested platform listings
        # (Fresha, Airbnb, Yelp, TripAdvisor) and partitions 3 tables
        # -------------------------------------------------------------
        if enable_platform or get_tables_split_data()["counts"]["total_listings"] > 0:
            emit_event("status", "Running Cross-Platform Normalization...")
            emit_event("log", f"🔄 [Cross-Platform Normalization] Normalizing Google Maps leads with harvested Platform listings ({', '.join(selected_platforms_list)})...")
            norm_stats = normalize_all_platform_listings(city_context=search_location)
            emit_event("log", f"✅ [Cross-Platform Normalization] Finished! Merged {norm_stats.get('newly_matched', 0)} verified leads into Master Table ({norm_stats['counts']['master']} Master, {norm_stats['counts']['maps']} Maps Only, {norm_stats['counts']['platform']} Platform Only).")
            emit_event("tables_split", get_tables_split_data())

        stop_stream_event.set()
        if stream_task:
            try:
                await stream_task
            except Exception:
                pass

        if maps_page:
            try:
                await maps_page.wait_for_timeout(500)
            except Exception:
                pass

        if cdp_connected:
            # Leave the Google Maps / intelligence tabs open in the user's browser so they can inspect them!
            try:
                if hasattr(browser, "disconnect"):
                    await browser.disconnect()
            except Exception:
                pass
        elif visible_browser:
            emit_event("log", "👁️ Visible Chrome window left open for your review.")
        else:
            await context.close()

        emit_event("completed", {
            "count": len(scraped_places),
            "places": scraped_places
        })

