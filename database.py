import os
import re
import sqlite3
import urllib.parse
from typing import Dict, Any, List, Optional

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
    """Returns a SQLite connection configured with WAL mode and generous busy timeout to prevent locking."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
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

        # Create indexes for fast lookup, collision matching, and hierarchy queries
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_name_addr ON leads(name, address);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_website ON leads(website);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_emp_company ON employees(company_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_emp_seniority ON employees(seniority_level);")
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

def clean_domain(url: str) -> str:
    """Extract clean domain name without protocol, www, or query parameters."""
    if not url or url.upper() in ("N/A", "NONE"):
        return ""
    try:
        clean = url.strip()
        if not clean.startswith(("http://", "https://")):
            clean = "http://" + clean
        parsed = urllib.parse.urlparse(clean)
        dom = parsed.netloc.lower()
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
                return True
            else:
                # Insert brand-new lead
                conn.execute("""
                    INSERT INTO leads (name, category, email, phone, address, hours, price, plus_code, rating, reviews, website, maps_url, lat, lon, instagram, facebook, linkedin, twitter, screenshot, bot_protection, cookie_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, category, email, phone, address, hours, price, plus_code, rating, reviews, website, maps_url, lat, lon, instagram, facebook, linkedin, twitter, screenshot, bot_protection, cookie_status))
                conn.commit()
                return True
        except Exception:
            return False

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
                org_scraped INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                    employee_count, org_scraped, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                l["new_id"], l["name"], l.get("category", "Business"), l["email"], l.get("phone", "N/A"),
                l.get("address", "N/A"), l.get("hours", "N/A"), l.get("price", "N/A"), l.get("plus_code", "N/A"),
                l.get("rating", "N/A"), l.get("reviews", "0"), l.get("website", "N/A"), l.get("maps_url", ""),
                l.get("lat"), l.get("lon"), l.get("instagram", ""), l.get("facebook", ""),
                l.get("linkedin", ""), l.get("twitter", ""), l.get("screenshot", ""),
                l["bot_protection"], l.get("cookie_status", "None"),
                l.get("employee_count", "0"), l.get("org_scraped", 0), l.get("created_at")
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

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_name_addr ON leads(name, address);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_website ON leads(website);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_company ON employees(company_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_seniority ON employees(seniority_level);")

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
    cookie_status: str = ""
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
                        cookie_status = CASE WHEN ? != '' THEN ? ELSE cookie_status END
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
                        cookie_status = CASE WHEN ? != '' THEN ? ELSE cookie_status END
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
                        cookie_status = CASE WHEN ? != '' THEN ? ELSE cookie_status END
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
                   created_at
            FROM leads ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_lead_count() -> int:
    """Return total count of leads in database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM leads")
        row = cursor.fetchone()
        return row[0] if row else 0

def clear_leads():
    """Clear all leads and employees from the database."""
    with get_connection() as conn:
        conn.execute("DELETE FROM employees")
        conn.execute("DELETE FROM leads")
        conn.commit()

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
    if not company_name or not employees:
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
                linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END
            WHERE name = ? OR (id = ? AND ? IS NOT NULL)
        """, (str(total_emp), company_linkedin_url, company_linkedin_url, company_name, lead_id, lead_id))

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
