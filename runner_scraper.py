import urllib.parse
import argparse
import asyncio
import base64
import datetime
import json
import logging
import os
import re
import sys
import math
import time
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from database import save_lead, save_employees_batch, classify_seniority, clean_domain, is_lead_in_db, save_platform_listing, normalize_all_platform_listings, get_tables_split_data, extract_core_brand_name, load_proximity_dedup_cache, is_place_already_scraped, is_platform_listing_already_scraped, get_pending_resume_leads, get_cached_census_total, set_cached_census_total, update_lead_website_data
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
        if not any(bad in lower for bad in ["/p/", "/explore", "/reels", "/stories", "sharer", "/about", "instagram.com/direct", "/legal", "instagram.com/?", "help.instagram.com", "about.meta.com"]):
            path = urllib.parse.urlparse(cleaned).path.strip("/")
            if path and "/" not in path and len(path) > 1:
                socials["instagram"] = cleaned
                break

    # Facebook
    for raw in candidates["facebook"]:
        cleaned = clean_social_url(raw)
        lower = cleaned.lower()
        if not any(bad in lower for bad in ["sharer", "/share", "/dialog", "/login", "/plugins", "facebook.com/tr", "/policies", "/help", "developers.facebook.com", "business.facebook.com"]):
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

        await asyncio.sleep(0.8)

async def clear_fixed_viewport(page):
    if not page:
        return
    try:
        cdp_sess = await page.context.new_cdp_session(page)
        await cdp_sess.send("Emulation.clearDeviceMetricsOverride")
        await cdp_sess.detach()
    except Exception:
        pass

