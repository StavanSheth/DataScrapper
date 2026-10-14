import os
import sys
import unittest
import tempfile
import sqlite3
import json
import math

ROOT_DIR = r"C:\Projects\Data Scrapper"
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import database
from runner_scraper import (
    clean_text,
    clean_social_url,
    extract_core_brand_name,
    parse_search_query_and_location,
    calculate_haversine_distance_km,
    radius_to_zoom,
    build_platform_area_url,
)
from scrapers.antibot import decode_cloudflare_email


class TestAgent1MapsEdgeCases(unittest.TestCase):
    """Stress test Agent 1: Google Maps parser, geofencing, distance, and query edge cases."""

    def test_haversine_extreme_and_invalid_coords(self):
        # Normal distance Mumbai to London (~7190 km)
        d = calculate_haversine_distance_km(19.0760, 72.8777, 51.5074, -0.1278)
        self.assertTrue(7100 < d < 7300, f"Expected ~7190km, got {d}")

        # Identical points (distance 0)
        self.assertAlmostEqual(calculate_haversine_distance_km(19.0, 72.0, 19.0, 72.0), 0.0)

        # Opposite poles / Antipodes (max distance ~20000 km)
        d_pole = calculate_haversine_distance_km(90.0, 0.0, -90.0, 0.0)
        self.assertTrue(19900 < d_pole < 20100)

        # Equator wrap around (-179.9 to +179.9)
        d_wrap = calculate_haversine_distance_km(0.0, -179.9, 0.0, 179.9)
        self.assertTrue(d_wrap < 30.0)

    def test_radius_to_zoom_boundaries(self):
        self.assertEqual(radius_to_zoom(0.1), 16)
        self.assertEqual(radius_to_zoom(1.5), 16)
        self.assertEqual(radius_to_zoom(2.0), 15)
        self.assertEqual(radius_to_zoom(3.5), 15)
        self.assertEqual(radius_to_zoom(5.0), 14)
        self.assertEqual(radius_to_zoom(10.0), 13)
        self.assertEqual(radius_to_zoom(20.0), 12)
        self.assertEqual(radius_to_zoom(40.0), 11)
        self.assertEqual(radius_to_zoom(100.0), 10)

    def test_clean_text_and_brand_extraction_edge_cases(self):
        self.assertEqual(clean_text("Starbucks\ue001 Coffee  \n Bandra"), "Starbucks Coffee Bandra")
        self.assertEqual(clean_text("   "), "")

        self.assertEqual(extract_core_brand_name("Starbucks Coffee - Bandra West"), "Starbucks Coffee")
        self.assertEqual(extract_core_brand_name("Taj Lands End | Luxury Hotel (Mumbai)"), "Taj Lands End")
        self.assertEqual(extract_core_brand_name("Apple Store Pvt Ltd"), "Apple Store")
        self.assertEqual(extract_core_brand_name(""), "")

    def test_clean_social_url_edge_cases(self):
        self.assertEqual(clean_social_url("https://www.instagram.com/apple/?hl=en#tag"), "https://www.instagram.com/apple")
        self.assertEqual(clean_social_url("https://facebook.com/brand/"), "https://facebook.com/brand")
        self.assertEqual(clean_social_url("javascript:void(0)"), "")
        self.assertEqual(clean_social_url(""), "")


class TestAgent2WebsiteScraperEdgeCases(unittest.TestCase):
    """Stress test Agent 2: Email de-obfuscation, junk filtering, and bot protection."""

    def test_cloudflare_email_xor_decoder(self):
        plain = "hello@world.com"
        key = 0x2b
        cipher = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in plain)
        decoded = decode_cloudflare_email(cipher)
        self.assertEqual(decoded, plain)

        self.assertEqual(decode_cloudflare_email(""), "")
        self.assertEqual(decode_cloudflare_email("zz"), "")
        self.assertEqual(decode_cloudflare_email("invalid_hex_string_123"), "")

    def test_junk_email_filter_stress(self):
        raw = (
            "valid.lead@company.com, "
            "lodash@4.17.21, "
            "wght@400..700, "
            "intl-segmenter-poly@1.0.0, "
            "u003eceo@enterprise.org, "
            "@12.34, "
            "not-an-email, "
            "founder@startup.io"
        )
        cleaned = database.clean_email_string(raw)
        self.assertIn("valid.lead@company.com", cleaned)
        self.assertIn("ceo@enterprise.org", cleaned)
        self.assertIn("founder@startup.io", cleaned)
        self.assertNotIn("lodash", cleaned)
        self.assertNotIn("wght", cleaned)
        self.assertNotIn("intl-segmenter", cleaned)
        self.assertNotIn("u003e", cleaned)

    def test_bot_protection_normalization(self):
        self.assertEqual(database.normalize_bot_protection_status("Cloudflare", website="https://example.com"), "Cloudflare (Access Granted)")
        self.assertEqual(database.normalize_bot_protection_status("Cloudflare", page_title="403 Forbidden"), "Cloudflare (Access Denied)")
        self.assertEqual(database.normalize_bot_protection_status("Datadome", email="ceo@test.com"), "Datadome (Access Granted)")
        self.assertEqual(database.normalize_bot_protection_status("Datadome", email=""), "Datadome (Access Denied)")
        self.assertEqual(database.normalize_bot_protection_status("none", website="https://example.com"), "none")


