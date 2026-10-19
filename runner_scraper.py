import urllib.parse
import argparse
import asyncio
import base64
import datetime
import json
import logging
logger = logging.getLogger("runner_scraper")
import os
import re
import sys
import math
import time
import subprocess
import shutil
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from database import save_lead, save_employees_batch, classify_seniority, clean_domain, is_lead_in_db, save_platform_listing, normalize_all_platform_listings, get_tables_split_data, extract_core_brand_name, load_proximity_dedup_cache, is_place_already_scraped, is_platform_listing_already_scraped, get_pending_resume_leads, get_cached_census_total, set_cached_census_total, update_lead_website_data, clean_email_string, get_connection
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
    "sentry.io", "wixpress.com", "example.com", "example.org", "example.net",
    "domain.com", "test.com", "schema.org", "google.com", "w3.org", "cloudflare.com",
    "gravatar.com", "polyfill.io", "doubleclick.net", "placeholder.com", "email.com",
    "lovable.app"
)

def is_valid_email(email_str: str) -> bool:
    """Strictly validates extracted emails, dropping dummy domains, placeholders, and binary extensions."""
    if not email_str or "@" not in email_str:
        return False
    em = email_str.strip().lower()
    if any(em.endswith(ext) for ext in JUNK_EXTENSIONS):
        return False
    parts = em.split("@")
    if len(parts) != 2:
        return False
    user, domain = parts[0], parts[1]
    if len(user) < 1 or len(domain) < 3 or "." not in domain:
        return False
    if any(bad in domain for bad in IGNORE_DOMAINS):
        return False
    if user in ("user", "username", "yourname", "email", "you", "placeholder"):
        return False
    return True

def clean_phone_number(phone_str: str) -> str:
    """Strips Google Maps phone icon glyphs (\ue0b0), newlines, and normalizes phone number."""
    if not phone_str or phone_str == "N/A":
        return "N/A"
    cleaned = re.sub(r'[\uE000-\uF8FF\r\n\t]+', ' ', str(phone_str)).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    digits = re.sub(r'\D', '', cleaned)
    if len(digits) >= 5:
        return cleaned
    return "N/A"

def clean_linkedin_url(url: str) -> str:
    """Validates and cleans LinkedIn URLs, strictly rejecting search/authwall/login URLs."""
    if not url or str(url).upper() in ("N/A", "NONE"):
        return ""
    u = str(url).strip()
    u_low = u.lower()
    if any(bad in u_low for bad in ["/search", "uas/login", "authwall", "checkpoint", "linkedin.com/help", "linkedin.com/feed", "linkedin.com/share"]):
        return ""
    if "linkedin.com" in u_low and ("/company/" in u_low or "/in/" in u_low):
        return u.split("?")[0].rstrip("/")
    return ""

def emit_event(event_type: str, data: Any, agent: Optional[str] = None):
    try:
        payload = {"type": event_type, "data": data}
        if agent:
            payload["agent"] = agent
        elif isinstance(data, dict) and "agent" in data:
            payload["agent"] = data["agent"]
        msg = json.dumps(payload, ensure_ascii=False)
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
        if event_type == "log":
            logger.info(str(data))
    except Exception as e:
        logger.error(f"Failed to emit event: {e}")

def emit_log(message: str, agent: str = "system"):
    emit_event("log", message, agent=agent)

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
                if email_part and "@" in email_part and is_valid_email(email_part):
                    found.add(email_part.lower())

        # 2. Cloudflare Protected Emails (<span class="__cf_email__" data-cfemail="..."> or /email-protection#...)
        for el in soup.select('[data-cfemail], a[href*="/email-protection#"], span.__cf_email__'):
            cf_hex = el.get("data-cfemail", "")
            if not cf_hex and el.get("href"):
                cf_hex = el.get("href", "").split("#")[-1]
            if cf_hex:
                decoded = decode_cloudflare_email(cf_hex)
                if decoded and is_valid_email(decoded):
                    found.add(decoded.lower().strip())

        # 3. JSON-LD structured data schema
        for s in soup.find_all("script", type="application/ld+json"):
            if s.string:
                for match in EMAIL_REGEX.findall(s.string):
                    if is_valid_email(match):
                        found.add(match.strip().lower())

        # 4. Standard RegEx pattern across page text
        for match in EMAIL_REGEX.findall(html):
            match = match.strip().lower()
            if is_valid_email(match):
                found.add(match)

        # 5. Obfuscated patterns like user [at] domain.com or user (at) domain.com
        obf_matches = re.findall(r'([a-zA-Z0-9_.+-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*([a-zA-Z0-9-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\.)\s*([a-zA-Z]{2,10})', html, re.I)
        for user, dom, tld in obf_matches:
            cand = f"{user}@{dom}.{tld}".lower()
            if is_valid_email(cand):
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


def extract_address_from_html(html: str, soup: Optional[BeautifulSoup] = None) -> str:
    """
    Extracts physical business address from HTML across:
    1. Schema.org JSON-LD PostalAddress
    2. Google Maps / Share Google links where anchor text contains an address
    3. HTML <address> tags
    4. Text blocks following 'Visit', 'Address', 'Location', 'Headquarters' headings
    5. Standard street address regex pattern matching
    """
    if not html:
        return ""
    if soup is None:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            soup = None

    if soup:
        # 1. Schema.org PostalAddress
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "{}")
                items = data if isinstance(data, list) else (data.get("@graph") or [data])
                for item in items:
                    addr_obj = item.get("address") if isinstance(item, dict) else None
                    if isinstance(addr_obj, dict):
                        parts = [
                            addr_obj.get("streetAddress"),
                            addr_obj.get("addressLocality"),
                            addr_obj.get("addressRegion"),
                            addr_obj.get("postalCode"),
                            addr_obj.get("addressCountry")
                        ]
                        cleaned = [str(p).strip() for p in parts if p and str(p).strip()]
                        if len(cleaned) >= 2:
                            return ", ".join(cleaned)
                    elif isinstance(addr_obj, str) and len(addr_obj) > 8:
                        return " ".join(addr_obj.split())
            except Exception:
                pass

        # 2. Google Maps / Share Google links (e.g. <a href="https://share.google/...">771 W Atlantic Blvd...</a>)
        for a in soup.find_all("a", href=True):
            h = a["href"].lower()
            if any(k in h for k in ["share.google", "maps.google", "google.com/maps"]):
                t = a.get_text().strip()
                if len(t) >= 10 and re.search(r'\d+', t) and re.search(r'[A-Za-z]', t):
                    if not any(bad in t.lower() for bad in ["view on", "get direction", "open map", "google map"]):
                        return " ".join(t.split())

        # 3. HTML <address> tags
        for addr_tag in soup.find_all("address"):
            t = addr_tag.get_text().strip()
            if len(t) >= 10 and re.search(r'\d+', t) and len(t) < 180:
                return " ".join(t.split())

        # 4. Text blocks following 'Visit' / 'Address' / 'Location' headings
        for h_tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "span"]):
            h_text = h_tag.get_text().strip().lower()
            if h_text in ["visit", "visit us", "our location", "address", "headquarters", "location", "our office"]:
                next_el = h_tag.find_next_sibling()
                if not next_el:
                    parent = h_tag.parent
                    if parent:
                        next_el = parent.find_next_sibling()
                if next_el:
                    cand = next_el.get_text().strip()
                    if 10 <= len(cand) <= 150 and re.search(r'\d+', cand) and re.search(r'[A-Za-z]', cand):
                        return " ".join(cand.split())

    # 5. Regex street address fallback across raw HTML
    addr_match = re.search(
        r'\b\d{1,6}\s+[A-Za-z0-9\s.,#-]+?\b(?:Blvd|Boulevard|Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Way|Lane|Ln|Court|Ct|Highway|Hwy|Place|Pl|Square|Sq|Pkwy|Parkway)\b[^\n<]{3,60}?\b(?:[A-Z]{2}\s+\d{5}(?:-\d{4})?|\b\d{5,6}\b|[A-Z]{1,2}\d[A-Z0-9]?\s*\d[A-Z]{2})\b',
        html,
        re.IGNORECASE
    )
    if addr_match:
        matched_str = " ".join(addr_match.group(0).split()).strip()
        if len(matched_str) >= 10:
            return matched_str

    return ""


def extract_phone_from_html(html: str, soup: Optional[BeautifulSoup] = None) -> str:
    """
    Extracts telephone numbers from:
    1. a[href^='tel:']
    2. Schema.org JSON-LD telephone
    3. Contact and footer regex patterns
    """
    if not html:
        return ""
    if soup is None:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            soup = None

    if soup:
        # 1. tel: anchor links
        for a in soup.find_all("a", href=True):
            h = a["href"].strip()
            if h.lower().startswith("tel:"):
                clean = clean_phone_number(h[4:])
                if clean and clean != "N/A":
                    return clean

        # 2. Schema.org telephone
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "{}")
                items = data if isinstance(data, list) else (data.get("@graph") or [data])
                for item in items:
                    if isinstance(item, dict):
                        tel = item.get("telephone") or item.get("phone")
                        if tel:
                            clean = clean_phone_number(str(tel))
                            if clean and clean != "N/A":
                                return clean
            except Exception:
                pass

    # 3. Regex pattern in contact / phone blocks
    phone_candidates = re.findall(r'(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\+\d{1,4}[-.\s]?\d{2,5}[-.\s]?\d{4,8}', html)
    for p in phone_candidates:
        clean = clean_phone_number(p)
        if clean and clean != "N/A":
            return clean

    return ""


