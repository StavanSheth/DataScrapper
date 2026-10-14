import urllib.parse
import urllib.request
import asyncio
import csv
import io
import json
import logging
import os
import subprocess
import sys
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from collections import deque
from database import (
    init_db,
    save_lead,
    update_lead_website_data,
    get_all_leads,
    get_lead_count,
    clear_leads,
    get_company_hierarchy,
    deduplicate_database,
    renumber_and_clean_database,
    get_platform_listings,
    get_platforms_config,
    save_platform_config,
    delete_platform_config,
    get_tables_split_data,
    normalize_all_platform_listings,
    update_lead,
    delete_lead,
    delete_leads_batch,
    batch_update_leads,
    get_lead_by_id,
    update_platform_listing,
    delete_platform_listing,
    delete_platform_listings_batch,
    batch_update_platform_listings,
    get_platform_listing_by_id,
    cleanup_orphan_screenshots,
    update_lead_linkedin_data,
    save_platform_listing,
)

# Force UTF-8 encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ScraperApp")

# Initialize database
init_db()

app = FastAPI(title="Mavon Leads & Org Intelligence Scraper")

# Enable full CORS for Chrome Extension, DevTools, and local origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets and screenshots directory
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
screenshots_dir = os.path.join(static_dir, "screenshots")
os.makedirs(screenshots_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/screenshots", StaticFiles(directory=screenshots_dir), name="screenshots")

# Global state
active_process: Optional[asyncio.subprocess.Process] = None
recent_logs: deque = deque(maxlen=300)
current_status: str = "Ready"
is_scraping: bool = False
active_websockets: List[WebSocket] = []
last_live_frame_maps: Optional[Dict[str, Any]] = None
last_live_frame_website: Optional[Dict[str, Any]] = None
last_live_frame_linkedin: Optional[Dict[str, Any]] = None
last_live_frame_platform: Optional[Dict[str, Any]] = None
extension_ws: Optional[WebSocket] = None

proximity_metrics: Dict[str, Any] = {
    "location": "",
    "query": "",
    "total_estimated": 0,
    "scraped_count": 0,
    "skipped_count": 0,
    "time_saved_sec": 0.0,
    "percent": 0,
    "platforms": {}
}

def add_log(message: str):
    recent_logs.append({"time": "", "message": message})

async def broadcast(event: Dict[str, Any]):
    for ws in list(active_websockets):
        try:
            await ws.send_json(event)
        except Exception:
            if ws in active_websockets:
                active_websockets.remove(ws)

tables_split_task: Optional[asyncio.Task] = None
tables_split_pending: bool = False

async def _debounced_tables_split():
    global tables_split_task, tables_split_pending
    try:
        await asyncio.sleep(0.5)
        if tables_split_pending:
            tables_split_pending = False
            tables_split_fresh = get_tables_split_data()
            await broadcast({"type": "tables_split", "data": tables_split_fresh})
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in debounced tables_split broadcast: {e}")
    finally:
        tables_split_task = None

def schedule_tables_split_broadcast():
    global tables_split_task, tables_split_pending
    tables_split_pending = True
    if tables_split_task is None or tables_split_task.done():
        tables_split_task = asyncio.create_task(_debounced_tables_split())

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "Mavon Leads & Org Intelligence"}

@app.websocket("/ws/extension")
async def extension_ws_endpoint(websocket: WebSocket):
    global extension_ws, last_live_frame_maps, last_live_frame_website, last_live_frame_linkedin, last_live_frame_platform
    await websocket.accept()
    extension_ws = websocket
    logger.info("🔌 Chrome Extension connected to /ws/extension")
    add_log("🔌 Chrome Extension connected: tabs will open directly in your active Chrome window!")
    await broadcast({"type": "log", "data": "🔌 Chrome Extension connected to active Chrome."})
    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                if data.get("type") == "LIVE_FRAME":
                    st = data.get("stream_type", "maps")
                    b64 = data.get("image_base64", "")
                    if st == "maps":
                        last_live_frame_maps = {"stream_type": "maps", "image_base64": b64, "tab": "maps", "image": f"data:image/jpeg;base64,{b64}"}
                        await broadcast({"type": "live_frame", "data": last_live_frame_maps})
                    elif st == "website":
                        last_live_frame_website = {"stream_type": "website", "image_base64": b64, "tab": "website", "image": f"data:image/jpeg;base64,{b64}"}
                        await broadcast({"type": "live_frame", "data": last_live_frame_website})
                    elif st == "linkedin":
                        last_live_frame_linkedin = {"stream_type": "linkedin", "image_base64": b64, "tab": "linkedin", "image": f"data:image/jpeg;base64,{b64}"}
                        await broadcast({"type": "live_frame", "data": last_live_frame_linkedin})
                    elif st == "platform":
                        last_live_frame_platform = {"stream_type": "platform", "image_base64": b64, "tab": "platform", "image": f"data:image/jpeg;base64,{b64}"}
                        await broadcast({"type": "live_frame", "data": last_live_frame_platform})
                elif data.get("type") == "SYNC_COOKIES":
                    cookies = data.get("cookies", [])
                    if cookies:
                        cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linkedin_cookies.json")
                        try:
                            with open(cookies_file, "w", encoding="utf-8") as f:
                                json.dump(cookies, f, indent=2)
                            logger.info(f"💾 Synced {len(cookies)} live LinkedIn session cookies from Extension to {cookies_file}")
                            add_log(f"🔑 Live LinkedIn session detected & saved ({len(cookies)} cookies synced from your Chrome).")
                        except Exception as e:
                            logger.error(f"Failed to save cookies: {e}")
            except Exception:
                pass
    except (WebSocketDisconnect, Exception):
        logger.info("Chrome Extension disconnected from /ws/extension")
    finally:
        if extension_ws == websocket:
            extension_ws = None

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        all_leads = get_all_leads()
        tables_data = get_tables_split_data()
        await websocket.send_json({
            "type": "init",
            "tables_split": tables_data,
            "is_scraping": is_scraping,
            "status": current_status,
            "proximity_metrics": proximity_metrics,
            "places": all_leads,
            "logs": list(recent_logs),
            "frame_maps": last_live_frame_maps,
            "frame_website": last_live_frame_website,
            "frame_linkedin": last_live_frame_linkedin,
            "frame_platform": last_live_frame_platform,
        })
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, Exception):
        if websocket in active_websockets:
            active_websockets.remove(websocket)