async def website_worker(context, queue: asyncio.Queue, done_event: asyncio.Event, website_page=None, maps_page=None, linkedin_queue: asyncio.Queue = None, pages_dict: Dict = None, cdp_connected: bool = False):
    tab_page = website_page
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

        # Prevent opening Meta platforms (Instagram, Facebook, Threads, Meta) in Tab 2
        w_low = website_url.lower()
        meta_domains = ["facebook.com", "instagram.com", "fb.com", "meta.com", "fb.me", "threads.net", "m.facebook.com"]
        if any(m in w_low for m in meta_domains):
            is_ig = "instagram.com" in w_low
            plat_name = "Instagram" if is_ig else "Facebook"
            emit_event("log", f"ℹ️ [Meta Platform Bypassed] #{idx} '{name}' uses {plat_name} as primary web link. Recorded under socials without opening Meta platform.")
            try:
                with get_connection() as conn:
                    if is_ig:
                        conn.execute("UPDATE leads SET instagram = ?, bot_protection = 'Social Profile (Instagram)', website_status = 'social' WHERE id = ? OR (name = ? AND address = ?)", (website_url, idx, name, address))
                    else:
                        conn.execute("UPDATE leads SET facebook = ?, bot_protection = 'Social Profile (Facebook)', website_status = 'social' WHERE id = ? OR (name = ? AND address = ?)", (website_url, idx, name, address))
                emit_event("place_updated", {
                    "id": idx, "name": name, "address": address, "website": website_url,
                    "instagram": website_url if is_ig else "",
                    "facebook": website_url if not is_ig else "",
                    "bot_protection": f"Social Profile ({plat_name})"
                })
            except Exception:
                pass
            queue.task_done()
            continue

        emit_event("log", f"🌐 [Tab 2 - Simultaneous] Inspecting shop website: {website_url}")
        emit_event("status", f"Browsing website #{idx}: {name}")

        try:

            # Strict Tab 2 Isolation: Dedicated page for Shop Website (Never touches Maps, LinkedIn, or Platform tabs)
            if tab_page is None or tab_page.is_closed():
                tab_page = await context.new_page()
                await clear_fixed_viewport(tab_page)
                try:
                    await tab_page.route("**/*.{mp4,mp3,avi,webm,mkv,wav,ogg,woff,woff2,ttf,eot}", lambda r: r.abort())
                except Exception:
                    pass
                if pages_dict is not None:
                    pages_dict["website"] = tab_page

            # Navigate dedicated tab to shop website with complete DOM & load state wait
            try:
                await tab_page.goto(website_url, wait_until="domcontentloaded", timeout=15000)
                try:
                    await tab_page.wait_for_load_state("load", timeout=3500)
                except Exception:
                    pass
                await tab_page.wait_for_timeout(800)
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

            # 4. Extract Emails & Social Media Links (Universal JSON-LD Schema + DOM Regex)
            fresh_html = await tab_page.content()
            emails = set(extract_emails_from_text(fresh_html))
            socials = extract_socials_from_text(fresh_html)

            # Universal Contract 1: Extract structured Schema.org / JSON-LD metadata
            try:
                ld_data = await tab_page.evaluate(r"""() => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    const ems = [];
                    const socs = {};
                    for (const s of scripts) {
                        try {
                            const raw = JSON.parse(s.innerText || s.textContent || "{}");
                            const items = Array.isArray(raw) ? raw : (raw['@graph'] || [raw]);
                            for (const item of items) {
                                if (item.email) {
                                    const em = String(item.email).replace(/^mailto:/i, '').trim();
                                    if (em.includes('@')) ems.push(em);
                                }
                                if (item.sameAs) {
                                    const links = Array.isArray(item.sameAs) ? item.sameAs : [item.sameAs];
                                    for (const l of links) {
                                        const u = String(l).toLowerCase();
                                        if (u.includes('instagram.com/')) socs['instagram'] = l;
                                        if (u.includes('facebook.com/')) socs['facebook'] = l;
                                        if (u.includes('linkedin.com/')) socs['linkedin'] = l;
                                        if (u.includes('twitter.com/') || u.includes('x.com/')) socs['twitter'] = l;
                                    }
                                }
                            }
                        } catch(e) {}
                    }
                    return { emails: ems, socials: socs };
                }""")
                if ld_data:
                    if ld_data.get("emails"):
                        emails.update(ld_data["emails"])
                    if ld_data.get("socials"):
                        for k, v in ld_data["socials"].items():
                            if not socials.get(k) and v:
                                socials[k] = v
            except Exception:
                pass

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

            # 5. Check Contact / About links if emails or socials are missing (Strictly internal only - NEVER click Meta or external socials)
            if not emails or not any(socials.values()):
                try:
                    contact_links = tab_page.locator('a[href*="contact" i], a[href*="about" i], a:has-text("Contact"), a:has-text("About")')
                    count = await contact_links.count()
                    for ci in range(min(count, 4)):
                        c_link = contact_links.nth(ci)
                        href_attr = (await c_link.get_attribute("href") or "").lower()
                        # Strictly skip external social and Meta links
                        if any(bad in href_attr for bad in ["facebook.com", "instagram.com", "meta.com", "fb.me", "threads.net", "twitter.com", "x.com", "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com"]):
                            continue
                        if await c_link.is_visible(timeout=800):
                            await c_link.click(timeout=3000)
                            await tab_page.wait_for_timeout(1800)
                            sub_html = await tab_page.content()
                            emails.update(extract_emails_from_text(sub_html))
                            sub_socials = extract_socials_from_text(sub_html)
                            for k, v in sub_socials.items():
                                if not socials.get(k) and v:
                                    socials[k] = v
                            break
                except Exception:
                    pass

            email_list = sorted(list(emails))
            primary_email = email_list[0] if email_list else ""

            # If emails were successfully extracted from the page, confirm Access Granted
            if primary_email and "Access Denied" in bot_status:
                bot_status = bot_status.replace("Access Denied", "Access Granted")
                emit_event("log", f"🎉 [Access Granted] Contact emails extracted from #{idx} {name}!")

            # Immediately update lead record in SQLite database!
            w_status = "found"
            if email_list:
                w_status = "emails_found"
            elif socials.get("instagram") or socials.get("facebook") or socials.get("twitter"):
                w_status = "socials_found"

            try:
                update_lead_website_data(
                    name=name,
                    address=address,
                    website=website_url,
                    email=primary_email,
                    instagram=socials.get("instagram", ""),
                    facebook=socials.get("facebook", ""),
                    linkedin=socials.get("linkedin", ""),
                    twitter=socials.get("twitter", ""),
                    screenshot=rel_screenshot_path,
                    bot_protection=bot_status,
                    cookie_status=cookie_status,
                    website_status=w_status
                )
            except Exception as dbe:
                pass

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
                "website_status": w_status
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
                        await tab_page.goto(search_co_url, wait_until="domcontentloaded", timeout=15000)
                        try:
                            await tab_page.wait_for_selector('.entity-result, li.reusable-search__result-container, .search-results-container, div[data-view-name]', timeout=4000)
                        except Exception:
                            await tab_page.wait_for_timeout(1000)
                        li_result = await tab_page.evaluate(r"""() => {
                            // Find all company profile links in search results (works with modern LinkedIn div[data-view-name] and legacy .entity-result)
                            const companyLinks = document.querySelectorAll('a[href*="/company/"]:not([href*="ads"]):not([href*="linkedin.com/help"])');
                            for (const link of companyLinks) {
                                const href = link.href.split('?')[0].replace(/\/+$/, '');
                                if (href.includes('/company/') && !href.includes('/company/setup') && !href.includes('/search') && !href.includes('/feed')) {
                                    const container = link.closest('.entity-result, li, div[data-view-name], .artdeco-entity-lockup, div.search-results-container') || link;
                                    const titleEl = container.querySelector('.entity-result__title-text, .app-aware-link, .artdeco-entity-lockup__title, span[aria-hidden="true"], h2, h3, a') || link;
                                    const rawTitle = titleEl.innerText || titleEl.textContent || "";
                                    const title = rawTitle.split('\n')[0].replace(/•.*/, '').trim();
                                    if (title && href.split('/company/')[1]) {
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
                    try:
                        await tab_page.wait_for_selector('div.org-people-profile-card, ul.org-people-profiles-module__profile-list, [data-view-name="org-people-profile-card"], .org-people-profiles-module, a[href*="/in/"]', timeout=3500)
                    except Exception:
                        await tab_page.wait_for_timeout(1000)
                except Exception as e:
                    emit_event("log", f"⚠️ Navigation note: {str(e)[:50]}")

                try:
                    safe_name = re.sub(r'[\'"]', '', core_brand)[:22]
                    await tab_page.evaluate(f"() => window.MavonScraper && window.MavonScraper.showHUD('LinkedIn: {safe_name}', 'Harvesting employees & leadership...', '#0a66c2')")
                except Exception:
                    pass

                # Micro-Business Fast-Exit Check (Company has 0 public employees or redirected away from /people/)
                curr_p_url = (tab_page.url or "").lower()
                is_zero_employees = await tab_page.evaluate(r"""() => {
                    const text = (document.body.innerText || "").toLowerCase();
                    if (text.includes("0 employees on linkedin") || text.includes("0 people") || text.includes("no people to show")) {
                        return true;
                    }
                    const inLinks = document.querySelectorAll('a[href*="/in/"]:not([href*="linkedin.com/help"])');
                    if (inLinks.length === 0 && (window.location.href.includes('/about') || !window.location.href.includes('/people'))) {
                        return true;
                    }
                    return false;
                }""")

                if is_zero_employees or ("/about" in curr_p_url and "/people" not in curr_p_url):
                    emit_event("log", f"ℹ️ [LinkedIn Fast-Exit] '{core_brand}' is a boutique / micro-business (0 public LinkedIn employees). Bypassing progressive scrolls.")
                else:
                    # Step 3: Progressive DOM scrolling to bypass top insights and reveal employee cards
                    emit_event("log", f"📜 [LinkedIn Step 3/5 - Progressive Scroll] Triggering member cards discovery on /people/...")
                    try:
                        await tab_page.evaluate(r"""() => {
                            const target = document.querySelector('.org-people-profiles-module, ul.org-people-profiles-module__profile-list, [data-view-name="org-people-profile-card"]');
                            if (target) {
                                target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            } else {
                                window.scrollBy({ top: 1100, behavior: 'smooth' });
                            }
                        }""")
                        await tab_page.wait_for_timeout(800)
                    except Exception:
                        pass

                    for s_i in range(3):
                        try:
                            await tab_page.evaluate("window.scrollBy({top: 900})")
                            await tab_page.wait_for_timeout(350)
                        except Exception:
                            break

                # Step 4: Universal Extract from company /people/ tab
                emit_event("log", f"🔍 [LinkedIn Step 4/5 - Card Parsing] Extracting employee cards from company directory...")
                try:
                    raw_extracted = await tab_page.evaluate(r"""() => {
                        const list = [];
                        const seenUrls = new Set();
                        const seenNames = new Set();

                        // Universal extraction: scan all /in/ profile anchors on the page
                        const profileLinks = document.querySelectorAll('a[href*="/in/"]:not([href*="linkedin.com/help"])');
                        for (const link of profileLinks) {
                            const profile = link.href.split('?')[0].replace(/\/+$/, '');
                            if (!profile || seenUrls.has(profile) || profile.endsWith('/in') || profile.endsWith('/in/')) {
                                continue;
                            }

                            const card = link.closest(
                                'div.org-people-profile-card, ' +
                                'li.org-people-profile-card__profile-card-spacing, ' +
                                'div[data-view-name*="people"], ' +
                                'div[data-view-name="org-people-profile-card"], ' +
                                'ul.org-people-profiles-module__profile-list > li, ' +
                                '.org-people-profiles-module__profile-list li, ' +
                                '.entity-result, ' +
                                'li.reusable-search__result-container, ' +
                                'li, div'
                            ) || link;

                            let nameEl = card.querySelector(
                                '.org-people-profile-card__profile-title, ' +
                                '.artdeco-entity-lockup__title a, ' +
                                '.artdeco-entity-lockup__title, ' +
                                'a[data-field="name"], ' +
                                '.entity-result__title-text a, ' +
                                'span[aria-hidden="true"], ' +
                                'h3, h2'
                            );
                            let titleEl = card.querySelector(
                                '.lt-line-clamp--multi-line, ' +
                                '.artdeco-entity-lockup__subtitle, ' +
                                'div.artdeco-entity-lockup__caption, ' +
                                '.org-people-profile-card__profile-position, ' +
                                '.entity-result__primary-subtitle'
                            );
                            let imgEl = card.querySelector('img[src*="licdn.com"], img.org-people-profile-card__profile-picture, img.presence-entity__image');
                            let locEl = card.querySelector('.entity-result__secondary-subtitle, .org-people-profile-card__profile-location');

                            let rawName = nameEl ? (nameEl.innerText || nameEl.textContent || "").trim() : "";
                            let rawTitle = titleEl ? (titleEl.innerText || titleEl.textContent || "").trim() : "";
                            let avatar = imgEl ? imgEl.src : "";
                            let loc = locEl ? (locEl.innerText || locEl.textContent || "").trim() : "";

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
                                seenUrls.add(profile);
                                seenNames.add(cleanName);
                                list.push({
                                    full_name: cleanName,
                                    title: cleanTitle || "Employee",
                                    linkedin_profile_url: profile,
                                    avatar_url: avatar,
                                    location: loc
                                });
                            }
                        }
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

            # Save batch to SQLite with explicit lead_id reference
            lead_id_target = item.get("id") or item.get("lead_id")
            saved = save_employees_batch(company_name=name, employees=employees, lead_id=lead_id_target, company_linkedin_url=final_linkedin_url)

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


def parse_search_query_and_location(query: str, lat: Optional[float] = None, lon: Optional[float] = None) -> Tuple[str, str]:
    """Extracts category/keyword and geographic location/proximity from user search query and coordinates."""
    q = (query or "").strip()
    category = q
    location_name = ""

    m = re.split(r'\s+(?:in|near|at|around)\s+', q, maxsplit=1, flags=re.I)
    if len(m) == 2:
        category = m[0].strip()
        location_name = m[1].strip()
    elif "," in q:
        parts = q.split(",", 1)
        category = parts[0].strip()
        location_name = parts[1].strip()
    elif lat is not None and lon is not None:
        if 18.8 <= float(lat) <= 19.4 and 72.7 <= float(lon) <= 73.2:
            location_name = "Mumbai"
        else:
            location_name = f"{lat:.2f},{lon:.2f}"
    else:
        location_name = q

    return category or "Business", location_name or "Area"

def build_platform_area_url(platform_name: str, category: str, location_name: str, custom_pattern: str = "") -> str:
    """
    Builds area/proximity search URL for ANY directory platform.
    Supports built-in platforms, custom templates ({query}, {location}, {category}, {city}),
    direct domain names, and smart fallback discovery.
    """
    p_lower = platform_name.lower().strip()
    enc_cat = urllib.parse.quote_plus(category)
    enc_loc = urllib.parse.quote_plus(location_name)
    loc_hyphen = urllib.parse.quote(re.sub(r'\s+', '-', location_name.strip()))
    cat_hyphen = urllib.parse.quote(re.sub(r'\s+', '-', category.strip()))

    # 1. Custom URL pattern with template variable replacement
    if custom_pattern and "http" in custom_pattern:
        url = custom_pattern
        url = url.replace("{query}", enc_cat).replace("{category}", enc_cat)
        url = url.replace("{location}", enc_loc).replace("{city}", enc_loc)
        url = url.replace("{loc_slug}", loc_hyphen).replace("{cat_slug}", cat_hyphen)
        if "{" not in custom_pattern and ("?" not in custom_pattern or "=" not in custom_pattern):
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}q={enc_cat}&location={enc_loc}"
        return url

    # 2. If platform_name itself is a full URL
    if p_lower.startswith("http://") or p_lower.startswith("https://"):
        url = platform_name
        if "{" in url:
            url = url.replace("{query}", enc_cat).replace("{category}", enc_cat)
            url = url.replace("{location}", enc_loc).replace("{city}", enc_loc)
        else:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}q={enc_cat}&location={enc_loc}"
        return url

    # 3. Built-in Smart Templates for known popular directories
    if "fresha" in p_lower:
        return f"https://www.fresha.com/search?query={enc_cat}&address={enc_loc}"
    elif "airbnb" in p_lower:
        return f"https://www.airbnb.com/s/{loc_hyphen}/homes?query={enc_cat}"
    elif "yelp" in p_lower:
        return f"https://www.yelp.com/search?find_desc={enc_cat}&find_loc={enc_loc}"
    elif "tripadvisor" in p_lower:
        return f"https://www.tripadvisor.com/Search?q={enc_cat}+{enc_loc}"
    elif "booking" in p_lower:
        return f"https://www.booking.com/searchresults.html?ss={enc_loc}+{enc_cat}"
    elif "zomato" in p_lower:
        return f"https://www.zomato.com/{loc_hyphen.lower()}/restaurants?q={enc_cat}"
    elif "justdial" in p_lower:
        return f"https://www.justdial.com/{loc_hyphen}/{enc_cat}"
    elif "treatwell" in p_lower:
        return f"https://www.treatwell.co.uk/places/treatment-{cat_hyphen.lower()}/in-{loc_hyphen.lower()}/"
    elif "yellowpages" in p_lower:
        return f"https://www.yellowpages.com/search?search_terms={enc_cat}&geo_location_terms={enc_loc}"
    elif "opentable" in p_lower:
        return f"https://www.opentable.com/s?term={enc_cat}&near={enc_loc}"
    elif "trustpilot" in p_lower:
        return f"https://www.trustpilot.com/search?query={enc_cat}+{enc_loc}"

    # 4. If platform_name is a domain (e.g. "somedirectory.com")
    if "." in p_lower and " " not in p_lower:
        clean_dom = p_lower.replace("www.", "")
        return f"https://www.{clean_dom}/search?q={enc_cat}&location={enc_loc}"

    # 5. Fallback: Proximity site search or Google directory discovery
    return f"https://www.google.com/search?q={enc_cat}+{enc_loc}+{urllib.parse.quote_plus(platform_name)}"