def clean_brand_name_from_page(title: str, domain: str, soup: Optional[BeautifulSoup] = None, html: str = "") -> str:
    """
    Discards generic page titles ('Home', 'Welcome', 'Index') and recovers
    the true brand name from copyright string, og:site_name, or domain name.
    """
    generic_words = {"home", "welcome", "homepage", "landing", "index", "website", "main", "default", "loading"}
    raw_title = str(title or "").strip()
    clean_t = raw_title.lower()

    # 1. Authoritative Copyright string (e.g. '© 2026 BOAT INC. ALL RIGHTS RESERVED.')
    if html:
        c_match = re.search(r'©\s*(?:20\d\d\s*)?([A-Za-z0-9\s,.-]+?)(?:\.|\s+ALL|\s+All|$)', html)
        if c_match:
            c_brand = c_match.group(1).strip()
            if 2 < len(c_brand) < 50 and c_brand.lower() not in generic_words:
                return c_brand.title()

    # 2. OpenGraph og:site_name
    if soup:
        og_site = soup.find("meta", property="og:site_name")
        if og_site and og_site.get("content"):
            c = og_site["content"].strip()
            if c and c.lower() not in generic_words:
                return c

    # 3. Clean page title with separator resolution
    if raw_title and clean_t not in generic_words and not raw_title.startswith("http"):
        for sep in [" | ", " - ", " • ", " — ", " :: "]:
            if sep in raw_title:
                parts = [p.strip() for p in raw_title.split(sep) if p.strip()]
                non_generic = [p for p in parts if p.lower() not in generic_words and not p.startswith("http")]
                if non_generic:
                    chosen = non_generic[-1] if len(non_generic[-1]) < len(non_generic[0]) and len(non_generic[-1]) > 2 else non_generic[0]
                    clean_chosen = re.sub(r'\.(com|org|net|io|co|in|uk|ai|de|fr)$', '', chosen, flags=re.I).strip()
                    if len(clean_chosen) >= 2:
                        return clean_chosen.title()
        clean_cand = re.sub(r'\.(com|org|net|io|co|in|uk|ai|de|fr)$', '', raw_title, flags=re.I).strip()
        if len(clean_cand) >= 2 and clean_cand.lower() not in generic_words:
            return clean_cand.title()

    # 4. Domain fallback: e.g. "boat.com" -> "Boat"
    if domain:
        clean_d = re.sub(r'^(?:www\d?|shop|store|m)\.', '', domain.lower())
        name_part = clean_d.split('.')[0]
        if len(name_part) >= 2:
            return name_part.title()

    return raw_title or "Website Lead"


def extract_socials_from_text(html: str) -> Dict[str, str]:
    """
    Extracts official social media profiles from HTML across:
    1. <a> href attributes
    2. JSON-LD structured data (<script type="application/ld+json">)
    3. <meta> tags (og:see_also, twitter:site, twitter:creator, etc.)
    4. Regex pattern matching across page source code.
    """
    socials = {"instagram": "", "facebook": "", "linkedin": "", "twitter": "", "youtube": "", "tiktok": "", "whatsapp": ""}
    if not html:
        return socials

    candidates = {
        "instagram": [],
        "facebook": [],
        "linkedin": [],
        "twitter": [],
        "youtube": [],
        "tiktok": [],
        "whatsapp": []
    }

    try:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Check all anchor tags
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            lower = href.lower()

            if "wa.me/" in lower or "api.whatsapp.com/send" in lower or "web.whatsapp.com/send" in lower or "whatsapp://" in lower:
                candidates["whatsapp"].append(href)
            elif "instagram.com/" in lower:
                candidates["instagram"].append(href)
            elif "facebook.com/" in lower or "fb.me/" in lower:
                candidates["facebook"].append(href)
            elif "linkedin.com/" in lower:
                candidates["linkedin"].append(href)
            elif "twitter.com/" in lower or "x.com/" in lower:
                candidates["twitter"].append(href)
            elif "youtube.com/" in lower or "youtu.be/" in lower:
                candidates["youtube"].append(href)
            elif "tiktok.com/" in lower:
                candidates["tiktok"].append(href)

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
                        elif "facebook.com/" in lower or "fb.me/" in lower: candidates["facebook"].append(obj)
                        elif "linkedin.com/" in lower: candidates["linkedin"].append(obj)
                        elif "twitter.com/" in lower or "x.com/" in lower: candidates["twitter"].append(obj)
                        elif "youtube.com/" in lower or "youtu.be/" in lower: candidates["youtube"].append(obj)
                        elif "tiktok.com/" in lower: candidates["tiktok"].append(obj)
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
            elif "facebook.com/" in lower or "fb.me/" in lower: candidates["facebook"].append(content)
            elif "linkedin.com/" in lower: candidates["linkedin"].append(content)
            elif "twitter.com/" in lower or "x.com/" in lower: candidates["twitter"].append(content)
            elif "youtube.com/" in lower or "youtu.be/" in lower: candidates["youtube"].append(content)
            elif "tiktok.com/" in lower: candidates["tiktok"].append(content)
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

        li_matches = re.findall(r'https?://(?:www\.)?linkedin\.com/(company|in)/([a-zA-Z0-9_.-]{2,50})/?', html, re.IGNORECASE)
        for kind, m in li_matches:
            candidates["linkedin"].append(f"https://www.linkedin.com/{kind.lower()}/{m}")

        tw_matches = re.findall(r'https?://(?:www\.)?(?:twitter|x)\.com/([a-zA-Z0-9_]{2,30})/?', html, re.IGNORECASE)
        for m in tw_matches:
            candidates["twitter"].append(f"https://x.com/{m}")

        yt_matches = re.findall(r'https?://(?:www\.)?(?:youtube\.com/(?:c/|channel/|user/|@)?|youtu\.be/)([a-zA-Z0-9_.-]{2,50})/?', html, re.IGNORECASE)
        for m in yt_matches:
            candidates["youtube"].append(f"https://www.youtube.com/@{m.lstrip('@')}")

        tt_matches = re.findall(r'https?://(?:www\.)?tiktok\.com/@([a-zA-Z0-9_.-]{2,50})/?', html, re.IGNORECASE)
        for m in tt_matches:
            candidates["tiktok"].append(f"https://www.tiktok.com/@{m}")

        wa_matches = re.findall(r'(?:https?://(?:wa\.me|api\.whatsapp\.com/send\?(?:[^"\'\s>]*&)?phone=)|whatsapp://send\?(?:[^"\'\s>]*&)?phone=)(\+?[0-9]{7,15})', html, re.IGNORECASE)
        for m in wa_matches:
            candidates["whatsapp"].append(f"https://wa.me/{m.lstrip('+')}")

    except Exception:
        pass

    # 5. Filter & Select Best Canonical URL for each platform
    # WhatsApp
    for raw in candidates["whatsapp"]:
        m = re.search(r'(?:wa\.me/|phone=|\b)(\+?[0-9]{7,15})\b', raw)
        if m:
            clean_digits = re.sub(r'[^0-9]', '', m.group(1))
            if 7 <= len(clean_digits) <= 15:
                socials["whatsapp"] = clean_digits
                break

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

    # LinkedIn (Prefer company, but accept /in/ personnel profile)
    for raw in candidates["linkedin"]:
        cleaned = clean_linkedin_url(raw)
        if cleaned:
            socials["linkedin"] = cleaned
            if "/company/" in cleaned:
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

    # YouTube
    for raw in candidates["youtube"]:
        cleaned = clean_social_url(raw)
        lower = cleaned.lower()
        if not any(bad in lower for bad in ["/watch", "/embed", "/shorts", "/playlist", "youtube.com/live", "share", "intent"]):
            path = urllib.parse.urlparse(cleaned).path.strip("/")
            if path and len(path) > 1:
                socials["youtube"] = cleaned
                break

    # TikTok
    for raw in candidates["tiktok"]:
        cleaned = clean_social_url(raw)
        lower = cleaned.lower()
        if not any(bad in lower for bad in ["/video/", "/share", "intent"]):
            path = urllib.parse.urlparse(cleaned).path.strip("/")
            if path and len(path) > 1:
                socials["tiktok"] = cleaned
                break

    return socials

