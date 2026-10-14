import urllib.parse
import json
import os
import re
import sqlite3
from typing import Dict, Any, List, Optional, Tuple

JUNK_EMAIL_PATTERNS = [
    re.compile(r"intl-segmenter", re.I),
    re.compile(r"lodash@", re.I),
    re.compile(r"wght@", re.I),
    re.compile(r"@\d+\.\d+", re.I),
]

def clean_email_string(email_str: str) -> str:
    """Filters out invalid build/package/regex artifact emails and removes HTML entity prefixes."""
    if not email_str or email_str == "N/A":
        return ""
    parts = [p.strip() for p in re.split(r"[,\s]+", str(email_str)) if p.strip()]
    cleaned = []
    for p in parts:
        if p.startswith("u003e") or p.startswith("u003c"):
            p = p[5:]
        if any(pat.search(p) for pat in JUNK_EMAIL_PATTERNS):
            continue
        if "@" in p and "." in p.split("@")[-1]:
            cleaned.append(p.lower())
    return ", ".join(sorted(list(set(cleaned))))

def normalize_bot_protection_status(bot: str, email: str = "", website: str = "", page_title: str = "") -> str:
    """Normalizes bot protection tags into explicit Access Granted vs Access Denied statuses."""
    b = (bot or "").strip()
    if not b or b == "N/A":
        return "N/A" if (not website or website == "N/A") else "Clean"
    if b == "Inspecting...":
        return "N/A" if (not website or website == "N/A") else "Clean"

    has_email = bool(email and email != "N/A")
    if "Access Granted" in b or "Access Denied" in b:
        return b

    w_lower = (website or "").lower()
    t_lower = (page_title or "").lower()

    if "Cloudflare" in b:
        if "thewhoshop" in w_lower or "403" in t_lower or "blocked" in t_lower:
            return "Cloudflare (Access Denied)"
        return "Cloudflare (Access Granted)" if (has_email or website) else "Cloudflare (Access Denied)"

    if "Captcha" in b:
        return "Captcha Challenge (Access Granted)" if (has_email or website) else "Captcha Challenge (Access Denied)"

    if "Datadome" in b:
        return "Datadome (Access Granted)" if has_email else "Datadome (Access Denied)"

    if "PerimeterX" in b:
        return "PerimeterX (Access Granted)" if has_email else "PerimeterX (Access Denied)"

    if "Akamai" in b:
        return "Akamai Shield (Access Denied)"

    if "Imperva" in b or "Incapsula" in b:
        return "Imperva / Incapsula (Access Granted)" if has_email else "Imperva / Incapsula (Access Denied)"

    if "Anti-Bot" in b:
        return "Anti-Bot Challenge (Access Granted)" if has_email else "Anti-Bot Challenge (Access Denied)"

    if b == "Clean":
        return "Clean"

    return b

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads.db")

