"""
Integration tests for Database Repositories (Employees & Platform Listings).
Uses an isolated SQLite database to verify data persistence and queries.
"""
import os
import tempfile
import sqlite3
import pytest

from packages.database.src.adapters.sqlite.connection import get_connection
from packages.database.src.repositories.employee_repository import (
    save_employees_batch,
    get_company_hierarchy,
    get_employees_by_lead_id
)
from packages.database.src.repositories.platform_repository import (
    save_platform_listing,
    get_platform_listings,
    get_platform_listing_by_id,
    is_platform_listing_already_scraped,
    save_platform_config,
    get_platforms_config,
    set_cached_census_total,
    get_cached_census_total
)

@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Initialize schema
    schema_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../database/migrations/sqlite/001_initial_schema.sql")
    )
    with open(schema_path, "r", encoding="utf-8") as f:
        ddl = f.read()

    conn = sqlite3.connect(path)
    conn.executescript(ddl)
    conn.commit()
    conn.close()

    yield path

    import gc
    gc.collect()
    try:
        if os.path.exists(path):
            os.remove(path)
    except PermissionError:
        pass

def test_employee_repository_crud(test_db):
    roster = [
        {
            "full_name": "Dr. Sarah Connor",
            "title": "Clinical Director",
            "seniority_level": "executive",
            "linkedin_profile_url": "https://www.linkedin.com/in/sarahconnor",
            "location": "Mumbai, India"
        },
        {
            "full_name": "John Smith",
            "title": "Operations Manager",
            "seniority_level": "management",
            "linkedin_profile_url": "https://www.linkedin.com/in/johnsmith",
            "location": "Mumbai, India"
        }
    ]

    saved_count = save_employees_batch(
        company_name="Apex Dental Clinic",
        employees=roster,
        company_linkedin_url="https://www.linkedin.com/company/apex-dental",
        db_path=test_db
    )
    assert saved_count == 2

    hierarchy = get_company_hierarchy("Apex Dental Clinic", db_path=test_db)
    assert hierarchy["total_employees"] == 2
    assert len(hierarchy["tiers"]["executive"]) == 1
    assert len(hierarchy["tiers"]["management"]) == 1
    assert hierarchy["tiers"]["executive"][0]["full_name"] == "Dr. Sarah Connor"

def test_platform_repository_crud(test_db):
    listing = {
        "platform": "Fresha",
        "title": "Enrich Salon - Bandra West",
        "clean_brand": "Enrich Salon",
        "category": "Salons & Spas",
        "url": "https://www.fresha.com/a/enrich-salon-bandra",
        "rating": 4.8,
        "reviews_count": 142,
        "price_info": "₹₹",
        "address": "Bandra West, Mumbai"
    }

    listing_id = save_platform_listing(listing, db_path=test_db)
    assert listing_id > 0

    fetched = get_platform_listing_by_id(listing_id, db_path=test_db)
    assert fetched is not None
    assert fetched["title"] == "Enrich Salon - Bandra West"
    assert fetched["rating"] == 4.8
    assert fetched["reviews_count"] == 142

    assert is_platform_listing_already_scraped(
        "Fresha", "Enrich Salon - Bandra West", "https://www.fresha.com/a/enrich-salon-bandra", db_path=test_db
    ) is True

    # Test census cache
    set_cached_census_total("Fresha", "Salons", "Bandra", 45, db_path=test_db)
    assert get_cached_census_total("Fresha", "Salons", "Bandra", db_path=test_db) == 45

    # Test platform config
    config_id = save_platform_config("Fresha", "https://www.fresha.com/search?q={query}", "Salons", 1, db_path=test_db)
    assert config_id > 0
    configs = get_platforms_config(db_path=test_db)
    assert len(configs) >= 1
    assert configs[0]["name"] == "Fresha"