async def frame_streamer_loop(maps_page=None, linkedin_page=None, pages_dict=None):
    """Streams live JPEG screenshot frames of Tab 1 (Google Maps), Tab 2 (Shop Website), Tab 3 (LinkedIn Org), and Tab 4 (Platform) to frontend."""
    p_dict = pages_dict if isinstance(pages_dict, dict) else {}
    while not stop_stream_event.is_set():
        # 1. Stream Tab 1 (Google Maps)
        cur_maps = p_dict.get("maps") or maps_page
        try:
            if cur_maps and not cur_maps.is_closed():
                maps_url = cur_maps.url or ""
                if maps_url and "about:blank" not in maps_url:
                    buf_maps = await cur_maps.screenshot(type="jpeg", quality=55)
                    if len(buf_maps) > 6000:
                        b64_maps = base64.b64encode(buf_maps).decode("ascii")
                        emit_event("live_frame", {
                            "tab": "maps",
                            "stream_type": "maps",
                            "image": f"data:image/jpeg;base64,{b64_maps}",
                            "url": maps_url,
                            "title": "Google Maps Live Agent",
                            "is_maps": True,
                            "is_website": False,
                            "is_linkedin": False,
                            "is_platform": False
                        })
        except Exception:
            pass

        # 2. Stream Tab 2 (Shop Website)
        cur_site = p_dict.get("website")
        try:
            if cur_site and not cur_site.is_closed():
                site_url = cur_site.url or ""
                if site_url and "about:blank" not in site_url:
                    buf_site = await cur_site.screenshot(type="jpeg", quality=55)
                    if len(buf_site) > 6000:
                        b64_site = base64.b64encode(buf_site).decode("ascii")
                        site_title = ""
                        try:
                            site_title = await cur_site.title()
                        except Exception:
                            pass
                        emit_event("live_frame", {
                            "tab": "website",
                            "stream_type": "website",
                            "image": f"data:image/jpeg;base64,{b64_site}",
                            "url": site_url,
                            "title": site_title[:50] if site_title else "Shop Website",
                            "is_maps": False,
                            "is_website": True,
                            "is_linkedin": False,
                            "is_platform": False
                        })
        except Exception:
            pass

        # 3. Stream Tab 3 (LinkedIn Org Intelligence)
        cur_li = p_dict.get("linkedin") or linkedin_page
        try:
            if cur_li and not cur_li.is_closed():
                li_url = cur_li.url or ""
                if li_url and "about:blank" not in li_url:
                    buf_li = await cur_li.screenshot(type="jpeg", quality=55)
                    if len(buf_li) > 6000:
                        b64_li = base64.b64encode(buf_li).decode("ascii")
                        li_title = ""
                        try:
                            li_title = await cur_li.title()
                        except Exception:
                            pass
                        emit_event("live_frame", {
                            "tab": "linkedin",
                            "stream_type": "linkedin",
                            "image": f"data:image/jpeg;base64,{b64_li}",
                            "url": li_url,
                            "title": li_title[:50] if li_title else "LinkedIn Org Intelligence",
                            "is_maps": False,
                            "is_website": False,
                            "is_linkedin": True,
                            "is_platform": False
                        })
        except Exception:
            pass

        # 4. Stream Tab 4 (Platform Directory Agent: Fresha, Airbnb, Yelp, etc.)
        cur_plat = p_dict.get("platform")
        try:
            if cur_plat and not cur_plat.is_closed():
                plat_url = cur_plat.url or ""
                if plat_url and "about:blank" not in plat_url:
                    buf_plat = await cur_plat.screenshot(type="jpeg", quality=55)
                    if len(buf_plat) > 6000:
                        b64_plat = base64.b64encode(buf_plat).decode("ascii")
                        plat_title = ""
                        try:
                            plat_title = await cur_plat.title()
                        except Exception:
                            pass
                        emit_event("live_frame", {
                            "tab": "platform",
                            "stream_type": "platform",
                            "image": f"data:image/jpeg;base64,{b64_plat}",
                            "url": plat_url,
                            "title": plat_title[:50] if plat_title else "Platform Directory Agent",
                            "is_maps": False,
                            "is_website": False,
                            "is_linkedin": False,
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
    explored_domains_cache: Dict[str, Dict[str, Any]] = {}
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
        lead_db_id = item.get("lead_id")
        name = item.get("name")
        address = item.get("address", "N/A")
        website_url = item.get("website")
        phone = item.get("phone", "N/A")
        category = item.get("category", "Business")
        deep_crawl = item.get("deep_crawl", False)
        force_crawl = item.get("force_crawl", False) or deep_crawl

        if not website_url or not website_url.startswith("http"):
            queue.task_done()
            continue

        clean_target_dom = clean_domain(website_url)

        # 1. In-session domain cache check (prevents re-checking same website in the same run)
        if not force_crawl and clean_target_dom and clean_target_dom in explored_domains_cache:
            cached_data = explored_domains_cache[clean_target_dom]
            emit_event("log", f"⚡ [Agent 2: Website] #{idx} '{name}' shares domain '{clean_target_dom}' already crawled in this session. Reusing verified data.")
            try:
                update_lead_website_data(
                    name=name,
                    address=address,
                    website=website_url,
                    email=cached_data.get("email", ""),
                    instagram=cached_data.get("instagram", ""),
                    facebook=cached_data.get("facebook", ""),
                    linkedin=cached_data.get("linkedin", ""),
                    twitter=cached_data.get("twitter", ""),
                    youtube=cached_data.get("youtube", ""),
                    tiktok=cached_data.get("tiktok", ""),
                    screenshot=cached_data.get("screenshot", ""),
                    bot_protection=cached_data.get("bot_protection", "Clean"),
                    cookie_status=cached_data.get("cookie_status", "None"),
                    website_status=cached_data.get("website_status", "clean"),
                    booking_url=cached_data.get("booking_url", ""),
                    platform_name=cached_data.get("platform_name", ""),
                    website_scraped_at=cached_data.get("website_scraped_at", ""),
                    whatsapp=cached_data.get("whatsapp", "")
                )
                emit_event("place_updated", {
                    "id": lead_db_id,
                    "name": name,
                    "address": address,
                    "website": website_url,
                    **cached_data
                })
            except Exception:
                pass
            queue.task_done()
            continue

        # 2. Database check for previously completed crawl (across past sessions)
        if not force_crawl:
            try:
                with get_connection() as conn:
                    existing_lead = None
                    if lead_db_id:
                        existing_lead = conn.execute(
                            "SELECT id, website_status, screenshot, email, instagram, facebook, linkedin, twitter, youtube, tiktok, bot_protection, cookie_status, booking_url, platform_name, name, address, phone FROM leads WHERE id = ?",
                            (lead_db_id,)
                        ).fetchone()
                    if not existing_lead and name:
                        existing_lead = conn.execute(
                            "SELECT id, website_status, screenshot, email, instagram, facebook, linkedin, twitter, youtube, tiktok, bot_protection, cookie_status, booking_url, platform_name, name, address, phone FROM leads WHERE name = ? AND address = ?",
                            (name, address)
                        ).fetchone()

                    if existing_lead:
                        ex_addr = (existing_lead["address"] or "").strip()
                        ex_name = (existing_lead["name"] or "").strip().lower()
                        # Only skip if lead is NOT a stub missing address or having generic placeholder name
                        is_stub = ex_name in ["home", "welcome", "index", clean_target_dom] or ex_addr in ["N/A", "", "None"]
                        w_st = str(existing_lead["website_status"] or "").strip().lower()
                        if not is_stub and w_st in ["emails_found", "clean", "social", "socials_found", "failed"]:
                            emit_event("log", f"⏩ [Agent 2: Website] #{idx} '{name}' was already explored ({w_st}). Skipping redundant crawl.")
                            if clean_target_dom:
                                explored_domains_cache[clean_target_dom] = {
                                    "email": existing_lead["email"] or "",
                                    "instagram": existing_lead["instagram"] or "",
                                    "facebook": existing_lead["facebook"] or "",
                                    "linkedin": existing_lead["linkedin"] or "",
                                    "twitter": existing_lead["twitter"] or "",
                                    "youtube": existing_lead["youtube"] or "",
                                    "tiktok": existing_lead["tiktok"] or "",
                                    "screenshot": existing_lead["screenshot"] or "",
                                    "bot_protection": existing_lead["bot_protection"] or "Clean",
                                    "cookie_status": existing_lead["cookie_status"] or "None",
                                    "website_status": w_st,
                                    "booking_url": existing_lead["booking_url"] or "",
                                    "platform_name": existing_lead["platform_name"] or ""
                                }
                            queue.task_done()
                            continue

                    # Also check if this exact domain was already explored under another lead in DB
                    if clean_target_dom and clean_target_dom not in ("facebook.com", "instagram.com", "google.com"):
                        prior_dom_lead = conn.execute("""
                            SELECT email, instagram, facebook, linkedin, twitter, youtube, tiktok, 
                                   screenshot, bot_protection, cookie_status, website_status, booking_url, platform_name, name, address, phone 
                            FROM leads 
                            WHERE website LIKE ? 
                              AND website_status IN ('emails_found', 'clean', 'social', 'socials_found')
                            ORDER BY (screenshot IS NOT NULL AND screenshot != 'N/A' AND screenshot != '') DESC, id DESC
                            LIMIT 1
                        """, (f"%{clean_target_dom}%",)).fetchone()
                        if prior_dom_lead:
                            ex_addr = (prior_dom_lead["address"] or "").strip()
                            ex_name = (prior_dom_lead["name"] or "").strip().lower()
                            is_stub = ex_name in ["home", "welcome", "index", clean_target_dom] or ex_addr in ["N/A", "", "None"]
                            if not is_stub:
                                w_st = str(prior_dom_lead["website_status"] or "clean").strip().lower()
                                emit_event("log", f"⏩ [Agent 2: Website] Domain '{clean_target_dom}' for #{idx} '{name}' was already explored in database ({w_st}). Reusing verified data.")
                                data_to_copy = {
                                    "email": prior_dom_lead["email"] or "",
                                    "instagram": prior_dom_lead["instagram"] or "",
                                    "facebook": prior_dom_lead["facebook"] or "",
                                    "linkedin": prior_dom_lead["linkedin"] or "",
                                    "twitter": prior_dom_lead["twitter"] or "",
                                    "youtube": prior_dom_lead["youtube"] or "",
                                    "tiktok": prior_dom_lead["tiktok"] or "",
                                    "screenshot": prior_dom_lead["screenshot"] or "",
                                    "bot_protection": prior_dom_lead["bot_protection"] or "Clean",
                                    "cookie_status": prior_dom_lead["cookie_status"] or "None",
                                    "website_status": w_st,
                                    "booking_url": prior_dom_lead["booking_url"] or "",
                                    "platform_name": prior_dom_lead["platform_name"] or ""
                                }
                                explored_domains_cache[clean_target_dom] = data_to_copy
                                update_lead_website_data(
                                    name=name, address=address, website=website_url,
                                    **data_to_copy
                                )
                                emit_event("place_updated", {"id": lead_db_id, "name": name, "address": address, "website": website_url, **data_to_copy})
                                queue.task_done()
                                continue
            except Exception:
                pass
            pass

        # Prevent opening Meta platforms (Instagram, Facebook, Threads, Meta) in Tab 2
        w_low = website_url.lower()
        meta_domains = ["facebook.com", "instagram.com", "fb.com", "meta.com", "fb.me", "threads.net", "m.facebook.com"]
        if any(m in w_low for m in meta_domains):
            is_ig = "instagram.com" in w_low
            plat_name = "Instagram" if is_ig else "Facebook"
            emit_event("log", f"ℹ️ [Agent 2: Website] #{idx} '{name}' uses {plat_name} as primary web link. Recorded under socials without opening external Meta platform.")
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
                    "bot_protection": f"Social Profile ({plat_name})",
                    "website_status": "social"
                })
            except Exception:
                pass
            queue.task_done()
            continue

        # Associated booking / directory platform detection (Airbnb, Fresha, Treatwell, Booksy, Practo, etc.)
        platform_mapping = {
            "airbnb.": "Airbnb",
            "fresha.com": "Fresha",
            "treatwell.": "Treatwell",
            "booksy.com": "Booksy",
            "practo.com": "Practo",
            "opentable.": "OpenTable",
            "zomato.com": "Zomato",
            "zoma.to": "Zomato",
            "swiggy.com": "Swiggy",
            "eazydiner.com": "EazyDiner",
            "booking.com": "Booking.com",
            "tripadvisor.": "TripAdvisor",
            "mindbodyonline.com": "Mindbody",
            "vagaro.com": "Vagaro",
            "resy.com": "Resy",
            "phorest.com": "Phorest"
        }
        detected_primary_plat = ""
        for plat_domain, p_name in platform_mapping.items():
            if plat_domain in w_low:
                detected_primary_plat = p_name
                break

        emit_event("log", f"🌐 [Agent 2: Website] Inspecting shop website for #{idx} '{name}': {website_url}")
        emit_event("status", f"Browsing website #{idx}: {name}")
        emit_event("website_navigated", {"url": website_url, "name": name, "index": idx})

        try:

            # Strict Tab 2 Isolation: Dedicated page for Shop Website (Never touches Maps, LinkedIn, or Platform tabs)
            if tab_page is None or tab_page.is_closed():
                tab_page = await context.new_page()
                await clear_fixed_viewport(tab_page)
                try:
                    await tab_page.route("**/*.{mp4,mp3,avi,webm,mkv,wav,ogg,woff,woff2,ttf,eot,svg,gif}", lambda r: r.abort())
                except Exception:
                    pass
                if pages_dict is not None:
                    pages_dict["website"] = tab_page

            # Navigate dedicated tab to shop website with complete DOM & load state wait (Fast 7s timeout)
            nav_success = False
            try:
                await tab_page.goto(website_url, wait_until="domcontentloaded", timeout=7000)
                try:
                    await tab_page.wait_for_load_state("load", timeout=1500)
                except Exception:
                    pass
                await tab_page.wait_for_timeout(300)
                nav_success = True
            except Exception as e:
                emit_event("log", f"⚠️ [Agent 2: Website] Navigation notice on #{idx} '{name}': {str(e)[:50]}")

            curr_url = tab_page.url or ""
            target_dom = clean_domain(website_url)
            curr_dom = clean_domain(curr_url)
            if not nav_success and (not curr_dom or (target_dom and target_dom not in curr_dom)):
                emit_event("log", f"🚫 [Agent 2: Website] #{idx} '{name}' website unreachable: {website_url}. Skipping extraction to prevent stale page bleed.")
                try:
                    await tab_page.goto("about:blank")
                except Exception:
                    pass
                try:
                    fail_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    update_lead_website_data(
                        name=name,
                        address=address,
                        website=website_url,
                        bot_protection="Unreachable (Navigation Failed)",
                        website_status="failed",
                        website_scraped_at=fail_time
                    )
                    emit_event("place_updated", {
                        "id": lead_db_id,
                        "name": name,
                        "address": address,
                        "website": website_url,
                        "bot_protection": "Unreachable (Navigation Failed)",
                        "website_status": "failed",
                        "website_scraped_at": fail_time
                    })
                except Exception:
                    pass
                queue.task_done()
                continue

            # Automatically accept cookies / consent banner if presented
            cookie_status = await detect_and_handle_cookies(tab_page)
            if cookie_status == "Accepted":
                emit_event("log", f"🍪 [Agent 2: Website] Auto-accepted cookie banner on #{idx} '{name}'")
                await tab_page.wait_for_timeout(400)
            elif cookie_status == "Detected (Unaccepted)":
                emit_event("log", f"🍪 [Agent 2: Website] Cookie banner detected on #{idx} '{name}'")

            # Check if Cloudflare Turnstile checkbox is present and attempt to click it
            solved_turnstile = await attempt_turnstile_solve(tab_page)
            if solved_turnstile:
                emit_event("log", f"🛡️ [Agent 2: Website] Handled anti-bot Turnstile checkbox on #{idx} '{name}'")

            page_title = ""
            try:
                page_title = await tab_page.title()
            except Exception:
                pass

            page_html = await tab_page.content()
            soup_pre = BeautifulSoup(page_html, "html.parser")
            name = clean_brand_name_from_page(name or page_title, clean_target_dom, soup_pre, page_html)

            # Show HUD on shop page via extension bridge
            try:
                safe_shop_name = re.sub(r'[\'"]', '', name)[:22]
                await tab_page.evaluate(f"() => window.MavonScraper && window.MavonScraper.showHUD('Shop #{idx}: {safe_shop_name}', 'Scanning emails & socials...', '#10b981')")
            except Exception:
                pass

            # 1. Detect Cloudflare / Anti-bot
            bot_status = detect_anti_bot_protection(page_html, page_title)
            if bot_status != "Clean":
                is_denied = "Access Denied" in bot_status
                log_icon = "🚫" if is_denied else "🛡️"
                emit_event("log", f"{log_icon} [Agent 2: Website] Anti-bot status for #{idx} '{name}' -> {bot_status}")
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

            # 3. Dynamic scroll down to trigger lazy loading of footers & contact sections
            try:
                await tab_page.evaluate("""async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 400;
                        const maxScrolls = 15;
                        let count = 0;
                        const timer = setInterval(() => {
                            const scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            count++;
                            if (totalHeight >= scrollHeight || count >= maxScrolls) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 200);
                    });
                }""")
                await tab_page.wait_for_timeout(600)
            except Exception:
                pass

            # 4. Extract Emails, Physical Address, Phone & Social Media Links
            fresh_html = await tab_page.content()
            soup_fresh = BeautifulSoup(fresh_html, "html.parser")
            emails = set(extract_emails_from_text(fresh_html))
            socials = extract_socials_from_text(fresh_html)

            # Re-check brand name with fresh post-scroll content if it was still generic
            name = clean_brand_name_from_page(name, clean_target_dom, soup_fresh, fresh_html)

            # Deep extraction: Physical Address
            if not address or address == "N/A" or len(address.strip()) < 5:
                extracted_addr = extract_address_from_html(fresh_html, soup_fresh)
                if extracted_addr:
                    address = extracted_addr
                    emit_event("log", f"📍 [Agent 2: Website] Extracted physical address for #{idx} '{name}': {address}")

            # Deep extraction: Phone number
            if not phone or phone == "N/A":
                extracted_phone = extract_phone_from_html(fresh_html, soup_fresh)
                if extracted_phone:
                    phone = extracted_phone
                    emit_event("log", f"📞 [Agent 2: Website] Extracted phone for #{idx} '{name}': {phone}")

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
                                        if (u.includes('facebook.com/') || u.includes('fb.me/')) socs['facebook'] = l;
                                        if (u.includes('linkedin.com/')) socs['linkedin'] = l;
                                        if (u.includes('twitter.com/') || u.includes('x.com/')) socs['twitter'] = l;
                                        if (u.includes('youtube.com/') || u.includes('youtu.be/')) socs['youtube'] = l;
                                        if (u.includes('tiktok.com/')) socs['tiktok'] = l;
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

            # 5. Check Contact / About links if emails, socials, address, or phone are missing or deep_crawl is enabled
            if deep_crawl or not emails or not any(socials.values()) or not address or address == "N/A" or not phone or phone == "N/A":
                try:
                    contact_links = tab_page.locator('a[href*="contact" i], a[href*="about" i], a:has-text("Contact"), a:has-text("About")')
                    count = await contact_links.count()
                    for ci in range(min(count, 5 if deep_crawl else 3)):
                        c_link = contact_links.nth(ci)
                        href_attr = (await c_link.get_attribute("href") or "").lower()
                        # Strictly skip external social and Meta links
                        if any(bad in href_attr for bad in ["facebook.com", "instagram.com", "meta.com", "fb.me", "threads.net", "twitter.com", "x.com", "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com"]):
                            continue
                        if await c_link.is_visible(timeout=800):
                            await c_link.click(timeout=3000)
                            await tab_page.wait_for_timeout(1800)
                            sub_html = await tab_page.content()
                            sub_soup = BeautifulSoup(sub_html, "html.parser")
                            emails.update(extract_emails_from_text(sub_html))
                            sub_socials = extract_socials_from_text(sub_html)
                            for k, v in sub_socials.items():
                                if not socials.get(k) and v:
                                    socials[k] = v
                            if not address or address == "N/A":
                                sub_addr = extract_address_from_html(sub_html, sub_soup)
                                if sub_addr:
                                    address = sub_addr
                                    emit_event("log", f"📍 [Agent 2: Website] Extracted physical address on contact page for #{idx} '{name}': {address}")
                            if not phone or phone == "N/A":
                                sub_phone = extract_phone_from_html(sub_html, sub_soup)
                                if sub_phone:
                                    phone = sub_phone
                                    emit_event("log", f"📞 [Agent 2: Website] Extracted phone on contact page for #{idx} '{name}': {phone}")
                            break
                except Exception:
                    pass

            email_list = sorted(list(emails))
            primary_email = email_list[0] if email_list else ""

            # 6. Extract Associated Booking & Directory Platform links (Airbnb, Fresha, Treatwell, Booksy, Practo, OpenTable, Zomato, etc.)
            found_booking_url = ""
            found_platform_name = detected_primary_plat
            if not found_booking_url and detected_primary_plat:
                found_booking_url = website_url
            try:
                soup_page = BeautifulSoup(fresh_html, "html.parser")
                for a in soup_page.find_all("a", href=True):
                    h_link = a["href"].strip()
                    if not h_link.startswith("http"): continue
                    h_link_low = h_link.lower()
                    for plat_domain, p_name in platform_mapping.items():
                        if plat_domain in h_link_low:
                            if not found_platform_name:
                                found_platform_name = p_name
                                found_booking_url = h_link
                            elif not found_booking_url:
                                found_booking_url = h_link
                            break
                    if found_platform_name and found_booking_url:
                        break
            except Exception:
                pass

            # If emails were successfully extracted from the page, confirm Access Granted
            if primary_email and "Access Denied" in bot_status:
                bot_status = bot_status.replace("Access Denied", "Access Granted")
                emit_event("log", f"🎉 [Agent 2: Website] Contact emails successfully extracted from #{idx} '{name}'!")

            # Immediately update lead record in SQLite database!
            w_status = "clean"
            if email_list:
                w_status = "emails_found"
            elif any(socials.get(k) for k in ["instagram", "facebook", "twitter", "linkedin", "youtube", "tiktok"]):
                w_status = "socials_found"

            now_scraped_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            found_wa = socials.get("whatsapp", "")
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
                    youtube=socials.get("youtube", ""),
                    tiktok=socials.get("tiktok", ""),
                    screenshot=rel_screenshot_path,
                    bot_protection=bot_status,
                    cookie_status=cookie_status,
                    website_status=w_status,
                    booking_url=found_booking_url,
                    platform_name=found_platform_name,
                    website_scraped_at=now_scraped_at,
                    whatsapp=found_wa,
                    phone=phone,
                    category=category
                )
            except Exception as dbe:
                pass

            # Cache extracted domain data for current session
            if clean_target_dom:
                explored_domains_cache[clean_target_dom] = {
                    "email": primary_email,
                    "emails": email_list,
                    "instagram": socials.get("instagram", ""),
                    "facebook": socials.get("facebook", ""),
                    "linkedin": socials.get("linkedin", ""),
                    "twitter": socials.get("twitter", ""),
                    "youtube": socials.get("youtube", ""),
                    "tiktok": socials.get("tiktok", ""),
                    "screenshot": rel_screenshot_path,
                    "bot_protection": bot_status,
                    "cookie_status": cookie_status,
                    "website_status": w_status,
                    "booking_url": found_booking_url,
                    "platform_name": found_platform_name,
                    "website_scraped_at": now_scraped_at,
                    "whatsapp": found_wa
                }

            # Emit update event for this place!
            emit_event("place_updated", {
                "id": lead_db_id,
                "name": name,
                "address": address,
                "phone": phone,
                "website": website_url,
                "email": primary_email,
                "emails": email_list,
                "instagram": socials.get("instagram", ""),
                "facebook": socials.get("facebook", ""),
                "linkedin": socials.get("linkedin", ""),
                "twitter": socials.get("twitter", ""),
                "youtube": socials.get("youtube", ""),
                "tiktok": socials.get("tiktok", ""),
                "screenshot": rel_screenshot_path,
                "bot_protection": bot_status,
                "cookie_status": cookie_status,
                "website_status": w_status,
                "booking_url": found_booking_url,
                "platform_name": found_platform_name,
                "website_scraped_at": now_scraped_at,
                "whatsapp": found_wa
            })

            log_parts = []
            if name: log_parts.append(f"🏢 {name}")
            if address and address != "N/A": log_parts.append(f"📍 {address}")
            if phone and phone != "N/A": log_parts.append(f"📞 {phone}")
            if email_list: log_parts.append(f"✉️ Emails: {', '.join(email_list)}")
            if socials.get("instagram"): log_parts.append(f"📸 IG: {socials['instagram']}")
            if socials.get("facebook"): log_parts.append(f"📘 FB: {socials['facebook']}")
            if socials.get("linkedin"): log_parts.append(f"💼 LinkedIn: {socials['linkedin']}")
            if socials.get("twitter"): log_parts.append(f"🐦 X: {socials['twitter']}")
            if socials.get("youtube"): log_parts.append(f"▶️ YT: {socials['youtube']}")
            if socials.get("tiktok"): log_parts.append(f"🎵 TT: {socials['tiktok']}")
            if found_platform_name and found_booking_url: log_parts.append(f"📅 Booking: {found_platform_name}")
            if bot_status != "Clean": log_parts.append(f"🛡️ {bot_status}")
            if cookie_status != "None": log_parts.append(f"🍪 {cookie_status}")
            msg = " | ".join(log_parts) if log_parts else "No contact emails/socials detected on page"
            emit_event("log", f"✅ [Agent 2: Website] Finished #{idx} '{name}' -> {msg}")

            # -------------------------------------------------------------
            # PARALLEL PIPELINE: Send company to Tab 3 (LinkedIn Intelligence)
            # -------------------------------------------------------------
            if linkedin_queue:
                linkedin_queue.put_nowait({
                    "index": idx,
                    "name": name,
                    "address": address or item.get("address", ""),
                    "website": website_url,
                    "linkedin_url": socials.get("linkedin", ""),
                    "website_emails": email_list
                })

        except Exception as err:
            emit_event("log", f"⚠️ Error processing website for #{idx}: {str(err)[:60]}")
            try:
                err_scraped_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                update_lead_website_data(
                    name=name,
                    address=address,
                    website=website_url,
                    bot_protection=f"Unreachable ({str(err)[:20]})",
                    website_status="failed",
                    website_scraped_at=err_scraped_at
                )
                emit_event("place_updated", {
                    "index": idx,
                    "name": name,
                    "address": address,
                    "website": website_url,
                    "bot_protection": f"Unreachable ({str(err)[:20]})",
                    "website_status": "failed",
                    "website_scraped_at": err_scraped_at
                })
            except Exception:
                pass
            if linkedin_queue:
                linkedin_queue.put_nowait({
                    "index": idx,
                    "name": name,
                    "address": item.get("address", ""),
                    "website": website_url,
                    "linkedin_url": "",
                    "website_emails": []
                })
        finally:
            try:
                import random
                await asyncio.sleep(random.uniform(1.5, 3.0))
            except Exception:
                pass
            try:
                queue.task_done()
            except ValueError:
                pass