async def read_process_output(proc: asyncio.subprocess.Process):
    global is_scraping, current_status, active_process
    global last_live_frame_maps, last_live_frame_website, last_live_frame_linkedin, last_live_frame_platform
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="ignore").strip()
            if not line_str:
                continue

            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    event = json.loads(line_str)
                    etype = event.get("type")
                    edata = event.get("data")
                    if etype == "place_scraped":
                        save_lead(edata)
                    elif etype == "website_navigated":
                        pass
                    elif etype == "place_updated":
                        update_lead_website_data(
                            name=edata.get("name", ""),
                            address=edata.get("address", ""),
                            website=edata.get("website", ""),
                            email=edata.get("email", ""),
                            instagram=edata.get("instagram", ""),
                            facebook=edata.get("facebook", ""),
                            linkedin=edata.get("linkedin", ""),
                            twitter=edata.get("twitter", ""),
                            screenshot=edata.get("screenshot", ""),
                            bot_protection=edata.get("bot_protection", ""),
                            cookie_status=edata.get("cookie_status", ""),
                            website_status=edata.get("website_status", "found")
                        )
                    elif etype == "org_updated":
                        update_lead_linkedin_data(
                            name=edata.get("company", ""),
                            linkedin_url=edata.get("linkedin_url", ""),
                            employee_count=str(edata.get("employee_count", "0")),
                            linkedin_status="scraped",
                            org_scraped=1
                        )
                        add_log(f"🌳 [Org Intelligence] Mapped {edata.get('employee_count', 0)} employees for {edata.get('company', '')}")
                    elif etype == "platform_listing_found":
                        p_name = edata.get("platform", "Platform")
                        c_name = edata.get("company_name", "") or edata.get("name", "")
                        add_log(f"🟣 [Platform Directory] Verified {p_name} listing for {c_name}: {edata.get('rating', '')} ★")
                    elif etype == "proximity_total":
                        p = edata.get("platform", "Google Maps")
                        tot = int(edata.get("total", 0))
                        if "platforms" not in proximity_metrics:
                            proximity_metrics["platforms"] = {}
                        if p not in proximity_metrics["platforms"]:
                            proximity_metrics["platforms"][p] = {"total": tot, "scraped": 0, "skipped": 0, "percent": 0}
                        else:
                            proximity_metrics["platforms"][p]["total"] = tot
                        if edata.get("location"):
                            proximity_metrics["location"] = edata.get("location")
                        if edata.get("query"):
                            proximity_metrics["query"] = edata.get("query")
                        proximity_metrics["total_estimated"] = max(1, sum(x["total"] for x in proximity_metrics["platforms"].values()))

                    elif etype == "platform_progress":
                        p = edata.get("platform", "Platform Scout")
                        if "platforms" not in proximity_metrics:
                            proximity_metrics["platforms"] = {}
                        if p not in proximity_metrics["platforms"]:
                            proximity_metrics["platforms"][p] = {"total": edata.get("total", 0), "scraped": 0, "skipped": 0, "percent": 0}
                        proximity_metrics["platforms"][p]["scraped"] = edata.get("scraped", 0)
                        proximity_metrics["platforms"][p]["skipped"] = edata.get("skipped", 0)
                        proximity_metrics["platforms"][p]["total"] = max(edata.get("total", 0), proximity_metrics["platforms"][p]["total"])
                        proximity_metrics["platforms"][p]["percent"] = edata.get("percent", 0)

                        # Recalculate area rollup metrics
                        proximity_metrics["scraped_count"] = sum(x["scraped"] for x in proximity_metrics["platforms"].values())
                        proximity_metrics["skipped_count"] = sum(x["skipped"] for x in proximity_metrics["platforms"].values())
                        proximity_metrics["total_estimated"] = max(1, sum(x["total"] for x in proximity_metrics["platforms"].values()))
                        done = proximity_metrics["scraped_count"] + proximity_metrics["skipped_count"]
                        proximity_metrics["percent"] = min(100, round((done / proximity_metrics["total_estimated"]) * 100))
                        proximity_metrics["time_saved_sec"] = round(proximity_metrics["skipped_count"] * 3.5, 1)

                    elif etype == "proximity_progress":
                        p = "Google Maps"
                        if "platforms" not in proximity_metrics:
                            proximity_metrics["platforms"] = {}
                        if p not in proximity_metrics["platforms"]:
                            proximity_metrics["platforms"][p] = {"total": edata.get("total", 0), "scraped": 0, "skipped": 0, "percent": 0}
                        proximity_metrics["platforms"][p]["scraped"] = edata.get("scraped", 0)
                        proximity_metrics["platforms"][p]["skipped"] = edata.get("skipped", 0)
                        proximity_metrics["platforms"][p]["total"] = max(edata.get("total", 0), proximity_metrics["platforms"][p]["total"])
                        proximity_metrics["platforms"][p]["percent"] = edata.get("percent", 0)

                        # Recalculate area rollup metrics
                        proximity_metrics["scraped_count"] = sum(x["scraped"] for x in proximity_metrics["platforms"].values())
                        proximity_metrics["skipped_count"] = sum(x["skipped"] for x in proximity_metrics["platforms"].values())
                        proximity_metrics["total_estimated"] = max(1, sum(x["total"] for x in proximity_metrics["platforms"].values()))
                        done = proximity_metrics["scraped_count"] + proximity_metrics["skipped_count"]
                        proximity_metrics["percent"] = min(100, round((done / proximity_metrics["total_estimated"]) * 100))
                        proximity_metrics["time_saved_sec"] = round(proximity_metrics["skipped_count"] * 3.5, 1)

                    elif etype == "lead_skipped":
                        p = edata.get("platform", "Google Maps")
                        if "platforms" in proximity_metrics and p in proximity_metrics["platforms"]:
                            proximity_metrics["platforms"][p]["skipped"] += 1
                        proximity_metrics["skipped_count"] += 1
                        proximity_metrics["time_saved_sec"] = round(proximity_metrics["skipped_count"] * 3.5, 1)
                        add_log(f"⏭️ [Skipped In DB] {edata.get('name', 'Shop')} already in DB. Bypassed crawl ({proximity_metrics['time_saved_sec']}s saved).")
                    elif etype == "linkedin_navigated":
                        pass
                    elif etype == "platform_navigated":
                        pass
                    elif etype == "status":
                        current_status = str(edata)
                    elif etype == "log":
                        add_log(str(edata))
                    elif etype == "live_frame":
                        tab = edata.get("tab")
                        if tab == "platform" or edata.get("is_platform"):
                            last_live_frame_platform = edata
                        elif tab == "linkedin" or edata.get("is_linkedin"):
                            last_live_frame_linkedin = edata
                        elif tab == "website" or edata.get("is_website"):
                            last_live_frame_website = edata
                        else:
                            last_live_frame_maps = edata
                    await broadcast(event)
                    if etype in ["place_scraped", "place_updated", "org_updated", "platform_listing_found"]:
                        schedule_tables_split_broadcast()
                except Exception:
                    add_log(line_str)
            else:
                add_log(line_str)
    except Exception as e:
        logger.error(f"Error reading process stdout: {e}")
    finally:
        await proc.wait()
        is_scraping = False
        current_status = "Finished"
        active_process = None
        if tables_split_task and not tables_split_task.done():
            tables_split_task.cancel()
        tables_split_fresh = get_tables_split_data()
        await broadcast({"type": "tables_split", "data": tables_split_fresh})
        add_log("🏁 Scraping session finished. All places and org hierarchies saved to database.")
        await broadcast({"type": "status", "data": "Finished"})
        await broadcast({"type": "job_finished", "data": {"total": get_lead_count()}})