def get_connection():
    """Returns a SQLite connection configured with WAL mode, optimized cache and mmap sizing to prevent high RAM usage."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA cache_size = -2048;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA mmap_size = 16777216;")
    conn.execute("PRAGMA wal_autocheckpoint = 100;")
    return conn

def init_db():
    """Initialize the SQLite leads database schema with all fields, migrations, and indexes."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT,
                email TEXT,
                phone TEXT,
                address TEXT,
                hours TEXT,
                price TEXT,
                plus_code TEXT,
                rating TEXT,
                reviews TEXT,
                website TEXT,
                maps_url TEXT,
                lat REAL,
                lon REAL,
                instagram TEXT,
                facebook TEXT,
                linkedin TEXT,
                twitter TEXT,
                screenshot TEXT,
                bot_protection TEXT,
                cookie_status TEXT,
                employee_count TEXT,
                org_scraped INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, address)
            )
        """)

        # Create employees table for company hierarchy & LinkedIn org intelligence
        conn.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                company_name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                title TEXT NOT NULL,
                seniority_level TEXT DEFAULT 'staff',
                linkedin_profile_url TEXT,
                email TEXT,
                location TEXT,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE,
                UNIQUE(company_name, full_name, title)
            )
        """)

        # Safely migrate leads table to add platform directory columns if missing
        new_platform_cols = [
            ("platform_name", "TEXT DEFAULT ''"),
            ("platform_url", "TEXT DEFAULT ''"),
            ("platform_rating", "TEXT DEFAULT ''"),
            ("platform_reviews", "TEXT DEFAULT '0'"),
            ("booking_url", "TEXT DEFAULT ''"),
            ("platform_price", "TEXT DEFAULT ''"),
            ("platform_verified", "INTEGER DEFAULT 0"),
            ("maps_status", "TEXT DEFAULT 'captured'"),
            ("website_status", "TEXT DEFAULT 'pending'"),
            ("linkedin_status", "TEXT DEFAULT 'pending'"),
            ("linkedin_url", "TEXT DEFAULT ''"),
        ]
        for col_name, col_def in new_platform_cols:
            try:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_def};")
            except Exception:
                pass

        # Create platforms_config table to manage Platform Directory targets dynamically
        conn.execute("""
            CREATE TABLE IF NOT EXISTS platforms_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                url_template TEXT NOT NULL,
                category TEXT DEFAULT 'General',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Seed default directory platforms if empty
        conn.execute("""
            INSERT OR IGNORE INTO platforms_config (name, url_template, category, is_active) VALUES
            ('Fresha', 'https://www.fresha.com/search?query={query}&address={city}', 'Salons & Wellness', 1),
            ('Airbnb', 'https://www.airbnb.com/s/{city}/homes?query={query}', 'Stays & Hospitality', 1),
            ('Yelp', 'https://www.yelp.com/search?find_desc={query}&find_loc={city}', 'Local Businesses', 1),
            ('TripAdvisor', 'https://www.tripadvisor.com/Search?q={query}+{city}', 'Attractions & Venues', 1),
            ('Treatwell', 'https://www.treatwell.co.uk/places/in-{city}/?q={query}', 'Beauty & Spas', 1),
            ('Justdial', 'https://www.justdial.com/{city}/{query}', 'Local Directory', 1);
        """)

        # Create platform_listings directory table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS platform_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                platform TEXT NOT NULL,
                listing_id TEXT,
                title TEXT NOT NULL,
                clean_brand TEXT,
                category TEXT,
                url TEXT NOT NULL,
                booking_url TEXT,
                rating REAL DEFAULT 0.0,
                reviews_count INTEGER DEFAULT 0,
                price_info TEXT,
                address TEXT,
                latitude REAL,
                longitude REAL,
                verified INTEGER DEFAULT 0,
                services_json TEXT,
                raw_metadata_json TEXT,
                screenshot TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE SET NULL,
                UNIQUE(platform, url)
            )
        """)

        # Create indexes for fast lookup, collision matching, and hierarchy queries
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_name_addr ON leads(name, address);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_website ON leads(website);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_emp_company ON employees(company_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_emp_seniority ON employees(seniority_level);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform_listings_brand ON platform_listings(clean_brand);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform_listings_lead ON platform_listings(lead_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform_listings_platform ON platform_listings(platform);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_name ON leads(name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_web_status ON leads(website_status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_verified_status ON leads(platform_verified, website_status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_emp_status ON leads(org_scraped, employee_count);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform_listings_lead_plat ON platform_listings(lead_id, platform);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform_listings_verified ON platform_listings(verified);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform_listings_title ON platform_listings(title);")
            conn.execute("ALTER TABLE platform_listings ADD COLUMN screenshot TEXT DEFAULT '';")

            # High-performance segmented SQLite views for fast table streaming
            conn.execute("""
                CREATE VIEW IF NOT EXISTS v_master_leads AS
                SELECT * FROM leads
                WHERE platform_verified = 1 OR (platform_name IS NOT NULL AND platform_name != '' AND platform_name != 'N/A')
                ORDER BY id DESC;
            """)
            conn.execute("""
                CREATE VIEW IF NOT EXISTS v_unmatched_maps AS
                SELECT * FROM leads ORDER BY id DESC;
            """)
            conn.execute("""
                CREATE VIEW IF NOT EXISTS v_website_leads AS
                SELECT * FROM leads
                WHERE (website IS NOT NULL AND website != '' AND website != 'N/A')
                   OR website_status IN ('clean', 'emails_found', 'social', 'failed')
                ORDER BY id DESC;
            """)
            conn.execute("""
                CREATE VIEW IF NOT EXISTS v_linkedin_leads AS
                SELECT * FROM leads
                WHERE (employee_count IS NOT NULL AND employee_count != '' AND employee_count != '0')
                   OR (linkedin IS NOT NULL AND linkedin != '' AND linkedin != 'N/A')
                   OR org_scraped > 0
                ORDER BY id DESC;
            """)
        except Exception:
            pass

        # Normalize any NULL values on existing legacy rows to avoid JSON null pointer edge cases
        conn.execute("""
            UPDATE leads SET
                category = COALESCE(category, 'Business'),
                email = COALESCE(email, 'N/A'),
                phone = COALESCE(phone, 'N/A'),
                address = COALESCE(address, 'N/A'),
                hours = COALESCE(hours, 'N/A'),
                price = COALESCE(price, 'N/A'),
                plus_code = COALESCE(plus_code, 'N/A'),
                rating = COALESCE(rating, 'N/A'),
                reviews = COALESCE(reviews, '0'),
                website = COALESCE(website, 'N/A'),
                maps_url = COALESCE(maps_url, ''),
                instagram = COALESCE(instagram, ''),
                facebook = COALESCE(facebook, ''),
                linkedin = COALESCE(linkedin, ''),
                twitter = COALESCE(twitter, ''),
                screenshot = COALESCE(screenshot, ''),
                bot_protection = COALESCE(bot_protection, 'N/A'),
                cookie_status = COALESCE(cookie_status, 'None')
            WHERE email IS NULL OR phone IS NULL OR address IS NULL OR bot_protection IS NULL OR cookie_status IS NULL;
        """)

        conn.commit()

        # Create census cache table to avoid redundant count probing for same location/query
        conn.execute("""
            CREATE TABLE IF NOT EXISTS census_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                query TEXT NOT NULL,
                location TEXT NOT NULL,
                total INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform, query, location)
            )
        """)

def clean_domain(url: str) -> str:
    """Extract clean domain name without protocol, www, or query parameters."""
    if not url or url.upper() in ("N/A", "NONE"):
        return ""
    try:
        clean = url.strip()
        if not clean.startswith(("http://", "https://")):
            clean = "http://" + clean
        parsed = urllib.parse.urlparse(clean)
        dom = parsed.netloc.lower().split(":")[0]
        if dom.startswith("www."):
            dom = dom[4:]
        return dom
    except Exception:
        return ""

def find_matching_lead_id(conn, name: str, address: str = "", website: str = "", phone: str = "") -> Optional[int]:
    """Finds an existing lead matching by (name+address), or clean website domain, or phone, or name with N/A address."""
    clean_n = name.strip()
    clean_addr = address.strip() if address else ""

    # 1. Exact match on name and address
    if clean_addr:
        row = conn.execute("SELECT id FROM leads WHERE name = ? AND address = ?", (clean_n, clean_addr)).fetchone()
        if row:
            return row["id"]

    # 2. Match by clean website domain if not a generic social or aggregator domain
    dom = clean_domain(website)
    if dom and dom not in ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "google.com", "maps.google.com"):
        row = conn.execute("SELECT id FROM leads WHERE website LIKE ?", (f"%{dom}%",)).fetchone()
        if row:
            return row["id"]

    # 3. Match by phone digits (if phone has at least 8 digits)
    phone_digits = re.sub(r"\D", "", phone or "")
    if len(phone_digits) >= 8:
        rows = conn.execute("SELECT id, phone FROM leads WHERE phone IS NOT NULL AND phone != '' AND phone != 'N/A'").fetchall()
        for r in rows:
            if re.sub(r"\D", "", r["phone"]) == phone_digits:
                return r["id"]

    # 4. Same business name where existing row has address = 'N/A' or empty, or incoming has address = 'N/A'
    row = conn.execute("SELECT id, address FROM leads WHERE LOWER(name) = LOWER(?)", (clean_n,)).fetchone()
    if row:
        existing_addr = (row["address"] or "").strip()
        if existing_addr in ("N/A", "") or clean_addr in ("N/A", ""):
            return row["id"]

    return None

def is_lead_in_db(name: str, address: str = "") -> bool:
    """Check if a shop is already indexed in the database to prevent re-scraping."""
    if not name:
        return False
    with get_connection() as conn:
        clean_n = name.strip()
        clean_addr = address.strip() if address else ""
        if clean_addr and clean_addr != "N/A":
            row = conn.execute("SELECT id FROM leads WHERE LOWER(name) = LOWER(?) AND LOWER(address) = LOWER(?)", (clean_n, clean_addr)).fetchone()
            if row:
                return True
        row = conn.execute("SELECT id, email, website FROM leads WHERE LOWER(name) = LOWER(?)", (clean_n,)).fetchone()
        if row and (row["email"] not in ("N/A", "") or row["website"] not in ("N/A", "")):
            return True
    return False

def load_proximity_dedup_cache(location_name: str = "") -> Dict[str, Any]:
    """
    Pre-caches existing leads and directory listings in memory for O(1) microsecond
    deduplication during live proximity search. Scoped by location to prevent false skips
    when a new location/city is searched.
    """
    cache = {
        "location": location_name.strip().lower(),
        "leads_names": set(),
        "leads_name_addr": set(),
        "leads_name_to_addrs": {},
        "leads_phones": set(),
        "listings_urls": set(),
        "listings_titles": set(),
        "total_existing_leads": 0,
        "total_existing_listings": 0
    }
    with get_connection() as conn:
        leads = conn.execute("SELECT name, address, phone FROM leads").fetchall()
        for l in leads:
            n = (l["name"] or "").strip().lower()
            a = (l["address"] or "").strip().lower()
            p = re.sub(r'\D', '', l["phone"] or "")
            if n:
                cache["leads_names"].add(n)
                if n not in cache["leads_name_to_addrs"]:
                    cache["leads_name_to_addrs"][n] = []
                if a and a != 'n/a':
                    cache["leads_name_addr"].add((n, a))
                    cache["leads_name_to_addrs"][n].append(a)
            if len(p) >= 8:
                cache["leads_phones"].add(p)
        cache["total_existing_leads"] = len(leads)

        listings = conn.execute("SELECT platform, title, url FROM platform_listings").fetchall()
        for lst in listings:
            t = (lst["title"] or "").strip().lower()
            u = (lst["url"] or "").split('?')[0].rstrip('/')
            if t:
                cache["listings_titles"].add(t)
            if u:
                cache["listings_urls"].add(u)
        cache["total_existing_listings"] = len(listings)

    return cache

def is_place_already_scraped(name: str, address_snippet: str = "", dedup_cache: Dict[str, Any] = None) -> bool:
    """
    Fast pre-click deduplication check.
    If dedup_cache is provided, performs an instantaneous in-memory check in O(1) time.
    Distinguishes franchise branches (e.g. Starbucks Bandra vs Starbucks Colaba).
    """
    if not name:
        return False
    clean_n = name.strip().lower()
    clean_a = address_snippet.strip().lower()

    if dedup_cache is not None:
        has_addr = bool(clean_a and clean_a != 'n/a')
        
        # O(1) dictionary lookup by business name
        name_to_addrs = dedup_cache.get("leads_name_to_addrs")
        if name_to_addrs is not None:
            ex_addrs = name_to_addrs.get(clean_n)
        else:
            ex_addrs = [ex_a for ex_n, ex_a in dedup_cache.get("leads_name_addr", set()) if ex_n == clean_n]
            if not ex_addrs and clean_n in dedup_cache.get("leads_names", set()):
                ex_addrs = []

        if ex_addrs is not None:
            if has_addr:
                for ex_a in ex_addrs:
                    if ex_a and ex_a != 'n/a' and (ex_a in clean_a or clean_a in ex_a):
                        return True
                # If address snippet was provided and did not match any existing branch, it's a distinct franchise branch!
                return False
            else:
                # Name matched and no address snippet provided
                target_loc = dedup_cache.get("location", "")
                if target_loc and ex_addrs:
                    has_same_loc = any(target_loc in ex_a for ex_a in ex_addrs)
                    if not has_same_loc:
                        return False  # Location has changed! Allow scraping this new branch
                return True
        return False

    # Fallback to direct DB check if cache is omitted
    return is_lead_in_db(name, address_snippet)

def is_platform_listing_already_scraped(platform: str, title: str, url: str = "", dedup_cache: Dict[str, Any] = None) -> bool:
    """
    Fast deduplication check for platform directory listings.
    """
    clean_t = (title or "").strip().lower()
    clean_u = (url or "").split('?')[0].rstrip('/')

    if dedup_cache:
        if clean_u and clean_u in dedup_cache.get("listings_urls", set()):
            return True
        if clean_t and clean_t in dedup_cache.get("listings_titles", set()):
            return True

    with get_connection() as conn:
        if clean_u:
            row = conn.execute("SELECT id FROM platform_listings WHERE url = ?", (clean_u,)).fetchone()
            if row:
                return True
        if clean_t:
            row = conn.execute("SELECT id FROM platform_listings WHERE LOWER(title) = ? AND platform = ?", (clean_t, platform)).fetchone()
            if row:
                return True
    return False

def save_lead(lead: Dict[str, Any]) -> bool:
    """Save or update a lead in the SQLite database, handling missing fields, multi-key deduplication, and merging data."""
    name = str(lead.get("name", "")).strip()
    if not name:
        return False

    category = str(lead.get("category", "") or "Business").strip()
    raw_email = str(lead.get("email", "") or "").strip()
    email = clean_email_string(raw_email)
    phone = str(lead.get("phone", "") or "").strip()
    if phone == "None" or not phone:
        phone = "N/A"
    address = str(lead.get("address", "") or "").strip()
    hours = str(lead.get("hours", "") or "").strip()
    price = str(lead.get("price", "") or "").strip()
    plus_code = str(lead.get("plus_code", "") or "").strip()
    rating = str(lead.get("rating", "") or "").strip()
    reviews = str(lead.get("reviews", "") or "0").strip()
    website = str(lead.get("website", "") or "").strip()
    maps_url = str(lead.get("maps_url", "") or "").strip()
    lat = lead.get("lat")
    lon = lead.get("lon")
    instagram = str(lead.get("instagram", "") or "").strip()
    facebook = str(lead.get("facebook", "") or "").strip()
    linkedin = str(lead.get("linkedin", "") or "").strip()
    twitter = str(lead.get("twitter", "") or "").strip()
    screenshot = str(lead.get("screenshot", "") or "").strip()
    bot_protection = normalize_bot_protection_status(str(lead.get("bot_protection", "") or "").strip(), email, website)
    cookie_status = str(lead.get("cookie_status", "") or "").strip()
    if cookie_status == "Inspecting...":
        cookie_status = "None"

    with get_connection() as conn:
        try:
            # Check for existing matching record across all unique vectors
            matching_id = find_matching_lead_id(conn, name=name, address=address, website=website, phone=phone)

            if matching_id:
                # Merge incoming data into existing lead without downgrading existing valid values
                conn.execute("""
                    UPDATE leads SET
                        category = CASE WHEN ? != '' AND ? != 'Business' THEN ? ELSE category END,
                        email = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE email END,
                        phone = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE phone END,
                        address = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE address END,
                        hours = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE hours END,
                        price = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE price END,
                        plus_code = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE plus_code END,
                        rating = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE rating END,
                        reviews = CASE WHEN ? != '' AND ? != '0' AND ? != 'N/A' THEN ? ELSE reviews END,
                        website = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE website END,
                        maps_url = CASE WHEN ? != '' THEN ? ELSE maps_url END,
                        lat = CASE WHEN ? IS NOT NULL THEN ? ELSE lat END,
                        lon = CASE WHEN ? IS NOT NULL THEN ? ELSE lon END,
                        instagram = CASE WHEN ? != '' THEN ? ELSE instagram END,
                        facebook = CASE WHEN ? != '' THEN ? ELSE facebook END,
                        linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END,
                        twitter = CASE WHEN ? != '' THEN ? ELSE twitter END,
                        screenshot = CASE WHEN ? != '' THEN ? ELSE screenshot END,
                        bot_protection = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE bot_protection END,
                        cookie_status = CASE WHEN ? != '' AND ? != 'None' THEN ? ELSE cookie_status END
                    WHERE id = ?
                """, (
                    category, category, category,
                    email, email, email,
                    phone, phone, phone,
                    address, address, address,
                    hours, hours, hours,
                    price, price, price,
                    plus_code, plus_code, plus_code,
                    rating, rating, rating,
                    reviews, reviews, reviews,
                    website, website, website,
                    maps_url, maps_url,
                    lat, lat,
                    lon, lon,
                    instagram, instagram,
                    facebook, facebook,
                    linkedin, linkedin,
                    twitter, twitter,
                    screenshot, screenshot,
                    bot_protection, bot_protection,
                    cookie_status, cookie_status,
                    matching_id
                ))
                conn.commit()
                return matching_id
            else:
                # Insert brand-new lead
                w_status = "pending" if (website and website.startswith("http")) else "no_website"
                cursor = conn.execute("""
                    INSERT INTO leads (name, category, email, phone, address, hours, price, plus_code, rating, reviews, website, maps_url, lat, lon, instagram, facebook, linkedin, twitter, screenshot, bot_protection, cookie_status, website_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, category, email, phone, address, hours, price, plus_code, rating, reviews, website, maps_url, lat, lon, instagram, facebook, linkedin, twitter, screenshot, bot_protection, cookie_status, w_status))
                conn.commit()
                return cursor.lastrowid
        except Exception:
            return 0

def deduplicate_database() -> int:
    """Scans leads.db and merges any duplicate records with matching names or websites into a single clean row."""
    with get_connection() as conn:
        leads = conn.execute("SELECT * FROM leads ORDER BY id ASC").fetchall()
        seen = {}
        merged_count = 0

        for lead in leads:
            lid = lead["id"]
            name = (lead["name"] or "").strip().lower()
            dom = clean_domain(lead["website"] or "")

            match_id = None
            if name in seen:
                match_id = seen[name]
            elif dom and dom in seen:
                match_id = seen[dom]

            if match_id and match_id != lid:
                # Re-link any employees associated with lid to match_id
                conn.execute("UPDATE employees SET lead_id = ? WHERE lead_id = ?", (match_id, lid))
                # Remove duplicate row first to prevent UNIQUE(name, address) collision during UPDATE
                conn.execute("DELETE FROM leads WHERE id = ?", (lid,))
                # Merge non-empty fields from current into keeper
                conn.execute("""
                    UPDATE leads SET
                        category = CASE WHEN (category IS NULL OR category = 'Business') AND ? != 'Business' THEN ? ELSE category END,
                        email = CASE WHEN (email IS NULL OR email = '' OR email = 'N/A') AND ? != 'N/A' THEN ? ELSE email END,
                        phone = CASE WHEN (phone IS NULL OR phone = '' OR phone = 'N/A') AND ? != 'N/A' THEN ? ELSE phone END,
                        address = CASE WHEN (address IS NULL OR address = '' OR address = 'N/A') AND ? != 'N/A' THEN ? ELSE address END,
                        website = CASE WHEN (website IS NULL OR website = '' OR website = 'N/A') AND ? != 'N/A' THEN ? ELSE website END,
                        maps_url = CASE WHEN (maps_url IS NULL OR maps_url = '') THEN ? ELSE maps_url END,
                        screenshot = CASE WHEN (screenshot IS NULL OR screenshot = '') THEN ? ELSE screenshot END,
                        bot_protection = CASE WHEN (bot_protection IS NULL OR bot_protection = '' OR bot_protection = 'N/A') AND ? != 'N/A' THEN ? ELSE bot_protection END,
                        cookie_status = CASE WHEN (cookie_status IS NULL OR cookie_status = '' OR cookie_status = 'None') AND ? != 'None' THEN ? ELSE cookie_status END
                    WHERE id = ?
                """, (
                    lead["category"], lead["category"],
                    lead["email"], lead["email"],
                    lead["phone"], lead["phone"],
                    lead["address"], lead["address"],
                    lead["website"], lead["website"],
                    lead["maps_url"],
                    lead["screenshot"],
                    lead["bot_protection"], lead["bot_protection"],
                    lead["cookie_status"], lead["cookie_status"],
                    match_id
                ))
                merged_count += 1
            else:
                seen[name] = lid
                if dom:
                    seen[dom] = lid

        conn.commit()
    renumber_and_clean_database()
    return merged_count

def renumber_and_clean_database() -> Dict[str, Any]:
    """
    Renumbers all leads and employees sequentially (1, 2, 3...) preserving foreign keys.
    Cleans email false-positives, normalizes bot protection (Access Granted vs Access Denied),
    and resets SQLite autoincrement sequence counters.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM leads ORDER BY created_at ASC, id ASC")
        raw_leads = cursor.fetchall()

        cursor.execute("SELECT * FROM employees ORDER BY id ASC")
        raw_employees = cursor.fetchall()

        if not raw_leads:
            return {"status": "ok", "leads_renumbered": 0, "employees_renumbered": 0}

        id_map = {}
        cleaned_leads = []

        for idx, row in enumerate(raw_leads, start=1):
            old_id = row["id"]
            id_map[old_id] = idx
            item = dict(row)
            item["new_id"] = idx

            clean_em = clean_email_string(item.get("email", ""))
            item["email"] = clean_em

            item["bot_protection"] = normalize_bot_protection_status(
                item.get("bot_protection", ""),
                clean_em,
                item.get("website", ""),
            )

            if item.get("cookie_status") == "Inspecting...":
                item["cookie_status"] = "None"

            ph = str(item.get("phone", "") or "").strip()
            item["phone"] = "N/A" if (not ph or ph == "None") else ph

            cleaned_leads.append(item)

        cleaned_employees = []
        for jdx, erow in enumerate(raw_employees, start=1):
            eitem = dict(erow)
            eitem["new_id"] = jdx
            old_lid = eitem.get("lead_id")
            eitem["lead_id"] = id_map.get(old_lid, None)
            cleaned_employees.append(eitem)

        cursor.execute("DROP TABLE IF EXISTS leads_backup;")
        cursor.execute("DROP TABLE IF EXISTS employees_backup;")
        cursor.execute("ALTER TABLE leads RENAME TO leads_backup;")
        cursor.execute("ALTER TABLE employees RENAME TO employees_backup;")

        cursor.execute("""
            CREATE TABLE leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT,
                email TEXT,
                phone TEXT,
                address TEXT,
                hours TEXT,
                price TEXT,
                plus_code TEXT,
                rating TEXT,
                reviews TEXT,
                website TEXT,
                maps_url TEXT,
                lat REAL,
                lon REAL,
                instagram TEXT,
                facebook TEXT,
                linkedin TEXT,
                twitter TEXT,
                screenshot TEXT,
                bot_protection TEXT,
                cookie_status TEXT,
                employee_count TEXT,
                org_scraped INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                platform_name TEXT DEFAULT '',
                platform_url TEXT DEFAULT '',
                platform_rating TEXT DEFAULT '',
                platform_reviews TEXT DEFAULT '0',
                booking_url TEXT DEFAULT '',
                platform_price TEXT DEFAULT '',
                platform_verified INTEGER DEFAULT 0,
                maps_status TEXT DEFAULT 'captured',
                website_status TEXT DEFAULT 'pending',
                linkedin_status TEXT DEFAULT 'pending',
                linkedin_url TEXT DEFAULT '',
                UNIQUE(name, address)
            );
        """)

        cursor.execute("""
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                company_name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                title TEXT NOT NULL,
                seniority_level TEXT DEFAULT 'staff',
                linkedin_profile_url TEXT,
                email TEXT,
                location TEXT,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE,
                UNIQUE(company_name, full_name, title)
            );
        """)

        for l in cleaned_leads:
            cursor.execute("""
                INSERT INTO leads (
                    id, name, category, email, phone, address, hours, price, plus_code,
                    rating, reviews, website, maps_url, lat, lon, instagram, facebook,
                    linkedin, twitter, screenshot, bot_protection, cookie_status,
                    employee_count, org_scraped, created_at,
                    platform_name, platform_url, platform_rating, platform_reviews,
                    booking_url, platform_price, platform_verified, maps_status,
                    website_status, linkedin_status, linkedin_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                l["new_id"], l["name"], l.get("category", "Business"), l["email"], l.get("phone", "N/A"),
                l.get("address", "N/A"), l.get("hours", "N/A"), l.get("price", "N/A"), l.get("plus_code", "N/A"),
                l.get("rating", "N/A"), l.get("reviews", "0"), l.get("website", "N/A"), l.get("maps_url", ""),
                l.get("lat"), l.get("lon"), l.get("instagram", ""), l.get("facebook", ""),
                l.get("linkedin", ""), l.get("twitter", ""), l.get("screenshot", ""),
                l["bot_protection"], l.get("cookie_status", "None"),
                l.get("employee_count", "0"), l.get("org_scraped", 0), l.get("created_at"),
                l.get("platform_name", ""), l.get("platform_url", ""), l.get("platform_rating", ""),
                l.get("platform_reviews", "0"), l.get("booking_url", ""), l.get("platform_price", ""),
                l.get("platform_verified", 0), l.get("maps_status", "captured"),
                l.get("website_status", "pending"), l.get("linkedin_status", "pending"),
                l.get("linkedin_url", "")
            ))

        for e in cleaned_employees:
            cursor.execute("""
                INSERT INTO employees (
                    id, lead_id, company_name, full_name, title, seniority_level,
                    linkedin_profile_url, email, location, avatar_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                e["new_id"], e["lead_id"], e["company_name"], e["full_name"], e["title"],
                e.get("seniority_level", "staff"), e.get("linkedin_profile_url", ""),
                e.get("email", ""), e.get("location", ""), e.get("avatar_url", ""), e.get("created_at")
            ))

        # Re-link platform_listings to renumbered leads
        for old_id, new_id in id_map.items():
            if old_id != new_id:
                cursor.execute("UPDATE platform_listings SET lead_id = ? WHERE lead_id = ?", (new_id, old_id))

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_name_addr ON leads(name, address);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_website ON leads(website);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_company ON employees(company_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_seniority ON employees(seniority_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_name ON leads(name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_web_status ON leads(website_status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_li_status ON leads(linkedin_status);")

        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('leads', 'employees');")
        cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('leads', ?);", (len(cleaned_leads),))
        cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('employees', ?);", (len(cleaned_employees),))

        cursor.execute("DROP TABLE IF EXISTS leads_backup;")
        cursor.execute("DROP TABLE IF EXISTS employees_backup;")

        conn.commit()

        return {
            "status": "ok",
            "leads_renumbered": len(cleaned_leads),
            "employees_renumbered": len(cleaned_employees),
            "max_lead_id": len(cleaned_leads),
        }


def update_lead_linkedin_data(
    name: str,
    address: str = "",
    linkedin_url: str = "",
    employee_count: str = "",
    linkedin_status: str = "found",
    org_scraped: int = 1
) -> bool:
    """Updates LinkedIn status and employee hierarchy info for an existing lead."""
    clean_name = str(name or "").strip()
    if not clean_name:
        return False

    with get_connection() as conn:
        try:
            matching_id = find_matching_lead_id(conn, name=clean_name, address=address)
            if not matching_id:
                # Try finding by name only
                row = conn.execute("SELECT id FROM leads WHERE name = ? ORDER BY id DESC LIMIT 1;", (clean_name,)).fetchone()
                if row:
                    matching_id = row["id"]

            if matching_id:
                conn.execute("""
                    UPDATE leads SET
                        linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END,
                        linkedin_url = CASE WHEN ? != '' THEN ? ELSE linkedin_url END,
                        employee_count = CASE WHEN ? != '' THEN ? ELSE employee_count END,
                        linkedin_status = ?,
                        org_scraped = CASE WHEN ? > 0 THEN ? ELSE org_scraped END
                    WHERE id = ?;
                """, (
                    linkedin_url, linkedin_url,
                    linkedin_url, linkedin_url,
                    employee_count, employee_count,
                    linkedin_status,
                    org_scraped, org_scraped,
                    matching_id
                ))
                conn.commit()
                return True
        except Exception:
            pass
    return False

def update_lead_website_data(
    name: str,
    address: str = "",
    website: str = "",
    email: str = "",
    instagram: str = "",
    facebook: str = "",
    linkedin: str = "",
    twitter: str = "",
    screenshot: str = "",
    bot_protection: str = "",
    cookie_status: str = "",
    website_status: str = "found"
) -> bool:
    """
    Updates website-extracted metadata for an existing lead using robust multi-tier matching:
    1. Match by website URL if known
    2. Fallback to name + flexible address match
    3. Fallback to name match
    """
    clean_name = str(name or "").strip()
    clean_address = str(address or "").strip()
    clean_website = str(website or "").strip()

    if not clean_name and not clean_website:
        return False

    email = clean_email_string(email)
    bot_protection = normalize_bot_protection_status(bot_protection, email, clean_website)
    if cookie_status == "Inspecting...":
        cookie_status = "None"

    with get_connection() as conn:
        try:
            # 1. First attempt: match by website URL
            cursor = None
            if clean_website and clean_website not in ["", "N/A"]:
                cursor = conn.execute("""
                    UPDATE leads SET
                        email = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE email END,
                        instagram = CASE WHEN ? != '' THEN ? ELSE instagram END,
                        facebook = CASE WHEN ? != '' THEN ? ELSE facebook END,
                        linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END,
                        twitter = CASE WHEN ? != '' THEN ? ELSE twitter END,
                        screenshot = CASE WHEN ? != '' THEN ? ELSE screenshot END,
                        bot_protection = CASE WHEN ? != '' THEN ? ELSE bot_protection END,
                        cookie_status = CASE WHEN ? != '' THEN ? ELSE cookie_status END,
                        website_status = CASE WHEN ? != '' THEN ? ELSE website_status END
                    WHERE website = ? OR website = ? OR website = ?
                """, (
                    email, email, email,
                    instagram, instagram,
                    facebook, facebook,
                    linkedin, linkedin,
                    twitter, twitter,
                    screenshot, screenshot,
                    bot_protection, bot_protection,
                    cookie_status, cookie_status,
                    website_status, website_status,
                    clean_website,
                    clean_website.rstrip('/'),
                    clean_website.rstrip('/') + '/'
                ))

            # 2. Second attempt: match by name and address (or fuzzy N/A address)
            if not cursor or cursor.rowcount == 0:
                cursor = conn.execute("""
                    UPDATE leads SET
                        email = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE email END,
                        instagram = CASE WHEN ? != '' THEN ? ELSE instagram END,
                        facebook = CASE WHEN ? != '' THEN ? ELSE facebook END,
                        linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END,
                        twitter = CASE WHEN ? != '' THEN ? ELSE twitter END,
                        screenshot = CASE WHEN ? != '' THEN ? ELSE screenshot END,
                        bot_protection = CASE WHEN ? != '' THEN ? ELSE bot_protection END,
                        cookie_status = CASE WHEN ? != '' THEN ? ELSE cookie_status END,
                        website_status = CASE WHEN ? != '' THEN ? ELSE website_status END
                    WHERE name = ? AND (
                        address = ?
                        OR address = 'N/A'
                        OR address = ''
                        OR ? = 'N/A'
                        OR ? = ''
                        OR address LIKE ?
                    )
                """, (
                    email, email, email,
                    instagram, instagram,
                    facebook, facebook,
                    linkedin, linkedin,
                    twitter, twitter,
                    screenshot, screenshot,
                    bot_protection, bot_protection,
                    cookie_status, cookie_status,
                    website_status, website_status,
                    clean_name,
                    clean_address,
                    clean_address,
                    clean_address,
                    f"%{clean_address[:15]}%" if len(clean_address) > 10 else clean_address
                ))

            # 3. Third attempt: match by exact name if still no rows updated
            if not cursor or cursor.rowcount == 0:
                conn.execute("""
                    UPDATE leads SET
                        email = CASE WHEN ? != '' AND ? != 'N/A' THEN ? ELSE email END,
                        instagram = CASE WHEN ? != '' THEN ? ELSE instagram END,
                        facebook = CASE WHEN ? != '' THEN ? ELSE facebook END,
                        linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END,
                        twitter = CASE WHEN ? != '' THEN ? ELSE twitter END,
                        screenshot = CASE WHEN ? != '' THEN ? ELSE screenshot END,
                        bot_protection = CASE WHEN ? != '' THEN ? ELSE bot_protection END,
                        cookie_status = CASE WHEN ? != '' THEN ? ELSE cookie_status END,
                        website_status = CASE WHEN ? != '' THEN ? ELSE website_status END
                    WHERE name = ?
                """, (
                    email, email, email,
                    instagram, instagram,
                    facebook, facebook,
                    linkedin, linkedin,
                    twitter, twitter,
                    screenshot, screenshot,
                    bot_protection, bot_protection,
                    cookie_status, cookie_status,
                    website_status, website_status,
                    clean_name
                ))

            conn.commit()
            return True
        except Exception:
            return False

def get_all_leads() -> List[Dict[str, Any]]:
    """Retrieve all saved leads from the SQLite database, with COALESCE to guarantee non-null string fields."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id,
                   name,
                   COALESCE(category, 'Business') AS category,
                   COALESCE(email, 'N/A') AS email,
                   COALESCE(phone, 'N/A') AS phone,
                   COALESCE(address, 'N/A') AS address,
                   COALESCE(hours, 'N/A') AS hours,
                   COALESCE(price, 'N/A') AS price,
                   COALESCE(plus_code, 'N/A') AS plus_code,
                   COALESCE(rating, 'N/A') AS rating,
                   COALESCE(reviews, '0') AS reviews,
                   COALESCE(website, 'N/A') AS website,
                   COALESCE(maps_url, '') AS maps_url,
                   lat,
                   lon,
                   COALESCE(instagram, '') AS instagram,
                   COALESCE(facebook, '') AS facebook,
                   COALESCE(linkedin, '') AS linkedin,
                   COALESCE(twitter, '') AS twitter,
                   COALESCE(screenshot, '') AS screenshot,
                   COALESCE(bot_protection, 'N/A') AS bot_protection,
                   COALESCE(cookie_status, 'None') AS cookie_status,
                   COALESCE(employee_count, '0') AS employee_count,
                   COALESCE(org_scraped, 0) AS org_scraped,
                   COALESCE(platform_name, '') AS platform_name,
                   COALESCE(platform_url, '') AS platform_url,
                   COALESCE(platform_rating, '') AS platform_rating,
                   COALESCE(platform_reviews, '0') AS platform_reviews,
                   COALESCE(booking_url, '') AS booking_url,
                   COALESCE(platform_price, '') AS platform_price,
                   COALESCE(platform_verified, 0) AS platform_verified,
                   created_at
            FROM leads ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_cached_census_total(platform: str, query: str, location: str) -> Optional[int]:
    """Retrieve verified census total for a given platform, query, and location to bypass redundant network requests."""
    if not platform or not location:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT total FROM census_cache WHERE LOWER(platform) = ? AND LOWER(query) = ? AND LOWER(location) = ?",
            (platform.strip().lower(), query.strip().lower(), location.strip().lower())
        ).fetchone()
        return row[0] if row else None

def set_cached_census_total(platform: str, query: str, location: str, total: int):
    """Store or update verified census total for a given platform, query, and location."""
    if total <= 0 or not platform or not location:
        return
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO census_cache (platform, query, location, total, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(platform, query, location) DO UPDATE SET total = excluded.total, updated_at = CURRENT_TIMESTAMP
        """, (platform.strip().lower(), query.strip().lower(), location.strip().lower(), total))

def get_pending_resume_leads() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Finds leads from database that were paused before their website or LinkedIn inspection finished.
    """
    pending_web = []
    pending_li = []
    with get_connection() as conn:
        # Leads with a website where email/anti-bot inspection was paused or not done
        rows_web = conn.execute("""
            SELECT id, name, address, website
            FROM leads
            WHERE website IS NOT NULL AND website != 'N/A' AND website LIKE 'http%'
              AND (bot_protection = 'Inspecting...' OR (email = 'N/A' AND (bot_protection IS NULL OR bot_protection = 'None')))
            ORDER BY id ASC
            LIMIT 500
        """).fetchall()
        for r in rows_web:
            pending_web.append({"index": r[0], "name": r[1], "address": r[2] or "N/A", "website": r[3]})

        # Leads where LinkedIn employee roster was not yet harvested
        rows_li = conn.execute("""
            SELECT id, name, address, website, linkedin
            FROM leads
            WHERE (org_scraped = 0 OR org_scraped IS NULL)
              AND id NOT IN (SELECT DISTINCT lead_id FROM employees WHERE lead_id IS NOT NULL)
            ORDER BY id ASC
            LIMIT 500
        """).fetchall()
        for r in rows_li:
            pending_li.append({
                "index": r[0],
                "name": r[1],
                "address": r[2] or "N/A",
                "website": r[3] if r[3] and r[3] != "N/A" else "",
                "linkedin_url": r[4] if r[4] and r[4] != "N/A" else ""
            })
    return pending_web, pending_li

def get_lead_count() -> int:
    """Return total count of leads in database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM leads")
        row = cursor.fetchone()
        return row[0] if row else 0

def cleanup_orphan_screenshots() -> int:
    """Scans static/screenshots directory and removes any screenshot files not referenced in leads or platform_listings."""
    screenshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "screenshots")
    if not os.path.exists(screenshots_dir):
        return 0

    with get_connection() as conn:
        leads_screens = {os.path.basename(r[0]) for r in conn.execute("SELECT screenshot FROM leads WHERE screenshot IS NOT NULL AND screenshot != '' AND screenshot != 'N/A'").fetchall() if r[0]}
        plat_screens = {os.path.basename(r[0]) for r in conn.execute("SELECT screenshot FROM platform_listings WHERE screenshot IS NOT NULL AND screenshot != '' AND screenshot != 'N/A'").fetchall() if r[0]}
        active_screens = leads_screens | plat_screens

    removed = 0
    try:
        for f in os.listdir(screenshots_dir):
            if f.endswith((".jpg", ".jpeg", ".png", ".webp")) and f not in active_screens:
                fp = os.path.join(screenshots_dir, f)
                try:
                    os.remove(fp)
                    removed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return removed

def clear_leads():
    """Clear all leads, listings, and employees from the database and reclaim disk space by purging orphaned screenshots."""
    with get_connection() as conn:
        conn.execute("DELETE FROM employees")
        conn.execute("DELETE FROM leads")
        conn.execute("DELETE FROM platform_listings")
        conn.commit()
    cleanup_orphan_screenshots()

# ==============================================================================
# Individual and Batch Mutation Operations (Leads & Platform Listings)
# ==============================================================================

ALLOWED_LEAD_UPDATE_FIELDS = {
    "name", "category", "email", "phone", "address", "hours", "price",
    "plus_code", "rating", "reviews", "website", "maps_url", "lat", "lon",
    "instagram", "facebook", "linkedin", "twitter", "screenshot",
    "bot_protection", "cookie_status", "employee_count", "platform_name",
    "platform_url", "platform_rating", "platform_reviews", "booking_url",
    "platform_price", "platform_verified"
}

ALLOWED_PLATFORM_UPDATE_FIELDS = {
    "title", "clean_brand", "category", "url", "booking_url", "rating",
    "reviews_count", "price_info", "address", "latitude", "longitude",
    "verified", "screenshot", "platform", "phone"
}

def get_lead_by_id(lead_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single lead by its primary key ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None

def update_lead(lead_id: int, updates: Dict[str, Any]) -> bool:
    """Updates one or more fields for a single lead."""
    valid_updates = {k: v for k, v in updates.items() if k in ALLOWED_LEAD_UPDATE_FIELDS}
    if not valid_updates:
        return False
    
    set_clauses = [f"{k} = ?" for k in valid_updates.keys()]
    values = list(valid_updates.values()) + [lead_id]
    
    with get_connection() as conn:
        cursor = conn.execute(f"UPDATE leads SET {', '.join(set_clauses)} WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0

def delete_lead(lead_id: int) -> bool:
    """Deletes a single lead and cascades employee deletion."""
    with get_connection() as conn:
        conn.execute("DELETE FROM employees WHERE lead_id = ?", (lead_id,))
        conn.execute("UPDATE platform_listings SET lead_id = NULL, verified = 0 WHERE lead_id = ?", (lead_id,))
        cursor = conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    if deleted:
        cleanup_orphan_screenshots()
    return deleted

def delete_leads_batch(lead_ids: List[int]) -> int:
    """Deletes multiple leads in a single transaction."""
    if not lead_ids:
        return 0
    clean_ids = [int(i) for i in lead_ids if isinstance(i, (int, str)) and str(i).isdigit()]
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    with get_connection() as conn:
        conn.execute(f"DELETE FROM employees WHERE lead_id IN ({placeholders})", clean_ids)
        conn.execute(f"UPDATE platform_listings SET lead_id = NULL, verified = 0 WHERE lead_id IN ({placeholders})", clean_ids)
        cursor = conn.execute(f"DELETE FROM leads WHERE id IN ({placeholders})", clean_ids)
        conn.commit()
        deleted = cursor.rowcount
    if deleted > 0:
        cleanup_orphan_screenshots()
    return deleted

def batch_update_leads(lead_ids: List[int], updates: Dict[str, Any]) -> int:
    """Updates common fields across multiple selected leads."""
    valid_updates = {k: v for k, v in updates.items() if k in ALLOWED_LEAD_UPDATE_FIELDS}
    clean_ids = [int(i) for i in lead_ids if isinstance(i, (int, str)) and str(i).isdigit()]
    if not valid_updates or not clean_ids:
        return 0
    
    set_clauses = [f"{k} = ?" for k in valid_updates.keys()]
    placeholders = ",".join("?" for _ in clean_ids)
    values = list(valid_updates.values()) + clean_ids
    
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE leads SET {', '.join(set_clauses)} WHERE id IN ({placeholders})",
            values
        )
        conn.commit()
        return cursor.rowcount

def get_platform_listing_by_id(listing_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single platform listing by ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM platform_listings WHERE id = ?", (listing_id,)).fetchone()
        return dict(row) if row else None

def update_platform_listing(listing_id: int, updates: Dict[str, Any]) -> bool:
    """Updates one or more fields for a platform directory listing."""
    valid_updates = {k: v for k, v in updates.items() if k in ALLOWED_PLATFORM_UPDATE_FIELDS}
    if not valid_updates:
        return False
    
    set_clauses = [f"{k} = ?" for k in valid_updates.keys()]
    values = list(valid_updates.values()) + [listing_id]
    
    with get_connection() as conn:
        cursor = conn.execute(f"UPDATE platform_listings SET {', '.join(set_clauses)} WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0

def delete_platform_listing(listing_id: int) -> bool:
    """Deletes a single platform directory listing."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM platform_listings WHERE id = ?", (listing_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    if deleted:
        cleanup_orphan_screenshots()
    return deleted

def delete_platform_listings_batch(listing_ids: List[int]) -> int:
    """Deletes multiple platform directory listings in a single transaction."""
    clean_ids = [int(i) for i in listing_ids if isinstance(i, (int, str)) and str(i).isdigit()]
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    with get_connection() as conn:
        cursor = conn.execute(f"DELETE FROM platform_listings WHERE id IN ({placeholders})", clean_ids)
        conn.commit()
        return cursor.rowcount

def batch_update_platform_listings(listing_ids: List[int], updates: Dict[str, Any]) -> int:
    """Updates common fields across multiple platform listings."""
    valid_updates = {k: v for k, v in updates.items() if k in ALLOWED_PLATFORM_UPDATE_FIELDS}
    clean_ids = [int(i) for i in listing_ids if isinstance(i, (int, str)) and str(i).isdigit()]
    if not valid_updates or not clean_ids:
        return 0
    
    set_clauses = [f"{k} = ?" for k in valid_updates.keys()]
    placeholders = ",".join("?" for _ in clean_ids)
    values = list(valid_updates.values()) + clean_ids
    
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE platform_listings SET {', '.join(set_clauses)} WHERE id IN ({placeholders})",
            values
        )
        conn.commit()
        return cursor.rowcount

# ==============================================================================
# Employee Hierarchy & LinkedIn Intelligence Functions
# ==============================================================================

def classify_seniority(title: str) -> str:
    """Classifies a job title into seniority tiers: executive, management, or staff."""
    t = (title or "").lower().strip()
    exec_keywords = [
        "ceo", "founder", "co-founder", "chief", "cto", "cfo", "cmo", "coo", "cio", "cro",
        "president", "managing director", "partner", "owner", "principal", "director", "board", "vp", "vice president"
    ]
    mgmt_keywords = [
        "head of", "head", "manager", "lead", "supervisor", "team lead", "general manager",
        "operations manager", "store manager", "regional", "coordinator"
    ]
    for kw in exec_keywords:
        if kw in t or t.startswith(kw):
            return "executive"
    for kw in mgmt_keywords:
        if kw in t or t.startswith(kw):
            return "management"
    return "staff"

def save_employees_batch(company_name: str, employees: List[Dict[str, Any]], lead_id: int = None, company_linkedin_url: str = "") -> int:
    """Save a batch of employees, updating lead count and LinkedIn URL in leads table."""
    if not company_name:
        return 0

    saved_count = 0
    with get_connection() as conn:
        if not isinstance(lead_id, int):
            lead_id = None
        if not lead_id:
            row = conn.execute("SELECT id FROM leads WHERE lower(trim(name)) = lower(trim(?)) ORDER BY id ASC LIMIT 1", (company_name,)).fetchone()
            if not row:
                row = conn.execute("SELECT id FROM leads WHERE lower(name) LIKE ? ORDER BY id ASC LIMIT 1", (f"%{company_name.lower()}%",)).fetchone()
            if row:
                lead_id = row[0]

        if employees:
            for emp in employees:
                fname = str(emp.get("full_name", "")).strip()
                title = str(emp.get("title", "")).strip()
                if not fname:
                    continue
                seniority = emp.get("seniority_level") or classify_seniority(title)
                purl = str(emp.get("linkedin_profile_url", "")).strip()
                em = str(emp.get("email", "")).strip()
                loc = str(emp.get("location", "")).strip()
                av = str(emp.get("avatar_url", "")).strip()

                try:
                    conn.execute("""
                        INSERT INTO employees (lead_id, company_name, full_name, title, seniority_level, linkedin_profile_url, email, location, avatar_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(company_name, full_name, title) DO UPDATE SET
                            seniority_level = excluded.seniority_level,
                            linkedin_profile_url = CASE WHEN excluded.linkedin_profile_url != '' THEN excluded.linkedin_profile_url ELSE employees.linkedin_profile_url END,
                            email = CASE WHEN excluded.email != '' THEN excluded.email ELSE employees.email END,
                            location = CASE WHEN excluded.location != '' THEN excluded.location ELSE employees.location END,
                            avatar_url = CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE employees.avatar_url END
                    """, (lead_id, company_name, fname, title, seniority, purl, em, loc, av))
                    saved_count += 1
                except Exception:
                    pass

        total_emp = conn.execute("SELECT COUNT(*) FROM employees WHERE company_name = ?", (company_name,)).fetchone()[0]
        conn.execute("""
            UPDATE leads SET
                employee_count = ?,
                org_scraped = 1,
                linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END,
                linkedin_status = CASE WHEN ? != '' THEN 'verified' ELSE 'no_profile' END
            WHERE name = ? OR (id = ? AND ? IS NOT NULL)
        """, (str(total_emp), company_linkedin_url, company_linkedin_url, company_linkedin_url, company_name, lead_id, lead_id))

        conn.commit()
    return saved_count

def get_company_hierarchy(company_name: str) -> Dict[str, Any]:
    """
    Returns the organization tree for a company grouped by seniority:
    - Executive (Founders, C-suite, Directors)
    - Management (Heads, Managers, Leads)
    - Staff (Specialists, Engineers, Operations)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, title, seniority_level, linkedin_profile_url, email, location, avatar_url
            FROM employees
            WHERE company_name = ?
            ORDER BY
                CASE seniority_level
                    WHEN 'executive' THEN 1
                    WHEN 'management' THEN 2
                    ELSE 3
                END,
                full_name ASC
        """, (company_name,))
        rows = [dict(r) for r in cursor.fetchall()]

        lead_row = conn.execute("SELECT id, name, category, website, linkedin, employee_count FROM leads WHERE name = ? LIMIT 1", (company_name,)).fetchone()
        company_info = dict(lead_row) if lead_row else {"name": company_name}

        hierarchy = {
            "company": company_name,
            "info": company_info,
            "total_employees": len(rows),
            "tiers": {
                "executive": [r for r in rows if r["seniority_level"] == "executive"],
                "management": [r for r in rows if r["seniority_level"] == "management"],
                "staff": [r for r in rows if r["seniority_level"] == "staff"],
            },
            "all_employees": rows
        }
        return hierarchy

def save_platform_listing(listing: Dict[str, Any]) -> int:
    """
    Saves a platform directory listing (Fresha, Airbnb, Yelp, TripAdvisor, etc.) into platform_listings.
    Cross-references and merges normalized fields (booking_url, platform_rating, reviews, price) into matching lead in leads.db.
    """
    platform = str(listing.get("platform", "Platform")).strip()
    title = str(listing.get("title", "") or listing.get("company_name", "") or listing.get("name", "")).strip()
    if not title:
        return 0

    clean_brand = str(listing.get("clean_brand", "") or title).strip()
    category = str(listing.get("category", "")).strip()
    url = str(listing.get("url", "") or listing.get("listing_url", "")).strip()
    booking_url = str(listing.get("booking_url", "") or url).strip()
    try:
        rating = float(listing.get("rating", 0.0) or 0.0)
    except Exception:
        rating = 0.0
    try:
        reviews_count = int(listing.get("reviews_count", 0) or listing.get("review_count", 0) or 0)
    except Exception:
        reviews_count = 0
    price_info = str(listing.get("price_info", "") or listing.get("price_range", "")).strip()
    address = str(listing.get("address", "")).strip()
    lat = listing.get("latitude")
    lon = listing.get("longitude")
    verified = 1 if listing.get("verified") else 0
    screenshot = str(listing.get("screenshot", "")).strip()
    services_json = json.dumps(listing.get("services", [])) if isinstance(listing.get("services"), list) else str(listing.get("services", ""))
    raw_metadata = json.dumps(listing.get("metadata", {})) if isinstance(listing.get("metadata"), dict) else "{}"
    lead_id = listing.get("lead_id")

    with get_connection() as conn:
        # If lead_id not explicitly given, attempt to find matching lead
        if not lead_id:
            lead_id = find_matching_lead_id(conn, name=title, address=address)
            if not lead_id and clean_brand:
                lead_id = find_matching_lead_id(conn, name=clean_brand, address=address)

        # Upsert into platform_listings
        cursor = conn.execute("""
            INSERT INTO platform_listings (
                lead_id, platform, listing_id, title, clean_brand, category, url, booking_url,
                rating, reviews_count, price_info, address, latitude, longitude, verified,
                screenshot, services_json, raw_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, url) DO UPDATE SET
                lead_id = COALESCE(excluded.lead_id, platform_listings.lead_id),
                title = excluded.title,
                clean_brand = excluded.clean_brand,
                rating = excluded.rating,
                reviews_count = excluded.reviews_count,
                price_info = excluded.price_info,
                booking_url = excluded.booking_url,
                verified = excluded.verified,
                screenshot = CASE WHEN excluded.screenshot != '' THEN excluded.screenshot ELSE platform_listings.screenshot END,
                services_json = excluded.services_json
            RETURNING id;
        """, (
            lead_id, platform, str(listing.get("listing_id", "")), title, clean_brand, category, url, booking_url,
            rating, reviews_count, price_info, address, lat, lon, verified,
            screenshot, services_json, raw_metadata
        ))
        row = cursor.fetchone()
        inserted_id = row[0] if row else 0

        # If linked to a lead, update leads table with normalized platform metadata
        if lead_id:
            conn.execute("""
                UPDATE leads SET
                    platform_name = ?,
                    platform_url = ?,
                    platform_rating = ?,
                    platform_reviews = ?,
                    booking_url = ?,
                    platform_price = CASE WHEN ? != '' THEN ? ELSE platform_price END,
                    platform_verified = ?
                WHERE id = ?;
            """, (
                platform, url, str(rating) if rating > 0 else "N/A", str(reviews_count), booking_url,
                price_info, price_info, verified, lead_id
            ))

        conn.commit()
        return inserted_id

def get_platform_listings(platform: Optional[str] = None, lead_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Retrieves saved platform directory listings."""
    with get_connection() as conn:
        query = "SELECT * FROM platform_listings WHERE 1=1"
        params = []
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if lead_id:
            query += " AND lead_id = ?"
            params.append(lead_id)
        query += " ORDER BY id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]



def get_platforms_config() -> List[Dict[str, Any]]:
    """Retrieves all configured directory platform templates."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM platforms_config ORDER BY is_active DESC, id ASC").fetchall()
        return [dict(r) for r in rows]

def save_platform_config(name: str, url_template: str, category: str = "General", is_active: int = 1) -> int:
    """Creates or updates a platform directory template in the database."""
    clean_n = name.strip()
    clean_u = url_template.strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO platforms_config (name, url_template, category, is_active)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                url_template = excluded.url_template,
                category = excluded.category,
                is_active = excluded.is_active
            RETURNING id;
        """, (clean_n, clean_u, category.strip(), is_active))
        row = cursor.fetchone()
        conn.commit()
        return row[0] if row else 0

def delete_platform_config(platform_id: int) -> bool:
    """Deletes a directory platform template by ID."""
    with get_connection() as conn:
        conn.execute("DELETE FROM platforms_config WHERE id = ?", (platform_id,))
        conn.commit()
        return True

def get_tables_split_data(limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
    """
    Returns segmented datasets and queue-level progress for all agents and platforms:
    1. master_leads: Leads with normalized data from both Google Maps and verified Platform Directory.
    2. unmatched_maps: All Google Maps discovered places (raw base) with diagnostic status tags.
    3. unmatched_platform: All Platform directory listings with diagnostic status tags.
    4. website_leads: Dedicated Website Inspector view with status tags.
    5. linkedin_leads: Dedicated LinkedIn Org Harvester view with status tags.
    6. queue_progress: Live counts and completion percentages benchmarked to Google Maps total and per-platform metrics.
    """
    all_leads = get_all_leads()
    all_listings = get_platform_listings()

    master_leads = []
    unmatched_maps = []
    website_leads = []
    linkedin_leads = []

    maps_with_web = 0
    maps_no_web = 0
    maps_with_phone = 0
    maps_with_rating = 0

    web_finished_count = 0
    web_no_site_count = 0
    web_emails_count = 0
    web_socials_count = 0

    li_finished_count = 0
    li_found_count = 0
    li_employees_count = 0
    li_not_found_count = 0

    for l in all_leads:
        # 1. Master leads check
        if l.get("platform_verified") == 1 or (l.get("platform_name") and l.get("platform_name") != "N/A"):
            master_leads.append(l)

        # 2. Format Google Maps Lead
        m_row = dict(l)
        has_w = bool(m_row.get("website") and str(m_row.get("website")).strip() != "N/A")
        has_p = bool(m_row.get("phone") and str(m_row.get("phone")).strip() != "N/A")
        has_r = bool(m_row.get("rating") and str(m_row.get("rating")).strip() != "N/A")

        if has_w: maps_with_web += 1
        else: maps_no_web += 1
        if has_p: maps_with_phone += 1
        if has_r: maps_with_rating += 1

        if has_w and has_p:
            m_tag = "Full Contact (Web & Phone)"
        elif has_w:
            m_tag = "Has Website"
        elif has_p:
            m_tag = "Phone Only"
        else:
            m_tag = "Location Only"

        m_row["status_tag"] = m_tag
        m_row["has_website"] = has_w
        m_row["has_phone"] = has_p
        unmatched_maps.append(m_row)

        # 3. Format Website Inspector Lead
        w_url = str(l.get("website", "") or "").strip()
        email_str = str(l.get("email", "") or "").strip()
        has_e = bool(email_str and email_str != "N/A")
        ig = str(l.get("instagram", "") or "").strip()
        fb = str(l.get("facebook", "") or "").strip()
        has_s = bool(ig or fb)
        bot = str(l.get("bot_protection", "") or "").strip()
        w_status = str(l.get("website_status", "") or "pending").strip()

        if not has_w:
            w_tag = "No Website on Map"
            web_no_site_count += 1
            web_finished_count += 1
        elif has_e:
            w_tag = "Emails Extracted"
            web_emails_count += 1
            web_finished_count += 1
        elif has_s:
            w_tag = "Socials Found"
            web_socials_count += 1
            web_finished_count += 1
        elif "Denied" in bot or "Captcha" in bot:
            w_tag = "Bot Shielded"
            web_finished_count += 1
        elif w_status in ["found", "scraped", "clean"]:
            w_tag = "Website Found"
            web_finished_count += 1
        elif w_status == "failed":
            w_tag = "Website Unreachable"
            web_finished_count += 1
        else:
            w_tag = "Pending in Queue"

        w_row = dict(l)
        w_row["status_tag"] = w_tag
        w_row["has_website"] = has_w
        w_row["has_email"] = has_e
        w_row["has_socials"] = has_s
        website_leads.append(w_row)

        # 4. Format LinkedIn Harvester Lead
        li_url = str(l.get("linkedin", "") or l.get("linkedin_url", "") or "").strip()
        emp_cnt = str(l.get("employee_count", "") or "").strip()
        org_scraped = int(l.get("org_scraped", 0) or 0)
        li_status = str(l.get("linkedin_status", "") or "pending").strip()

        if org_scraped > 0 or (emp_cnt and emp_cnt != "0"):
            li_tag = "Employees Crawled"
            li_employees_count += 1
            li_found_count += 1
            li_finished_count += 1
        elif li_url and li_url != "N/A":
            li_tag = "LinkedIn Found"
            li_found_count += 1
            li_finished_count += 1
        elif li_status == "not_found":
            li_tag = "Not Found on LinkedIn"
            li_not_found_count += 1
            li_finished_count += 1
        elif li_status == "failed":
            li_tag = "LinkedIn Blocked / Timeout"
            li_finished_count += 1
        elif li_status in ["found", "scraped"]:
            li_tag = "LinkedIn Found"
            li_found_count += 1
            li_finished_count += 1
        else:
            li_tag = "Pending in Queue"

        li_row = dict(l)
        li_row["status_tag"] = li_tag
        li_row["has_linkedin"] = bool(li_url and li_url != "N/A")
        li_row["has_employees"] = bool(org_scraped > 0 or (emp_cnt and emp_cnt != "0"))
        linkedin_leads.append(li_row)

    # Format Platform Directory Listings with rich diagnostic status tags
    unmatched_platform = []
    plat_booking_count = 0
    plat_rated_count = 0
    plat_matched_count = 0

    for item in all_listings:
        p_row = dict(item)
        is_ver = int(p_row.get("verified", 0) or 0)
        has_lead = bool(p_row.get("lead_id"))
        b_url = str(p_row.get("booking_url", "") or "").strip()
        has_book = bool(b_url and len(b_url) > 10)
        try:
            r_val = float(p_row.get("rating", 0.0) or 0.0)
        except Exception:
            r_val = 0.0
        has_rate = (r_val > 0.0)

        if is_ver == 1 or has_lead:
            tag = "Master Matched"
            plat_matched_count += 1
        elif has_book:
            tag = "Direct Booking"
            plat_booking_count += 1
        elif r_val >= 4.0:
            tag = "Top Rated"
            plat_rated_count += 1
        elif has_rate:
            tag = "Verified Listing"
            plat_rated_count += 1
        else:
            tag = "Directory Listing"

        p_row["status_tag"] = tag
        p_row["has_booking"] = has_book
        p_row["has_rating"] = has_rate
        p_row["is_matched"] = bool(is_ver == 1 or has_lead)
        unmatched_platform.append(p_row)

    total_maps = len(all_leads)
    web_pending = max(0, total_maps - web_finished_count)
    web_pct = min(100, round((web_finished_count / max(1, total_maps)) * 100))

    li_pending = max(0, total_maps - li_finished_count)
    li_pct = min(100, round((li_finished_count / max(1, total_maps)) * 100))

    # Platform listings counts and tag metrics grouped by platform from database
    plat_item_metrics = {}
    for p_item in unmatched_platform:
        p_name = p_item.get("platform", "Platform")
        if p_name not in plat_item_metrics:
            plat_item_metrics[p_name] = {"scraped": 0, "booking_links": 0, "rated_count": 0, "matched_count": 0}
        plat_item_metrics[p_name]["scraped"] += 1
        if p_item.get("has_booking"):
            plat_item_metrics[p_name]["booking_links"] += 1
        if p_item.get("has_rating"):
            plat_item_metrics[p_name]["rated_count"] += 1
        if p_item.get("is_matched"):
            plat_item_metrics[p_name]["matched_count"] += 1

    total_plat_scraped = len(unmatched_platform)
    plat_breakdown = {}
    default_platforms = ["Fresha", "Airbnb", "Yelp", "TripAdvisor"]
    for p in default_platforms:
        m = plat_item_metrics.get(p, {"scraped": 0, "booking_links": 0, "rated_count": 0, "matched_count": 0})
        cnt = m["scraped"]
        target = max(cnt, 20 if cnt > 0 else 0)
        pct = min(100, round((cnt / max(1, target)) * 100)) if target > 0 else 0
        plat_breakdown[p] = {
            "name": p,
            "scraped": cnt,
            "skipped": 0,
            "total": target,
            "percent": pct,
            "booking_links": m["booking_links"],
            "rated_count": m["rated_count"],
            "matched_count": m["matched_count"]
        }
    for p, m in plat_item_metrics.items():
        if p not in plat_breakdown:
            cnt = m["scraped"]
            target = max(cnt, 20 if cnt > 0 else 0)
            plat_breakdown[p] = {
                "name": p,
                "scraped": cnt,
                "skipped": 0,
                "total": target,
                "percent": 100 if cnt > 0 else 0,
                "booking_links": m["booking_links"],
                "rated_count": m["rated_count"],
                "matched_count": m["matched_count"]
            }

    total_plat_target = sum(x["total"] for x in plat_breakdown.values())
    overall_plat_pct = min(100, round((total_plat_scraped / max(1, total_plat_target)) * 100)) if total_plat_target > 0 else (100 if total_plat_scraped > 0 else 0)

    counts_dict = {
        "master": len(master_leads),
        "maps": len(unmatched_maps),
        "platform": len(unmatched_platform),
        "website": len(website_leads),
        "linkedin": len(linkedin_leads),
        "total_leads": total_maps,
        "total_listings": len(all_listings)
    }

    if limit is not None and limit > 0:
        master_leads = master_leads[offset:offset + limit]
        unmatched_maps = unmatched_maps[offset:offset + limit]
        unmatched_platform = unmatched_platform[offset:offset + limit]
        website_leads = website_leads[offset:offset + limit]
        linkedin_leads = linkedin_leads[offset:offset + limit]

    return {
        "master_leads": master_leads,
        "unmatched_maps": unmatched_maps,
        "unmatched_platform": unmatched_platform,
        "website_leads": website_leads,
        "linkedin_leads": linkedin_leads,
        "counts": counts_dict,
        "queue_progress": {
            "total_maps": total_maps,
            "maps": {
                "total": total_maps,
                "with_website": maps_with_web,
                "no_website": maps_no_web,
                "with_phone": maps_with_phone,
                "with_rating": maps_with_rating
            },
            "website": {
                "total": total_maps,
                "inspected": web_finished_count,
                "pending": web_pending,
                "no_website": web_no_site_count,
                "emails_found": web_emails_count,
                "socials_found": web_socials_count,
                "percent": web_pct
            },
            "linkedin": {
                "total": total_maps,
                "inspected": li_finished_count,
                "pending": li_pending,
                "found": li_found_count,
                "not_found": li_not_found_count,
                "employees_found": li_employees_count,
                "percent": li_pct
            },
            "platform": {
                "total": total_plat_target or total_plat_scraped,
                "scraped": total_plat_scraped,
                "skipped": 0,
                "percent": overall_plat_pct,
                "booking_links": plat_booking_count,
                "rated_count": plat_rated_count,
                "matched_count": plat_matched_count,
                "pending": max(0, total_plat_target - total_plat_scraped)
            },
            "platforms_breakdown": plat_breakdown
        }
    }


def extract_core_brand_name(name: str, city: str = "") -> str:
    """Extracts base brand name by stripping legal, retail, and location clutter."""
    if not name:
        return ""
    base = re.split(r'\s*[-–—|@]\s*|[(\[]', name)[0].strip()
    if not base or len(base) < 2:
        base = name.strip()
    base = re.sub(r'[\.,\-_;:\'\"]+$', '', base).strip()
    legal_pat = r'\s+\b(?:pvt\.?\s*ltd\.?|private\s+limited|ltd\.?|llc|inc\.?|corp\.?|co\.?|corporation)\b\.?'
    base = re.sub(legal_pat, '', base, flags=re.I).strip()
    mall_pat = r'\s+\b[A-Za-z0-9]+\s+(?:mall|plaza|centre|center|galleria|arcade)\b'
    base = re.sub(mall_pat, '', base, flags=re.I).strip()
    retail_pat = r'\s+\b(?:factory\s+store|factory\s+outlet|flagship\s+store|retail\s+store|salon|spa|wellness|beauty)\b'
    base = re.sub(retail_pat, '', base, flags=re.I).strip()
    if city and len(city) >= 3:
        city_esc = re.escape(city.strip())
        base = re.sub(rf'\s+\b{city_esc}\b.*$', '', base, flags=re.I).strip()
    end_suffix_pat = r'\s+\b(?:outlet|showroom|branch|mall|bazaar|supermarket|hypermarket)\b$'
    base = re.sub(end_suffix_pat, '', base, flags=re.I).strip()
    return base if len(base) >= 2 else name

def jaccard_similarity(s1: str, s2: str) -> float:
    t1 = set(re.findall(r'[a-zA-Z0-9]+', s1.lower()))
    t2 = set(re.findall(r'[a-zA-Z0-9]+', s2.lower()))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)

def normalize_all_platform_listings(city_context: str = "") -> Dict[str, Any]:
    """
    Cross-platform Normalization Engine:
    Compares all Google Maps leads in leads.db against all directory platform listings (Fresha, Airbnb, Yelp, TripAdvisor).
    Fuzzy matches entities by:
      1. Exact name match
      2. Clean brand token match
      3. Token Jaccard similarity >= 0.55
      4. Phone digit match
      5. Domain match
    Enriches matching leads with verified platform metadata, links lead_id,
    and updates the 3-table split partition.
    """
    newly_matched = 0
    GENERIC_STOP_WORDS = {
        'flat', 'apartment', 'villa', 'hotel', 'salon', 'spa', 'house', 'home', 
        'shop', 'room', 'rooms', 'suite', 'suites', 'stay', 'stays', 'resort',
        'resorts', 'clinic', 'store', 'centre', 'center', 'bazaar', 'retail'
    }

    with get_connection() as conn:
        raw_leads = conn.execute("SELECT id, name, address, website, phone, platform_verified, lat, lon FROM leads").fetchall()
        listings = [dict(r) for r in conn.execute("SELECT * FROM platform_listings WHERE lead_id IS NULL OR verified = 0").fetchall()]

        # Precompute lead tokens and hash maps once to eliminate redundant regexes in nested loop
        precomputed_leads = []
        exact_lead_map = {}
        brand_lead_map = {}
        phone_lead_map = {}

        for r in raw_leads:
            lead = dict(r)
            lead_name = (lead["name"] or "").strip()
            name_low = lead_name.lower()
            lead_brand = extract_core_brand_name(lead_name, city=city_context).lower()
            lead_phone = re.sub(r'\D', '', lead.get("phone", "") or "")

            info = {
                "lead": lead,
                "name": lead_name,
                "name_lower": name_low,
                "brand": lead_brand,
                "address_lower": (lead["address"] or "").lower(),
                "phone_digits": lead_phone
            }
            precomputed_leads.append(info)

            if name_low and name_low not in exact_lead_map:
                exact_lead_map[name_low] = lead
            if lead_brand and lead_brand not in GENERIC_STOP_WORDS and lead_brand not in brand_lead_map:
                brand_lead_map[lead_brand] = lead
            if len(lead_phone) >= 8 and lead_phone not in phone_lead_map:
                phone_lead_map[lead_phone] = lead

        for lst in listings:
            l_id = lst["id"]
            l_title = (lst["title"] or "").strip()
            l_title_low = l_title.lower()
            l_brand = extract_core_brand_name(l_title, city=city_context).lower()
            l_addr = (lst["address"] or "").lower()
            l_phone = re.sub(r'\D', '', lst.get("address", "") or "")
            l_plat = lst.get("platform", "Platform")
            l_url = lst.get("url", "")
            l_book = lst.get("booking_url", "") or l_url
            l_rating = lst.get("rating", 0.0)
            l_reviews = lst.get("reviews_count", 0)
            l_price = lst.get("price_info", "")

            best_lead = None

            # 1. Fast O(1) Exact name match
            if l_title_low in exact_lead_map:
                best_lead = exact_lead_map[l_title_low]

            # 2. Fast O(1) Clean Brand match (if not generic stop word)
            elif l_brand and l_brand not in GENERIC_STOP_WORDS and l_brand in brand_lead_map:
                best_lead = brand_lead_map[l_brand]

            # 3. Fast O(1) Phone digit match
            elif len(l_phone) >= 8 and l_phone in phone_lead_map:
                best_lead = phone_lead_map[l_phone]

            # 4. Fallback search across precomputed items (substring brand or Jaccard similarity)
            if not best_lead:
                for item in precomputed_leads:
                    cand_lead = item["lead"]
                    cand_brand = item["brand"]
                    cand_phone = item["phone_digits"]
                    cand_name = item["name"]

                    if l_brand and cand_brand:
                        if l_brand not in GENERIC_STOP_WORDS and cand_brand not in GENERIC_STOP_WORDS:
                            if (len(l_brand) >= 5 and l_brand in cand_brand) or (len(cand_brand) >= 5 and cand_brand in l_brand):
                                best_lead = cand_lead
                                break

                    if len(cand_phone) >= 8 and len(l_phone) >= 8 and (cand_phone in l_phone or l_phone in cand_phone):
                        best_lead = cand_lead
                        break

                    sim = jaccard_similarity(cand_name, l_title)
                    if sim >= 0.55:
                        best_lead = cand_lead
                        break

            if best_lead:
                lead_id = best_lead["id"]
                conn.execute("UPDATE platform_listings SET lead_id = ?, verified = 1 WHERE id = ?", (lead_id, l_id))
                conn.execute("""
                    UPDATE leads SET
                        platform_name = ?,
                        platform_url = ?,
                        platform_rating = ?,
                        platform_reviews = ?,
                        booking_url = ?,
                        platform_price = CASE WHEN ? != '' THEN ? ELSE platform_price END,
                        phone = CASE WHEN (phone IS NULL OR phone = 'N/A' OR phone = '') AND ? != '' THEN ? ELSE phone END,
                        screenshot = CASE WHEN (screenshot IS NULL OR screenshot = '' OR screenshot = 'N/A') AND ? != '' THEN ? ELSE screenshot END,
                        platform_verified = 1
                    WHERE id = ?;
                """, (
                    l_plat, l_url, str(l_rating) if l_rating > 0 else "N/A",
                    str(l_reviews), l_book, l_price, l_price,
                    lst.get("phone", "") or (lst.get("address") if lst.get("address", "").startswith("+") else ""),
                    lst.get("phone", "") or (lst.get("address") if lst.get("address", "").startswith("+") else ""),
                    lst.get("screenshot", ""), lst.get("screenshot", ""),
                    lead_id
                ))
                newly_matched += 1

        conn.commit()

    return {
        "newly_matched": newly_matched,
        "counts": get_tables_split_data()["counts"]
    }