PLATFORM_PROFILES = {
    "Fresha": {"baseline_sec": 5.0, "timeout_sec": 6.0, "color": "#a855f7", "icon": "🟣"},
    "Airbnb": {"baseline_sec": 6.0, "timeout_sec": 7.2, "color": "#ef4444", "icon": "🔴"},
    "Yelp": {"baseline_sec": 4.5, "timeout_sec": 5.4, "color": "#f97316", "icon": "🟠"},
    "TripAdvisor": {"baseline_sec": 5.5, "timeout_sec": 6.6, "color": "#10b981", "icon": "🟢"},
    "Google Maps": {"baseline_sec": 4.5, "timeout_sec": 5.4, "color": "#3b82f6", "icon": "🗺️"},
}

async def extract_platform_total_count(platform_page, platform_name: str) -> int:
    """
    Parses exact count badge rendered by directory platforms on proximity search.
    """
    try:
        return await platform_page.evaluate(r"""(p) => {
            const text = document.body.innerText || '';
            if (p === 'Airbnb') {
                const counter = document.querySelector('[data-testid="results-counter"], h1 span, [class*="results-counter"]');
                if (counter) {
                    const m = counter.innerText.match(/(\d[\d,]*)\s+(?:stays?|places?|homes?)/i);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
            } else if (p === 'Yelp') {
                const el = document.querySelector('[class*="pagination-results-count"], span.css-1122ukr');
                if (el) {
                    const m = el.innerText.match(/of\s+(\d[\d,]*)/i);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
            } else if (p === 'TripAdvisor') {
                const el = document.querySelector('.geos_widget_title, [class*="result-count"]');
                if (el) {
                    const m = el.innerText.match(/(\d[\d,]*)\s+(?:places?|properties|restaurants)/i);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
            }
            const gen = text.match(/\b(\d[\d,]*)\s+(?:results?|listings?|places?|venues?)\b/i);
            return gen ? parseInt(gen[1].replace(/,/g, '')) : 0;
        }""", platform_name)
    except Exception:
        return 0

