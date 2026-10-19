"""
DataScrapper Modular API Server.
Coordinates HTTP REST endpoints, WebSocket streams, and static dashboard assets.
Runs natively without Docker.
"""
import asyncio
import base64
import datetime
from collections import deque
import json
import logging
import os
import re
import subprocess
import sys
from typing import Dict, Any, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Setup project roots
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, BASE_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass

from packages.database.src.adapters.sqlite.connection import get_connection, DEFAULT_DB_PATH
from packages.database.src.repositories.employee_repository import (
    save_employees_batch,
    get_company_hierarchy,
    get_pending_linkedin_leads,
    get_employees_by_lead_id,
    clean_linkedin_url
)
from packages.database.src.repositories.platform_repository import (
    save_platform_listing,
    get_platform_listings,
    get_platform_listing_by_id,
    update_platform_listing,
    delete_platform_listing,
    delete_platform_listings_batch,
    batch_update_platform_listings,
    get_platforms_config,
    save_platform_config,
    delete_platform_config,
    get_cached_census_total,
    set_cached_census_total,
    is_platform_listing_already_scraped
)
from backend.src.datascrapper.modules.source_registry.platform_profiles import (
    PLATFORM_PROFILES,
    build_platform_area_url
)
from backend.src.datascrapper.modules.normalization.brand_cleaner import clean_brand_tokens

# UTF-8 and Windows event loop policy
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# Import Agent 4: Platform Directory Scout
from playwright.async_api import async_playwright
import importlib.util

agent_path = os.path.join(BASE_DIR, "agents/agents/directory-discovery/agent.py")
if os.path.exists(agent_path):
    spec = importlib.util.spec_from_file_location("directory_discovery_agent", agent_path)
    dir_agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dir_agent)
    platform_area_search_worker = dir_agent.platform_area_search_worker
else:
    platform_area_search_worker = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DataScrapperServer")

