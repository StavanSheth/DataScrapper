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
recent_logs: List[Dict[str, str]] = []
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
    global recent_logs
    recent_logs.append({"time": "", "message": message})
    if len(recent_logs) > 300:
        recent_logs = recent_logs[-300:]

async def broadcast(event: Dict[str, Any]):
    for ws in list(active_websockets):
        try:
            await ws.send_json(event)
        except Exception:
            if ws in active_websockets:
                active_websockets.remove(ws)

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
            "logs": recent_logs,
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
                        if extension_ws and edata.get("website") and str(edata.get("website")).startswith("http"):
                            asyncio.create_task(extension_ws.send_json({"action": "OPEN_SHOP_TAB", "payload": {"url": edata.get("website")}}))
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
                            cookie_status=edata.get("cookie_status", "")
                        )
                    elif etype == "org_updated":
                        # Emitted when Tab 3 finishes extracting LinkedIn hierarchy for a company
                        add_log(f"🌳 [Org Intelligence] Mapped {edata.get('employee_count', 0)} employees for {edata.get('company', '')}")
                    elif etype == "platform_listing_found":
                        # Emitted when Tab 4 discovers/matches a platform directory listing
                        add_log(f"🟣 [Platform Directory] Verified {edata.get('platform', '')} listing for {edata.get('name', '')}: {edata.get('rating', '')} ★")
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
                        if extension_ws and edata.get("url"):
                            asyncio.create_task(extension_ws.send_json({"action": "NAVIGATE_LINKEDIN", "payload": edata}))
                    elif etype == "platform_navigated":
                        if extension_ws and edata.get("url"):
                            asyncio.create_task(extension_ws.send_json({"action": "NAVIGATE_PLATFORM", "payload": edata}))
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
                        tables_split_fresh = get_tables_split_data()
                        await broadcast({"type": "tables_split", "data": tables_split_fresh})
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

    recent_logs = []
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
        if extension_ws:
            encoded_q = urllib.parse.quote_plus(query)
            search_u = f"https://www.google.com/maps/search/{encoded_q}?hl=en"
            if lat is not None and lon is not None:
                search_u = f"https://www.google.com/maps/search/{encoded_q}/@{lat},{lon},{zoom}z?hl=en"
            try:
                start_payload = {}
                if enable_maps:
                    start_payload["maps_url"] = search_u
                if enable_linkedin:
                    start_payload["linkedin_url"] = "https://www.linkedin.com/"
                if enable_platform:
                    p_target = (platform_name or "Fresha").lower().strip()
                    if "airbnb" in p_target:
                        start_payload["platform_url"] = "https://www.airbnb.com/"
                    elif "yelp" in p_target:
                        start_payload["platform_url"] = "https://www.yelp.com/"
                    elif "tripadvisor" in p_target:
                        start_payload["platform_url"] = "https://www.tripadvisor.com/"
                    elif "booking" in p_target:
                        start_payload["platform_url"] = "https://www.booking.com/"
                    elif "zomato" in p_target:
                        start_payload["platform_url"] = "https://www.zomato.com/"
                    elif "justdial" in p_target:
                        start_payload["platform_url"] = "https://www.justdial.com/"
                    elif "treatwell" in p_target:
                        start_payload["platform_url"] = "https://www.treatwell.com/"
                    elif "yellowpages" in p_target:
                        start_payload["platform_url"] = "https://www.yellowpages.com/"
                    elif "opentable" in p_target:
                        start_payload["platform_url"] = "https://www.opentable.com/"
                    elif platform_custom_url and "http" in platform_custom_url:
                        start_payload["platform_url"] = platform_custom_url.split("?")[0]
                    elif "." in p_target and " " not in p_target:
                        start_payload["platform_url"] = f"https://www.{p_target.replace('www.', '')}" if not p_target.startswith("http") else p_target
                    else:
                        start_payload["platform_url"] = "https://www.fresha.com/"

                await extension_ws.send_json({
                    "action": "START_HARVESTER",
                    "payload": start_payload
                })
                add_log("🔌 Chrome Extension: opened Tab 1 (Maps) and Tab 2 (LinkedIn) in active Chrome.")
            except Exception:
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

    recent_logs = []
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
        "logs": recent_logs,
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

@app.get("/api/export/csv")
async def export_csv(request: Request):
    leads = get_all_leads()
    if not leads:
        raise HTTPException(status_code=404, detail="No scraped data available to export.")

    base_url = str(request.base_url).rstrip("/")
    output = io.StringIO()
    fieldnames = [
        "id", "name", "category", "phone", "email", "instagram", "facebook",
        "linkedin", "twitter", "bot_protection", "cookie_status", "employee_count",
        "platform_name", "platform_url", "platform_rating", "platform_reviews",
        "booking_url", "platform_price", "platform_verified",
        "screenshot", "screenshot_url", "screenshot_file_path",
        "address", "hours", "price", "plus_code", "rating",
        "reviews", "website", "maps_url", "lat", "lon", "created_at"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in leads:
        filtered = {k: row.get(k, "") for k in fieldnames}
        screen_val = (row.get("screenshot") or "").strip()
        if screen_val and screen_val != "N/A":
            clean_rel = screen_val if screen_val.startswith("/") else f"/{screen_val}"
            filtered["screenshot"] = clean_rel
            filtered["screenshot_url"] = f"{base_url}{clean_rel}"
            file_name = clean_rel.replace("/screenshots/", "")
            filtered["screenshot_file_path"] = os.path.abspath(os.path.join(screenshots_dir, file_name))
        else:
            filtered["screenshot"] = ""
            filtered["screenshot_url"] = ""
            filtered["screenshot_file_path"] = ""
        writer.writerow(filtered)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_with_hierarchy.csv"},
    )

@app.get("/api/export/json")
async def export_json(request: Request):
    leads = get_all_leads()
    if not leads:
        raise HTTPException(status_code=404, detail="No scraped data available to export.")

    base_url = str(request.base_url).rstrip("/")
    for row in leads:
        screen_val = (row.get("screenshot") or "").strip()
        if screen_val and screen_val != "N/A":
            clean_rel = screen_val if screen_val.startswith("/") else f"/{screen_val}"
            row["screenshot"] = clean_rel
            row["screenshot_url"] = f"{base_url}{clean_rel}"
            file_name = clean_rel.replace("/screenshots/", "")
            row["screenshot_file_path"] = os.path.abspath(os.path.join(screenshots_dir, file_name))
        else:
            row["screenshot_url"] = ""
            row["screenshot_file_path"] = ""

    return JSONResponse(
        content=leads,
        headers={"Content-Disposition": "attachment; filename=leads_with_hierarchy.json"},
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
async def get_tables_split_endpoint():
    return get_tables_split_data()

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