async def platform_area_search_worker(
    context,
    platform_page,
    selected_platforms: List[str],
    category: str,
    location_name: str,
    radius_km: float = 5.0,
    max_results: int = 15,
    custom_url_pattern: str = "",
    visible_browser: bool = True,
    dedup_cache: Dict[str, Any] = None,
):
    """
    Dedicated Proximity & Area Worker for Tab 4 (Multi-Source Platform Directory Scout).
    Operates identically to Google Maps area scraping:
    Searches the platform directly for the target category/query in the target geographic area/locality,
    smoothly scrolls to discover all proximity listing cards, clicks cards to inspect verified details,
    extracts ratings/reviews/prices/booking URLs, captures detail screenshots, and stores them into the database.
    """
    try:
        if not selected_platforms:
            selected_platforms = ["Fresha"]

        active_clean_platforms = [p.strip() for p in selected_platforms if p.strip()]
        emit_event("log", f"🟣 [Tab 4 Platform Scout] Target platforms active ({len(active_clean_platforms)}): {', '.join(active_clean_platforms)}")

        # =========================================================================
        # PHASE 1: PROXIMITY CENSUS (Discover total businesses across ALL platforms)
        # =========================================================================
        platform_totals = {}
        for p_name in active_clean_platforms:
            target_url = build_platform_area_url(p_name, category, location_name, custom_url_pattern)
            prof = PLATFORM_PROFILES.get(p_name, {"baseline_sec": 5.0, "timeout_sec": 12.0})
            timeout_ms = 15000  # Generous 15s timeout to prevent premature aborts

            emit_event("status", f"Census: Probing {p_name} volume for '{category}' in '{location_name}'...")
            emit_event("log", f"🎯 [Proximity Census] Probing {p_name} total available businesses in '{location_name}'...")
            emit_event("platform_navigated", {"url": target_url, "title": f"{p_name} Proximity Census", "platform": p_name})

            # Check if verified total was already discovered for this platform & location
            cached_tot = get_cached_census_total(p_name, category, location_name)
            if cached_tot and cached_tot > 0:
                final_plat_total = cached_tot
                emit_event("log", f"⚡ [Census Cache] Reusing verified count for {p_name} in '{location_name}': ~{final_plat_total} businesses (Bypassing redundant probe).")
            else:
                detected_total = 0
                try:
                    await platform_page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await platform_page.wait_for_timeout(1000)

                    detected_total = await extract_platform_total_count(platform_page, p_name)
                    if detected_total <= 0:
                        detected_total = await platform_page.evaluate("""() => {
                            return document.querySelectorAll('div[data-testid="card-container"], div[data-qa="venue-card"], li.border-color--default__09f24__Nrmcg, div.listing_details, article, [role="article"]').length;
                        }""")
                except Exception as ce:
                    emit_event("log", f"⚠️ [Proximity Census] {p_name} network response slow. Defaulting to progressive count.")

                final_plat_total = max(detected_total, max_results if max_results > 0 else 15)
                set_cached_census_total(p_name, category, location_name, final_plat_total)

            platform_totals[p_name] = final_plat_total
            emit_event("proximity_total", {
                "platform": p_name,
                "query": category,
                "location": location_name,
                "total": final_plat_total
            })
            emit_event("platform_progress", {
                "platform": p_name,
                "scraped": 0,
                "skipped": 0,
                "total": final_plat_total,
                "percent": 0
            })
            emit_event("log", f"🎯 [Proximity Census Result] {p_name} reports ~{final_plat_total} businesses/listings in {location_name}.")

        emit_event("log", "✅ Proximity Census Complete across all selected platforms. Beginning sequential harvesting...")

        # =========================================================================
        # PHASE 2: SEQUENTIAL HARVESTING & CARD CLICKING (1 Platform After Another)
        # =========================================================================
        for plat_idx, p_name in enumerate(active_clean_platforms, 1):
            try:
                target_url = build_platform_area_url(p_name, category, location_name, custom_url_pattern)
                plat_total = platform_totals.get(p_name, max_results)
                plat_scraped = 0
                plat_skipped = 0

                emit_event("status", f"Platform Scout [{plat_idx}/{len(active_clean_platforms)}]: Harvesting {p_name} in '{location_name}'...")
                emit_event("log", f"🟣 [Tab 4 - Stage {plat_idx}/{len(active_clean_platforms)}] Harvesting {p_name} for '{category}' in '{location_name}'...")
                emit_event("platform_navigated", {"url": target_url, "title": f"{p_name}: {category} in {location_name}", "platform": p_name})

                try:
                    if platform_page.url != target_url:
                        await platform_page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                        try:
                            await platform_page.wait_for_load_state("load", timeout=3500)
                        except Exception:
                            pass
                        await platform_page.wait_for_timeout(1000)
                except Exception as nav_e:
                    emit_event("log", f"⚠️ [Tab 4 - {p_name}] Navigation notice: {str(nav_e)[:60]}")

                # Show HUD on Tab 4
                try:
                    safe_loc = re.sub(r'[\'\"]', '', location_name)[:25]
                    await platform_page.evaluate(f"() => window.MavonScraper && window.MavonScraper.showHUD('Platform: {p_name}', 'Harvesting {category} in {safe_loc}...', '#a855f7')")
                except Exception:
                    pass

                # 1. Accept cookies & handle anti-bot on directory page
                try:
                    await detect_and_handle_cookies(platform_page)
                except Exception:
                    pass
                try:
                    await attempt_turnstile_solve(platform_page)
                except Exception:
                    pass

                # 2. Dismiss any blocking dialogs, currency selectors, sign-in banners, or location modals
                try:
                    await platform_page.evaluate("""() => {
                        const dismiss = [
                            'button[aria-label="Close"]', 'button[aria-label*="close" i]',
                            'button[data-testid*="modal-close"]', 'button[data-testid="modal-container-close"]',
                            'div[aria-label="Close"]', '.modal-close', 'button.close',
                            '[data-qa*="close"]', 'button[aria-label="Dismiss"]'
                        ];
                        for (const sel of dismiss) {
                            document.querySelectorAll(sel).forEach(el => { try { el.click(); } catch(e){} });
                        }
                        // Check button text safely without pseudo-selectors
                        document.querySelectorAll('button').forEach(b => {
                            const t = (b.innerText || '').toLowerCase().trim();
                            if (t === 'accept' || t === 'agree' || t === 'ok' || t === 'continue without supporting') {
                                try { b.click(); } catch(e){}
                            }
                        });
                    }""")
                except Exception:
                    pass

                # 5X PLATFORM SPEEDUP: Abort heavy images, videos, webfonts, and third-party trackers
                async def handle_plat_routes(route):
                    req_type = route.request.resource_type
                    r_url = route.request.url.lower()
                    if req_type in ["image", "media", "font"]:
                        await route.abort()
                    elif any(ext in r_url for ext in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".mp4", ".woff", ".woff2"]):
                        await route.abort()
                    elif any(trk in r_url for trk in ["google-analytics", "doubleclick", "segment.io", "datadoghq", "sentry", "facebook.net"]):
                        await route.abort()
                    else:
                        await route.continue_()

                try:
                    await platform_page.route("**/*", handle_plat_routes)
                except Exception:
                    pass

                # =====================================================================
                # PROGRESSIVE MULTI-PASS SCROLLING & DISCOVERY
                # =====================================================================
                is_infinite = (scrape_all or max_results >= 9999)
                max_scroll_passes = 9999 if is_infinite else max(8, min(60, (max_results // 2) + 6))
                consecutive_stagnant = 0
                extracted_listings = []
                seen_listing_urls = set()

                emit_event("log", f"📜 [Tab 4 - {p_name}] Beginning progressive scrolling discovery (Target: {max_results} listings)...")

                for scroll_pass in range(1, max_scroll_passes + 1):
                    # Extract cards currently in DOM
                    current_batch = await platform_page.evaluate(r"""() => {
                        const results = [];
                        const currUrl = window.location.href;
                        const isAirbnb = currUrl.includes('airbnb');
                        const isFresha = currUrl.includes('fresha');
                        const isYelp = currUrl.includes('yelp');
                        const isTripAdvisor = currUrl.includes('tripadvisor');

                        const junkRegex = /^(?:filters?|filter\s*\(?\d*\)?|show\s+map|map|search|clear\s+all|explore|instant\s+book|rooms\s+and\s+beds|property\s+type|amenities|sort\s+by|guest\s+favorites?|menu|view\s+in\s+map|sign\s+in|log\s+in|navigation|next|previous|page\s+\d+|categories|ratings?|prices?|display\s+total|share|save)$/i;

                        let cardSelectors = [];
                        if (isAirbnb) {
                            cardSelectors = ['div[data-testid="card-container"]', 'div[itemprop="itemListElement"]', 'div[aria-labelledby*="title_"]', 'div[class*="c4mnd7m"]', 'a[href*="/rooms/"]'];
                        } else if (isFresha) {
                            cardSelectors = ['div[data-qa="venue-card"]', 'div.venue-card', 'a[href*="/a/"]', 'a[href*="/v/"]', 'a[href*="/b/"]', '[class*="venueCard"]', 'article'];
                        } else if (isYelp) {
                            cardSelectors = ['div[data-testid="serp-ia-card"]', 'li.border-color--default__09f24__Nrmcg', 'div.container__09f24__FeTO7', 'div[class*="container__"]'];
                        } else if (isTripAdvisor) {
                            cardSelectors = ['div.listing_details', 'div.listItem', 'div[data-automation="hotel-card-title"]', 'div.result-card', 'div[data-block-id]', 'div[class*="listItem"]'];
                        } else {
                            cardSelectors = [
                                'article', '[role="article"]',
                                'div[data-testid*="property-card"]', 'div[data-testid*="listing"]', 'div[data-testid*="card"]', 'div[data-testid*="result"]',
                                'div[itemprop="itemListElement"]', 'li[itemprop="itemListElement"]',
                                'div.search-result', 'li.search-result', 'div.search-result-card', 'div.search-item',
                                'div.venue-card', 'div.place-card', 'div.businessCard', 'div.listing-card', 'div.result-card',
                                'div.directory-card', 'div.directory-item', 'div.store-card', 'div.vendor-card',
                                'div.property-card', 'a.property-card'
                            ];
                        }

                        let cards = Array.from(document.querySelectorAll(cardSelectors.join(', ')));

                        if (cards.length === 0) {
                            const headingLinks = document.querySelectorAll('main h2 a, main h3 a, main h4 a, #root h2 a, #root h3 a, body h2 a, body h3 a');
                            const seenContainers = new Set();
                            headingLinks.forEach(hl => {
                                const cont = hl.closest('article, [class*="card"], [class*="item"], [class*="listing"], [class*="result"], li, div');
                                if (cont && !seenContainers.has(cont) && cont !== document.body && cont !== document.documentElement) {
                                    seenContainers.add(cont);
                                    cards.push(cont);
                                }
                            });
                        }

                        const seenUrlsOnPage = new Set();

                        cards.forEach((card, c_idx) => {
                            let linkEl = null;
                            if (card.matches('a')) {
                                linkEl = card;
                            } else {
                                if (isAirbnb) {
                                    linkEl = card.querySelector('a[href*="/rooms/"]');
                                } else if (isFresha) {
                                    linkEl = card.querySelector('a[href*="/a/"], a[href*="/v/"], a[href*="/b/"], a[href*="/salon/"], a[href*="/venue/"], a[data-qa="venue-name-link"]');
                                } else if (isYelp) {
                                    linkEl = card.querySelector('a[href*="/biz/"]');
                                } else if (isTripAdvisor) {
                                    linkEl = card.querySelector('a[href*="_Review-"], a[href*="/Restaurant_Review"], a[href*="/Hotel_Review"], a[href*="/Attraction_Review"], a[href*="/VacationRentalReview"]');
                                }
                                if (!linkEl) {
                                    linkEl = card.querySelector('h2 a, h3 a, h4 a, [data-testid*="title"] a, a[class*="title"], [class*="title"] a, a[href*="/place/"], a[href*="/biz/"], a[href*="/venue/"], a[href*="/hotel/"], a[href*="/restaurant/"], a[href*="/detail/"], a[href*="/item/"]');
                                }
                                if (!linkEl) {
                                    linkEl = card.querySelector('a[href^="http"], a[href^="/"]');
                                }
                            }

                            if (!linkEl || !linkEl.href) return;
                            let href = linkEl.href.split('?')[0].replace(/\/+$/, '');

                            if (isAirbnb && !href.includes('/rooms/')) return;
                            if (isFresha && !href.match(/\/(?:a|v|b|salon|venue|providers)\//i) && !card.querySelector('[data-qa="venue-card"]')) return;
                            if (isYelp && !href.includes('/biz/')) return;
                            if (isTripAdvisor && !href.includes('_Review-') && !href.includes('/Hotel_Review') && !href.includes('/Restaurant_Review') && !href.includes('/Attraction_Review')) return;

                            if (href === currUrl.split('?')[0] || href.match(/\/search(?:results)?\b/i) || href.match(/\/find\b/i)) return;
                            if (isAirbnb && (href.includes('/s/') || href.includes('/homes'))) return;
                            if (href.match(/\/(?:login|signin|signup|register|auth|terms|privacy|cookie|about|contact|help|faq)\b/i)) return;
                            if (href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) return;

                            if (seenUrlsOnPage.has(href)) return;
                            seenUrlsOnPage.add(href);

                            card.setAttribute('data-mavon-card', c_idx.toString());

                            // Title extraction
                            let title = '';
                            let titleEl = card.querySelector('[data-testid="listing-card-title"], div[id^="title_"], [data-qa="venue-name"], h2, h3, h4, .title, a.booking-link, [class*="t1jqs7"]');
                            if (titleEl) {
                                title = (titleEl.innerText || titleEl.textContent || '').trim();
                            }

                            const aria = (linkEl.getAttribute('aria-label') || card.getAttribute('aria-label') || '').trim();
                            if ((!title || junkRegex.test(title)) && aria) {
                                title = aria.split(' - ')[0].split(' · ')[0].split(', rated')[0].trim();
                            }

                            if (!title || junkRegex.test(title)) {
                                const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(s => s.length >= 3 && !junkRegex.test(s));
                                if (lines.length > 0) title = lines[0];
                            }

                            if (!title || title.length < 3 || junkRegex.test(title)) return;

                            // Address / Subtitle
                            let address = '';
                            const subEls = Array.from(card.querySelectorAll('[data-testid="listing-card-subtitle"], [data-qa="venue-address"], .subtitle, [class*="subtitle"], address, [class*="address"], [class*="locality"], [class*="location"]'));
                            for (const el of subEls) {
                                const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                                if (txt && !txt.match(/\b\d+\s*(?:km|kilometres?|miles?)\s*away\b/i) &&
                                    !txt.match(/\b\d+[-–]\d+\s+[A-Za-z]+\b/) &&
                                    !txt.match(/^(?:individual host|superhost|entire\s+|private\s+room)/i) &&
                                    txt.length >= 3) {
                                    address = txt;
                                    break;
                                }
                            }
                            if (!address && title) {
                                const inMatch = title.match(/\bin\s+([A-Za-z0-9\s,\.\-]+)$/i);
                                if (inMatch && inMatch[1].trim().length >= 3) {
                                    address = inMatch[1].trim();
                                }
                            }

                            // Rating & Reviews
                            let ratingVal = 0.0;
                            let revCount = 0;
                            const rBadge = card.querySelector('[data-qa="rating-badge"], [aria-label*="rating"], [aria-label*="star"], [class*="rating"], span.r1dxllyb, span.ceNzKf');
                            const rBadgeText = rBadge ? (rBadge.getAttribute('aria-label') || rBadge.innerText || '') : '';
                            const textToScan = (rBadgeText + ' ' + aria + ' ' + (card.innerText || '')).replace(/\s+/g, ' ');

                            let mRate = textToScan.match(/(?:rated\s+|rating:?\s*|score:?\s*|★\s*)([0-5](?:\.\d+)?)/i);
                            if (!mRate) mRate = textToScan.match(/\b([0-5](?:\.\d+)?)\s*(?:★|\/5\b|out of 5\b|\bstar(?:s)?\b)/i);
                            if (!mRate) mRate = textToScan.match(/\b([1-5]\.\d{1,2})\b/);
                            if (mRate) ratingVal = parseFloat(mRate[1]);

                            const revEl = card.querySelector('[data-qa="reviews-count"], .review-count, [class*="review"], [class*="count"]');
                            const revText = revEl ? (revEl.innerText || revEl.getAttribute('aria-label') || '') : '';
                            const revScan = (revText + ' ' + textToScan);
                            const mk = revScan.match(/\(?\s*(\d+(?:\.\d+)?)\s*k\s*(?:reviews?|ratings?|votes?)?\s*\)?/i);
                            if (mk && (revScan.toLowerCase().includes('k review') || revScan.toLowerCase().includes('k rating') || mk[0].includes('('))) {
                                revCount = Math.round(parseFloat(mk[1]) * 1000);
                            } else {
                                const mRev = revScan.match(/(?:from\s*|\(|\b)(\d[\d,]*)\s*(?:reviews?|ratings?|votes?)\b/i) ||
                                             revScan.match(/[0-5](?:\.\d+)?\s*\(\s*(\d[\d,]*)\s*\)/) ||
                                             revScan.match(/(?:average\s*rating,?\s*|from\s*)(\d[\d,]*)/i);
                                if (mRev) revCount = parseInt(mRev[1].replace(/,/g, ''), 10);
                            }

                            // Price
                            let priceText = '';
                            const priceEl = card.querySelector('[data-testid*="price"], [data-qa="price"], .price, [class*="_11jcbg2"], [class*="price"]');
                            if (priceEl) priceText = (priceEl.innerText || '').replace(/[\r\n]+/g, ' ').trim();
                            if (!priceText) {
                                const pMatch = textToScan.match(/(?:[\$£€₹]|Rs\.?)\s*[\d,]+(?:\s*(?:\/|\s+per\s+)?(?:night|total|person|stay))?/i);
                                if (pMatch) priceText = pMatch[0];
                            }
                            if (priceText && !priceText.toLowerCase().includes('night') && !priceText.toLowerCase().includes('total')) {
                                if (textToScan.toLowerCase().includes('night')) priceText = priceText + ' / night';
                            }

                            results.push({
                                card_dom_idx: c_idx,
                                title: title.replace(/[\r\n]+/g, ' ').trim(),
                                url: href,
                                address: address,
                                rating: ratingVal,
                                reviews_count: revCount,
                                price_info: priceText.replace(/[\r\n]+/g, ' ').trim(),
                                screenshot: ""
                            });
                        });

                        return results;
                    }""")

                    new_in_pass = 0
                    for item in current_batch:
                        u = item.get("url")
                        if u and u not in seen_listing_urls:
                            seen_listing_urls.add(u)
                            item["card_index"] = len(extracted_listings)
                            extracted_listings.append(item)
                            new_in_pass += 1

                    emit_event("log", f"📜 [Tab 4 - {p_name}] Scroll pass {scroll_pass}: Found {len(extracted_listings)}/{max_results} listings ({new_in_pass} new in this view).")
                    emit_event("platform_progress", {
                        "platform": p_name,
                        "scraped": len(extracted_listings),
                        "skipped": plat_skipped,
                        "total": plat_total,
                        "percent": min(100, round((len(extracted_listings) / max(1, plat_total)) * 100))
                    })

                    if len(extracted_listings) >= max_results:
                        emit_event("log", f"🎯 [Tab 4 - {p_name}] Reached target quota of {max_results} listings!")
                        break

                    if new_in_pass == 0:
                        consecutive_stagnant += 1
                        if consecutive_stagnant >= 4:
                            has_next = await platform_page.evaluate("""() => {
                                const nextBtn = document.querySelector('a[aria-label="Next"], a[data-qa="pagination-next"], a[rel="next"], [class*="pagination-next"]');
                                if (nextBtn) { nextBtn.click(); return true; }
                                return false;
                            }""")
                            if has_next:
                                emit_event("log", f"➡️ [Tab 4 - {p_name}] Triggered next pagination page...")
                                await platform_page.wait_for_timeout(1500)
                                consecutive_stagnant = 0
                                continue
                            else:
                                emit_event("log", f"🏁 [Tab 4 - {p_name}] Reached end of directory results ({len(extracted_listings)} listings discovered).")
                                break
                    else:
                        consecutive_stagnant = 0

                    await platform_page.evaluate("window.scrollBy({top: 1100, behavior: 'smooth'})")
                    await platform_page.wait_for_timeout(600)

                emit_event("log", f"🟣 [Tab 4 - {p_name}] Total harvested listings from {p_name}: {len(extracted_listings)}.")

                # =====================================================================
                # CARD CLICKING & VERIFIED DETAILS INSPECTION
                # Clicks each card, highlights it visually, captures detail screenshots
                # =====================================================================
                ss_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static", "screenshots"))
                os.makedirs(ss_dir, exist_ok=True)

                saved_count = 0
                items_to_process = extracted_listings if is_infinite else extracted_listings[:max_results]
                for cand in items_to_process:
                    c_title = cand.get("title", "")
                    if not c_title:
                        continue
                    c_url = cand.get("url", target_url)
                    c_idx = cand.get("card_index", 0)
                    dom_idx = cand.get("card_dom_idx", c_idx)

                    # Deduplication pre-check
                    if is_platform_listing_already_scraped(p_name, c_title, c_url, dedup_cache):
                        plat_skipped += 1
                        emit_event("lead_skipped", {
                            "platform": p_name,
                            "name": c_title,
                            "reason": "Already in database",
                            "scraped": plat_scraped,
                            "skipped": plat_skipped,
                            "total": plat_total
                        })
                        emit_event("platform_progress", {
                            "platform": p_name,
                            "scraped": plat_scraped,
                            "skipped": plat_skipped,
                            "total": plat_total,
                            "percent": min(100, round(((plat_scraped + plat_skipped) / max(1, plat_total)) * 100))
                        })
                        continue

                    # Visual highlight and click on card
                    emit_event("log", f"👉 [Tab 4 Click #{c_idx + 1}] Inspecting {p_name} card: {c_title}")
                    emit_event("status", f"Platform #{c_idx + 1}: {c_title}")

                    clean_fn = re.sub(r'[^a-zA-Z0-9]', '_', c_title or p_name)[:25]
                    ss_file = f"{p_name}_{clean_fn}_{c_idx}_{int(time.time())}.jpg"
                    ss_full = os.path.join(ss_dir, ss_file)

                    try:
                        card_loc = platform_page.locator(f'[data-mavon-card="{dom_idx}"]').first
                        if await card_loc.count() > 0:
                            await card_loc.scroll_into_view_if_needed(timeout=1000)
                            await platform_page.wait_for_timeout(150)

                            # Visual highlight card using extension bridge
                            try:
                                await card_loc.evaluate(f"el => window.MavonScraper && window.MavonScraper.highlight(el, 'Inspecting #{c_idx + 1}')")
                            except Exception:
                                pass

                            # Fast visual highlight and snapshot (first 5 cards or sample to maintain 5x velocity)
                            if c_idx < 5 or c_idx % 4 == 0:
                                await card_loc.screenshot(path=ss_full, quality=70, type="jpeg")
                                if os.path.exists(ss_full):
                                    cand["screenshot"] = f"/screenshots/{ss_file}"
                    except Exception as card_e:
                        pass

                    c_addr = cand.get("address")
                    if not c_addr or len(c_addr) < 3:
                        c_addr = f"{location_name}, Proximity Radius"
                    elif location_name.lower() not in c_addr.lower():
                        c_addr = f"{c_addr}, {location_name}"

                    cand_data = {
                        "platform": p_name,
                        "title": c_title,
                        "clean_brand": extract_core_brand_name(c_title, city=location_name),
                        "url": cand.get("url", target_url),
                        "booking_url": cand.get("booking_url", cand.get("url", target_url)),
                        "rating": cand.get("rating", 0.0),
                        "reviews_count": cand.get("reviews_count", 0),
                        "price_info": cand.get("price_info", ""),
                        "address": c_addr,
                        "screenshot": cand.get("screenshot", ""),
                        "verified": 0
                    }
                    save_platform_listing(cand_data)
                    saved_count += 1
                    plat_scraped += 1
                    if dedup_cache:
                        dedup_cache["listings_titles"].add(c_title.strip().lower())
                        dedup_cache["listings_urls"].add(c_url.split('?')[0].rstrip('/'))
                    emit_event("platform_progress", {
                        "platform": p_name,
                        "scraped": plat_scraped,
                        "skipped": plat_skipped,
                        "total": plat_total,
                        "percent": min(100, round(((plat_scraped + plat_skipped) / max(1, plat_total)) * 100))
                    })
                    emit_event("platform_listing_found", {
                        "lead_id": None,
                        "company_name": c_title,
                        "platform": p_name,
                        "rating": cand.get("rating", 0.0),
                        "review_count": cand.get("reviews_count", 0),
                        "listing_url": cand.get("url", target_url),
                        "booking_url": cand.get("url", target_url),
                        "price_range": cand.get("price_info", ""),
                        "verified": False
                    })

                emit_event("log", f"🟣 [Tab 4 - {p_name}] Stored {saved_count} listings in database for '{location_name}'.")

            except Exception as plat_err:
                emit_event("log", f"⚠️ [Tab 4 Error on {p_name}] {type(plat_err).__name__}: {plat_err}")
                logging.exception(f"Error on platform {p_name}")

    except Exception as worker_err:
        emit_event("log", f"❌ [Tab 4 Worker Error] {type(worker_err).__name__}: {worker_err}")
        logging.exception("Platform area worker encountered fatal error")


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
):
    cleaned_query = query.strip() if query else ""
    if not cleaned_query or cleaned_query.lower() in ["all", "all shops", "all shops in area"]:
        cleaned_query = "shops"

    search_category, search_location = parse_search_query_and_location(cleaned_query, lat=lat, lon=lon)
    selected_platforms_list = [p.strip() for p in (platforms or platform_name).split(",") if p.strip()] if enable_platform else []

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
        if standalone_companies or (not enable_maps and enable_linkedin and not enable_platform and not enable_website):
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
            existing_maps = [p for p in context.pages if "google.com/maps" in p.url]
            existing_li = [p for p in context.pages if "linkedin.com" in p.url]
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

            maps_page = existing_maps[0] if (existing_maps and enable_maps) else (await context.new_page() if enable_maps else None)
            linkedin_page = existing_li[0] if (existing_li and enable_linkedin) else (await context.new_page() if enable_linkedin else None)
            platform_page = existing_plat[0] if (existing_plat and enable_platform) else (await context.new_page() if enable_platform else None)
            website_page = await context.new_page() if (enable_website and extract_emails) else None
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
                emit_event("log", "Navigating Tab 2 (LinkedIn): https://www.linkedin.com/")
                await linkedin_page.goto("https://www.linkedin.com/", wait_until="domcontentloaded")
            except Exception:
                pass

        # Setup Parallel Asynchronous Queues for Tab 2, Tab 3, and Tab 4
        website_queue = asyncio.Queue() if (enable_website and extract_emails) else None
        linkedin_queue = asyncio.Queue() if linkedin_page else None

        # RESUME CAPABILITY: Check for any incomplete leads from a previously paused run
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
                custom_url_pattern=platform_custom_url or "",
                visible_browser=visible_browser,
                dedup_cache=dedup_cache
            ))
        proximity_total_estimated = max_results if not scrape_all else 120
        emit_event("proximity_total", {"platform": "Google Maps", "query": cleaned_query, "location": search_location, "total": proximity_total_estimated})
        emit_event("log", f"⚡ Loaded proximity deduplication cache ({dedup_cache['total_existing_leads']} leads, {dedup_cache['total_existing_listings']} directory listings in DB).")

        # Start live screen streaming across all active agent viewports
        stop_stream_event.clear()
        stream_task = asyncio.create_task(frame_streamer_loop(maps_page, linkedin_page, pages_dict))

        if enable_maps and maps_page:
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

            await maps_page.wait_for_timeout(1000)
        seen_titles = set()
        seen_signatures = set()
        seen_phones = set()
        seen_domains = set()
        scroll_attempts = 0
        is_infinite = (scrape_all or max_results >= 9999)
        target_max = 999999 if is_infinite else max_results
        max_scroll_attempts = 99999 if is_infinite else max(15, (max_results // 3) + 10)
        consecutive_no_new = 0

        emit_event("status", "Extracting places from feed...")

        while (enable_maps and maps_page) and (len(scraped_places) + skipped_count) < target_max and scroll_attempts < max_scroll_attempts:
            links = maps_page.locator('div[role="feed"] a.hfpxzc, div[role="feed"] a[href*="/maps/place/"]')
            count = await links.count()
            if count == 0:
                links = maps_page.locator('a.hfpxzc, div[role="article"] a')
                count = await links.count()

            new_found_this_scroll = 0

            for i in range(count):
                if (len(scraped_places) + skipped_count) >= target_max:
                    break

                try:
                    elem = links.nth(i)
                    title = await elem.get_attribute("aria-label") or ""
                    title = clean_text(title)

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
                        emit_event("log", f"⏭️ [Skipped In DB] '{title}' already verified in database. Bypassing detail pane.")
                        try:
                            await elem.evaluate("el => window.MavonScraper && window.MavonScraper.highlight(el, 'Skipped (In DB)', '#f59e0b')")
                        except Exception:
                            pass
                        continue

                    idx = len(scraped_places) + 1

                    emit_event("log", f"👉 [{idx}] Inspecting: {title}")
                    emit_event("status", f"Scraping #{idx}: {title}")

                    # Highlight place card visually using extension bridge
                    try:
                        await elem.evaluate(f"el => window.MavonScraper && window.MavonScraper.highlight(el, 'Inspecting #{idx}')")
                    except Exception:
                        pass

                    # FAST CLICK & BATCH IN-PAGE EXTRACTION (Zero-CDP lag)
                    await elem.click()
                    try:
                        await maps_page.wait_for_selector('h1.DUwDvf', timeout=1000)
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
                                ig: '',
                                fb: '',
                                li: '',
                                tw: '',
                                lat: null,
                                lon: null
                            };

                            // Title
                            const h1 = document.querySelector('h1.DUwDvf');
                            if (h1) d.title = h1.innerText.trim();

                            // Category
                            const catBtn = document.querySelector('button.DkEaL, button[jsaction*="category"], div.fontBodyMedium button, span.YhemCb');
                            if (catBtn) {
                                const cText = catBtn.innerText.trim();
                                const ignore = ["learn more", "see more", "read more", "claim this business", "suggest an edit", "save", "nearby", "send to phone", "share", "reviews", "photos", "overview", "about", "directions", "copy"];
                                if (cText && !ignore.some(x => cText.toLowerCase().includes(x))) {
                                    d.category = cText;
                                }
                            }

                            // Rating
                            const ratingEl = document.querySelector('div.F7nice span[aria-hidden="true"], span.ceNzKf, div.fontDisplayLarge, span[aria-label*="stars"], span.MW4etd');
                            if (ratingEl) {
                                const text = ratingEl.innerText || ratingEl.getAttribute('aria-label') || '';
                                const m = text.match(/\b([0-5]\.\d+)\b/);
                                if (m) d.rating = m[1];
                            }

                            // Reviews
                            const revEl = document.querySelector('div.F7nice span[aria-label*="reviews"], span.mgr77e, button[aria-label*="reviews"], span[aria-label*="reviews"], span.UY7F9, div.F7nice button');
                            if (revEl) {
                                const text = revEl.getAttribute('aria-label') || revEl.innerText || '';
                                const digits = text.match(/[\d,]+/);
                                if (digits && digits[0] !== '0') d.reviews = digits[0].replace(/,/g, '');
                            }

                            // Address
                            const addrEl = document.querySelector('button[data-item-id="address"], button[aria-label*="Address:"], div[data-item-id="address"], button[data-tooltip*="Copy address"], [data-item-id*="address"]');
                            if (addrEl) {
                                const text = addrEl.innerText || addrEl.getAttribute('aria-label') || '';
                                d.address = text.replace(/^Address:\s*/i, '').trim();
                            }

                            // Phone
                            const phoneEl = document.querySelector('button[data-item-id*="phone:"], button[aria-label*="Phone:"], button[data-tooltip*="Copy phone"], a[href^="tel:"]');
                            if (phoneEl) {
                                const text = phoneEl.innerText || phoneEl.getAttribute('aria-label') || '';
                                d.phone = text.replace(/^Phone:\s*/i, '').trim();
                            }

                            // Website
                            const webEl = document.querySelector('a[data-item-id="authority"], a[aria-label*="Website:"]');
                            if (webEl && webEl.href) {
                                d.website = webEl.href;
                            }

                            // Hours
                            const hoursEl = document.querySelector('button[data-item-id*="oh"], div[data-item-id*="oh"], button[aria-label*="Hours"], div[aria-label*="Hours"]');
                            if (hoursEl) {
                                d.hours = (hoursEl.innerText || '').split('\n')[0].trim();
                            }

                            // Price
                            const priceEl = document.querySelector('span[aria-label*="per person"], span[aria-label*="Price"], button[data-item-id*="price"], div[aria-label*="£"], div[aria-label*="$"]');
                            if (priceEl) {
                                d.price = priceEl.innerText.trim();
                            }

                            // Plus code
                            const pcEl = document.querySelector('button[data-item-id="oloc"], button[aria-label*="Plus code"]');
                            if (pcEl) {
                                d.plus_code = pcEl.innerText.trim();
                            }

                            // Socials
                            document.querySelectorAll('a[href*="instagram.com"], a[href*="facebook.com"], a[href*="linkedin.com"], a[href*="twitter.com"], a[href*="x.com"]').forEach(a => {
                                const h = (a.href || '').split('?')[0];
                                if (h.includes('instagram.com') && !d.ig && !h.includes('/p/')) d.ig = h;
                                else if (h.includes('facebook.com') && !d.fb && !h.includes('sharer')) d.fb = h;
                                else if (h.includes('linkedin.com') && !d.li) d.li = h;
                                else if ((h.includes('twitter.com') || h.includes('x.com')) && !d.tw) d.tw = h;
                            });

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
                    hours = detail_data.get("hours") or ""
                    price = detail_data.get("price") or ""
                    plus_code = detail_data.get("plus_code") or ""
                    maps_ig = detail_data.get("ig") or ""
                    maps_fb = detail_data.get("fb") or ""
                    maps_li = detail_data.get("li") or ""
                    maps_tw = detail_data.get("tw") or "" 

                    if website:
                        w_low = website.lower()
                        if "instagram.com/" in w_low and not maps_ig: maps_ig = website
                        elif "facebook.com/" in w_low and not maps_fb: maps_fb = website
                        elif "linkedin.com/" in w_low and not maps_li: maps_li = website
                        elif ("twitter.com/" in w_low or "x.com/" in w_low) and not maps_tw: maps_tw = website

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
                        "instagram": maps_ig,
                        "facebook": maps_fb,
                        "linkedin": maps_li,
                        "twitter": maps_tw,
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
            stagnant_limit = 16 if is_continuous else 8
            if consecutive_no_new >= stagnant_limit:
                emit_event("log", f"No new places loaded after {stagnant_limit} scrolls. All area shops captured.")
                break

            emit_event("log", f"📜 Scrolling Tab 1 feed down to load more shops (Pass {scroll_attempts})...")
            try:
                feed = maps_page.locator('div[role="feed"]').first
                if await feed.is_visible(timeout=1000):
                    await feed.evaluate("el => el.scrollBy(0, 2000)")
                    await maps_page.wait_for_timeout(450)
            except Exception:
                await maps_page.mouse.wheel(0, 1500)
                await maps_page.wait_for_timeout(450)

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
    parser.add_argument("--platforms", type=str, default="Fresha")
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
        platforms=args.platforms,
        platform_custom_url=args.platform_custom_url,
        dedup_area=args.dedup_area,
        skip_existing_db=args.skip_existing_db,
        standalone_companies=args.standalone_companies,
    ))
