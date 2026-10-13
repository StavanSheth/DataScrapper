import argparse
import asyncio
import base64
import datetime
import json
import logging
import os
import re
import sys
import urllib.parse
import math
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from database import save_lead, save_employees_batch, classify_seniority, clean_domain, is_lead_in_db, save_platform_listing, get_platform_listings
from scrapers.antibot import (
    decode_cloudflare_email,
    detect_and_handle_cookies,
    attempt_turnstile_solve,
    detect_anti_bot_protection,
)

def calculate_haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS coordinates in kilometers."""
    R = 6371.0  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def radius_to_zoom(radius_km: float) -> int:
    """Calculates appropriate Google Maps viewport zoom level for the given radius."""
    if radius_km <= 1.5:
        return 16
    elif radius_km <= 3.5:
        return 15
    elif radius_km <= 7.0:
        return 14
    elif radius_km <= 15.0:
        return 13
    elif radius_km <= 30.0:
        return 12
    elif radius_km <= 45.0:
        return 11
    else:
        return 10

stop_stream_event = asyncio.Event()

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# Force UTF-8 on Windows stdout/stderr
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stderr)
logger = logging.getLogger("RunnerScraper")

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
JUNK_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".js", ".css", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3"
)
IGNORE_DOMAINS = (
    "sentry.io", "wixpress.com", "example.com", "schema.org", "google.com",
    "w3.org", "cloudflare.com", "gravatar.com", "polyfill.io", "doubleclick.net"
)

def emit_event(event_type: str, data: Any):
    try:
        msg = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
    except Exception as e:
        logger.error(f"Failed to emit event: {e}")

def clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\ue000-\uf8ff]", "", text)
    return " ".join(cleaned.split()).strip()

def get_screen_dimensions():
    screen_w, screen_h = 1920, 1080
    if sys.platform == "win32":
        try:
            import ctypes
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        except Exception:
            pass
    return screen_w, screen_h

def force_foreground_window():
    """Bring the active Chrome scraper window to foreground on Windows desktop."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        found_hwnds = []

        def enum_cb(hwnd, extra):
            if user32.IsWindowVisible(hwnd):
                cls_buff = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buff, 256)
                cls_name = cls_buff.value
                if "Chrome_WidgetWin" in cls_name:
                    length = user32.GetWindowTextLengthW(hwnd)
                    val = ""
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        val = buff.value
                    # Skip code editors (VS Code / Antigravity)
                    if "Visual Studio Code" not in val and "Antigravity" not in val:
                        found_hwnds.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        for hwnd in found_hwnds:
            try:
                # 1. Simulate ALT key to bypass Windows LockSetForegroundWindow restriction
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 2, 0)

                # 2. Attach thread input for seamless focus transfer
                current_thread_id = kernel32.GetCurrentThreadId()
                foreground_hwnd = user32.GetForegroundWindow()
                foreground_thread_id = user32.GetWindowThreadProcessId(foreground_hwnd, None)
                if current_thread_id != foreground_thread_id:
                    user32.AttachThreadInput(current_thread_id, foreground_thread_id, True)

                # 3. HWND_TOPMOST (-1) then HWND_NOTOPMOST (-2) trick: brings window to front of all apps
                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

                # 4. Show and maximize (keep full-screen maximized, never shrink/restore)
                user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)

                if current_thread_id != foreground_thread_id:
                    user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)
            except Exception:
                pass
    except Exception:
        pass

def extract_emails_from_text(html: str) -> List[str]:
    found = set()
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Standard mailto: links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                email_part = href.split(":", 1)[1].split("?")[0].strip()
                if email_part and "@" in email_part:
                    found.add(email_part.lower())

        # 2. Cloudflare Protected Emails (<span class="__cf_email__" data-cfemail="..."> or /email-protection#...)
        for el in soup.select('[data-cfemail], a[href*="/email-protection#"], span.__cf_email__'):
            cf_hex = el.get("data-cfemail", "")
            if not cf_hex and el.get("href"):
                cf_hex = el.get("href", "").split("#")[-1]
            if cf_hex:
                decoded = decode_cloudflare_email(cf_hex)
                if decoded and "@" in decoded and "." in decoded:
                    found.add(decoded.lower().strip())

        # 3. JSON-LD structured data schema
        for s in soup.find_all("script", type="application/ld+json"):
            if s.string:
                for match in EMAIL_REGEX.findall(s.string):
                    found.add(match.strip().lower())

        # 4. Standard RegEx pattern across page text
        for match in EMAIL_REGEX.findall(html):
            match = match.strip().lower()
            if any(match.endswith(ext) for ext in JUNK_EXTENSIONS):
                continue
            if any(bad in match for bad in IGNORE_DOMAINS):
                continue
            parts = match.split("@")
            if len(parts) == 2 and "." in parts[1] and len(parts[1].split(".")[-1]) >= 2:
                found.add(match)

        # 5. Obfuscated patterns like user [at] domain.com or user (at) domain.com
        obf_matches = re.findall(r'([a-zA-Z0-9_.+-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*([a-zA-Z0-9-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\.)\s*([a-zA-Z]{2,10})', html, re.I)
        for user, dom, tld in obf_matches:
            cand = f"{user}@{dom}.{tld}".lower()
            if not any(cand.endswith(ext) for ext in JUNK_EXTENSIONS) and not any(bad in cand for bad in IGNORE_DOMAINS):
                found.add(cand)

    except Exception:
        pass
    return sorted(list(found))