@app.get("/api/proximity-stats")
async def get_proximity_stats():
    return {
        "status": "running" if is_scraping else "idle",
        **proximity_metrics
    }

@app.post("/api/normalize")
async def manual_normalize_endpoint():
    stats = normalize_all_platform_listings()
    tables_fresh = get_tables_split_data()
    await broadcast({"type": "tables_split", "data": tables_fresh})
    await broadcast({"type": "log", "data": f"🔄 [Cross-Platform Normalization] Merged {stats.get('newly_matched', 0)} verified leads into Master Table ({stats['counts']['master']} Master, {stats['counts']['maps']} Maps Only, {stats['counts']['platform']} Platform Only)."})
    return {"status": "ok", "stats": stats, "tables_split": tables_fresh}

@app.post("/api/start")
async def start_scraping(payload: Dict[str, Any]):
    global active_process, is_scraping, recent_logs, current_status
    global last_live_frame_maps, last_live_frame_website, last_live_frame_linkedin, last_live_frame_platform
    if is_scraping and active_process and active_process.returncode is None:
        return {"status": "already_running", "count": get_lead_count()}

    query = payload.get("query", "").strip()
    scrape_all = bool(payload.get("scrape_all", False))
    if not query:
        query = "shops"

    max_results = int(payload.get("max_results", 20))
    visible_browser = bool(payload.get("visible_browser", True))
    extract_emails = bool(payload.get("extract_emails", True))
    lat = payload.get("lat")
    lon = payload.get("lon")
    zoom = int(payload.get("zoom", 14))
    radius_km = float(payload.get("radius_km", 5.0))
    enable_maps = bool(payload.get("enable_maps", True))
    enable_website = bool(payload.get("enable_website", True))
    enable_linkedin = bool(payload.get("enable_linkedin", True))
    enable_platform = bool(payload.get("enable_platform", True))
    raw_platforms = payload.get("platforms", [])
    if isinstance(raw_platforms, list) and raw_platforms:
        platforms_list = [str(p).strip() for p in raw_platforms if str(p).strip()]
    else:
        platforms_list = [str(payload.get("platform_name", "Fresha")).strip()]
    platform_name = platforms_list[0] if platforms_list else "Fresha"
    platforms_str = ",".join(platforms_list)
    platform_custom_url = str(payload.get("platform_custom_url", "")).strip()
    dedup_area = bool(payload.get("dedup_area", True))
    skip_existing_db = bool(payload.get("skip_existing_db", False))

    init_plats = {}
    if enable_maps:
        init_plats["Google Maps"] = {"total": max_results if not scrape_all else 120, "scraped": 0, "skipped": 0, "percent": 0}
    if enable_platform:
        for p in platforms_list:
            init_plats[p] = {"total": 0, "scraped": 0, "skipped": 0, "percent": 0}

    proximity_metrics["location"] = payload.get("location", "") or query
    proximity_metrics["query"] = query
    proximity_metrics["platforms"] = init_plats
    proximity_metrics["total_estimated"] = sum(x["total"] for x in init_plats.values()) if init_plats else (max_results if not scrape_all else 120)
    proximity_metrics["scraped_count"] = 0
    proximity_metrics["skipped_count"] = 0
    proximity_metrics["time_saved_sec"] = 0.0
    proximity_metrics["percent"] = 0

    recent_logs.clear()
    last_live_frame_maps = None
    last_live_frame_website = None
    last_live_frame_linkedin = None
    last_live_frame_platform = None
    is_scraping = True
    current_status = "Opening Chrome window on screen..."
    agents_desc = []
    if enable_maps: agents_desc.append("Maps")
    if enable_website: agents_desc.append("Website")
    if enable_linkedin: agents_desc.append("LinkedIn")
    if enable_platform: agents_desc.append(f"Platform ({platform_name})")
    active_str = " + ".join(agents_desc) if agents_desc else "None"
    add_log(f"🚀 Launching Live Chrome Agents [{active_str}] for: '{query}' (Radius: {radius_km}km, Continuous: {scrape_all})")

    sub_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner_scraper.py"),
        "--query", query,
        "--max", str(max_results),
        "--radius-km", str(radius_km),
    ]
    if scrape_all:
        cmd.append("--scrape-all")
    if visible_browser:
        cmd.append("--visible")
    if extract_emails:
        cmd.append("--extract-emails")
    if lat is not None:
        cmd.extend(["--lat", str(lat)])
    if lon is not None:
        cmd.extend(["--lon", str(lon)])
    cmd.extend(["--zoom", str(zoom)])

    if enable_maps:
        cmd.append("--enable-maps")
    else:
        cmd.append("--no-maps")

    if enable_website:
        cmd.append("--enable-website")
    else:
        cmd.append("--no-website")

    if enable_linkedin:
        cmd.append("--enable-linkedin")
    else:
        cmd.append("--no-linkedin")

    if enable_platform:
        cmd.append("--enable-platform")
        cmd.extend(["--platform-name", platform_name])
        cmd.extend(["--platforms", platforms_str])
        if platform_custom_url:
            cmd.extend(["--platform-custom-url", platform_custom_url])
    else:
        cmd.append("--no-platform")

    if dedup_area:
        cmd.append("--dedup-area")
    else:
        cmd.append("--no-dedup-area")

    if skip_existing_db:
        cmd.append("--skip-existing-db")

    try:
        pass

        active_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=sub_env,
            limit=10 * 1024 * 1024,
        )
        asyncio.create_task(read_process_output(active_process))
        return {"status": "started", "query": query, "scrape_all": scrape_all}
    except Exception as e:
        is_scraping = False
        current_status = "Failed to launch"
        logger.error(f"Failed to start scraper process: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start scraper process: {e}")