class TestAgent3LinkedInEdgeCases(unittest.TestCase):
    """Stress test Agent 3: Seniority classification and domain cleanup."""

    def test_seniority_classification(self):
        self.assertEqual(database.classify_seniority("Managing Director & Founder"), "executive")
        self.assertEqual(database.classify_seniority("Chief Technology Officer (CTO)"), "executive")
        self.assertEqual(database.classify_seniority("Vice President of Sales"), "executive")
        self.assertEqual(database.classify_seniority("VP Engineering"), "executive")
        self.assertEqual(database.classify_seniority("Senior Product Manager"), "management")
        self.assertEqual(database.classify_seniority("HR Generalist"), "staff")
        self.assertEqual(database.classify_seniority("Software Engineer"), "staff")
        self.assertEqual(database.classify_seniority("Intern"), "staff")
        self.assertEqual(database.classify_seniority(""), "staff")

    def test_clean_domain(self):
        self.assertEqual(database.clean_domain("https://www.google.com/search?q=test"), "google.com")
        self.assertEqual(database.clean_domain("http://sub.domain.co.uk:8080/path/"), "sub.domain.co.uk")
        self.assertEqual(database.clean_domain("example.com"), "example.com")
        self.assertEqual(database.clean_domain(""), "")


class TestAgent4PlatformDirectoryEdgeCases(unittest.TestCase):
    """Stress test Agent 4: Query location parsing, multi-platform URLs, and normalization."""

    def test_parse_search_query_and_location(self):
        cat, loc = parse_search_query_and_location("Salons in Chembur Mumbai")
        self.assertEqual(cat.lower(), "salons")
        self.assertIn("chembur", loc.lower())

        cat, loc = parse_search_query_and_location("Boutiques near Bandra")
        self.assertEqual(cat.lower(), "boutiques")
        self.assertEqual(loc.lower(), "bandra")

        cat, loc = parse_search_query_and_location("Hotels, London UK")
        self.assertEqual(cat.lower(), "hotels")
        self.assertEqual(loc.lower(), "london uk")

        cat, loc = parse_search_query_and_location("Restaurants")
        self.assertEqual(cat.lower(), "restaurants")
        self.assertTrue(len(loc) > 0)

        # Coordinate based parsing inside Mumbai boundary
        cat, loc = parse_search_query_and_location("Dentists", lat=19.076, lon=72.877)
        self.assertEqual(cat.lower(), "dentists")
        self.assertEqual(loc, "Mumbai")

        # Coordinate based parsing outside Mumbai
        cat, loc = parse_search_query_and_location("Dentists", lat=51.507, lon=-0.128)
        self.assertEqual(cat.lower(), "dentists")
        self.assertEqual(loc, "51.51,-0.13")

    def test_build_platform_area_urls(self):
        f_url = build_platform_area_url("Fresha", "Salon", "Mumbai")
        self.assertIn("fresha.com", f_url)
        self.assertIn("query=Salon", f_url)

        a_url = build_platform_area_url("Airbnb", "Villa", "Goa")
        self.assertIn("airbnb.com", a_url)
        self.assertIn("query=Villa", a_url)

        y_url = build_platform_area_url("Yelp", "Pizza", "New York")
        self.assertIn("yelp.com", y_url)
        self.assertIn("find_desc=Pizza", y_url)


class TestDatabaseAndNormalizationPipeline(unittest.TestCase):
    """Stress test multi-table schema, fuzzy normalization, and duplicate resolution."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_file.name
        self.temp_file.close()
        self.old_db = database.DB_PATH
        database.DB_PATH = self.temp_db_path
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.old_db
        try:
            os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_fuzzy_normalization_pipeline(self):
        lead_id = database.save_lead({
            "name": "Artisan Bakery & Cafe",
            "category": "Bakery",
            "address": "45 Park Street, Kolkata",
            "lat": 22.5530,
            "lon": 88.3510,
            "website": "https://artisanbakery.in",
            "phone": "+91 33 2222 1111",
            "screenshot": "/static/screenshots/Artisan_Bakery.jpg"
        })
        self.assertGreater(lead_id, 0)

        listing_id = database.save_platform_listing({
            "platform": "Yelp",
            "title": "Artisan Bakery & Cafe (Park St)",
            "url": "https://www.yelp.com/biz/artisan-bakery-kolkata",
            "address": "Park Street 45, Kolkata",
            "latitude": 22.5532,
            "longitude": 88.3512,
            "rating": 4.8,
            "reviews_count": 210,
            "booking_url": "https://yelp.com/reservations/artisan",
            "lead_id": None,
            "screenshot": ""
        })
        self.assertGreater(listing_id, 0)

        listing2_id = database.save_platform_listing({
            "platform": "Airbnb",
            "title": "Heritage Suite in North Kolkata",
            "url": "https://www.airbnb.com/rooms/998877",
            "address": "Shyambazar, Kolkata",
            "latitude": 22.6000,
            "longitude": 88.3700,
            "rating": 4.95,
            "reviews_count": 45,
            "lead_id": None
        })
        self.assertGreater(listing2_id, 0)

        stats = database.normalize_all_platform_listings()
        self.assertGreaterEqual(stats["newly_matched"], 1)

        split = database.get_tables_split_data()
        self.assertIn("master_leads", split)
        self.assertIn("unmatched_maps", split)
        self.assertIn("unmatched_platform", split)

        master_lead = next((l for l in split["master_leads"] if l["id"] == lead_id), None)
        self.assertIsNotNone(master_lead)
        self.assertEqual(master_lead["platform_name"], "Yelp")
        self.assertEqual(master_lead["platform_rating"], "4.8")
        self.assertEqual(master_lead["booking_url"], "https://yelp.com/reservations/artisan")

        unmatched_titles = [p["title"] for p in split["unmatched_platform"]]
        self.assertIn("Heritage Suite in North Kolkata", unmatched_titles)


if __name__ == "__main__":
    unittest.main()
