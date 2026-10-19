"""
Platform Directory Repository.
Manages multi-source directory listings (Fresha, Airbnb, Yelp, TripAdvisor, Treatwell, Justdial),
census caches, and platform configuration.
"""
import json
import logging
from typing import Dict, Any, List, Optional
import sqlite3

from packages.database.src.adapters.sqlite.connection import get_connection

logger = logging.getLogger("platform_repository")

def get_platform_listings(
    platform: Optional[str] = None,
    lead_id: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieves saved platform directory listings with optional filtering and pagination."""
    with get_connection(db_path) as conn:
        query = "SELECT * FROM platform_listings WHERE 1=1"
        params: List[Any] = []
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if lead_id:
            query += " AND lead_id = ?"
            params.append(lead_id)
        query += " ORDER BY id DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

def get_platform_listing_by_id(listing_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches a single platform listing by ID."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM platform_listings WHERE id = ?", (listing_id,)).fetchone()
        return dict(row) if row else None

def save_platform_listing(listing: Dict[str, Any], db_path: Optional[str] = None) -> int:
    """
    Saves or updates a platform directory listing into platform_listings.
    Enforces UNIQUE(platform, url) constraint.
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
    
    services_json = json.dumps(listing.get("services", [])) if isinstance(listing.get("services"), list) else str(listing.get("services", "[]"))
    raw_metadata = json.dumps(listing.get("metadata", {})) if isinstance(listing.get("metadata"), dict) else "{}"
    lead_id = listing.get("lead_id")
    
    website = str(listing.get("website", "")).strip()
    phone = str(listing.get("phone", "")).strip()
    email = str(listing.get("email", "")).strip()
    emails_raw = listing.get("emails", [])
    if isinstance(emails_raw, list) and emails_raw:
        emails_json = json.dumps(emails_raw)
        if not email and emails_raw:
            email = str(emails_raw[0]).strip()
    else:
        emails_json = listing.get("emails_json", "[]")

    maps_url = str(listing.get("maps_url", "")).strip()
    instagram = str(listing.get("instagram", "")).strip()
    facebook = str(listing.get("facebook", "")).strip()
    linkedin = str(listing.get("linkedin", "")).strip()
    twitter = str(listing.get("twitter", "")).strip()
    youtube = str(listing.get("youtube", "")).strip()
    tiktok = str(listing.get("tiktok", "")).strip()
    whatsapp = str(listing.get("whatsapp", "")).strip()
    bot_protection = str(listing.get("bot_protection", "")).strip() or "Clean"
    notes = str(listing.get("notes", "")).strip()
    website_status = str(listing.get("website_status", "")).strip() or "pending"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO platform_listings (
                lead_id, platform, title, clean_brand, category, url, booking_url,
                rating, reviews_count, price_info, address, latitude, longitude,
                verified, website_status, email, emails_json, phone, website,
                maps_url, instagram, facebook, linkedin, twitter, youtube, tiktok,
                whatsapp, bot_protection, notes, services_json, raw_metadata_json, screenshot
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(platform, url) DO UPDATE SET
                title = excluded.title,
                clean_brand = excluded.clean_brand,
                category = excluded.category,
                booking_url = excluded.booking_url,
                rating = excluded.rating,
                reviews_count = excluded.reviews_count,
                price_info = excluded.price_info,
                address = excluded.address,
                phone = CASE WHEN excluded.phone != '' THEN excluded.phone ELSE platform_listings.phone END,
                email = CASE WHEN excluded.email != '' THEN excluded.email ELSE platform_listings.email END,
                website = CASE WHEN excluded.website != '' THEN excluded.website ELSE platform_listings.website END,
                screenshot = CASE WHEN excluded.screenshot != '' THEN excluded.screenshot ELSE platform_listings.screenshot END,
                verified = excluded.verified,
                notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE platform_listings.notes END
            RETURNING id;
        """, (
            lead_id, platform, title, clean_brand, category, url, booking_url,
            rating, reviews_count, price_info, address, lat, lon,
            verified, website_status, email, emails_json, phone, website,
            maps_url, instagram, facebook, linkedin, twitter, youtube, tiktok,
            whatsapp, bot_protection, notes, services_json, raw_metadata, screenshot
        ))
        row = cursor.fetchone()
        conn.commit()
        return row[0] if row else 0

def update_platform_listing(listing_id: int, updates: Dict[str, Any], db_path: Optional[str] = None) -> bool:
    """Updates selected fields of a platform directory listing."""
    if not updates:
        return False
    with get_connection(db_path) as conn:
        fields = []
        vals = []
        for k, v in updates.items():
            fields.append(f"{k} = ?")
            vals.append(v)
        vals.append(listing_id)
        conn.execute(f"UPDATE platform_listings SET {', '.join(fields)} WHERE id = ?", vals)
        conn.commit()
        return True

def delete_platform_listing(listing_id: int, db_path: Optional[str] = None) -> bool:
    """Deletes a platform listing by ID."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM platform_listings WHERE id = ?", (listing_id,))
        conn.commit()
        return True

def delete_platform_listings_batch(listing_ids: List[int], db_path: Optional[str] = None) -> int:
    """Deletes multiple platform listings in one transaction."""
    if not listing_ids:
        return 0
    with get_connection(db_path) as conn:
        placeholders = ",".join("?" for _ in listing_ids)
        cursor = conn.execute(f"DELETE FROM platform_listings WHERE id IN ({placeholders})", listing_ids)
        conn.commit()
        return cursor.rowcount

def batch_update_platform_listings(listing_ids: List[int], updates: Dict[str, Any], db_path: Optional[str] = None) -> int:
    """Batch updates multiple platform listings."""
    if not listing_ids or not updates:
        return 0
    with get_connection(db_path) as conn:
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        placeholders = ",".join("?" for _ in listing_ids)
        values = list(updates.values()) + listing_ids
        cursor = conn.execute(
            f"UPDATE platform_listings SET {', '.join(set_clauses)} WHERE id IN ({placeholders})",
            values
        )
        conn.commit()
        return cursor.rowcount

def is_platform_listing_already_scraped(
    platform: str,
    title: str,
    url: str = "",
    dedup_cache: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None
) -> bool:
    """Fast deduplication check for platform directory listings."""
    clean_t = (title or "").strip().lower()
    clean_u = (url or "").split('?')[0].rstrip('/')

    if dedup_cache:
        if clean_u and clean_u in dedup_cache.get("listings_urls", set()):
            return True
        if clean_t and clean_t in dedup_cache.get("listings_titles", set()):
            return True

    with get_connection(db_path) as conn:
        if clean_u:
            row = conn.execute("SELECT id FROM platform_listings WHERE url = ?", (clean_u,)).fetchone()
            if row:
                return True
        if clean_t:
            row = conn.execute(
                "SELECT id FROM platform_listings WHERE LOWER(title) = ? AND platform = ?",
                (clean_t, platform)
            ).fetchone()
            if row:
                return True
    return False

def get_platforms_config(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all configured directory platform templates."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM platforms_config ORDER BY is_active DESC, id ASC").fetchall()
        return [dict(r) for r in rows]

def save_platform_config(
    name: str,
    url_template: str,
    category: str = "General",
    is_active: int = 1,
    db_path: Optional[str] = None
) -> int:
    """Creates or updates a platform directory template in the database."""
    clean_n = name.strip()
    clean_u = url_template.strip()
    with get_connection(db_path) as conn:
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

def delete_platform_config(platform_id: int, db_path: Optional[str] = None) -> bool:
    """Deletes a directory platform template by ID."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM platforms_config WHERE id = ?", (platform_id,))
        conn.commit()
        return True

def get_cached_census_total(platform: str, query: str, location: str, db_path: Optional[str] = None) -> Optional[int]:
    """Retrieve verified census total for a given platform, query, and location."""
    if not platform or not location:
        return None
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT total FROM census_cache WHERE LOWER(platform) = ? AND LOWER(query) = ? AND LOWER(location) = ?",
            (platform.strip().lower(), query.strip().lower(), location.strip().lower())
        ).fetchone()
        return row[0] if row else None

def set_cached_census_total(platform: str, query: str, location: str, total: int, db_path: Optional[str] = None):
    """Store or update verified census total for a given platform, query, and location."""
    if total <= 0 or not platform or not location:
        return
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO census_cache (platform, query, location, total, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(platform, query, location) DO UPDATE SET total = excluded.total, updated_at = CURRENT_TIMESTAMP
        """, (platform.strip().lower(), query.strip().lower(), location.strip().lower(), total))
        conn.commit()