async def extract_single_linkedin_profile(page) -> Optional[Dict[str, Any]]:
    """Extracts profile details from an individual LinkedIn profile (/in/<username>)."""
    try:
        return await page.evaluate(r"""() => {
            const nameEl = document.querySelector('h1.inline.t-24.v-align-middle, h1.text-heading-xlarge, h1');
            const titleEl = document.querySelector('.text-body-medium.break-words, div[data-generated-suggestion-target], .pv-text-details__left-panel div.text-body-medium');
            const locEl = document.querySelector('span.text-body-small.inline.t-black--light.break-words, .pv-text-details__left-panel span.text-body-small');
            const imgEl = document.querySelector('img.pv-top-card-profile-picture__image, img[data-view-name="profile-card"], img.presence-entity__image');
            
            let rawName = nameEl ? (nameEl.innerText || nameEl.textContent || "").trim() : "";
            let rawTitle = titleEl ? (titleEl.innerText || titleEl.textContent || "").trim() : "";
            let loc = locEl ? (locEl.innerText || locEl.textContent || "").trim() : "";
            let avatar = imgEl ? imgEl.src : "";
            
            let cleanName = rawName.replace(/•\s*(1st|2nd|3rd\+?|Following|Follow)/gi, '').replace(/\(He\/Him\)|\(She\/Her\)|\(They\/Them\)/gi, '').trim();
            let cleanTitle = rawTitle.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
            
            if (cleanName && cleanName !== "LinkedIn Member" && cleanName.length > 2) {
                return {
                    full_name: cleanName,
                    title: cleanTitle || "Key Personnel",
                    linkedin_profile_url: window.location.href.split('?')[0].replace(/\/+$/, ''),
                    avatar_url: avatar,
                    location: loc
                };
            }
            return null;
        }""")
    except Exception:
        return None

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

        emit_event("log", f"💼 [Agent 3: LinkedIn] Resolving verified LinkedIn profile for #{idx} '{name}' (Brand: '{core_brand}')...")
        emit_event("status", f"Resolving LinkedIn profile: {core_brand}")

        try:
            # Step 1: Determine target verified company URL via cascading directory search
            verified_company_url = None
            known_person_url = None
            if known_linkedin:
                clean_base = clean_linkedin_url(known_linkedin)
                if clean_base and "/company/" in clean_base:
                    verified_company_url = clean_base
                    emit_event("log", f"🔗 [Agent 3: LinkedIn] Using verified corporate LinkedIn URL from website: {verified_company_url}")
                elif clean_base and "/in/" in clean_base:
                    known_person_url = clean_base
                    emit_event("log", f"👤 [Agent 3: LinkedIn] Detected key personnel profile from website: {known_person_url}")

            if not verified_company_url:
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
                    emit_event("log", f"🏢 [Agent 3: LinkedIn] Searching corporate directory for '{cand_query}'...")
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
                            cand_href = clean_linkedin_url(li_result.get("href", ""))
                            cand_title = li_result.get("title", "")
                            if cand_href and (verify_company_name_match(cand_query, cand_title) or verify_company_name_match(core_brand, cand_title)):
                                verified_company_url = cand_href
                                emit_event("log", f"🎯 [Agent 3: LinkedIn] Verified corporate page match: '{cand_title}' ({verified_company_url})")
                                break
                            else:
                                emit_event("log", f"⚠️ [Agent 3: LinkedIn] Candidate '{cand_title}' did not match target '{cand_query}'")
                    except Exception as e:
                        emit_event("log", f"⚠️ [Agent 3: LinkedIn] Search note for '{cand_query}': {str(e)[:40]}")

            if not verified_company_url:
                emit_event("log", f"ℹ️ [Agent 3: LinkedIn] No corporate page found for '{name}'. Switching to Personnel Fallback Search...")

            employees = []

            # Step 2: Open company's /people/ directory if verified corporate page exists
            if verified_company_url:
                people_target = f"{verified_company_url}/people/"
                emit_event("log", f"👥 [Agent 3: LinkedIn] Opening People directory: {people_target}")
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

            # Fallback 1: If 0 cards from company directory and website had a direct personal LinkedIn profile, scrape it
            if len(employees) == 0 and known_person_url:
                try:
                    emit_event("log", f"👤 [LinkedIn Step 2/5] Inspecting personnel profile from website: {known_person_url}...")
                    emit_event("linkedin_navigated", {"url": known_person_url, "name": core_brand})
                    await tab_page.goto(known_person_url, wait_until="domcontentloaded", timeout=12000)
                    await tab_page.wait_for_timeout(1000)
                    p_data = await extract_single_linkedin_profile(tab_page)
                    if p_data:
                        employees.append(p_data)
                        emit_event("log", f"✅ [LinkedIn Step 2/5] Verified personnel profile: '{p_data['full_name']}' ({p_data['title']})")
                except Exception as d_err:
                    emit_event("log", f"⚠️ Direct personnel scrape note: {str(d_err)[:40]}")

            # Fallback 2: Targeted Boolean People Search directly on LinkedIn
            if len(employees) == 0:
                role_bool = '("Founder" OR "Co-Founder" OR "Owner" OR "Director" OR "CEO" OR "Manager" OR "Head" OR "Principal")'
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
                            const seenUrls = new Set();
                            const seenNames = new Set();

                            // Universal search: find all profile anchors matching /in/
                            const profileLinks = document.querySelectorAll('a[href*="/in/"]:not([href*="linkedin.com/help"])');
                            for (const link of profileLinks) {
                                const profile = link.href.split('?')[0].replace(/\/+$/, '');
                                if (!profile || seenUrls.has(profile) || profile.endsWith('/in') || profile.endsWith('/in/')) continue;

                                const card = link.closest('.entity-result, li.reusable-search__result-container, div[data-view-name], .artdeco-entity-lockup, div.org-people-profile-card, li, div') || link;

                                let nameEl = card.querySelector('.org-people-profile-card__profile-title, .entity-result__title-text a, .artdeco-entity-lockup__title, span[aria-hidden="true"], h3, h2, a');
                                let titleEl = card.querySelector('.lt-line-clamp--multi-line, .entity-result__primary-subtitle, .artdeco-entity-lockup__subtitle, .artdeco-entity-lockup__caption');
                                let imgEl = card.querySelector('img[src*="licdn.com"]');
                                let locEl = card.querySelector('.entity-result__secondary-subtitle, .org-people-profile-card__profile-location');
                                let snippetEl = card.querySelector('.entity-result__summary, .reusable-search__card-summary');

                                let rawName = nameEl ? (nameEl.innerText || nameEl.textContent || "") : "";
                                let rawTitle = titleEl ? (titleEl.innerText || titleEl.textContent || "") : "";
                                let avatar = imgEl ? imgEl.src : "";
                                let loc = locEl ? (locEl.innerText || locEl.textContent || "").trim() : "";
                                let snippet = snippetEl ? (snippetEl.innerText || snippetEl.textContent || "").trim() : "";

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
                                    seenUrls.add(profile);
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
                            }
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
                                emit_event("log", f"✅ [Agent 3: LinkedIn] Discovered {len(employees)} verified personnel profiles for '{core_brand}' via targeted keyword search")
                                break
                    except Exception as pe_err:
                        emit_event("log", f"⚠️ [Agent 3: LinkedIn] People search note for query '{p_query}': {str(pe_err)[:40]}")

            # If no corporate company page was found, but linked personnel were discovered, deep-scrape primary individual
            top_person = None
            if employees and not verified_company_url:
                exec_words = ["founder", "owner", "ceo", "director", "managing", "partner", "principal", "president", "head"]
                top_person = next((e for e in employees if any(kw in e.get("title", "").lower() for kw in exec_words)), employees[0])
                p_url = clean_linkedin_url(top_person.get("linkedin_profile_url", ""))
                if p_url and "/in/" in p_url and (not tab_page.url or p_url not in tab_page.url):
                    try:
                        emit_event("log", f"👤 [Agent 3: LinkedIn] Personnel Fallback: Scraping profile details for '{top_person.get('full_name')}' ({p_url})...")
                        emit_event("linkedin_navigated", {"url": p_url, "name": top_person.get('full_name')})
                        await tab_page.goto(p_url, wait_until="domcontentloaded", timeout=12000)
                        await tab_page.wait_for_timeout(800)
                        single_data = await extract_single_linkedin_profile(tab_page)
                        if single_data:
                            top_person.update({k: v for k, v in single_data.items() if v})
                    except Exception as p_err:
                        emit_event("log", f"⚠️ [Agent 3: LinkedIn] Personnel profile scrape note: {str(p_err)[:40]}")

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
            if verified_company_url:
                final_linkedin_url = verified_company_url
                resolved_status = "verified"
            elif employees:
                if not top_person:
                    exec_words = ["founder", "owner", "ceo", "director", "managing", "partner", "principal", "president", "head"]
                    top_person = next((e for e in employees if any(kw in e.get("title", "").lower() for kw in exec_words)), employees[0])
                final_linkedin_url = clean_linkedin_url(top_person.get("linkedin_profile_url", ""))
                resolved_status = "personnel_verified"
            elif known_linkedin:
                clean_known = clean_linkedin_url(known_linkedin)
                final_linkedin_url = clean_known
                resolved_status = "verified" if "/company/" in clean_known else ("personnel_verified" if "/in/" in clean_known else "no_profile")
            else:
                final_linkedin_url = ""
                resolved_status = "no_profile"

            final_linkedin_url = clean_linkedin_url(final_linkedin_url)

            # Save batch to SQLite with explicit lead_id reference
            lead_id_target = item.get("id") or item.get("lead_id")
            saved = save_employees_batch(
                company_name=name,
                employees=employees,
                lead_id=lead_id_target,
                company_linkedin_url=final_linkedin_url,
                linkedin_status=resolved_status
            )

            exec_count = sum(1 for e in employees if classify_seniority(e.get("title", "")) == "executive")
            mgmt_count = sum(1 for e in employees if classify_seniority(e.get("title", "")) == "management")
            staff_count = len(employees) - exec_count - mgmt_count

            emit_event("org_updated", {
                "company": name,
                "linkedin_url": final_linkedin_url,
                "linkedin_status": resolved_status,
                "employee_count": len(employees),
                "tiers": {
                    "executive": exec_count,
                    "management": mgmt_count,
                    "staff": staff_count
                }
            })

            emit_event("place_updated", {
                "id": lead_id_target,
                "name": name,
                "address": address,
                "linkedin": final_linkedin_url,
                "linkedin_url": final_linkedin_url,
                "linkedin_status": resolved_status,
                "employee_count": str(len(employees))
            })

            if resolved_status == "personnel_verified":
                p_name = top_person.get("full_name") if top_person else "Key Personnel"
                emit_event("log", f"👤 [Agent 3: LinkedIn] Finished #{idx} '{name}' -> Linked key personnel: '{p_name}' ({final_linkedin_url}). Total {len(employees)} personnel profiles mapped.")
            elif verified_company_url:
                emit_event("log", f"🏢 [Agent 3: LinkedIn] Finished #{idx} '{name}' -> Corporate page verified ({final_linkedin_url}). Hierarchy: {exec_count} Execs | {mgmt_count} Leads | {staff_count} Staff.")
            else:
                emit_event("log", f"ℹ️ [Agent 3: LinkedIn] Finished #{idx} '{name}' -> No public corporate page or verified personnel on LinkedIn.")

        except Exception as err:
            emit_event("log", f"⚠️ [Agent 3: LinkedIn] Error scanning LinkedIn for '{name}': {str(err)[:60]}")
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
        f_cat = "salon" if enc_cat.lower() in ["shops", "shop", "all", "business"] else enc_cat
        return f"https://www.fresha.com/search?query={f_cat}&address={enc_loc}"
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
    scrape_all: bool = False,
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
        emit_event("log", f"🟣 [Agent 4: Platform] Target platforms active ({len(active_clean_platforms)}): {', '.join(active_clean_platforms)}")

        # =========================================================================
        # PHASE 1: PROXIMITY CENSUS (Discover total businesses across ALL platforms)
        # =========================================================================
        platform_totals = {}
        for p_name in active_clean_platforms:
            target_url = build_platform_area_url(p_name, category, location_name, custom_url_pattern)
            prof = PLATFORM_PROFILES.get(p_name, {"baseline_sec": 5.0, "timeout_sec": 12.0})
            timeout_ms = 15000  # Generous 15s timeout to prevent premature aborts

            emit_event("status", f"Census: Probing {p_name} volume for '{category}' in '{location_name}'...")
            emit_event("log", f"🎯 [Agent 4: Platform] Probing {p_name} total available businesses in '{location_name}'...")
            emit_event("platform_navigated", {"url": target_url, "title": f"{p_name} Proximity Census", "platform": p_name})

            # Check if verified total was already discovered for this platform & location
            cached_tot = get_cached_census_total(p_name, category, location_name)
            if cached_tot and cached_tot > 0:
                final_plat_total = cached_tot
                emit_event("log", f"⚡ [Agent 4: Platform] Reusing verified census count for {p_name} in '{location_name}': ~{final_plat_total} businesses.")
            else:
                detected_total = 0
                try:
                    await platform_page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    try:
                        await platform_page.wait_for_selector(
                            'div[data-testid="card-container"], div[data-qa="venue-card"], a[href*="/a/"], a[href*="/v/"], [data-testid="serp-ia-card"], div.listing_details, article, [role="article"]',
                            timeout=6000
                        )
                    except Exception:
                        pass
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
                            await platform_page.wait_for_selector(
                                'div[data-testid="card-container"], div[data-qa="venue-card"], a[href*="/a/"], a[href*="/v/"], [data-testid="serp-ia-card"], div.listing_details, article, [role="article"]',
                                timeout=8000
                            )
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
                cookie_res = "None"
                bot_res = "Clean"
                try:
                    cookie_res = await detect_and_handle_cookies(platform_page)
                except Exception:
                    pass
                try:
                    await attempt_turnstile_solve(platform_page)
                except Exception:
                    pass
                try:
                    html_src = await platform_page.content()
                    p_title = await platform_page.title()
                    bot_res = detect_anti_bot_protection(html_src, p_title, has_extracted_data=False)
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

                # 3. Smart Location Fallback: If 0 cards detected for micro-location, auto-widen to parent city
                loc_parts = [p.strip() for p in re.split(r'[,–-]+', location_name) if p.strip()]
                if len(loc_parts) > 1:
                    try:
                        init_cards = await platform_page.evaluate("""() => {
                            return document.querySelectorAll('div[data-testid="card-container"], div[data-qa="venue-card"], a[href*="/a/"], a[href*="/v/"], [data-testid="serp-ia-card"], div.listing_details, article, [role="article"]').length;
                        }""")
                        if init_cards == 0:
                            parent_city = loc_parts[-1]
                            fallback_url = build_platform_area_url(p_name, category, parent_city, custom_url_pattern)
                            if fallback_url != target_url:
                                emit_event("log", f"🔄 [Tab 4 - {p_name}] 0 listings for '{loc_parts[0]}'. Smart Fallback auto-widening to parent city '{parent_city}'...")
                                try:
                                    await platform_page.goto(fallback_url, wait_until="domcontentloaded", timeout=12000)
                                    target_url = fallback_url
                                    try:
                                        await detect_and_handle_cookies(platform_page)
                                    except Exception:
                                        pass
                                except Exception as fb_err:
                                    emit_event("log", f"⚠️ [Tab 4 - {p_name}] Smart Fallback notice: {str(fb_err)[:50]}")
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

                        cards.forEach((initialCard, c_idx) => {
                            let linkEl = null;
                            if (initialCard.matches('a')) {
                                linkEl = initialCard;
                            } else {
                                if (isAirbnb) {
                                    linkEl = initialCard.querySelector('a[href*="/rooms/"]');
                                } else if (isFresha) {
                                    linkEl = initialCard.querySelector('a[href*="/a/"], a[href*="/v/"], a[href*="/b/"], a[href*="/salon/"], a[href*="/venue/"], a[data-qa="venue-name-link"]');
                                } else if (isYelp) {
                                    linkEl = initialCard.querySelector('a[href*="/biz/"]');
                                } else if (isTripAdvisor) {
                                    linkEl = initialCard.querySelector('a[href*="_Review-"], a[href*="/Restaurant_Review"], a[href*="/Hotel_Review"], a[href*="/Attraction_Review"], a[href*="/VacationRentalReview"]');
                                }
                                if (!linkEl) {
                                    linkEl = initialCard.querySelector('h2 a, h3 a, h4 a, [data-testid*="title"] a, a[class*="title"], [class*="title"] a, a[href*="/place/"], a[href*="/biz/"], a[href*="/venue/"], a[href*="/hotel/"], a[href*="/restaurant/"], a[href*="/detail/"], a[href*="/item/"]');
                                }
                                if (!linkEl) {
                                    linkEl = initialCard.querySelector('a[href^="http"], a[href^="/"]');
                                }
                            }

                            if (!linkEl || !linkEl.href) return;
                            let href = linkEl.href.split('?')[0].replace(/\/+$/, '');

                            if (isAirbnb && !href.includes('/rooms/')) return;
                            if (isFresha && !href.match(/\/(?:a|v|b|salon|venue|providers)\//i) && !initialCard.querySelector('[data-qa="venue-card"]')) return;
                            if (isYelp && !href.includes('/biz/')) return;
                            if (isTripAdvisor && !href.includes('_Review-') && !href.includes('/Hotel_Review') && !href.includes('/Restaurant_Review') && !href.includes('/Attraction_Review')) return;

                            if (href === currUrl.split('?')[0] || href.match(/\/search(?:results)?\b/i) || href.match(/\/find\b/i)) return;
                            if (isAirbnb && (href.includes('/s/') || href.includes('/homes'))) return;
                            if (href.match(/\/(?:login|signin|signup|register|auth|terms|privacy|cookie|about|contact|help|faq)\b/i)) return;
                            if (href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) return;

                            if (seenUrlsOnPage.has(href)) return;
                            seenUrlsOnPage.add(href);

                            // IMPORTANT: Find the real containing card with text and metadata (not an empty overlay link)
                            let card = initialCard;
                            if (card.matches('a') || (card.innerText || '').trim().length < 5) {
                                let parent = linkEl.closest('article, [class*="card"], li, div') || linkEl.parentElement;
                                while (parent && parent.parentElement && (parent.innerText || '').trim().length < 5) {
                                    parent = parent.parentElement;
                                }
                                if (parent && (parent.innerText || '').trim().length >= 5) {
                                    card = parent;
                                }
                            }

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
                            if (!address) {
                                const cardLines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
                                for (const l of cardLines) {
                                    if (l !== title && (l.includes('mi ') || l.includes('km ') || l.includes('East') || l.includes('West') || l.includes('Street') || l.includes('Road') || l.includes('Avenue') || l.includes('Nagar') || l.includes('Compound') || l.includes('Colony'))) {
                                        address = l.replace(/^[0-9\.\s]+(?:mi|km)\s*·?\s*/i, '').trim();
                                        break;
                                    }
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

                            // Extra fields: maps, social links, website, phone
                            let mapsUrl = '';
                            let igLink = '';
                            let fbLink = '';
                            let liLink = '';
                            let twLink = '';
                            let waLink = '';
                            let extWebsite = '';
                            let phoneNum = '';

                            const allCardLinks = Array.from(card.querySelectorAll('a[href]'));
                            for (const a of allCardLinks) {
                                const h = (a.href || '').trim();
                                const hLower = h.toLowerCase();
                                if (!h || h.startsWith('javascript:') || h.startsWith('#')) continue;

                                if (hLower.includes('maps.google.') || hLower.includes('goo.gl/maps') || hLower.includes('maps.app.goo.gl') || hLower.includes('google.com/maps')) {
                                    if (!mapsUrl) mapsUrl = h;
                                } else if (hLower.includes('instagram.com/')) {
                                    if (!igLink && !hLower.includes('/p/') && !hLower.includes('/explore/')) igLink = h;
                                } else if (hLower.includes('facebook.com/') || hLower.includes('fb.com/')) {
                                    if (!fbLink && !hLower.includes('/sharer') && !hLower.includes('/share')) fbLink = h;
                                } else if (hLower.includes('linkedin.com/')) {
                                    if (!liLink) liLink = h;
                                } else if (hLower.includes('twitter.com/') || hLower.includes('x.com/')) {
                                    if (!twLink && !hLower.includes('/intent/')) twLink = h;
                                } else if (hLower.includes('wa.me/') || hLower.includes('whatsapp.com/send') || hLower.includes('api.whatsapp.com')) {
                                    if (!waLink) waLink = h;
                                } else if (h.startsWith('tel:')) {
                                    if (!phoneNum) phoneNum = h.replace(/^tel:/i, '').trim();
                                } else if (h.startsWith('http')) {
                                    const currHost = window.location.hostname.replace(/^www\./, '');
                                    try {
                                        const linkHost = new URL(h).hostname.replace(/^www\./, '');
                                        if (linkHost && !linkHost.includes(currHost) && !currHost.includes(linkHost)) {
                                            if (!extWebsite && !hLower.match(/\.(png|jpg|jpeg|gif|svg|pdf)$/)) {
                                                extWebsite = h;
                                            }
                                        }
                                    } catch(e) {}
                                }
                            }

                            if (!phoneNum) {
                                const telMatch = textToScan.match(/(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}/);
                                if (telMatch && telMatch[0].replace(/\D/g, '').length >= 8) {
                                    phoneNum = telMatch[0].trim();
                                }
                            }

                            results.push({
                                card_dom_idx: c_idx,
                                title: title.replace(/[\r\n]+/g, ' ').trim(),
                                url: href,
                                address: address,
                                rating: ratingVal,
                                reviews_count: revCount,
                                price_info: priceText.replace(/[\r\n]+/g, ' ').trim(),
                                maps_url: mapsUrl,
                                instagram: igLink,
                                facebook: fbLink,
                                linkedin: liLink,
                                twitter: twLink,
                                whatsapp: waLink,
                                website: extWebsite,
                                phone: phoneNum,
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

                    emit_event("log", f"📜 [Agent 4: Platform - {p_name}] Scroll pass {scroll_pass}: Discovered {len(extracted_listings)}/{max_results} listings ({new_in_pass} new cards).")
                    emit_event("platform_progress", {
                        "platform": p_name,
                        "scraped": len(extracted_listings),
                        "skipped": plat_skipped,
                        "total": plat_total,
                        "percent": min(100, round((len(extracted_listings) / max(1, plat_total)) * 100))
                    })

                    if len(extracted_listings) >= max_results:
                        emit_event("log", f"🎯 [Agent 4: Platform - {p_name}] Reached target quota of {max_results} listings!")
                        break

                    if scroll_pass >= 2 and len(extracted_listings) == 0:
                        emit_event("log", f"⚡ [Agent 4: Platform - {p_name}] Zero listings detected after 2 passes. Fast circuit breaker activated.")
                        break

                    if new_in_pass == 0:
                        consecutive_stagnant += 1
                        if consecutive_stagnant >= 7:
                            has_next = await platform_page.evaluate("""() => {
                                const nextBtn = document.querySelector('a[aria-label="Next"], a[data-qa="pagination-next"], a[rel="next"], [class*="pagination-next"]');
                                if (nextBtn) { nextBtn.click(); return true; }
                                return false;
                            }""")
                            if has_next:
                                emit_event("log", f"➡️ [Agent 4: Platform - {p_name}] Navigating to next directory page...")
                                await platform_page.wait_for_timeout(1500)
                                consecutive_stagnant = 0
                                continue
                            else:
                                emit_event("log", f"🏁 [Agent 4: Platform - {p_name}] Reached end of directory results ({len(extracted_listings)} listings discovered).")
                                break
                    else:
                        consecutive_stagnant = 0

                    await platform_page.evaluate("window.scrollBy({top: 1100, behavior: 'smooth'})")
                    await platform_page.wait_for_timeout(600)

                emit_event("log", f"🟣 [Agent 4: Platform - {p_name}] Total harvested listings from {p_name}: {len(extracted_listings)}.")

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
                        "verified": 0,
                        "maps_url": cand.get("maps_url", ""),
                        "instagram": cand.get("instagram", ""),
                        "facebook": cand.get("facebook", ""),
                        "linkedin": cand.get("linkedin", ""),
                        "twitter": cand.get("twitter", ""),
                        "whatsapp": cand.get("whatsapp", ""),
                        "website": cand.get("website", ""),
                        "phone": cand.get("phone", ""),
                        "cookie_status": cookie_res,
                        "bot_protection": bot_res
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
                        "maps_url": cand.get("maps_url", ""),
                        "instagram": cand.get("instagram", ""),
                        "facebook": cand.get("facebook", ""),
                        "linkedin": cand.get("linkedin", ""),
                        "twitter": cand.get("twitter", ""),
                        "whatsapp": cand.get("whatsapp", ""),
                        "website": cand.get("website", ""),
                        "phone": cand.get("phone", ""),
                        "cookie_status": cookie_res,
                        "bot_protection": bot_res,
                        "verified": False
                    })

                emit_event("log", f"✅ [Agent 4: Platform - {p_name}] Stored {saved_count} verified directory listings in database for '{location_name}'.")

            except Exception as plat_err:
                emit_event("log", f"⚠️ [Agent 4: Platform Error on {p_name}] {type(plat_err).__name__}: {plat_err}")
                logging.exception(f"Error on platform {p_name}")

    except Exception as worker_err:
        emit_event("log", f"❌ [Agent 4: Platform Worker Error] {type(worker_err).__name__}: {worker_err}")
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
    standalone_websites: Optional[str] = None,
    urls_file: Optional[str] = None,
    deep_crawl: bool = False,
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
        if urls_file or standalone_websites or (not enable_maps and enable_website and not enable_linkedin and not enable_platform):
            site_items = []
            if urls_file and os.path.exists(urls_file):
                try:
                    with open(urls_file, "r", encoding="utf-8") as uf:
                        loaded_data = json.load(uf)
                    if isinstance(loaded_data, list):
                        for item in loaded_data:
                            if isinstance(item, str):
                                u = item.strip()
                                if u:
                                    if not u.startswith("http://") and not u.startswith("https://"):
                                        u = "https://" + u
                                    clean_h = u.split("//")[-1].split("/")[0]
                                    site_items.append({"url": u, "name": clean_h, "category": "Business", "address": "N/A", "phone": "N/A"})
                            elif isinstance(item, dict):
                                u = (item.get("url") or item.get("website") or "").strip()
                                if u:
                                    if not u.startswith("http://") and not u.startswith("https://"):
                                        u = "https://" + u
                                    clean_h = u.split("//")[-1].split("/")[0]
                                    site_items.append({
                                        "url": u,
                                        "name": item.get("name") or clean_h,
                                        "category": item.get("category") or "Business",
                                        "address": item.get("address") or "N/A",
                                        "phone": item.get("phone") or "N/A"
                                    })
                except Exception as e:
                    emit_event("log", f"⚠️ [Agent 2: Website] Error loading urls_file: {e}")

            if not site_items:
                if standalone_websites:
                    site_list = [w.strip() for w in standalone_websites.split(",") if w.strip()]
                    for s in site_list:
                        u = s if (s.startswith("http://") or s.startswith("https://")) else "https://" + s
                        clean_h = u.split("//")[-1].split("/")[0]
                        site_items.append({"url": u, "name": clean_h, "category": "Business", "address": "N/A", "phone": "N/A"})
                else:
                    from database import get_all_leads
                    db_leads = get_all_leads()
                    raw_urls = [
                        l["website"] for l in db_leads
                        if l.get("website") and l["website"].startswith("http") and (
                            not l.get("website_status")
                            or l.get("website_status") in ["pending", "None", "", "failed"]
                            or not l.get("screenshot")
                            or l.get("email") in ["N/A", "", None]
                        )
                    ][:25]
                    if not raw_urls:
                        raw_urls = [l["website"] for l in db_leads if l.get("website") and l["website"].startswith("http")][:10]
                    if not raw_urls:
                        raw_urls = ["https://grind.co.uk"]
                    for u in raw_urls:
                        clean_h = u.split("//")[-1].split("/")[0]
                        site_items.append({"url": u, "name": clean_h, "category": "Business", "address": "N/A", "phone": "N/A"})

            emit_event("status", f"Scanning {len(site_items)} websites...")
            emit_event("log", f"🌐 [Agent 2: Website] Starting Standalone Direct Website Scraper for {len(site_items)} target sites")

            website_page = await context.new_page() if cdp_connected else (context.pages[0] if context.pages else await context.new_page())
            await clear_fixed_viewport(website_page)

            stop_stream_event.clear()
            stream_task = asyncio.create_task(frame_streamer_loop(pages_dict={"website": website_page}))

            website_queue = asyncio.Queue()
            done_event = asyncio.Event()

            worker_task = asyncio.create_task(website_worker(context, website_queue, done_event, website_page=website_page, cdp_connected=cdp_connected))

            for idx, sitem in enumerate(site_items, start=1):
                website_queue.put_nowait({
                    "index": idx,
                    "name": sitem["name"],
                    "address": sitem["address"],
                    "website": sitem["url"],
                    "phone": sitem.get("phone", "N/A"),
                    "category": sitem.get("category", "Business"),
                    "deep_crawl": deep_crawl,
                    "force_crawl": True
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
            emit_event("log", "🏁 Finished Standalone Direct Website Scraper.")
            emit_event("completed", {"count": len(site_items), "places": []})
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, default="businesses")
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
    parser.add_argument("--standalone-websites", type=str, default=None)
    parser.add_argument("--urls-file", type=str, default=None)
    parser.add_argument("--deep-crawl", dest="deep_crawl", action="store_true", default=False)
    parser.add_argument("--extension-active", action="store_true", default=False)
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
        standalone_websites=args.standalone_websites,
        urls_file=args.urls_file,
        deep_crawl=args.deep_crawl,
        extension_active=args.extension_active,
    ))
