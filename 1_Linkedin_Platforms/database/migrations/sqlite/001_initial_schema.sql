-- Initial SQLite Schema for DataScrapper
-- Tables for Leads, Employees (LinkedIn workforce), Platform Listings, Platform Config, and Census Cache

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
    youtube TEXT,
    tiktok TEXT,
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
    order_url TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    whatsapp TEXT DEFAULT '',
    UNIQUE(name, address)
);

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
);

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
    website_status TEXT DEFAULT 'pending',
    email TEXT DEFAULT '',
    emails_json TEXT DEFAULT '[]',
    phone TEXT DEFAULT '',
    website TEXT DEFAULT '',
    maps_url TEXT DEFAULT '',
    instagram TEXT DEFAULT '',
    facebook TEXT DEFAULT '',
    linkedin TEXT DEFAULT '',
    twitter TEXT DEFAULT '',
    youtube TEXT DEFAULT '',
    tiktok TEXT DEFAULT '',
    whatsapp TEXT DEFAULT '',
    bot_protection TEXT DEFAULT 'Clean',
    cookie_status TEXT DEFAULT 'None',
    notes TEXT DEFAULT '',
    services_json TEXT,
    raw_metadata_json TEXT,
    screenshot TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE SET NULL,
    UNIQUE(platform, url)
);

CREATE TABLE IF NOT EXISTS platforms_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    url_template TEXT NOT NULL,
    category TEXT DEFAULT 'General',
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS census_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    query TEXT NOT NULL,
    location TEXT NOT NULL,
    total INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform, query, location)
);

CREATE INDEX IF NOT EXISTS idx_leads_name_addr ON leads(name, address);
CREATE INDEX IF NOT EXISTS idx_emp_company ON employees(company_name);
CREATE INDEX IF NOT EXISTS idx_emp_seniority ON employees(seniority_level);
CREATE INDEX IF NOT EXISTS idx_platform_listings_brand ON platform_listings(clean_brand);
CREATE INDEX IF NOT EXISTS idx_platform_listings_lead ON platform_listings(lead_id);
CREATE INDEX IF NOT EXISTS idx_platform_listings_plat ON platform_listings(platform);