@app.post("/api/start-companies")
async def start_companies_scraping(payload: Dict[str, Any]):
    global active_process, is_scraping, recent_logs, current_status
    global last_live_frame_maps, last_live_frame_website, last_live_frame_linkedin, last_live_frame_platform
    if is_scraping and active_process and active_process.returncode is None:
        return {"status": "already_running", "count": get_lead_count()}

    companies = payload.get("companies", "").strip()
    if not companies:
        raise HTTPException(status_code=400, detail="Please provide company name(s).")

    visible_browser = bool(payload.get("visible_browser", True))

    recent_logs.clear()
    last_live_frame_maps = None
    last_live_frame_website = None
    last_live_frame_linkedin = None
    is_scraping = True
    current_status = "Launching Tab 3 for Standalone LinkedIn Org Harvester..."
    add_log(f"🏢 Launching Standalone LinkedIn Org Harvester for: '{companies}'")

    sub_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner_scraper.py"),
        "--standalone-companies", companies,
    ]
    if visible_browser:
        cmd.append("--visible")

    try:
        active_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=sub_env,
            limit=10 * 1024 * 1024,
        )
        asyncio.create_task(read_process_output(active_process))
        return {"status": "started", "mode": "standalone_companies", "companies": companies}
    except Exception as e:
        is_scraping = False
        current_status = "Failed to launch"
        logger.error(f"Failed to start company scraper: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start company scraper: {e}")

@app.post("/api/stop")
async def stop_scraping():
    global active_process, is_scraping, current_status
    if active_process and active_process.returncode is None:
        try:
            active_process.terminate()
        except Exception:
            pass
        add_log("⏹️ Scraping stopped by user.")
        await broadcast({"type": "log", "data": "⏹️ Scraping stopped by user."})
        current_status = "Stopped"
        await broadcast({"type": "status", "data": "Stopped"})
        is_scraping = False
        return {"status": "stopping"}
    is_scraping = False
    return {"status": "idle"}

@app.get("/api/status")
async def get_status():
    leads = get_all_leads()
    tables_data = get_tables_split_data()
    return {
        "is_scraping": is_scraping,
        "status": current_status,
        "count": len(leads),
        "places": leads,
        "tables_split": tables_data,
        "logs": list(recent_logs),
        "frame_maps": last_live_frame_maps,
        "frame_website": last_live_frame_website,
        "frame_linkedin": last_live_frame_linkedin,
        "frame_platform": last_live_frame_platform,
        "live_frame": last_live_frame_maps or last_live_frame_website or last_live_frame_linkedin or last_live_frame_platform,
    }

@app.get("/api/leads")
async def get_leads():
    return get_all_leads()