# Initialize SQLite database schema
def init_schema():
    schema_path = os.path.join(BASE_DIR, "database/migrations/sqlite/001_initial_schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            ddl = f.read()
        with get_connection() as conn:
            conn.executescript(ddl)
            conn.commit()
    logger.info("Database schema initialized.")

init_schema()

app = FastAPI(title="DataScrapper Modular Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and Screenshot paths
static_dir = os.path.join(BASE_DIR, "apps/web/static")
screenshots_dir = os.path.join(BASE_DIR, "data/storage/screenshots")
os.makedirs(screenshots_dir, exist_ok=True)

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/screenshots", StaticFiles(directory=screenshots_dir), name="screenshots")

# Real-Time WebSocket State
active_websockets: List[WebSocket] = []
extension_ws: Optional[WebSocket] = None
recent_logs = deque(maxlen=200)
current_status = "Ready"
is_scraping = False

proximity_metrics: Dict[str, Any] = {
    "location": "",
    "query": "",
    "total_estimated": 0,
    "scraped_count": 0,
    "skipped_count": 0,
    "percent": 0,
    "platforms": {}
}

async def broadcast(event: Dict[str, Any]):
    """Broadcasts event payload to all connected frontend clients."""
    for ws in list(active_websockets):
        try:
            await ws.send_json(event)
        except Exception:
            if ws in active_websockets:
                active_websockets.remove(ws)

def add_log(message: str, agent: str = "system"):
    """Appends to memory logs and broadcasts via WebSocket."""
    t_str = datetime.datetime.now().strftime("%H:%M:%S")
    clean_msg = str(message).strip()
    if not clean_msg:
        return
    entry = {"time": t_str, "message": clean_msg, "agent": agent}
    recent_logs.append(entry)
    logger.info(f"[{agent.upper()}] {clean_msg}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(broadcast({"type": "log", "agent": agent, "data": clean_msg, "time": t_str}))
    except Exception:
        pass

# ==============================================================================
# Health & Status Routes
# ==============================================================================

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "database": "connected",
        "active_clients": len(active_websockets),
        "extension_connected": extension_ws is not None
    }

@app.get("/api/status")
async def get_status():
    return {
        "status": current_status,
        "is_scraping": is_scraping,
        "extension_connected": extension_ws is not None,
        "active_clients": len(active_websockets)
    }

@app.get("/api/chrome/status")
@app.get("/api/chrome-status")
async def get_chrome_status():
    ext_active = (extension_ws is not None)
    return {
        "active": ext_active,
        "cdp_active": False,
        "is_primary": ext_active,
        "extension_active": ext_active,
        "browser": "This Chrome (Extension Active)" if ext_active else None,
        "message": "Connected directly to your active Chrome profile via Extension!" if ext_active else "Chrome not connected."
    }

@app.get("/api/extension/download")
async def download_extension():
    zip_path = os.path.join(BASE_DIR, "apps/extension/dist/datascrapper-extension-v3.0.0.zip")
    if os.path.exists(zip_path):
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="datascrapper-extension-v3.0.0.zip"
        )
    raise HTTPException(status_code=404, detail="Extension package not found")

@app.post("/api/job-finished")
async def job_finished_endpoint(payload: Optional[Dict[str, Any]] = None):
    global is_scraping, current_status
    is_scraping = False
    current_status = "Ready"
    await broadcast({"type": "status", "data": "Ready"})
    return {"status": "ok"}

@app.get("/api/tables-split")
async def get_tables_split_endpoint():
    listings = get_platform_listings()
    unmatched_platform = []
    for l in listings:
        p_row = dict(l)
        w_stat = str(p_row.get("website_status") or "").strip().lower()
        has_e = bool(p_row.get("email") and p_row.get("email") != "N/A")
        has_p = bool(p_row.get("phone") and p_row.get("phone") != "N/A")
        has_soc = bool(p_row.get("instagram") or p_row.get("facebook") or p_row.get("linkedin") or p_row.get("twitter") or p_row.get("whatsapp"))
        bot_p = str(p_row.get("bot_protection") or "Clean")
        if "Cloudflare" in bot_p or "Turnstile" in bot_p or "Captcha" in bot_p or "Challenge" in bot_p or "Denied" in bot_p:
            tag = "Bot Shield (Data Extracted)" if (has_e or has_soc) else "Bot Shield Active"
        elif w_stat == "contacts_found" or has_e or has_soc:
            tag = "Contacts Found"
        elif w_stat == "no_contacts" or w_stat == "clean":
            tag = "No Contacts Found"
        elif p_row.get("verified") == 1 or p_row.get("lead_id"):
            tag = "Master Matched"
        elif p_row.get("booking_url"):
            tag = "Booking Link Available"
        elif has_p:
            tag = "Phone Only"
        else:
            tag = "Directory Discovered"
        p_row["status_tag"] = tag
        p_row["name"] = p_row.get("title", "")
        p_row["platform_name"] = p_row.get("platform", "Platform")
        unmatched_platform.append(p_row)

    with get_connection() as conn:
        lead_rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        leads_list = [dict(r) for r in lead_rows]

    unmatched_maps = []
    website_leads = []
    linkedin_leads = []
    master_leads = []

    for l in leads_list:
        maps_link = str(l.get("maps_url", "") or "").strip()
        has_real_maps = bool(maps_link and ("google.com/maps" in maps_link or "goo.gl/maps" in maps_link or "maps.app.goo.gl" in maps_link))
        if has_real_maps:
            m_row = dict(l)
            has_w = bool(m_row.get("website") and str(m_row.get("website")).strip() != "N/A")
            has_p = bool(m_row.get("phone") and str(m_row.get("phone")).strip() != "N/A")
            m_row["status_tag"] = "Full Contact (Web & Phone)" if (has_w and has_p) else ("Has Website" if has_w else ("Phone Only" if has_p else "Location Only"))
            unmatched_maps.append(m_row)
            if l.get("platform_verified") == 1:
                master_leads.append(m_row)
            if has_w:
                w_row = dict(l)
                w_row["status_tag"] = "Contacts Found" if (l.get("email") or l.get("instagram")) else "In Queue"
                website_leads.append(w_row)
            if l.get("linkedin"):
                li_row = dict(l)
                li_row["status_tag"] = "LinkedIn Found"
                linkedin_leads.append(li_row)

    return {
        "master_leads": master_leads,
        "unmatched_maps": unmatched_maps,
        "unmatched_platform": unmatched_platform,
        "website_leads": website_leads,
        "linkedin_leads": linkedin_leads,
        "counts": {
            "master": len(master_leads),
            "maps": len(unmatched_maps),
            "platform": len(unmatched_platform),
            "website": len(website_leads),
            "linkedin": len(linkedin_leads),
            "total_listings": len(unmatched_platform)
        },
        "queue_progress": {
            "platform": {"total": len(unmatched_platform)}
        }
    }

@app.post("/api/activate-tab")
async def activate_chrome_tab_endpoint(payload: Dict[str, Any]):
    target_tag = (payload.get("tab") or "").lower().strip()
    if extension_ws:
        try:
            await extension_ws.send_json({"type": "ACTIVATE_TAB", "tab": target_tag})
            return {"status": "success", "via": "extension", "tab": target_tag}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Extension not connected"}

# ==============================================================================
# WebSocket Endpoints
# ==============================================================================

@app.websocket("/ws")
async def websocket_dashboard(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        await websocket.send_json({"type": "status", "data": current_status})
        await websocket.send_json({"type": "logs_history", "data": list(recent_logs)})
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
                action = data.get("action")
                if action == "ping":
                    await websocket.send_json({"type": "pong"})
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

@app.websocket("/ws/extension")
async def websocket_extension_bridge(websocket: WebSocket):
    global extension_ws
    await websocket.accept()
    extension_ws = websocket
    add_log("🔌 Chrome Extension connected to bridge", agent="system")
    await broadcast({"type": "extension_status", "connected": True})
    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                evt_type = data.get("type")
                if evt_type == "LOG":
                    add_log(data.get("message", ""), agent=data.get("agent", "system"))
                elif evt_type == "STATUS":
                    global current_status
                    current_status = data.get("status", "Ready")
                    await broadcast({"type": "status", "data": current_status})
                elif evt_type == "HEARTBEAT":
                    await websocket.send_json({"type": "PONG"})
                elif evt_type == "LIVE_FRAME":
                    stream_type = data.get("stream_type") or "platform"
                    b64_img = data.get("image_base64", "")
                    if b64_img and not b64_img.startswith("data:"):
                        b64_img = "data:image/jpeg;base64," + b64_img
                    await broadcast({
                        "type": "live_frame",
                        "data": {
                            "tab": stream_type,
                            "stream_type": stream_type,
                            "is_platform": (stream_type == "platform"),
                            "image": b64_img
                        }
                    })
                elif evt_type == "PLATFORM_PROGRESS":
                    await broadcast({"type": "platform_progress", "data": data.get("data")})
                elif evt_type == "JOB_FINISHED":
                    global is_scraping
                    is_scraping = False
                    current_status = "Ready"
                    await broadcast({"type": "status", "data": "Ready"})
                    add_log(f"🏁 Finished! Chrome Extension completed platform scraping (Total: {data.get('total', 0)} listings).", agent="platform")
                elif evt_type == "PLATFORM_LISTING_FOUND":
                    p_data = data.get("data", {})
                    p_name = p_data.get("platform", "Fresha")
                    title = p_data.get("title", "").strip()
                    url = p_data.get("url", "").strip()
                    if title and url:
                        clean_brand = clean_brand_tokens(title)
                        phones_list = p_data.get("phones", [])
                        emails_list = p_data.get("emails", [])
                        socials_dict = p_data.get("socials", {}) if isinstance(p_data.get("socials"), dict) else {}
                        primary_phone = str(p_data.get("phone", "")).strip() or (phones_list[0] if phones_list else "")
                        primary_email = str(p_data.get("email", "")).strip() or (emails_list[0] if emails_list else "")

                        listing_data = {
                            "platform": p_name,
                            "title": title,
                            "clean_brand": clean_brand,
                            "category": p_data.get("category", "Salon"),
                            "url": url,
                            "booking_url": p_data.get("booking_url", url),
                            "rating": p_data.get("rating", 0.0),
                            "reviews_count": p_data.get("reviews_count", 0),
                            "price_info": p_data.get("price_info", ""),
                            "address": p_data.get("address", ""),
                            "website_status": p_data.get("website_status", "captured"),
                            "phone": primary_phone,
                            "email": primary_email,
                            "emails": emails_list,
                            "emails_json": json.dumps(emails_list),
                            "phones": phones_list,
                            "instagram": p_data.get("instagram", "") or socials_dict.get("instagram", ""),
                            "facebook": p_data.get("facebook", "") or socials_dict.get("facebook", ""),
                            "linkedin": p_data.get("linkedin", "") or socials_dict.get("linkedin", ""),
                            "twitter": p_data.get("twitter", "") or socials_dict.get("twitter", ""),
                            "youtube": p_data.get("youtube", "") or socials_dict.get("youtube", ""),
                            "tiktok": p_data.get("tiktok", "") or socials_dict.get("tiktok", ""),
                            "whatsapp": p_data.get("whatsapp", "") or socials_dict.get("whatsapp", ""),
                            "website": p_data.get("website", ""),
                            "bot_protection": p_data.get("bot_protection", "Clean"),
                            "cookie_status": p_data.get("cookie_status", "None")
                        }
                        lid = save_platform_listing(listing_data, db_path=DEFAULT_DB_PATH)
                        if lid:
                            listing_data["id"] = lid
                            listing_data["status_tag"] = "Contacts Found" if (primary_phone or primary_email) else "Directory Discovered"
                            await broadcast({"type": "platform_listing_found", "data": listing_data})
                            await broadcast({"type": "platform_listing_saved", "data": listing_data})
                            proximity_metrics["scraped_count"] += 1
                            await broadcast({"type": "proximity_update", "data": proximity_metrics})
                            add_log(f"💾 [Agent 4: Platform] Upserted listing: '{title}' ({p_name}) - Phone: {primary_phone or 'N/A'}", agent="platform")
            except Exception as pe:
                logger.debug(f"Extension WS parse error: {pe}")
    except WebSocketDisconnect:
        extension_ws = None
        add_log("⚠️ Chrome Extension disconnected", agent="system")
        await broadcast({"type": "extension_status", "connected": False})

# ==============================================================================
# LinkedIn & Employee Routes
# ==============================================================================

@app.get("/api/leads/pending-linkedin")
async def get_pending_linkedin_endpoint(limit: int = 50):
    leads = get_pending_linkedin_leads(limit=limit)
    return {"status": "success", "count": len(leads), "leads": leads}

@app.post("/api/save_employees")
async def save_employees_endpoint(payload: Dict[str, Any]):
    company_name = payload.get("company_name", "").strip()
    employees = payload.get("employees", [])
    lead_id = payload.get("lead_id")
    company_linkedin_url = payload.get("company_linkedin_url", "")
    linkedin_status = payload.get("linkedin_status", "")

    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")

    saved = save_employees_batch(
        company_name=company_name,
        employees=employees,
        lead_id=lead_id,
        company_linkedin_url=company_linkedin_url,
        linkedin_status=linkedin_status
    )
    add_log(f"👥 Saved {saved} employees for '{company_name}'", agent="linkedin")
    await broadcast({
        "type": "org_updated",
        "data": {"company": company_name, "employees_count": saved}
    })
    return {"status": "success", "company": company_name, "saved_count": saved}

@app.get("/api/leads/{name}/hierarchy")
async def get_company_hierarchy_endpoint(name: str):
    hierarchy = get_company_hierarchy(name)
    return {"status": "success", "hierarchy": hierarchy}

# ==============================================================================
# Platform Directory Routes
# ==============================================================================

@app.get("/api/platform-listings")
async def get_platform_listings_endpoint(
    platform: Optional[str] = None,
    lead_id: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0
):
    listings = get_platform_listings(platform=platform, lead_id=lead_id, limit=limit, offset=offset)
    return {
        "status": "success",
        "platform": platform or "all",
        "count": len(listings),
        "listings": listings
    }

@app.delete("/api/platform-listings/{listing_id}")
async def delete_platform_listing_endpoint(listing_id: int):
    success = delete_platform_listing(listing_id)
    return {"status": "success" if success else "error", "deleted_id": listing_id}

@app.post("/api/platform-listings/batch-delete")
async def batch_delete_platform_listings_endpoint(payload: Dict[str, Any]):
    listing_ids = payload.get("listing_ids", [])
    count = delete_platform_listings_batch(listing_ids)
    return {"status": "success", "deleted_count": count}

@app.patch("/api/platform-listings/{listing_id}")
async def edit_platform_listing_endpoint(listing_id: int, payload: Dict[str, Any]):
    success = update_platform_listing(listing_id, payload)
    return {"status": "success" if success else "error", "updated_id": listing_id}

@app.get("/api/platforms")
async def get_platforms_endpoint():
    platforms = get_platforms_config()
    return {"status": "success", "platforms": platforms}

@app.post("/api/platforms")
async def save_platform_endpoint(payload: Dict[str, Any]):
    name = payload.get("name", "").strip()
    url_template = payload.get("url_template", "").strip()
    category = payload.get("category", "General").strip()
    is_active = int(payload.get("is_active", 1))

    if not name or not url_template:
        raise HTTPException(status_code=400, detail="name and url_template are required")

    config_id = save_platform_config(name, url_template, category, is_active)
    return {"status": "success", "id": config_id, "name": name}

@app.delete("/api/platforms/{platform_id}")
async def delete_platform_endpoint(platform_id: int):
    success = delete_platform_config(platform_id)
    return {"status": "success" if success else "error", "deleted_id": platform_id}

@app.get("/api/proximity-stats")
async def get_proximity_stats():
    return {"status": "success", "metrics": proximity_metrics}

# ==============================================================================
# Leads & CRM Routes
# ==============================================================================

@app.get("/api/leads")
async def get_all_leads_endpoint(limit: Optional[int] = None, offset: int = 0):
    with get_connection() as conn:
        q = "SELECT * FROM leads ORDER BY id DESC"
        params = []
        if limit is not None:
            q += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        rows = conn.execute(q, params).fetchall()
        leads = [dict(r) for r in rows]
        tot = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        return {"status": "success", "total": tot, "count": len(leads), "leads": leads}

@app.post("/api/clear")
async def clear_database_endpoint():
    with get_connection() as conn:
        conn.execute("DELETE FROM leads;")
        conn.execute("DELETE FROM employees;")
        conn.execute("DELETE FROM platform_listings;")
        conn.commit()
    add_log("🗑️ Cleared all records from database", agent="system")
    await broadcast({"type": "database_cleared"})
    return {"status": "success", "message": "Database cleared"}

# ==============================================================================
# Scraper Start & Stop Controls
# ==============================================================================

active_scraper_task: Optional[asyncio.Task] = None
active_browser = None

async def run_platform_worker_task(payload: Dict[str, Any]):
    global is_scraping, current_status, active_browser
    raw_query = payload.get("query", "").strip()
    if not raw_query or raw_query.lower() in ["businesses", "all", "all businesses", "all shops", "all shops in area", "shop", "shops"]:
        category = "Salon"
    else:
        category = raw_query

    loc = payload.get("location", "").strip() or "London"
    max_res = int(payload.get("max_results", 15))
    plats = payload.get("platforms", [])
    if isinstance(plats, list) and plats:
        plats = [str(p).strip() for p in plats if str(p).strip()]
    else:
        plats = [str(payload.get("platform_name", "Fresha")).strip()]
    if not plats:
        plats = ["Fresha"]

    custom_url = payload.get("platform_custom_url", "")
    add_log(f"🟣 [Agent 4: Platform] Launching browser to scrape '{category}' in '{loc}' on {', '.join(plats)} (Target: {max_res})...", agent="platform")
    current_status = f"Searching {', '.join(plats)}: '{category}' in '{loc}'"
    await broadcast({"type": "status", "data": current_status})

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            active_browser = browser
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()

            async def capture_frame():
                try:
                    s_bytes = await page.screenshot(type="jpeg", quality=60)
                    b64 = "data:image/jpeg;base64," + base64.b64encode(s_bytes).decode()
                    await broadcast({
                        "type": "live_frame",
                        "data": {
                            "tab": "platform",
                            "stream_type": "platform",
                            "is_platform": True,
                            "image": b64
                        }
                    })
                except Exception:
                    pass

            def emit_fn(evt: str, data: Any):
                loop = asyncio.get_event_loop()
                if evt == "log":
                    add_log(str(data), agent="platform")
                elif evt == "status":
                    global current_status
                    current_status = str(data)
                    if loop.is_running():
                        asyncio.create_task(broadcast({"type": "status", "data": current_status}))
                elif evt == "platform_listing_saved":
                    if loop.is_running():
                        asyncio.create_task(broadcast({"type": "platform_listing_saved", "data": data}))
                        place_obj = {
                            "id": data.get("id"),
                            "name": data.get("title"),
                            "title": data.get("title"),
                            "clean_brand": data.get("clean_brand"),
                            "website": data.get("url"),
                            "url": data.get("url"),
                            "category": category,
                            "address": loc,
                            "rating": data.get("rating", 0.0),
                            "reviews": data.get("reviews_count", 0),
                            "platform": data.get("platform", "Fresha"),
                            "website_status": "captured"
                        }
                        asyncio.create_task(broadcast({"type": "place_scraped", "data": place_obj}))
                        proximity_metrics["scraped_count"] += 1
                        asyncio.create_task(broadcast({"type": "proximity_update", "data": proximity_metrics}))
                elif evt == "platform_navigated":
                    if loop.is_running():
                        asyncio.create_task(capture_frame())

            if platform_area_search_worker:
                total_saved = await platform_area_search_worker(
                    context=context,
                    platform_page=page,
                    selected_platforms=plats,
                    category=category,
                    location_name=loc,
                    max_results=max_res,
                    custom_url_pattern=custom_url,
                    emit_event_fn=emit_fn,
                    db_path=DEFAULT_DB_PATH
                )
                await capture_frame()
                add_log(f"✅ [Agent 4: Platform] Completed scrape run. Total saved: {total_saved}", agent="platform")
            else:
                add_log("❌ [Agent 4: Platform] platform_area_search_worker module not found", agent="platform")

            await browser.close()
            active_browser = None

    except asyncio.CancelledError:
        add_log("🛑 [Agent 4: Platform] Scrape task stopped by user.", agent="platform")
    except Exception as e:
        logger.error(f"Platform worker error: {e}", exc_info=True)
        add_log(f"❌ [Agent 4: Platform] Error: {e}", agent="platform")
    finally:
        is_scraping = False
        current_status = "Ready"
        await broadcast({"type": "status", "data": "Ready"})
        if active_browser:
            try:
                await active_browser.close()
            except Exception:
                pass
            active_browser = None

@app.post("/api/start")
async def start_scraper_endpoint(payload: Dict[str, Any]):
    global is_scraping, current_status, active_scraper_task, extension_ws
    raw_query = payload.get("query", "").strip()
    if not raw_query or raw_query.lower() in ["businesses", "all", "all businesses", "all shops", "all shops in area", "shop", "shops"]:
        category = "Salon"
    else:
        category = raw_query

    loc = payload.get("location", "").strip() or "London"
    max_res = int(payload.get("max_results", 15))
    plats = payload.get("platforms", [])
    if isinstance(plats, list) and plats:
        plats = [str(p).strip() for p in plats if str(p).strip()]
    else:
        plats = [str(payload.get("platform_name", "Fresha")).strip()]
    if not plats:
        plats = ["Fresha"]

    # Guardrail: Explicitly block Maps, Website, and LinkedIn agents in this setup
    requested_maps = payload.get("agent_maps", False)
    requested_website = payload.get("agent_website", False)
    requested_linkedin = payload.get("agent_linkedin", False)
    if requested_maps or requested_website or requested_linkedin:
        add_log("🚫 Blocked: Agent 1 (Maps), Agent 2 (Website), and Agent 3 (LinkedIn) are blocked. Running ONLY Agent 4: Platform Directory Scout.", agent="system")

    if extension_ws:
        plat_configs = []
        for p in plats:
            p_clean = p.strip()
            url = build_platform_area_url(p_clean, category, loc)
            plat_configs.append({"name": p_clean, "url": url})

        add_log(f"🟢 [Agent 4: Platform] Launching LIVE Chrome tab in front of you for '{category}' in '{loc}' on {', '.join(plats)} (Target: {max_res})...", agent="platform")
        current_status = f"Searching {', '.join(plats)}: '{category}' in '{loc}'"
        await broadcast({"type": "status", "data": current_status})

        cmd = {
            "action": "START_HARVESTER",
            "payload": {
                "enable_platform": True,
                "enable_maps": False,
                "enable_website": False,
                "enable_linkedin": False,
                "platforms": plat_configs,
                "platform_name": plats[0],
                "location": loc,
                "query": category,
                "max_results": max_res,
                "active_tab": True
            }
        }
        await extension_ws.send_json(cmd)
        is_scraping = True
        return {
            "status": "started",
            "mode": "extension_live",
            "query": category,
            "location": loc,
            "platforms": plats,
            "agents": {
                "maps": "blocked",
                "website": "blocked",
                "linkedin": "blocked",
                "platform": "active_in_chrome"
            }
        }

    if active_scraper_task and not active_scraper_task.done():
        return {"status": "already_running"}

    add_log("⚠️ Chrome Extension is not currently connected. Launching local fallback worker. Load the extension in Chrome for live visible tabs.", agent="platform")
    is_scraping = True
    active_scraper_task = asyncio.create_task(run_platform_worker_task(payload))

    return {
        "status": "started",
        "mode": "fallback_worker",
        "query": category,
        "agents": {
            "maps": "blocked",
            "website": "blocked",
            "linkedin": "blocked",
            "platform": "active"
        }
    }

@app.post("/api/start-companies")
async def start_companies_endpoint(payload: Optional[Dict[str, Any]] = None):
    raise HTTPException(
        status_code=403,
        detail="LinkedIn Agent (Agent 3) is blocked in this setup. Only Platform Directory Scout is permitted."
    )

@app.post("/api/start-website-list")
async def start_website_list_endpoint(payload: Optional[Dict[str, Any]] = None):
    raise HTTPException(
        status_code=403,
        detail="Website Agent (Agent 2) is blocked in 1_Linkedin_Platforms. Only Platform Directory Scout is permitted."
    )

@app.post("/api/start-maps")
async def start_maps_endpoint(payload: Optional[Dict[str, Any]] = None):
    raise HTTPException(
        status_code=403,
        detail="Google Maps Agent (Agent 1) is blocked in 1_Linkedin_Platforms. Only Platform Directory Scout is permitted."
    )

@app.post("/api/stop")
async def stop_scraper_endpoint():
    global is_scraping, current_status, active_scraper_task, active_browser, extension_ws
    is_scraping = False
    current_status = "Stopped"
    if extension_ws:
        try:
            await extension_ws.send_json({"action": "ABORT_HARVESTER"})
        except Exception:
            pass
    if active_scraper_task and not active_scraper_task.done():
        active_scraper_task.cancel()
    if active_browser:
        try:
            await active_browser.close()
        except Exception:
            pass
        active_browser = None
    add_log("🛑 Stopped collection pipeline", agent="system")
    await broadcast({"type": "status", "data": current_status})
    return {"status": "stopped"}

# ==============================================================================
# Root Dashboard Page
# ==============================================================================

@app.get("/")
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "DataScrapper API is running. UI index.html not found."}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8085))
    logger.info(f"Starting DataScrapper server on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