def clean_social_url(url: str) -> str:
    """Cleans tracking query parameters, hashes, and formats social URLs."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        return ""
    base = url.split("?")[0].split("#")[0].rstrip("/")
    return base

def extract_core_brand_name(name: str, city: str = "") -> str:
    """
    Extracts the clean parent brand/business name by stripping mall, branch,
    retail descriptor, and legal entity suffixes (e.g., 'Nike Factory Store Viviana Mall' -> 'Nike').
    """
    if not name:
        return ""
    # 1. Take part before explicit separators like ' - ', ' | ', ' @ ', '(', '['
    base = re.split(r'\s*[-–—|@]\s*|[(\[]', name)[0].strip()
    if not base or len(base) < 2:
        base = name.strip()

    # 2. Strip trailing punctuation
    base = re.sub(r'[\.,\-_;:\'\"]+$', '', base).strip()

    # 3. Strip legal entity suffixes from end
    legal_pat = r'\s+\b(?:pvt\.?\s*ltd\.?|private\s+limited|ltd\.?|llc|inc\.?|corp\.?|co\.?|corporation)\b\.?$'
    base = re.sub(legal_pat, '', base, flags=re.I).strip()

    # 4. Strip mall phrases with mall name, e.g. 'Viviana Mall', 'Inorbit Mall'
    mall_pat = r'\s+\b[A-Za-z0-9]+\s+(?:mall|plaza|centre|center|galleria|arcade)\b'
    base = re.sub(mall_pat, '', base, flags=re.I).strip()

    # 5. Strip retail phrases in middle/end
    retail_pat = r'\s+\b(?:factory\s+store|factory\s+outlet|flagship\s+store|retail\s+store)\b'
    base = re.sub(retail_pat, '', base, flags=re.I).strip()

    # 6. If city is provided, strip trailing city from end
    if city and len(city) >= 3:
        city_esc = re.escape(city.strip())
        base = re.sub(rf'\s+\b{city_esc}\b.*$', '', base, flags=re.I).strip()

    # 7. Standalone end suffixes
    end_suffix_pat = r'\s+\b(?:outlet|showroom|branch|mall|bazaar|supermarket|hypermarket)\b$'
    base = re.sub(end_suffix_pat, '', base, flags=re.I).strip()

    return base if len(base) >= 2 else name

clean_brand_tokens = extract_core_brand_name

def extract_brand_from_domain(url: str) -> str:
    """Extracts the brand name directly from the domain (e.g., 'https://superkicks.in' -> 'superkicks')."""
    if not url or not url.startswith("http"):
        return ""
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        netloc = re.sub(r'^(?:www\d?|m|shop|store)\.', '', netloc)
        parts = netloc.split('.')
        if len(parts) >= 2 and len(parts[0]) >= 3:
            return parts[0]
    except Exception:
        pass
    return ""

def extract_city_from_address(address: str) -> str:
    """Extracts city or locality from standard Google Maps address strings."""
    if not address or address == "N/A":
        return ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return ""
    candidates = [p for p in parts if not re.search(r'^\d+$', p)]
    if len(candidates) >= 2:
        for part in reversed(candidates[:-1]):
            clean_part = re.sub(r'\b[A-Z0-9]{2,4}\s+[A-Z0-9]{3}\b|\b\d{3,7}\b', '', part, flags=re.I).strip()
            tokens = clean_part.split()
            if 1 <= len(tokens) <= 2 and not any(t.lower() in ["india", "uk", "usa", "state", "road", "street", "st", "ave", "highway"] for t in tokens):
                return tokens[0]
    return ""

def verify_company_name_match(searched_name: str, result_title: str) -> bool:
    """
    Strictly verifies whether a candidate search result title or card text
    corresponds to the searched business brand, preventing unrelated companies from being matched.
    """
    if not searched_name or not result_title:
        return False

    clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', searched_name).lower()
    clean_title = re.sub(r'[^a-zA-Z0-9\s]', ' ', result_title).lower()

    if clean_search in clean_title or clean_title in clean_search:
        return True

    stop_words = {
        "ltd", "limited", "uk", "inc", "llc", "the", "and", "&", "co", "company",
        "shop", "store", "stores", "london", "official", "group", "holdings", "linkedin",
        "india", "international", "retail", "outlet"
    }
    search_tokens = [w for w in clean_search.split() if len(w) > 1]
    distinctive_tokens = [w for w in search_tokens if w not in stop_words]

    tokens_to_match = distinctive_tokens if distinctive_tokens else search_tokens
    if not tokens_to_match:
        return False

    title_words = set(clean_title.split())

    matched_count = 0
    for tok in tokens_to_match:
        if any(tok in tw or tw.startswith(tok) or (len(tok) > 3 and tok[:4] == tw[:4]) for tw in title_words):
            matched_count += 1

    ratio = matched_count / len(tokens_to_match)
    return ratio >= 0.5

def is_person_relevant_to_brand(brand: str, title: str, subtitle: str = "") -> bool:
    """Verifies that an extracted individual is affiliated with the target brand or role."""
    if not brand:
        return True
    combined = f"{title} {subtitle}".lower()
    clean_brand = re.sub(r'[^a-zA-Z0-9\s]', ' ', brand).lower().strip()
    brand_tokens = [t for t in clean_brand.split() if len(t) > 2 and t not in {"the", "and", "co", "ltd", "inc", "shop", "store"}]
    if not brand_tokens:
        return True
    return any(tok in combined for tok in brand_tokens)

def extract_socials_from_text(html: str) -> Dict[str, str]:
    """
    Extracts official social media profiles from HTML across:
    1. <a> href attributes
    2. JSON-LD structured data (<script type="application/ld+json">)
    3. <meta> tags (og:see_also, twitter:site, twitter:creator, etc.)
    4. Regex pattern matching across page source code.
    """
    socials = {"instagram": "", "facebook": "", "linkedin": "", "twitter": ""}
    if not html:
        return socials

    candidates = {
        "instagram": [],
        "facebook": [],
        "linkedin": [],
        "twitter": []
    }

    try:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Check all anchor tags
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            lower = href.lower()

            if "instagram.com/" in lower:
                candidates["instagram"].append(href)
            elif "facebook.com/" in lower:
                candidates["facebook"].append(href)
            elif "linkedin.com/" in lower:
                candidates["linkedin"].append(href)
            elif "twitter.com/" in lower or "x.com/" in lower:
                candidates["twitter"].append(href)

        # 2. Check JSON-LD structured data (<script type="application/ld+json">)
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "")
                def walk_json(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            walk_json(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            walk_json(item)
                    elif isinstance(obj, str):
                        lower = obj.lower()
                        if "instagram.com/" in lower: candidates["instagram"].append(obj)
                        elif "facebook.com/" in lower: candidates["facebook"].append(obj)
                        elif "linkedin.com/" in lower: candidates["linkedin"].append(obj)
                        elif "twitter.com/" in lower or "x.com/" in lower: candidates["twitter"].append(obj)
                walk_json(data)
            except Exception:
                pass

        # 3. Check <meta> tags
        for meta in soup.find_all("meta"):
            content = meta.get("content", "").strip()
            if not content:
                continue
            lower = content.lower()
            prop = (meta.get("property") or meta.get("name") or "").lower()
            if "instagram.com/" in lower: candidates["instagram"].append(content)
            elif "facebook.com/" in lower: candidates["facebook"].append(content)
            elif "linkedin.com/" in lower: candidates["linkedin"].append(content)
            elif "twitter.com/" in lower or "x.com/" in lower: candidates["twitter"].append(content)
            elif "twitter:site" in prop or "twitter:creator" in prop:
                handle = content.lstrip("@").strip()
                if handle and len(handle) < 30 and not any(ign in handle.lower() for ign in ["share", "intent"]):
                    candidates["twitter"].append(f"https://x.com/{handle}")

        # 4. Regex fallback across raw HTML
        ig_matches = re.findall(r'https?://(?:www\.)?instagram\.com/([a-zA-Z0-9_.]{2,30})/?', html, re.IGNORECASE)
        for m in ig_matches:
            candidates["instagram"].append(f"https://www.instagram.com/{m}")

        fb_matches = re.findall(r'https?://(?:www\.)?facebook\.com/([a-zA-Z0-9_.]{2,50})/?', html, re.IGNORECASE)
        for m in fb_matches:
            candidates["facebook"].append(f"https://www.facebook.com/{m}")

        li_matches = re.findall(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/([a-zA-Z0-9_.-]{2,50})/?', html, re.IGNORECASE)
        for m in li_matches:
            candidates["linkedin"].append(f"https://www.linkedin.com/company/{m}")

        tw_matches = re.findall(r'https?://(?:www\.)?(?:twitter|x)\.com/([a-zA-Z0-9_]{2,30})/?', html, re.IGNORECASE)
        for m in tw_matches:
            candidates["twitter"].append(f"https://x.com/{m}")

    except Exception:
        pass

    # 5. Filter & Select Best Canonical URL for each platform
    # Instagram
    for raw in candidates["instagram"]:
        cleaned = clean_social_url(raw)
        lower = cleaned.lower()
        if not any(bad in lower for bad in ["/p/", "/explore", "/reels", "/stories", "sharer", "/about", "instagram.com/direct", "/legal", "instagram.com/?"]):
            path = urllib.parse.urlparse(cleaned).path.strip("/")
            if path and "/" not in path and len(path) > 1:
                socials["instagram"] = cleaned
                break

    # Facebook
    for raw in candidates["facebook"]:
        cleaned = clean_social_url(raw)
        lower = cleaned.lower()
        if not any(bad in lower for bad in ["sharer", "/share", "/dialog", "/login", "/plugins", "facebook.com/tr", "/policies", "/help"]):
            path = urllib.parse.urlparse(cleaned).path.strip("/")
            if path and len(path) > 1:
                socials["facebook"] = cleaned
                break

    # LinkedIn
    for raw in candidates["linkedin"]:
        cleaned = clean_social_url(raw)
        lower = cleaned.lower()
        if any(k in lower for k in ["/company/", "/in/"]):
            if not any(bad in lower for bad in ["sharearticle", "sharing", "legal", "feed"]):
                socials["linkedin"] = cleaned
                break

    # Twitter / X
    for raw in candidates["twitter"]:
        cleaned = clean_social_url(raw)
        lower = cleaned.lower()
        if not any(bad in lower for bad in ["intent", "share", "sharer", "widgets", "privacy", "tos", "i/flow", "search"]):
            path = urllib.parse.urlparse(cleaned).path.strip("/")
            if path and "/" not in path and len(path) > 1:
                socials["twitter"] = cleaned
                break

    return socials

async def frame_streamer_loop(maps_page=None, linkedin_page=None, pages_dict=None):
    """Streams live JPEG screenshot frames of Tab 1 (Google Maps), Tab 2 (Shop Website), and Tab 3 (LinkedIn Org) to frontend."""
    while not stop_stream_event.is_set():
        # 1. Stream Tab 1 (Google Maps)
        try:
            if maps_page and not maps_page.is_closed():
                maps_url = maps_page.url or ""
                if maps_url and "about:blank" not in maps_url:
                    buf_maps = await maps_page.screenshot(type="jpeg", quality=55)
                    if len(buf_maps) > 6000:
                        b64_maps = base64.b64encode(buf_maps).decode("ascii")
                        emit_event("live_frame", {
                            "tab": "maps",
                            "image": f"data:image/jpeg;base64,{b64_maps}",
                            "url": maps_url,
                            "title": "Google Maps Live Agent",
                            "is_website": False
                        })
        except Exception:
            pass

        # 2. Stream Tab 2 (Shop Website)
        website_page = pages_dict.get("website") if pages_dict else None
        try:
            if website_page and not website_page.is_closed():
                site_url = website_page.url or ""
                if site_url and "about:blank" not in site_url:
                    buf_site = await website_page.screenshot(type="jpeg", quality=55)
                    if len(buf_site) > 6000:
                        b64_site = base64.b64encode(buf_site).decode("ascii")
                        site_title = ""
                        try:
                            site_title = await website_page.title()
                        except Exception:
                            pass
                        emit_event("live_frame", {
                            "tab": "website",
                            "image": f"data:image/jpeg;base64,{b64_site}",
                            "url": site_url,
                            "title": site_title[:50] if site_title else "Shop Website",
                            "is_website": True
                        })
        except Exception:
            pass

        # 3. Stream Tab 3 (LinkedIn Org Intelligence)
        try:
            if linkedin_page and not linkedin_page.is_closed():
                li_url = linkedin_page.url or ""
                if li_url and "about:blank" not in li_url:
                    buf_li = await linkedin_page.screenshot(type="jpeg", quality=55)
                    if len(buf_li) > 6000:
                        b64_li = base64.b64encode(buf_li).decode("ascii")
                        li_title = ""
                        try:
                            li_title = await linkedin_page.title()
                        except Exception:
                            pass
                        emit_event("live_frame", {
                            "tab": "linkedin",
                            "image": f"data:image/jpeg;base64,{b64_li}",
                            "url": li_url,
                            "title": li_title[:50] if li_title else "LinkedIn Org Intelligence",
                            "is_linkedin": True
                        })
        except Exception:
            pass

        # 4. Stream Tab 4 (Platform Directory Agent: Fresha, Airbnb, Yelp, etc.)
        platform_page = pages_dict.get("platform") if pages_dict else None
        try:
            if platform_page and not platform_page.is_closed():
                plat_url = platform_page.url or ""
                if plat_url and "about:blank" not in plat_url:
                    buf_plat = await platform_page.screenshot(type="jpeg", quality=55)
                    if len(buf_plat) > 6000:
                        b64_plat = base64.b64encode(buf_plat).decode("ascii")
                        plat_title = ""
                        try:
                            plat_title = await platform_page.title()
                        except Exception:
                            pass
                        emit_event("live_frame", {
                            "tab": "platform",
                            "image": f"data:image/jpeg;base64,{b64_plat}",
                            "url": plat_url,
                            "title": plat_title[:50] if plat_title else "Platform Directory Agent",
                            "is_platform": True
                        })
        except Exception:
            pass

        await asyncio.sleep(0.4)

async def clear_fixed_viewport(page):
    if not page:
        return
    try:
        cdp_sess = await page.context.new_cdp_session(page)
        await cdp_sess.send("Emulation.clearDeviceMetricsOverride")
    except Exception:
        pass

async def website_worker(context, queue: asyncio.Queue, done_event: asyncio.Event, maps_page=None, linkedin_queue: asyncio.Queue = None, pages_dict: Dict = None, cdp_connected: bool = False):
    tab_page = None
    """
    Dedicated Worker for Tab 2: Visually loads shop websites in parallel, checks Cloudflare/anti-bot,
    takes landing page screenshots, extracts emails and social media accounts simultaneously.
    Runs quietly in the background without stealing active tab focus or window focus.
    """
    while not done_event.is_set() or not queue.empty():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except Exception:
            break

        idx = item.get("index")
        name = item.get("name")
        address = item.get("address")
        website_url = item.get("website")

        if not website_url or not website_url.startswith("http"):
            queue.task_done()
            continue

        emit_event("log", f"🌐 [Tab 2 - Simultaneous] Inspecting shop website: {website_url}")
        emit_event("status", f"Browsing website #{idx}: {name}")

        try:

            # Open Tab 3 (Shop Website) dynamically only when a shop with website is processed
            if tab_page is None or tab_page.is_closed():
                if cdp_connected:
                    candidate_pages = [p for p in context.pages if p != maps_page and p != (pages_dict.get("linkedin") if pages_dict else None) and "google.com/maps" not in p.url and "linkedin.com" not in p.url]
                    if candidate_pages:
                        tab_page = candidate_pages[0]
                    else:
                        tab_page = await context.new_page()
                else:
                    tab_page = await context.new_page()
                await clear_fixed_viewport(tab_page)
                if pages_dict is not None:
                    pages_dict["website"] = tab_page

            # Navigate Tab 3 to shop website quietly in background
            try:
                await tab_page.goto(website_url, wait_until="domcontentloaded", timeout=12000)
                await tab_page.wait_for_timeout(1500)
            except Exception as e:
                emit_event("log", f"⚠️ Website note on #{idx}: {str(e)[:50]}")

            # Automatically accept cookies / consent banner if presented
            cookie_status = await detect_and_handle_cookies(tab_page)
            if cookie_status == "Accepted":
                emit_event("log", f"🍪 Auto-accepted cookie banner on #{idx} {name}")
                await tab_page.wait_for_timeout(400)
            elif cookie_status == "Detected (Unaccepted)":
                emit_event("log", f"🍪 Cookie banner detected (unaccepted) on #{idx} {name}")

            # Check if Cloudflare Turnstile checkbox is present and attempt to click it
            solved_turnstile = await attempt_turnstile_solve(tab_page)
            if solved_turnstile:
                emit_event("log", f"🛡️ Handled anti-bot checkbox on #{idx} {name}")

            page_title = ""
            try:
                page_title = await tab_page.title()
            except Exception:
                pass

            # Show HUD on shop page via extension bridge
            try:
                safe_shop_name = re.sub(r'[\'"]', '', name)[:22]
                await tab_page.evaluate(f"() => window.MavonScraper && window.MavonScraper.showHUD('Shop #{idx}: {safe_shop_name}', 'Scanning emails & socials...', '#10b981')")
            except Exception:
                pass

            page_html = await tab_page.content()

            # 1. Detect Cloudflare / Anti-bot
            bot_status = detect_anti_bot_protection(page_html, page_title)
            if bot_status != "Clean":
                is_denied = "Access Denied" in bot_status
                log_icon = "🚫" if is_denied else "🛡️"
                emit_event("log", f"{log_icon} [Anti-Bot Alert] #{idx} {name} -> {bot_status}")
                if is_denied:
                    # Stamp the warning banner on page DOM before screenshot so it is visibly baked on the image
                    try:
                        await tab_page.evaluate(f"""() => {{
                            const b = document.createElement('div');
                            b.id = 'agent-antibot-banner';
                            b.style.position = 'fixed';
                            b.style.top = '0';
                            b.style.left = '0';
                            b.style.width = '100%';
                            b.style.zIndex = '2147483647';
                            b.style.backgroundColor = '#dc2626';
                            b.style.color = '#ffffff';
                            b.style.padding = '14px 20px';
                            b.style.fontSize = '20px';
                            b.style.fontFamily = 'Arial, sans-serif';
                            b.style.fontWeight = 'bold';
                            b.style.textAlign = 'center';
                            b.style.boxShadow = '0 6px 18px rgba(0,0,0,0.7)';
                            b.innerText = '🚫 [{bot_status.upper()}]';
                            document.body.prepend(b);
                        }}""")
                        await tab_page.wait_for_timeout(300)
                    except Exception:
                        pass

            # 2. Capture screenshot of landing page
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)[:30]
            screenshot_filename = f"{safe_name}_{idx}.jpg"
            screenshot_path = os.path.join(SCREENSHOTS_DIR, screenshot_filename)
            rel_screenshot_path = f"/screenshots/{screenshot_filename}"
            try:
                await tab_page.screenshot(path=screenshot_path, type="jpeg", quality=75)
            except Exception:
                rel_screenshot_path = ""

            # 3. Smooth scroll down for lazy loading & email discovery
            try:
                await tab_page.evaluate("window.scrollBy({top: 450, behavior: 'smooth'})")
                await tab_page.wait_for_timeout(700)
                await tab_page.evaluate("window.scrollBy({top: 450, behavior: 'smooth'})")
                await tab_page.wait_for_timeout(700)
            except Exception:
                pass

            # 4. Extract Emails & Social Media Links
            fresh_html = await tab_page.content()
            emails = set(extract_emails_from_text(fresh_html))
            socials = extract_socials_from_text(fresh_html)

            # Re-check cookies after scroll
            second_cookie = await detect_and_handle_cookies(tab_page)
            if second_cookie == "Accepted":
                cookie_status = "Accepted"
            elif second_cookie == "Detected (Unaccepted)" and cookie_status == "None":
                cookie_status = "Detected (Unaccepted)"

            # In addition to Python parsing, combine in-page DOM extraction via Extension Bridge
            try:
                ext_info = await tab_page.evaluate("() => window.MavonScraper && window.MavonScraper.extractSocialsAndEmails()")
                if ext_info:
                    if ext_info.get("emails"):
                        emails.update(ext_info["emails"])
                    if ext_info.get("socials"):
                        for k, v in ext_info["socials"].items():
                            if not socials.get(k) and v:
                                socials[k] = v
            except Exception:
                pass

            # 5. Check Contact / About links if emails or socials are missing
            if not emails or not any(socials.values()):
                try:
                    contact_links = tab_page.locator('a[href*="contact" i], a[href*="about" i], a:has-text("Contact"), a:has-text("About")')
                    if await contact_links.count() > 0:
                        c_link = contact_links.first
                        if await c_link.is_visible(timeout=800):
                            await c_link.click(timeout=3000)
                            await tab_page.wait_for_timeout(1800)
                            sub_html = await tab_page.content()
                            emails.update(extract_emails_from_text(sub_html))
                            sub_socials = extract_socials_from_text(sub_html)
                            for k, v in sub_socials.items():
                                if not socials.get(k) and v:
                                    socials[k] = v
                except Exception:
                    pass

            email_list = sorted(list(emails))
            primary_email = email_list[0] if email_list else ""

            # If emails were successfully extracted from the page, confirm Access Granted
            if primary_email and "Access Denied" in bot_status:
                bot_status = bot_status.replace("Access Denied", "Access Granted")
                emit_event("log", f"🎉 [Access Granted] Contact emails extracted from #{idx} {name}!")

            # Emit update event for this place!
            emit_event("place_updated", {
                "name": name,
                "address": address,
                "website": website_url,
                "email": primary_email,
                "emails": email_list,
                "instagram": socials.get("instagram", ""),
                "facebook": socials.get("facebook", ""),
                "linkedin": socials.get("linkedin", ""),
                "twitter": socials.get("twitter", ""),
                "screenshot": rel_screenshot_path,
                "bot_protection": bot_status,
                "cookie_status": cookie_status,
            })

            log_parts = []
            if email_list: log_parts.append(f"✉️ {', '.join(email_list)}")
            if socials.get("instagram"): log_parts.append(f"📸 IG: {socials['instagram']}")
            if socials.get("facebook"): log_parts.append(f"📘 FB: {socials['facebook']}")
            if bot_status != "Clean": log_parts.append(f"🛡️ {bot_status}")
            if cookie_status != "None": log_parts.append(f"🍪 {cookie_status}")
            msg = " | ".join(log_parts) if log_parts else "No emails/socials detected"
            emit_event("log", f"✅ [Tab 2 Finished: #{idx} {name}] {msg}")

            # -------------------------------------------------------------
            # PARALLEL PIPELINE: Send company to Tab 3 (LinkedIn Intelligence)
            # -------------------------------------------------------------
            if linkedin_queue:
                linkedin_queue.put_nowait({
                    "index": idx,
                    "name": name,
                    "address": item.get("address", ""),
                    "website": website_url,
                    "linkedin_url": socials.get("linkedin", ""),
                    "website_emails": email_list
                })

        except Exception as err:
            emit_event("log", f"⚠️ Error processing website for #{idx}: {str(err)[:60]}")
        finally:
            queue.task_done()

async def linkedin_worker(tab_page, queue: asyncio.Queue, done_event: asyncio.Event):
    """
    Dedicated Worker for Tab 3: Navigates company's LinkedIn profile / search directly in the user's active Chrome session,
    extracts the employee list, classifies job roles into seniority tiers (Executive, Management, Staff),
    and saves the full organization hierarchy into the database.
    """
    while not done_event.is_set() or not queue.empty():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except Exception:
            break

        idx = item.get("index", 1)
        name = item.get("name", "").strip()
        address = item.get("address", "")
        website_url = item.get("website", "")
        known_linkedin = item.get("linkedin_url", "")
        website_emails = item.get("website_emails", [])

        if not name:
            queue.task_done()
            continue

        city = extract_city_from_address(address)
        core_brand = clean_brand_tokens(name, city=city)
        domain_brand = extract_brand_from_domain(website_url)

        emit_event("log", f"💼 [LinkedIn Step 1/5 - Company Resolution] Resolving verified LinkedIn profile for #{idx} '{name}' (Brand: '{core_brand}')...")
        emit_event("status", f"Resolving LinkedIn profile: {core_brand}")

        try:
            # Step 1: Determine target verified company URL via cascading directory search
            verified_company_url = None
            if known_linkedin and "linkedin.com/company/" in known_linkedin:
                clean_base = known_linkedin.split("?")[0].rstrip("/")
                verified_company_url = clean_base
                emit_event("log", f"🔗 [LinkedIn Step 1/5] Using verified LinkedIn company URL from website: {verified_company_url}")
            else:
                # Build prioritized search candidate queries: Core Brand -> Exact Maps Name -> Domain Brand
                search_candidates = []
                if core_brand and core_brand.lower() != name.lower():
                    search_candidates.append(core_brand)
                search_candidates.append(name)
                if domain_brand and len(domain_brand) >= 3 and domain_brand.lower() not in [c.lower() for c in search_candidates]:
                    search_candidates.append(domain_brand)

                for cand_query in search_candidates:
                    encoded_cand = urllib.parse.quote(cand_query)
                    search_co_url = f"https://www.linkedin.com/search/results/companies/?keywords={encoded_cand}"
                    emit_event("log", f"🏢 [LinkedIn Step 1/5] Searching company directory on LinkedIn for '{cand_query}'...")
                    emit_event("linkedin_navigated", {"url": search_co_url, "name": cand_query})
                    try:
                        await tab_page.goto(search_co_url, wait_until="domcontentloaded", timeout=12000)
                        await tab_page.wait_for_timeout(1500)
                        li_result = await tab_page.evaluate(r"""() => {
                            const cards = document.querySelectorAll('.entity-result, li.reusable-search__result-container');
                            for (const card of cards) {
                                const link = card.querySelector('a[href*="/company/"]:not([href*="ads"])');
                                const titleEl = card.querySelector('.entity-result__title-text, .app-aware-link, .artdeco-entity-lockup__title');
                                if (link && titleEl) {
                                    const href = link.href.split('?')[0].replace(/\/+$/, '');
                                    const title = titleEl.innerText.trim();
                                    if (!href.includes('/search') && !href.includes('/help') && !href.includes('/feed')) {
                                        return { href, title };
                                    }
                                }
                            }
                            return null;
                        }""")
                        if li_result and isinstance(li_result, dict):
                            cand_href = li_result.get("href", "")
                            cand_title = li_result.get("title", "")
                            if verify_company_name_match(cand_query, cand_title) or verify_company_name_match(core_brand, cand_title):
                                verified_company_url = cand_href
                                emit_event("log", f"🏢 [LinkedIn Step 1/5] Verified company via LinkedIn directory: '{cand_title}' ({verified_company_url})")
                                break
                            else:
                                emit_event("log", f"⚠️ [LinkedIn Step 1/5] Skipped non-matching company candidate '{cand_title}' for '{cand_query}'")
                    except Exception as e:
                        emit_event("log", f"⚠️ Company search note for '{cand_query}': {str(e)[:40]}")

            if not verified_company_url:
                emit_event("log", f"ℹ️ [LinkedIn Step 1/5] No official corporate page for '{name}'. Using targeted Boolean role search in People directory...")

            employees = []

            # Step 2: Open company's /people/ directory if verified corporate page exists
            if verified_company_url:
                people_target = f"{verified_company_url}/people/"
                emit_event("log", f"👥 [LinkedIn Step 2/5 - Directory Navigation] Opening people directory: {people_target}")
                emit_event("linkedin_navigated", {"url": people_target, "name": core_brand})
                try:
                    await tab_page.goto(people_target, wait_until="domcontentloaded", timeout=15000)
                    await tab_page.wait_for_timeout(2000)
                except Exception as e:
                    emit_event("log", f"⚠️ Navigation note: {str(e)[:50]}")

                try:
                    safe_name = re.sub(r'[\'"]', '', core_brand)[:22]
                    await tab_page.evaluate(f"() => window.MavonScraper && window.MavonScraper.showHUD('LinkedIn: {safe_name}', 'Harvesting employees & leadership...', '#0a66c2')")
                except Exception:
                    pass

                # Step 3: Progressive DOM scrolling
                emit_event("log", f"📜 [LinkedIn Step 3/5 - Progressive Scroll] Triggering member cards discovery...")
                for s_i in range(3):
                    try:
                        await tab_page.evaluate("window.scrollBy({top: 650, behavior: 'smooth'})")
                        await tab_page.wait_for_timeout(900)
                    except Exception:
                        break

                # Step 4: Extract from company /people/ tab
                emit_event("log", f"🔍 [LinkedIn Step 4/5 - Card Parsing] Extracting employee cards from company directory...")
                try:
                    raw_extracted = await tab_page.evaluate(r"""() => {
                        const list = [];
                        const seenNames = new Set();
                        const cards = document.querySelectorAll('div.org-people-profile-card, li.org-people-profile-card__profile-card-spacing, div[data-view-name="org-people-profile-card"], .entity-result, li.reusable-search__result-container');

                        cards.forEach(card => {
                            let nameEl = card.querySelector('.org-people-profile-card__profile-title, .entity-result__title-text a, .artdeco-entity-lockup__title, span[aria-hidden="true"]');
                            let titleEl = card.querySelector('.lt-line-clamp--multi-line, .entity-result__primary-subtitle, .artdeco-entity-lockup__subtitle');
                            let linkEl = card.querySelector('a[href*="/in/"]');
                            let imgEl = card.querySelector('img[src*="licdn.com"]');
                            let locEl = card.querySelector('.entity-result__secondary-subtitle, .org-people-profile-card__profile-location');

                            let rawName = nameEl ? nameEl.innerText.trim() : "";
                            let rawTitle = titleEl ? titleEl.innerText.trim() : "";
                            let profile = linkEl ? linkEl.href.split('?')[0] : "";
                            let avatar = imgEl ? imgEl.src : "";
                            let loc = locEl ? locEl.innerText.trim() : "";

                            let cleanName = rawName
                                .replace(/•\s*(1st|2nd|3rd\+?|Following|Follow)/gi, '')
                                .replace(/\(He\/Him\)|\(She\/Her\)|\(They\/Them\)/gi, '')
                                .replace(/View.*profile/gi, '')
                                .replace(/\b(connection|connections)\b/gi, '')
                                .replace(/[\r\n]+/g, ' ')
                                .replace(/\s+/g, ' ')
                                .trim();

                            let cleanTitle = rawTitle
                                .replace(/[\r\n]+/g, ' ')
                                .replace(/\s+/g, ' ')
                                .trim();

                            if (cleanName && cleanName !== "LinkedIn Member" && !seenNames.has(cleanName) && cleanName.length > 2 && cleanName.length < 50) {
                                seenNames.add(cleanName);
                                list.push({
                                    full_name: cleanName,
                                    title: cleanTitle || "Employee",
                                    linkedin_profile_url: profile,
                                    avatar_url: avatar,
                                    location: loc,
                                    snippet: ""
                                });
                            }
                        });
                        return list;
                    }""")
                    if raw_extracted and isinstance(raw_extracted, list):
                        employees = raw_extracted
                except Exception as e:
                    emit_event("log", f"⚠️ Employee DOM parse note: {str(e)[:50]}")

            # Fallback: If 0 cards extracted from /people/ OR if no company page existed,
            # execute targeted Boolean People Search directly on LinkedIn!
            if len(employees) == 0:
                role_bool = '("Founder" OR "Co-Founder" OR "Owner" OR "Director" OR "CEO" OR "Manager" OR "Head")'
                people_queries = [
                    f'"{core_brand}" {role_bool}',
                    f'"{core_brand}"'
                ]
                if core_brand.lower() != name.lower():
                    people_queries.append(f'"{name}"')

                for p_query in people_queries:
                    search_people_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(p_query)}"
                    emit_event("log", f"👥 [LinkedIn People Search] Searching personnel using query: {p_query}...")
                    emit_event("linkedin_navigated", {"url": search_people_url, "name": core_brand})
                    try:
                        await tab_page.goto(search_people_url, wait_until="domcontentloaded", timeout=14000)
                        await tab_page.wait_for_timeout(1800)
                        for s_i in range(2):
                            await tab_page.evaluate("window.scrollBy({top: 650, behavior: 'smooth'})")
                            await tab_page.wait_for_timeout(700)

                        li_peop_extracted = await tab_page.evaluate(r"""() => {
                            const list = [];
                            const seenNames = new Set();
                            const cards = document.querySelectorAll('.entity-result, li.reusable-search__result-container, div.org-people-profile-card');
                            cards.forEach(card => {
                                let nameEl = card.querySelector('.org-people-profile-card__profile-title, .entity-result__title-text a, .artdeco-entity-lockup__title, span[aria-hidden="true"]');
                                let titleEl = card.querySelector('.lt-line-clamp--multi-line, .entity-result__primary-subtitle, .artdeco-entity-lockup__subtitle');
                                let linkEl = card.querySelector('a[href*="/in/"]');
                                let imgEl = card.querySelector('img[src*="licdn.com"]');
                                let locEl = card.querySelector('.entity-result__secondary-subtitle, .org-people-profile-card__profile-location');
                                let snippetEl = card.querySelector('.entity-result__summary, .reusable-search__card-summary');

                                let rawName = nameEl ? (nameEl.innerText || nameEl.textContent) : "";
                                let rawTitle = titleEl ? (titleEl.innerText || titleEl.textContent) : "";
                                let profile = linkEl ? linkEl.href.split('?')[0] : "";
                                let avatar = imgEl ? imgEl.src : "";
                                let loc = locEl ? locEl.innerText.trim() : "";
                                let snippet = snippetEl ? snippetEl.innerText.trim() : "";

                                let cleanName = rawName
                                    .replace(/•\s*(1st|2nd|3rd\+?|Following|Follow)/gi, '')
                                    .replace(/\(He\/Him\)|\(She\/Her\)|\(They\/Them\)/gi, '')
                                    .replace(/View.*profile/gi, '')
                                    .replace(/\b(connection|connections)\b/gi, '')
                                    .replace(/[\r\n]+/g, ' ')
                                    .replace(/\s+/g, ' ')
                                    .trim();

                                let cleanTitle = rawTitle.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();

                                if (cleanName && cleanName !== "LinkedIn Member" && !seenNames.has(cleanName) && cleanName.length > 2 && cleanName.length < 50) {
                                    seenNames.add(cleanName);
                                    list.push({
                                        full_name: cleanName,
                                        title: cleanTitle || "Employee",
                                        linkedin_profile_url: profile,
                                        avatar_url: avatar,
                                        location: loc,
                                        snippet: snippet
                                    });
                                }
                            });
                            return list;
                        }""")

                        if li_peop_extracted and isinstance(li_peop_extracted, list) and len(li_peop_extracted) > 0:
                            verified_candidates = []
                            for cand in li_peop_extracted:
                                c_title = cand.get("title", "")
                                c_snip = f"{cand.get('snippet', '')} {cand.get('location', '')}"
                                if is_person_relevant_to_brand(core_brand, c_title, c_snip):
                                    verified_candidates.append(cand)

                            if verified_candidates:
                                employees = verified_candidates
                                emit_event("log", f"✅ [LinkedIn Step 4/5] Discovered {len(employees)} verified personnel profiles for '{core_brand}' via targeted keyword search")
                                break
                    except Exception as pe_err:
                        emit_event("log", f"⚠️ People search note for query '{p_query}': {str(pe_err)[:40]}")

            # Enrich employee emails from snippet text or matched business website emails
            for emp in employees:
                loc_text = f"{emp.get('location', '')} {emp.get('snippet', '')}"
                if not emp.get("email") and "@" in loc_text:
                    snip_matches = EMAIL_REGEX.findall(loc_text)
                    if snip_matches and not any(snip_matches[0].lower().endswith(ext) for ext in JUNK_EXTENSIONS):
                        emp["email"] = snip_matches[0].lower()

                if not emp.get("email") and website_emails:
                    f_parts = emp.get("full_name", "").lower().split()
                    first_n = f_parts[0] if f_parts else ""
                    last_n = f_parts[-1] if len(f_parts) > 1 else ""
                    for w_em in website_emails:
                        u_part = w_em.split("@")[0].lower()
                        if (first_n and len(first_n) > 2 and first_n in u_part) or (last_n and len(last_n) > 2 and last_n in u_part):
                            emp["email"] = w_em
                            break

            # Step 5: Classify & save into Database
            final_linkedin_url = verified_company_url or (tab_page.url.split("?")[0].rstrip("/") if (tab_page.url and "linkedin.com" in tab_page.url) else known_linkedin)
            if final_linkedin_url and "/people" in final_linkedin_url:
                final_linkedin_url = final_linkedin_url.replace("/people", "")

            # Save batch to SQLite
            saved = save_employees_batch(company_name=name, employees=employees, company_linkedin_url=final_linkedin_url)

            exec_count = sum(1 for e in employees if classify_seniority(e.get("title", "")) == "executive")
            mgmt_count = sum(1 for e in employees if classify_seniority(e.get("title", "")) == "management")
            staff_count = len(employees) - exec_count - mgmt_count

            emit_event("org_updated", {
                "company": name,
                "linkedin_url": final_linkedin_url,
                "employee_count": len(employees),
                "tiers": {
                    "executive": exec_count,
                    "management": mgmt_count,
                    "staff": staff_count
                }
            })

            emit_event("log", f"🌳 [Tab 3 Finished: {name}] {len(employees)} employees mapped: {exec_count} Execs | {mgmt_count} Leads | {staff_count} Staff")

        except Exception as err:
            emit_event("log", f"⚠️ Error scanning LinkedIn for {name}: {str(err)[:60]}")
        finally:
            queue.task_done()

async def platform_worker(
    context,
    queue: asyncio.Queue,
    done_event: asyncio.Event,
    pages_dict: Dict,
    platform_name: str = "Fresha",
    custom_url_pattern: str = "",
    cdp_connected: bool = False,
    maps_page = None,
    linkedin_page = None,
    general_location: str = ""
):
    """
    Dedicated Worker for Tab 4 (Multi-Platform Directory Agent: Fresha, Airbnb, Yelp, TripAdvisor, Custom).
    Searches target platforms using location and radius context, verifies brand matches,
    extracts direct booking URLs, platform ratings, reviews, and pricing tiers,
    and merges the normalized directory intelligence into the database.
    """
    tab_page = None
    p_name = platform_name.strip() if platform_name else "Fresha"

    while not done_event.is_set() or not queue.empty():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except Exception:
            break

        idx = item.get("index", 1)
        name = item.get("name", "").strip()
        address = item.get("address", "")
        lead_id = item.get("id")

        if not name:
            queue.task_done()
            continue

        city = extract_city_from_address(address) or general_location
        core_brand = clean_brand_tokens(name, city=city)

        emit_event("log", f"🟣 [Tab 4 - Platform Agent] Searching {p_name} for #{idx} '{name}' (Brand: '{core_brand}', Loc: '{city}')...")
        emit_event("status", f"Scanning {p_name}: {core_brand}")

        try:
            # 1. Ensure Tab 4 page exists
            if tab_page is None or tab_page.is_closed():
                if cdp_connected:
                    other_pages = [
                        p for p in context.pages
                        if p != maps_page
                        and p != linkedin_page
                        and p != (pages_dict.get("website") if pages_dict else None)
                        and "google.com/maps" not in p.url
                        and "linkedin.com" not in p.url
                    ]
                    if other_pages:
                        tab_page = other_pages[0]
                    else:
                        tab_page = await context.new_page()
                else:
                    tab_page = await context.new_page()

                await clear_fixed_viewport(tab_page)
                if pages_dict is not None:
                    pages_dict["platform"] = tab_page

            # 2. Build platform search URL
            enc_brand = urllib.parse.quote(core_brand)
            enc_city = urllib.parse.quote(city) if city else ""
            target_url = ""

            p_lower = p_name.lower()
            if custom_url_pattern and "http" in custom_url_pattern:
                target_url = custom_url_pattern.replace("{query}", enc_brand).replace("{location}", enc_city).replace("{city}", enc_city)
            elif "fresha" in p_lower:
                target_url = f"https://www.fresha.com/search?query={enc_brand}&address={enc_city}" if enc_city else f"https://www.fresha.com/search?query={enc_brand}"
            elif "airbnb" in p_lower:
                target_url = f"https://www.airbnb.com/s/{enc_city or enc_brand}/homes?query={enc_brand}"
            elif "yelp" in p_lower:
                target_url = f"https://www.yelp.com/search?find_desc={enc_brand}&find_loc={enc_city}"
            elif "tripadvisor" in p_lower:
                target_url = f"https://www.tripadvisor.com/Search?q={enc_brand}+{enc_city}"
            else:
                target_url = f"https://www.google.com/search?q={urllib.parse.quote(f'{core_brand} {city} {p_name}')}"

            emit_event("log", f"🌐 [Tab 4] Navigating to {p_name}: {target_url}")
            try:
                await tab_page.goto(target_url, wait_until="domcontentloaded", timeout=14000)
                await tab_page.wait_for_timeout(1800)
            except Exception as nav_e:
                emit_event("log", f"⚠️ Tab 4 navigation note: {str(nav_e)[:50]}")

            # HUD on Tab 4
            try:
                safe_brand = re.sub(r'[\'"]', '', core_brand)[:20]
                await tab_page.evaluate(f"() => window.MavonScraper && window.MavonScraper.showHUD('Platform: {p_name}', 'Matching {safe_brand}...', '#a855f7')")
            except Exception:
                pass

            # Scroll once to trigger listings
            try:
                await tab_page.evaluate("window.scrollBy({top: 500, behavior: 'smooth'})")
                await tab_page.wait_for_timeout(800)
            except Exception:
                pass

            # 3. Extract candidate listings across platforms
            extracted_listings = await tab_page.evaluate(r"""() => {
                const results = [];
                const cards = document.querySelectorAll(
                    'a[href*="/a/"], div[data-qa="venue-card"], div.venue-card, ' +
                    'div[data-testid="card-container"], div[itemprop="itemListElement"], ' +
                    'div[data-testid="serp-ia-card"], li.border-color--default__09f24__Nrmcg, ' +
                    '.search-result-card, a.property-card, div.result-card, ' +
                    'div[role="group"], a[href*="/rooms/"]'
                );

                cards.forEach(card => {
                    let titleEl = card.querySelector('h2, h3, h4, .title, [data-qa="venue-name"], [data-testid="listing-card-title"], div[id^="title_"], a.booking-link, [class*="t1jqs7"]');
                    let ratingEl = card.querySelector('[data-qa="rating-badge"], .rating, [aria-label*="rating"], [aria-label*="star"], span[class*="rating"], span[class*="r1dxllyb"]');
                    let reviewsEl = card.querySelector('[data-qa="reviews-count"], .review-count, span[class*="review"], span[class*="count"]');
                    let linkEl = card.matches('a') ? card : card.querySelector('a[href*="/rooms/"], a[href*="/a/"], a[href]');

                    let title = titleEl ? (titleEl.innerText || titleEl.textContent || "").trim() : "";
                    if (!title && linkEl) {
                        const aria = linkEl.getAttribute('aria-label') || '';
                        title = aria.split(' - ')[0] || aria.split(' · ')[0] || aria;
                    }
                    if (!title) {
                        title = (card.innerText || "").split('\n')[0].trim();
                    }

                    let url = linkEl ? linkEl.href : window.location.href;
                    let rawRating = ratingEl ? (ratingEl.getAttribute('aria-label') || ratingEl.innerText || "").trim() : "";
                    if (!rawRating) {
                        const m = (card.innerText || '').match(/(?:★|star|rating)?\s*(\d\.\d+)\s*(?:\((\d+)\))?/i);
                        if (m) rawRating = m[0];
                    }

                    let rawReviews = reviewsEl ? (reviewsEl.innerText || "").trim() : "";
                    
                    let priceText = '';
                    let priceEl = card.querySelector('[data-qa="price"], .price, [class*="price"]');
                    if (priceEl) {
                        priceText = (priceEl.innerText || "").trim();
                    } else {
                        card.querySelectorAll('span, div').forEach(el => {
                            const txt = (el.innerText || '').trim();
                            if (txt.match(/(?:[\$£€₹]|Rs\.?)\s*[\d,]+/i) && (!priceText || txt.length < priceText.length)) {
                                priceText = txt;
                            }
                        });
                    }

                    let rMatch = rawRating.match(/(\d+(?:\.\d+)?)/);
                    let ratingVal = rMatch ? parseFloat(rMatch[1]) : 0.0;

                    let revMatch = rawReviews.match(/(\d[\d,]*)/);
                    let revCount = revMatch ? parseInt(revMatch[1].replace(/,/g, ''), 10) : 0;

                    const lowerTitle = title.toLowerCase();
                    if (title && url && url.startsWith('http') && 
                        !url.includes('/login') && !url.includes('/signup') &&
                        lowerTitle !== 'filters' && lowerTitle !== 'filter' && 
                        lowerTitle !== 'show map' && lowerTitle !== 'search') {
                        results.push({
                            title: title.replace(/[\r\n]+/g, ' ').trim(),
                            url: url.split('?')[0],
                            rating: ratingVal,
                            reviews_count: revCount,
                            price_info: priceText.replace(/[\r\n]+/g, ' ').trim()
                        });
                    }
                });

                return results;
            }""")

            # 4. Filter, Match & Populate Directory
            best_match = None
            if extracted_listings and isinstance(extracted_listings, list):
                # Save top discovered listings into platform directory
                for cand in extracted_listings[:6]:
                    c_title = cand.get("title", "")
                    if not c_title:
                        continue
                    is_match = (
                        verify_company_name_match(core_brand, c_title) or 
                        verify_company_name_match(name, c_title) or
                        (core_brand.lower() in c_title.lower() and len(core_brand) >= 3)
                    )
                    cand_lead_id = lead_id if is_match else None
                    cand_data = {
                        "lead_id": cand_lead_id,
                        "platform": p_name,
                        "title": c_title,
                        "clean_brand": clean_brand_tokens(c_title, city=city),
                        "url": cand.get("url", target_url),
                        "booking_url": cand.get("url", target_url),
                        "rating": cand.get("rating", 0.0),
                        "reviews_count": cand.get("reviews_count", 0),
                        "price_info": cand.get("price_info", ""),
                        "address": f"{city}, Area Radius" if city else address,
                        "verified": 1 if is_match else 0
                    }
                    save_platform_listing(cand_data)
                    if is_match and not best_match:
                        best_match = cand

            if best_match:
                emit_event("platform_listing_found", {
                    "lead_id": lead_id,
                    "company_name": name,
                    "platform": p_name,
                    "rating": best_match.get("rating", 0.0),
                    "review_count": best_match.get("reviews_count", 0),
                    "listing_url": best_match.get("url", target_url),
                    "booking_url": best_match.get("url", target_url),
                    "price_range": best_match.get("price_info", ""),
                    "verified": True
                })
                emit_event("log", f"🟣 [Tab 4 Finished: #{idx} {name}] Verified on {p_name}: {best_match.get('rating')} ★ ({best_match.get('reviews_count')} reviews) | 💰 {best_match.get('price_info')} | 🔗 {best_match.get('url')}")
            elif extracted_listings:
                top_cand = extracted_listings[0]
                emit_event("platform_listing_found", {
                    "lead_id": lead_id,
                    "company_name": name,
                    "platform": p_name,
                    "rating": top_cand.get("rating", 0.0),
                    "review_count": top_cand.get("reviews_count", 0),
                    "listing_url": top_cand.get("url", target_url),
                    "booking_url": top_cand.get("url", target_url),
                    "price_range": top_cand.get("price_info", ""),
                    "verified": False
                })
                emit_event("log", f"🟣 [Tab 4] Stored {len(extracted_listings[:6])} {p_name} listings in directory for area '{city}'. Top listing: '{top_cand.get('title')}' ({top_cand.get('rating')} ★, {top_cand.get('price_info')})")
            else:
                emit_event("log", f"ℹ️ [Tab 4] No listings returned on {p_name} for '{name}' ({city})")

        except Exception as err:
            emit_event("log", f"⚠️ Error scanning {p_name} for #{idx} {name}: {str(err)[:60]}")
        finally:
            queue.task_done()

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
    platform_custom_url: Optional[str] = None,
    dedup_area: bool = True,
    skip_existing_db: bool = False,
    standalone_companies: Optional[str] = None,
):
    cleaned_query = query.strip() if query else ""
    if not cleaned_query or cleaned_query.lower() in ["all", "all shops", "all shops in area"]:
        cleaned_query = "shops"

    emit_event("status", "Launching Google Chrome on your screen...")
    emit_event("log", f"Starting Desktop Chrome (Visible: {visible_browser})...")

    async with async_playwright() as p:
        profile_dir = os.path.abspath("./chrome_live_profile")
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

        if visible_browser:
            # First priority: connect directly to user's active Chrome browser via CDP port 9222
            try:
                emit_event("log", "🔗 Connecting to your active Google Chrome browser (CDP :9222)...")
                browser = await p.chromium.connect_over_cdp("http://localhost:9222", timeout=3000)
                context = browser.contexts[0] if browser.contexts else await browser.new_context(no_viewport=True)
                cdp_connected = True
                emit_event("log", "✅ Successfully attached to your active Google Chrome window! All logins, extensions and active accounts are preserved.")
            except Exception:
                emit_event("log", "ℹ️ Chrome port 9222 not reachable. Launching dedicated scraper Chrome window. (Tip: Run 'start_chrome_debug.bat' anytime to attach to your active Chrome window).")

            # Second priority: launch dedicated visible Chrome if CDP is not available
            if not context:
                # Purge stale session cache so Chrome never re-opens tabs from old sessions
                stale_sessions = os.path.join(profile_dir, "Default", "Sessions")
                if os.path.exists(stale_sessions):
                    try:
                        shutil.rmtree(stale_sessions, ignore_errors=True)
                    except Exception:
                        pass

                emit_event("log", "Launching fresh Google Chrome window with Mavon Extension...")
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
        if standalone_companies or not enable_maps:
            if standalone_companies:
                comp_list = [c.strip() for c in standalone_companies.split(",") if c.strip()]
            elif cleaned_query and cleaned_query != "shops":
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
            stream_task = asyncio.create_task(frame_streamer_loop(None, linkedin_page, None))

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
        # MULTI-TAB PARALLEL SCRAPER:
        # Tab 1: Google Maps Master Tab
        # Tab 2: Dedicated Shop Website Tab
        # Tab 3: Dedicated LinkedIn Org Intelligence Tab
        # =============================================================
        # By default, open ONLY 2 tabs on startup: Tab 1 (Maps) and Tab 2 (LinkedIn)
        # Tab 3 (Shop Website) opens dynamically based on shop website
        pages_dict = {"website": None, "linkedin": None, "platform": None}
        if cdp_connected:
            existing_maps = [p for p in context.pages if "google.com/maps" in p.url]
            existing_li = [p for p in context.pages if "linkedin.com" in p.url]
            maps_page = existing_maps[0] if (existing_maps and enable_maps) else (await context.new_page() if enable_maps else None)
            if existing_li and enable_linkedin:
                linkedin_page = existing_li[0]
            elif enable_linkedin:
                linkedin_page = await context.new_page()
            else:
                linkedin_page = None
        else:
            pages_avail = list(context.pages)
            maps_page = pages_avail.pop(0) if (enable_maps and pages_avail) else (await context.new_page() if enable_maps else None)
            linkedin_page = pages_avail.pop(0) if (enable_linkedin and pages_avail) else (await context.new_page() if enable_linkedin else None)
            # Close any leftover stray tabs so exactly 2 tabs exist at startup
            for stray in pages_avail:
                try:
                    await stray.close()
                except Exception:
                    pass

        if maps_page:
            await clear_fixed_viewport(maps_page)
        if linkedin_page:
            pages_dict["linkedin"] = linkedin_page
            await clear_fixed_viewport(linkedin_page)

    
        if visible_browser and maps_page:
            try:
                await maps_page.bring_to_front()
            except Exception:
                pass

        # Navigate Tab 2 (LinkedIn) on startup so both Maps and LinkedIn tabs are open by default
        if linkedin_page:
            try:
                emit_event("log", "Navigating Tab 2 (LinkedIn): https://www.linkedin.com/")
                await linkedin_page.goto("https://www.linkedin.com/", wait_until="domcontentloaded")
            except Exception:
                pass

        # Setup Parallel Asynchronous Queues for Tab 2, Tab 3, and Tab 4
        website_queue = asyncio.Queue() if (enable_website and extract_emails) else None
        linkedin_queue = asyncio.Queue() if linkedin_page else None
        platform_queue = asyncio.Queue() if enable_platform else None
        website_done_event = asyncio.Event()
        linkedin_done_event = asyncio.Event()
        platform_done_event = asyncio.Event()

        worker_task = None
        if website_queue:
            worker_task = asyncio.create_task(website_worker(context, website_queue, website_done_event, maps_page=maps_page, linkedin_queue=linkedin_queue, pages_dict=pages_dict, cdp_connected=cdp_connected))

        linkedin_task = None
        if linkedin_page and linkedin_queue:
            linkedin_task = asyncio.create_task(linkedin_worker(linkedin_page, linkedin_queue, linkedin_done_event))

        platform_task = None
        if enable_platform and platform_queue:
            platform_task = asyncio.create_task(platform_worker(
                context=context,
                queue=platform_queue,
                done_event=platform_done_event,
                pages_dict=pages_dict,
                platform_name=platform_name,
                custom_url_pattern=platform_custom_url or "",
                cdp_connected=cdp_connected,
                maps_page=maps_page,
                linkedin_page=linkedin_page,
                general_location=cleaned_query
            ))

        # Dynamic zoom from radius_km
        effective_zoom = radius_to_zoom(radius_km) if radius_km else zoom
        encoded_query = urllib.parse.quote_plus(cleaned_query)
        if lat is not None and lon is not None:
            search_url = f"https://www.google.com/maps/search/{encoded_query}/@{lat},{lon},{effective_zoom}z?hl=en"
        else:
            search_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"

        emit_event("log", f"Navigating Tab 1 (Google Maps): {search_url}")
        emit_event("status", f"Searching Google Maps: {cleaned_query}")
        await maps_page.goto(search_url, wait_until="domcontentloaded")
        force_foreground_window()

        # Handle Cookie Consent on Google Maps
        try:
            consent_btn = maps_page.locator('button:has-text("Reject all"), button:has-text("Accept all"), form[action*="consent"] button').first
            if await consent_btn.is_visible(timeout=2000):
                emit_event("log", "Accepting cookie consent...")
                await consent_btn.click()
                await maps_page.wait_for_timeout(1000)
        except Exception:
            pass

        # Wait for results feed
        feed_selector = 'div[role="feed"]'
        try:
            await maps_page.wait_for_selector(feed_selector, timeout=12000)
            emit_event("log", "Google Maps results feed loaded.")
        except Exception:
            emit_event("log", "Results feed container detected.")

        # Start live screen streaming across all 3 viewports
        stop_stream_event.clear()
        stream_task = asyncio.create_task(frame_streamer_loop(maps_page, linkedin_page, pages_dict))

        await maps_page.wait_for_timeout(1000)

        scraped_places = []
        seen_titles = set()
        seen_signatures = set()
        seen_phones = set()
        seen_domains = set()
        scroll_attempts = 0
        target_max = 9999 if scrape_all else max_results
        max_scroll_attempts = 300 if scrape_all else max(15, (max_results // 3) + 10)
        consecutive_no_new = 0

        emit_event("status", "Extracting places from feed...")

        while len(scraped_places) < target_max and scroll_attempts < max_scroll_attempts:
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
                    title = await elem.get_attribute("aria-label") or ""
                    title = clean_text(title)

                    if not title or title in seen_titles:
                        continue

                    seen_titles.add(title)
                    new_found_this_scroll += 1
                    idx = len(scraped_places) + 1

                    emit_event("log", f"👉 [{idx}] Inspecting: {title}")
                    emit_event("status", f"Scraping #{idx}: {title}")

                    # Highlight place card visually using extension bridge
                    try:
                        await elem.evaluate(f"el => window.MavonScraper && window.MavonScraper.highlight(el, 'Inspecting #{idx}')")
                    except Exception:
                        pass

                    # Click place card in Tab 1 and wait for detail panel
                    await elem.click()
                    try:
                        await maps_page.wait_for_selector('h1.DUwDvf', timeout=3500)
                    except Exception:
                        pass
                    await maps_page.wait_for_timeout(800)

                    # Smoothly scroll detail panel down to trigger lazy loading of address/phone/website
                    try:
                        await maps_page.evaluate("""() => {
                            const main = document.querySelector('div[role="main"]') || document.querySelector('div.m6QErb.DxyBCb');
                            if (main) {
                                main.scrollBy(0, 400);
                            }
                        }""")
                        await maps_page.wait_for_timeout(500)
                    except Exception:
                        pass

                    # Extract Business Name
                    place_title = title
                    try:
                        h1 = maps_page.locator("h1.DUwDvf").first
                        if await h1.count() > 0:
                            t_val = clean_text(await h1.inner_text())
                            if t_val:
                                place_title = t_val
                    except Exception:
                        pass

                    # Extract Category
                    category = ""
                    try:
                        cat_candidates = maps_page.locator('button.DkEaL, button[jsaction*="category"], div.fontBodyMedium button, span.YhemCb')
                        for c_i in range(await cat_candidates.count()):
                            candidate = cat_candidates.nth(c_i)
                            if await candidate.is_visible(timeout=300):
                                c_text = clean_text(await candidate.inner_text())
                                ignore_categories = [
                                    "learn more", "see more", "read more", "claim this business",
                                    "suggest an edit", "save", "nearby", "send to phone", "share",
                                    "reviews", "photos", "overview", "about",
                                    "update results when map moves", "search this area",
                                    "search", "directions", "copy"
                                ]
                                if c_text and not any(ign in c_text.lower() for ign in ignore_categories):
                                    category = c_text
                                    break
                    except Exception:
                        pass

                    # Extract Rating and Reviews Count
                    rating = ""
                    reviews = ""
                    try:
                        rating_el = maps_page.locator('div.F7nice span[aria-hidden="true"]').first
                        if await rating_el.is_visible(timeout=300):
                            rating = clean_text(await rating_el.inner_text())
                        reviews_el = maps_page.locator('div.F7nice span[aria-label*="reviews"]').first
                        if await reviews_el.is_visible(timeout=300):
                            r_aria = await reviews_el.get_attribute("aria-label") or ""
                            r_digits = re.findall(r"[\d,]+", r_aria)
                            if r_digits:
                                reviews = r_digits[0].replace(",", "")
                    except Exception:
                        pass

                    # Extract Address
                    address = ""
                    try:
                        addr_el = maps_page.locator('button[data-item-id="address"], button[aria-label*="Address:"]').first
                        if await addr_el.is_visible(timeout=400):
                            address = clean_text(await addr_el.inner_text())
                    except Exception:
                        pass

                    # Extract Phone Number
                    phone = ""
                    try:
                        phone_el = maps_page.locator('button[data-item-id*="phone:"], button[aria-label*="Phone:"]').first
                        if await phone_el.is_visible(timeout=400):
                            phone = clean_text(await phone_el.inner_text())
                    except Exception:
                        pass

                    # Extract Website URL
                    website = ""
                    try:
                        web_el = maps_page.locator('a[data-item-id="authority"], a[aria-label*="Website:"]').first
                        if await web_el.is_visible(timeout=400):
                            website = await web_el.get_attribute("href") or ""
                    except Exception:
                        pass

                    # Extract Opening Hours
                    hours = ""
                    try:
                        for h_sel in ['button[data-item-id*="oh"]', 'div[data-item-id*="oh"]', 'button[aria-label*="Hours"]', 'div[aria-label*="Hours"]']:
                            h_el = maps_page.locator(h_sel).first
                            if await h_el.is_visible(timeout=400):
                                h_val = clean_text(await h_el.inner_text())
                                if h_val:
                                    hours = h_val.split("\n")[0]
                                    break
                    except Exception:
                        pass

                    # Extract Price Range
                    price = ""
                    try:
                        p_el = maps_page.locator('span[aria-label*="per person"], span[aria-label*="Price"], button[data-item-id*="price"], div[aria-label*="£"], div[aria-label*="$"]').first
                        if await p_el.is_visible(timeout=400):
                            price = clean_text(await p_el.inner_text())
                    except Exception:
                        pass

                    # Extract Plus Code
                    plus_code = ""
                    try:
                        pc_el = maps_page.locator('button[data-item-id="oloc"], button[aria-label*="Plus code"]').first
                        if await pc_el.is_visible(timeout=400):
                            plus_code = clean_text(await pc_el.inner_text())
                    except Exception:
                        pass

                    # Extract GPS Coordinates (Lat, Lon) from Google Maps URL
                    lat_val = None
                    lon_val = None
                    url_match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", maps_page.url)
                    if url_match:
                        lat_val = float(url_match.group(1))
                        lon_val = float(url_match.group(2))
                    else:
                        data_match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", maps_page.url)
                        if data_match:
                            lat_val = float(data_match.group(1))
                            lon_val = float(data_match.group(2))

                    # --- RADIUS FILTERING (Strict Haversine Distance Check) ---
                    if lat is not None and lon is not None and radius_km is not None and lat_val is not None and lon_val is not None:
                        dist_km = calculate_haversine_distance_km(lat, lon, lat_val, lon_val)
                        if dist_km > (radius_km * 1.15):
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
                        if phone_digits and len(phone_digits) >= 7 and phone_digits in seen_phones:
                            emit_event("log", f"🔄 [Area Dedup] Skipped '{place_title}' (phone matches existing shop).")
                            continue
                        if dom and dom in seen_domains:
                            emit_event("log", f"🔄 [Area Dedup] Skipped '{place_title}' (domain '{dom}' matches existing shop).")
                            continue

                    if skip_existing_db:
                        if is_lead_in_db(place_title, address):
                            emit_event("log", f"🏢 [DB Dedup] Skipped '{place_title}' (already saved in database).")
                            continue

                    seen_signatures.add((norm_name, norm_addr))
                    if phone_digits and len(phone_digits) >= 7:
                        seen_phones.add(phone_digits)
                    if dom:
                        seen_domains.add(dom)

                    place_info = {
                        "index": idx,
                        "name": place_title,
                        "category": category or "Business",
                        "address": address or "N/A",
                        "phone": phone or "N/A",
                        "hours": hours or "N/A",
                        "price": price or "N/A",
                        "plus_code": plus_code or "N/A",
                        "emails": [],
                        "email": "N/A",
                        "instagram": "",
                        "facebook": "",
                        "linkedin": "",
                        "twitter": "",
                        "screenshot": "",
                        "bot_protection": "Inspecting..." if (enable_website and extract_emails and website) else "N/A",
                        "cookie_status": "Inspecting..." if (enable_website and extract_emails and website) else "None",
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
                    emit_event("log", f"✅ Added: {place_title} | 🏷️ {category or 'Business'} | 📞 {phone or 'N/A'}")

                    # -----------------------------------------------------------------
                    # PARALLEL PIPELINE: Send website job to Tab 2 simultaneously!
                    # Tab 1 DOES NOT STOP! It immediately moves to the next place!
                    # -----------------------------------------------------------------
                    if enable_website and extract_emails and website and website.startswith("http") and website_queue:
                        website_queue.put_nowait({
                            "index": idx,
                            "name": place_title,
                            "address": address or "N/A",
                            "website": website,
                        })
                    elif enable_linkedin and linkedin_queue:
                        linkedin_queue.put_nowait({
                            "index": idx,
                            "name": place_title,
                            "address": address or "N/A",
                            "website": website if (website and website != "N/A") else "",
                            "linkedin_url": "",
                        })

                    if enable_platform and platform_queue:
                        platform_queue.put_nowait({
                            "index": idx,
                            "name": place_title,
                            "address": address or "N/A",
                            "lat": lat_val,
                            "lon": lon_val,
                            "id": lead_db_id,
                        })

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
                    emit_event("log", "🏁 Reached the end of Google Maps results!")
            except Exception:
                pass

            if end_reached:
                break

            scroll_attempts += 1
            if new_found_this_scroll == 0:
                consecutive_no_new += 1
            else:
                consecutive_no_new = 0

            if consecutive_no_new >= 8 and scrape_all:
                emit_event("log", "No new places loaded after 8 scrolls. All area shops captured.")
                break

            emit_event("log", f"📜 Scrolling Tab 1 feed down to load more shops (Pass {scroll_attempts})...")
            try:
                feed = maps_page.locator('div[role="feed"]').first
                if await feed.is_visible(timeout=1000):
                    await feed.evaluate("el => el.scrollBy(0, 1600)")
                    await maps_page.wait_for_timeout(1800)
            except Exception:
                await maps_page.mouse.wheel(0, 1200)
                await maps_page.wait_for_timeout(1800)

        emit_event("status", "Google Maps harvesting complete. Finalizing website & LinkedIn org inspections...")

        # Signal website worker that no more places will be added from Maps
        website_done_event.set()
        if worker_task and website_queue:
            try:
                await asyncio.wait_for(website_queue.join(), timeout=45.0)
            except Exception:
                pass
            worker_task.cancel()

        # Signal LinkedIn worker that all companies have been pushed and wait for org intelligence to complete
        linkedin_done_event.set()
        if linkedin_task and linkedin_queue:
            try:
                await asyncio.wait_for(linkedin_queue.join(), timeout=60.0)
            except Exception:
                pass
            linkedin_task.cancel()

        # Signal Platform worker that all places have been pushed and wait for directory scan to complete
        platform_done_event.set()
        if platform_task and platform_queue:
            try:
                await asyncio.wait_for(platform_queue.join(), timeout=60.0)
            except Exception:
                pass
            platform_task.cancel()

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, default="shops")
    parser.add_argument("--max", type=int, default=15)
    parser.add_argument("--scrape-all", action="store_true")
    parser.add_argument("--visible", dest="visible", action="store_true", default=True)
    parser.add_argument("--headless", dest="visible", action="store_false")
    parser.add_argument("--extract-emails", action="store_true")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--zoom", type=int, default=14)
    parser.add_argument("--radius-km", type=float, default=5.0)
    parser.add_argument("--enable-maps", dest="enable_maps", action="store_true", default=True)
    parser.add_argument("--no-maps", dest="enable_maps", action="store_false")
    parser.add_argument("--enable-website", dest="enable_website", action="store_true", default=True)
    parser.add_argument("--no-website", dest="enable_website", action="store_false")
    parser.add_argument("--enable-linkedin", dest="enable_linkedin", action="store_true", default=True)
    parser.add_argument("--no-linkedin", dest="enable_linkedin", action="store_false")
    parser.add_argument("--enable-platform", dest="enable_platform", action="store_true", default=False)
    parser.add_argument("--no-platform", dest="enable_platform", action="store_false")
    parser.add_argument("--platform-name", type=str, default="Fresha")
    parser.add_argument("--platform-custom-url", type=str, default="")
    parser.add_argument("--dedup-area", dest="dedup_area", action="store_true", default=True)
    parser.add_argument("--no-dedup-area", dest="dedup_area", action="store_false")
    parser.add_argument("--skip-existing-db", action="store_true", default=False)
    parser.add_argument("--standalone-companies", type=str, default=None)
    args = parser.parse_args()

    asyncio.run(run_scraper(
        query=args.query,
        max_results=args.max,
        scrape_all=args.scrape_all,
        visible_browser=args.visible,
        extract_emails=args.extract_emails,
        lat=args.lat,
        lon=args.lon,
        zoom=args.zoom,
        radius_km=args.radius_km,
        enable_maps=args.enable_maps,
        enable_website=args.enable_website,
        enable_linkedin=args.enable_linkedin,
        enable_platform=args.enable_platform,
        platform_name=args.platform_name,
        platform_custom_url=args.platform_custom_url,
        dedup_area=args.dedup_area,
        skip_existing_db=args.skip_existing_db,
        standalone_companies=args.standalone_companies,
    ))