@app.get("/api/leads/{name}/hierarchy")
async def get_lead_hierarchy(name: str):
    hierarchy = get_company_hierarchy(name)
    return hierarchy

@app.post("/api/clear")
async def clear_database():
    clear_leads()
    add_log("🗑️ Leads database cleared.")
    await broadcast({"type": "db_cleared"})
    return {"status": "cleared"}

@app.post("/api/cleanup-screenshots")
async def cleanup_screenshots_endpoint():
    deleted_count = cleanup_orphan_screenshots()
    add_log(f"🧹 Cleanup: Removed {deleted_count} orphaned screenshot files from disk.")
    await broadcast({"type": "log", "data": f"🧹 Cleanup: Removed {deleted_count} orphaned screenshot files from disk."})
    return {"status": "ok", "deleted_count": deleted_count}

@app.post("/api/save")
async def save_lead_endpoint(lead_data: Dict[str, Any]):
    name = str(lead_data.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Missing required field 'name'")
    
    saved = save_lead(lead_data)
    if saved:
        add_log(f"💾 Lead saved via Chrome Extension: {name}")
        await broadcast({"type": "place_scraped", "data": lead_data})
        await broadcast({"type": "log", "data": f"💾 Lead saved via Chrome Extension: {name}"})
        return {"status": "success", "message": f"Lead '{name}' saved successfully", "lead": lead_data}
    else:
        raise HTTPException(status_code=400, detail="Failed to save lead: missing name or duplicate")

@app.post("/api/save-batch")
async def save_leads_batch_endpoint(payload: Dict[str, Any]):
    leads = payload.get("leads", [])
    if not isinstance(leads, list):
        raise HTTPException(status_code=400, detail="'leads' must be a list")
    
    saved_count = 0
    for lead in leads:
        if isinstance(lead, dict) and str(lead.get("name", "")).strip():
            if save_lead(lead):
                saved_count += 1
                await broadcast({"type": "place_scraped", "data": lead})
                
    add_log(f"💾 Saved {saved_count} leads via Extension batch sync.")
    await broadcast({"type": "log", "data": f"💾 Saved {saved_count} leads via Extension batch sync."})
    return {"status": "success", "saved": saved_count, "total": len(leads)}

@app.post("/api/deduplicate")
async def trigger_deduplicate():
    merged = deduplicate_database()
    add_log(f"🧹 Database Deduplication: Merged {merged} duplicate leads & re-indexed sequentially.")
    await broadcast({"type": "log", "data": f"🧹 Database Deduplication: Merged {merged} duplicate leads & re-indexed sequentially."})
    leads = get_all_leads()
    await broadcast({"type": "init", "places": leads, "count": len(leads)})
    return {"status": "ok", "merged": merged, "total": len(leads), "places": leads}

@app.post("/api/renumber")
async def trigger_renumber():
    res = renumber_and_clean_database()
    leads = get_all_leads()
    add_log(f"🔢 Database Renumbered & Cleaned: {res.get('leads_renumbered', 0)} leads sequentially indexed (1..{len(leads)}).")
    await broadcast({"type": "log", "data": f"🔢 Database Renumbered & Cleaned: {res.get('leads_renumbered', 0)} leads sequentially indexed."})
    await broadcast({"type": "init", "places": leads, "count": len(leads)})
    return {"status": "ok", "info": res, "total": len(leads), "places": leads}

@app.get("/api/chrome/status")
@app.get("/api/chrome-status")
async def get_chrome_status():
    if extension_ws is not None:
        return {
            "active": True,
            "connected": True,
            "browser": "Chrome (Extension Connected)",
            "message": "Connected to active Chrome via Extension Bridge"
        }
    import socket
    def check_socket():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            res = s.connect_ex(("127.0.0.1", 9222))
            s.close()
            return res == 0
        except Exception:
            return False

    is_open = await asyncio.to_thread(check_socket)
    if not is_open:
        return {"active": False, "browser": None, "message": "Port 9222 not connected"}

    try:
        req = urllib.request.Request("http://localhost:9222/json/version")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            data = json.loads(resp.read().decode())
            return {
                "active": True,
                "browser": data.get("Browser", "Chrome"),
                "message": "Connected to active Chrome (Port 9222)"
            }
    except Exception:
        return {"active": False, "browser": None, "message": "Port 9222 not connected"}

@app.post("/api/chrome/launch")
async def launch_chrome_debug():
    chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_exe):
        chrome_exe = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_exe):
        raise HTTPException(status_code=404, detail="Google Chrome executable not found at standard path.")

    try:
        # Check if already active
        try:
            req = urllib.request.Request("http://localhost:9222/json/version")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                return {"status": "success", "message": "Chrome Port 9222 is already connected!"}
        except Exception:
            pass

        # Relaunch Chrome with port 9222 and session restore to preserve all real user accounts & logins
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
        await asyncio.sleep(1.0)
        cmd = f'start "" "{chrome_exe}" --remote-debugging-port=9222 --remote-allow-origins=* --restore-last-session --start-maximized "http://localhost:8080"'
        subprocess.Popen(cmd, shell=True)
        return {
            "status": "success",
            "message": "Chrome launched on Remote Debugging Port 9222 with all your logins, accounts, and tabs preserved!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch Chrome: {e}")

@app.get("/api/platform-listings")
async def get_all_platform_directory_listings(platform: Optional[str] = None, lead_id: Optional[int] = None):
    return get_platform_listings(platform=platform, lead_id=lead_id)

# ------------------------------------------------------------------------------
# Lead Mutations (Individual & Batch)
# ------------------------------------------------------------------------------

@app.delete("/api/leads/{lead_id}")
async def delete_single_lead(lead_id: int):
    lead = get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead ID {lead_id} not found")
    name = lead.get("name", f"Lead #{lead_id}")
    success = delete_lead(lead_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete lead")
    
    add_log(f"🗑️ Deleted lead: {name} (ID: {lead_id})")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    await broadcast({"type": "init", "places": get_all_leads(), "count": len(get_all_leads())})
    return {"status": "success", "id": lead_id, "name": name}

@app.post("/api/leads/batch-delete")
async def batch_delete_leads_endpoint(payload: Dict[str, Any]):
    ids = payload.get("ids", [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="Missing or invalid 'ids' list")
    
    deleted = delete_leads_batch(ids)
    add_log(f"🗑️ Batch Deleted {deleted} leads.")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    await broadcast({"type": "init", "places": get_all_leads(), "count": len(get_all_leads())})
    return {"status": "success", "deleted_count": deleted}

@app.patch("/api/leads/{lead_id}")
@app.post("/api/leads/{lead_id}/edit")
async def edit_single_lead(lead_id: int, payload: Dict[str, Any]):
    lead = get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead ID {lead_id} not found")
    
    success = update_lead(lead_id, payload)
    if not success:
        raise HTTPException(status_code=400, detail="No valid fields to update or update failed")
    
    add_log(f"✏️ Updated lead #{lead_id} ({lead.get('name', '')})")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    await broadcast({"type": "init", "places": get_all_leads(), "count": len(get_all_leads())})
    updated_lead = get_lead_by_id(lead_id)
    return {"status": "success", "lead": updated_lead}

@app.post("/api/leads/batch-update")
async def batch_update_leads_endpoint(payload: Dict[str, Any]):
    ids = payload.get("ids", [])
    updates = payload.get("updates", {})
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="Missing or invalid 'ids' list")
    if not isinstance(updates, dict) or not updates:
        raise HTTPException(status_code=400, detail="Missing or invalid 'updates' dict")
    
    updated_count = batch_update_leads(ids, updates)
    add_log(f"🏷️ Batch updated {updated_count} leads.")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    await broadcast({"type": "init", "places": get_all_leads(), "count": len(get_all_leads())})
    return {"status": "success", "updated_count": updated_count}

# ------------------------------------------------------------------------------
# Platform Listing Mutations (Individual & Batch)
# ------------------------------------------------------------------------------

@app.delete("/api/platform-listings/{listing_id}")
async def delete_single_platform_listing(listing_id: int):
    listing = get_platform_listing_by_id(listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail=f"Listing ID {listing_id} not found")
    title = listing.get("title", f"Listing #{listing_id}")
    success = delete_platform_listing(listing_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete listing")
    
    add_log(f"🗑️ Deleted directory listing: {title} (ID: {listing_id})")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    return {"status": "success", "id": listing_id, "title": title}

@app.post("/api/platform-listings/batch-delete")
async def batch_delete_platform_listings_endpoint(payload: Dict[str, Any]):
    ids = payload.get("ids", [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="Missing or invalid 'ids' list")
    
    deleted = delete_platform_listings_batch(ids)
    add_log(f"🗑️ Batch Deleted {deleted} platform listings.")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    return {"status": "success", "deleted_count": deleted}

@app.patch("/api/platform-listings/{listing_id}")
@app.post("/api/platform-listings/{listing_id}/edit")
async def edit_single_platform_listing(listing_id: int, payload: Dict[str, Any]):
    listing = get_platform_listing_by_id(listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail=f"Listing ID {listing_id} not found")
    
    success = update_platform_listing(listing_id, payload)
    if not success:
        raise HTTPException(status_code=400, detail="No valid fields to update or update failed")
    
    add_log(f"✏️ Updated platform listing #{listing_id} ({listing.get('title', '')})")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    updated_listing = get_platform_listing_by_id(listing_id)
    return {"status": "success", "listing": updated_listing}

@app.post("/api/platform-listings/batch-update")
async def batch_update_platform_listings_endpoint(payload: Dict[str, Any]):
    ids = payload.get("ids", [])
    updates = payload.get("updates", {})
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="Missing or invalid 'ids' list")
    if not isinstance(updates, dict) or not updates:
        raise HTTPException(status_code=400, detail="Missing or invalid 'updates' dict")
    
    updated_count = batch_update_platform_listings(ids, updates)
    add_log(f"🏷️ Batch updated {updated_count} platform listings.")
    await broadcast({"type": "tables_split", "data": get_tables_split_data()})
    return {"status": "success", "updated_count": updated_count}

# ------------------------------------------------------------------------------
# 3-Table Situated CSV and JSON Exports
# ------------------------------------------------------------------------------

@app.get("/api/export/csv")
async def export_csv(request: Request, table: str = "all", ids: Optional[str] = None):
    split_data = get_tables_split_data()
    master_leads = split_data.get("master_leads", [])
    maps_leads = split_data.get("unmatched_maps", [])
    platform_listings = split_data.get("unmatched_platform", [])
    website_leads = split_data.get("website_leads", [])
    linkedin_leads = split_data.get("linkedin_leads", [])

    selected_ids = None
    if ids:
        selected_ids = set()
        for i in ids.split(","):
            i = i.strip()
            if i.isdigit():
                selected_ids.add(int(i))

    if selected_ids is not None:
        master_leads = [m for m in master_leads if m.get("id") in selected_ids]
        maps_leads = [m for m in maps_leads if m.get("id") in selected_ids]
        platform_listings = [p for p in platform_listings if p.get("id") in selected_ids]
        website_leads = [w for w in website_leads if w.get("id") in selected_ids]
        linkedin_leads = [l for l in linkedin_leads if l.get("id") in selected_ids]

    table_mode = table.lower().strip()
    export_master = (table_mode in ["all", "master"])
    export_maps = (table_mode in ["all", "maps"])
    export_website = (table_mode in ["all", "website"])
    export_linkedin = (table_mode in ["all", "linkedin"])
    export_platform = (table_mode in ["all", "platform"])

    if table_mode == "master":
        filename = "master_normalized_leads.csv"
    elif table_mode == "maps":
        filename = "google_maps_leads.csv"
    elif table_mode == "website":
        filename = "website_inspector_leads.csv"
    elif table_mode == "linkedin":
        filename = "linkedin_harvester_leads.csv"
    elif table_mode == "platform":
        filename = "platform_directory_listings.csv"
    else:
        filename = "all_5_tables_complete_export.csv"

    total_rows = (len(master_leads) if export_master else 0) + \
                 (len(maps_leads) if export_maps else 0) + \
                 (len(website_leads) if export_website else 0) + \
                 (len(linkedin_leads) if export_linkedin else 0) + \
                 (len(platform_listings) if export_platform else 0)

    if total_rows == 0:
        raise HTTPException(status_code=404, detail="No scraped data available to export for requested selection.")

    base_url = str(request.base_url).rstrip("/")
    output = io.StringIO()

    fieldnames = [
        "table_partition", "id", "name_or_title", "status_tag", "platform_source", "category",
        "phone", "email", "address", "rating", "reviews_count", "price_info",
        "website_url", "booking_url", "listing_url", "bot_security", "cookie_status",
        "employee_count", "instagram", "facebook", "linkedin", "twitter",
        "screenshot_url", "screenshot_file_path", "created_at"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    def format_lead_row(lead: Dict[str, Any], partition_name: str) -> Dict[str, Any]:
        screen_val = (lead.get("screenshot") or "").strip()
        screen_url = ""
        screen_path = ""
        if screen_val and screen_val != "N/A":
            clean_rel = screen_val if screen_val.startswith("/") else f"/{screen_val}"
            screen_url = f"{base_url}{clean_rel}"
            file_name = clean_rel.replace("/screenshots/", "")
            screen_path = os.path.abspath(os.path.join(screenshots_dir, file_name))

        plat_source = "Google Maps"
        if lead.get("platform_name") and lead.get("platform_name") != "N/A":
            plat_source = f"Google Maps + {lead.get('platform_name')}"

        tag = lead.get("status_tag") or lead.get("maps_status") or "Captured"

        return {
            "table_partition": partition_name,
            "id": lead.get("id", ""),
            "name_or_title": lead.get("name", ""),
            "status_tag": tag,
            "platform_source": plat_source,
            "category": lead.get("category", ""),
            "phone": lead.get("phone", ""),
            "email": lead.get("email", ""),
            "address": lead.get("address", ""),
            "rating": lead.get("rating", ""),
            "reviews_count": lead.get("reviews", ""),
            "price_info": lead.get("price", ""),
            "website_url": lead.get("website", ""),
            "booking_url": lead.get("booking_url", ""),
            "listing_url": lead.get("maps_url", ""),
            "bot_security": lead.get("bot_protection", ""),
            "cookie_status": lead.get("cookie_status", ""),
            "employee_count": lead.get("employee_count", ""),
            "instagram": lead.get("instagram", ""),
            "facebook": lead.get("facebook", ""),
            "linkedin": lead.get("linkedin", ""),
            "twitter": lead.get("twitter", ""),
            "screenshot_url": screen_url,
            "screenshot_file_path": screen_path,
            "created_at": lead.get("created_at", "")
        }

    def format_platform_row(item: Dict[str, Any], partition_name: str) -> Dict[str, Any]:
        screen_val = (item.get("screenshot") or "").strip()
        screen_url = ""
        screen_path = ""
        if screen_val and screen_val != "N/A":
            clean_rel = screen_val if screen_val.startswith("/") else f"/{screen_val}"
            screen_url = f"{base_url}{clean_rel}"
            file_name = clean_rel.replace("/screenshots/", "")
            screen_path = os.path.abspath(os.path.join(screenshots_dir, file_name))

        return {
            "table_partition": partition_name,
            "id": item.get("id", ""),
            "name_or_title": item.get("title", ""),
            "status_tag": "Verified Listing",
            "platform_source": item.get("platform", ""),
            "category": item.get("category", ""),
            "phone": item.get("phone", ""),
            "email": "",
            "address": item.get("address", ""),
            "rating": item.get("rating", ""),
            "reviews_count": item.get("reviews_count", ""),
            "price_info": item.get("price_info", ""),
            "website_url": item.get("url", ""),
            "booking_url": item.get("booking_url", ""),
            "listing_url": item.get("url", ""),
            "bot_security": "N/A",
            "cookie_status": "N/A",
            "employee_count": "",
            "instagram": "",
            "facebook": "",
            "linkedin": "",
            "twitter": "",
            "screenshot_url": screen_url,
            "screenshot_file_path": screen_path,
            "created_at": item.get("created_at", "")
        }

    # Partition 1: Master Normalized Leads
    if export_master and master_leads:
        for row in master_leads:
            writer.writerow(format_lead_row(row, "Table 1: Master Normalized Leads"))

    # Partition 2: Google Maps Leads
    if export_maps and maps_leads:
        for row in maps_leads:
            writer.writerow(format_lead_row(row, "Table 2: Google Maps Leads"))

    # Partition 3: Website Inspector Leads
    if export_website and website_leads:
        for row in website_leads:
            writer.writerow(format_lead_row(row, "Table 3: Website Inspector Leads"))

    # Partition 4: LinkedIn Harvester Leads
    if export_linkedin and linkedin_leads:
        for row in linkedin_leads:
            writer.writerow(format_lead_row(row, "Table 4: LinkedIn Harvester Leads"))

    # Partition 5: Platform Directory Listings
    if export_platform and platform_listings:
        for row in platform_listings:
            writer.writerow(format_platform_row(row, "Table 5: Platform Directory Listings"))

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@app.get("/api/export/json")
async def export_json(request: Request, table: str = "all", ids: Optional[str] = None):
    split_data = get_tables_split_data()
    master_leads = split_data.get("master_leads", [])
    maps_leads = split_data.get("unmatched_maps", [])
    platform_listings = split_data.get("unmatched_platform", [])

    selected_ids = None
    if ids:
        selected_ids = set()
        for i in ids.split(","):
            i = i.strip()
            if i.isdigit():
                selected_ids.add(int(i))

    if selected_ids is not None:
        master_leads = [m for m in master_leads if m.get("id") in selected_ids]
        maps_leads = [m for m in maps_leads if m.get("id") in selected_ids]
        platform_listings = [p for p in platform_listings if p.get("id") in selected_ids]

    table_mode = table.lower().strip()
    if table_mode == "master":
        content = master_leads
        filename = "master_normalized_leads.json"
    elif table_mode == "maps":
        content = maps_leads
        filename = "google_maps_leads.json"
    elif table_mode == "platform":
        content = platform_listings
        filename = "platform_directory_listings.json"
    else:
        content = {
            "summary": {
                "master_leads_count": len(master_leads),
                "google_maps_leads_count": len(maps_leads),
                "platform_directory_listings_count": len(platform_listings)
            },
            "master_normalized_leads": master_leads,
            "google_maps_leads": maps_leads,
            "platform_directory_listings": platform_listings
        }
        filename = "all_tables_complete_export.json"

    return JSONResponse(
        content=content,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/platforms")
async def list_platforms():
    return get_platforms_config()

@app.post("/api/platforms")
async def save_platform(payload: Dict[str, Any]):
    name = str(payload.get("name", "")).strip()
    url_template = str(payload.get("url_template", "")).strip()
    category = str(payload.get("category", "General")).strip()
    is_active = int(payload.get("is_active", 1))
    if not name or not url_template:
        raise HTTPException(status_code=400, detail="Name and URL Template are required.")
    pid = save_platform_config(name=name, url_template=url_template, category=category, is_active=is_active)
    add_log(f"⚙️ Directory Platform '{name}' saved.")
    await broadcast({"type": "platform_config_updated", "platforms": get_platforms_config()})
    return {"status": "success", "id": pid, "platforms": get_platforms_config()}

@app.delete("/api/platforms/{platform_id}")
async def delete_platform(platform_id: int):
    delete_platform_config(platform_id)
    add_log(f"🗑️ Directory Platform #{platform_id} deleted.")
    await broadcast({"type": "platform_config_updated", "platforms": get_platforms_config()})
    return {"status": "success", "platforms": get_platforms_config()}

@app.get("/api/tables-split")
async def get_tables_split_endpoint(limit: Optional[int] = None, offset: int = 0):
    data = get_tables_split_data(limit=limit, offset=offset)
    # Merge active real-time proximity metrics if scraper is running
    if "platforms" in proximity_metrics and proximity_metrics["platforms"]:
        if "queue_progress" not in data:
            data["queue_progress"] = {}
        if "platforms_breakdown" not in data["queue_progress"]:
            data["queue_progress"]["platforms_breakdown"] = {}
        for p, metrics in proximity_metrics["platforms"].items():
            tot = metrics.get("total", 0)
            scraped = metrics.get("scraped", 0)
            skipped = metrics.get("skipped", 0)
            pct = metrics.get("percent", 0)
            data["queue_progress"]["platforms_breakdown"][p] = {
                "name": p,
                "scraped": scraped,
                "skipped": skipped,
                "total": tot,
                "percent": pct
            }
        data["queue_progress"]["platform"] = {
            "total": proximity_metrics.get("total_estimated", 0),
            "scraped": proximity_metrics.get("scraped_count", 0),
            "skipped": proximity_metrics.get("skipped_count", 0),
            "percent": proximity_metrics.get("percent", 0)
        }
    return data

@app.get("/api/leads/view/{table_type}")
async def get_table_view(table_type: str, limit: int = 100, offset: int = 0, search: Optional[str] = None):
    """
    Dedicated high-speed modular endpoint for querying individual table views:
    table_type: 'master' | 'maps' | 'website' | 'linkedin' | 'platform'
    """
    data = get_tables_split_data()
    key_map = {
        "master": "master_leads",
        "maps": "unmatched_maps",
        "website": "website_leads",
        "linkedin": "linkedin_leads",
        "platform": "unmatched_platform"
    }
    target_key = key_map.get(table_type.lower(), "unmatched_maps")
    rows = data.get(target_key, [])
    if search:
        s_lower = search.strip().lower()
        rows = [r for r in rows if s_lower in str(r.get("name", "") or r.get("title", "")).lower() or s_lower in str(r.get("address", "")).lower() or s_lower in str(r.get("category", "")).lower()]
    total_count = len(rows)
    paginated_rows = rows[offset:offset + limit]
    return {
        "status": "success",
        "table": table_type,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "rows": paginated_rows
    }

@app.get("/", response_class=FileResponse)
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Mavon Leads & Org Intelligence on http://localhost:{port}")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
