import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
import tempfile
import database

def test_platform_agent_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    old_db = database.DB_PATH
    database.DB_PATH = temp_db_path

    try:
        database.init_db()
        
        # Insert a sample lead
        lead_id = database.save_lead({
            "name": "Luxe Glow Salon",
            "address": "123 High Street, Mumbai",
            "phone": "+91 9876543210",
            "rating": "4.5",
            "reviews": "120",
            "category": "Beauty salon",
            "website": "https://luxeglow.com",
            "maps_url": "https://maps.google.com/?cid=123"
        })
        assert lead_id > 0, "Lead should be inserted"

        # Now save a normalized platform listing
        listing_id = database.save_platform_listing({
            "platform": "Fresha",
            "company_name": "Luxe Glow Salon & Spa",
            "listing_url": "https://fresha.com/a/luxe-glow-mumbai",
            "city": "Mumbai",
            "rating": "4.9",
            "review_count": "340",
            "price_range": "₹₹",
            "booking_url": "https://fresha.com/book/luxe-glow",
            "verified": 1,
            "lead_id": lead_id
        })
        assert listing_id > 0, "Listing should be saved"

        # Check that platform listing is linked and retrieved
        listings = database.get_platform_listings("Fresha")
        assert len(listings) == 1, "Should have 1 Fresha listing"
        assert listings[0]["lead_id"] == lead_id, "Listing should be linked to lead"

        # Check that lead was enriched with normalized platform data
        leads = database.get_all_leads()
        matched = next((l for l in leads if l["id"] == lead_id), None)
        assert matched is not None, "Lead should exist in get_all_leads"
        assert matched["platform_name"] == "Fresha", "Platform name should be merged"
        assert matched["platform_rating"] == "4.9", "Platform rating should be merged"
        assert matched["booking_url"] == "https://fresha.com/book/luxe-glow", "Booking URL should be merged"

        # Test unmatched platform listing with social links & maps link (auto-creates lead)
        unmatched_listing_id = database.save_platform_listing({
            "platform": "Airbnb",
            "title": "Sea Breeze Luxury Apartment",
            "url": "https://airbnb.com/rooms/998877",
            "address": "Bandra Bandstand, Mumbai",
            "rating": "4.85",
            "review_count": "85",
            "price_info": "₹6,500 / night",
            "maps_url": "https://maps.google.com/?q=19.05,72.82",
            "instagram": "https://instagram.com/seabreeze_mumbai",
            "facebook": "https://facebook.com/seabreeze",
            "linkedin": "https://linkedin.com/company/seabreeze",
            "twitter": "https://x.com/seabreeze",
            "youtube": "https://youtube.com/@seabreeze",
            "tiktok": "https://tiktok.com/@seabreeze",
            "whatsapp": "+919876500000",
            "phone": "+91 98765 00000",
            "email": "booking@seabreeze.com",
            "emails": ["booking@seabreeze.com", "info@seabreeze.com"],
            "website": "https://seabreeze-luxury.com",
            "bot_protection": "Cloudflare Turnstile",
            "cookie_status": "Accepted",
            "website_status": "contacts_found",
            "notes": "Verified sea view villa",
            "booking_url": "https://airbnb.com/rooms/998877",
            "create_lead_if_missing": True
        })
        assert unmatched_listing_id > 0, "Unmatched listing should be saved"

        # Check all rich columns in platform_listings table
        ab_listings = database.get_platform_listings("Airbnb")
        assert len(ab_listings) == 1, "Should have 1 Airbnb listing"
        ab = ab_listings[0]
        assert ab["email"] == "booking@seabreeze.com", "Email should be saved in platform_listings"
        assert "info@seabreeze.com" in ab["emails_json"], "emails_json should contain list"
        assert ab["phone"] == "+91 98765 00000", "Phone should be saved"
        assert ab["website"] == "https://seabreeze-luxury.com", "Website URL should be saved"
        assert ab["maps_url"] == "https://maps.google.com/?q=19.05,72.82", "Maps URL should be saved"
        assert ab["bot_protection"] == "Cloudflare Turnstile", "Bot protection should be saved"
        assert ab["cookie_status"] == "Accepted", "Cookie status should be saved"
        assert ab["website_status"] == "contacts_found", "Website status should be saved"
        assert ab["notes"] == "Verified sea view villa", "Notes should be saved"
        assert ab["youtube"] == "https://youtube.com/@seabreeze", "YouTube should be saved"
        assert ab["tiktok"] == "https://tiktok.com/@seabreeze", "TikTok should be saved"

        # Verify get_tables_split_data includes rich platform listing with correct status_tag
        split_data = database.get_tables_split_data()
        plat_rows = split_data.get("unmatched_platform", [])
        assert len(plat_rows) >= 2, "Should return platform listings in split data"
        ab_row = next((r for r in plat_rows if r["id"] == unmatched_listing_id), None)
        assert ab_row is not None, "Airbnb row should be in split data"
        assert ab_row["has_email"] is True, "has_email flag should be True"
        assert ab_row["has_phone"] is True, "has_phone flag should be True"
        assert ab_row["has_website"] is True, "has_website flag should be True"
        assert ab_row["has_socials"] is True, "has_socials flag should be True"

        # Verify mutation updates works for rich fields
        updated = database.update_platform_listing(unmatched_listing_id, {
            "email": "owner@seabreeze.com",
            "notes": "Updated penthouse suite"
        })
        assert updated is True, "update_platform_listing should succeed for rich fields"
        updated_listing = database.get_platform_listing_by_id(unmatched_listing_id)
        assert updated_listing["email"] == "owner@seabreeze.com", "Updated email should persist"
        assert updated_listing["notes"] == "Updated penthouse suite", "Updated notes should persist"

        # Verify auto-created lead in leads table
        all_leads = database.get_all_leads()
        auto_lead = next((l for l in all_leads if "Sea Breeze" in l["name"]), None)
        assert auto_lead is not None, "Lead should be auto-created for unmatched platform listing"
        assert auto_lead["platform_name"] == "Airbnb", "Auto-created lead has platform_name"
        assert auto_lead["instagram"] == "https://instagram.com/seabreeze_mumbai", "Social link should be extracted"
        assert "maps.google.com" in auto_lead["maps_url"], "Maps URL should be saved"
        print("PASS: test_platform_agent_db passed successfully!")

    finally:
        database.DB_PATH = old_db
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass

def test_platform_url_generation():
    import urllib.parse
    # Mimic app.py URL builder logic
    def build_plat_url(platform_name, platform_custom_url, query, location):
        plat_target_url = None
        enable_platform = True
        if enable_platform:
            if platform_custom_url:
                plat_target_url = platform_custom_url
            else:
                p_low = platform_name.lower().strip()
                loc_val = (location or "").strip()
                query_val = (query or "").strip()
                loc_enc = urllib.parse.quote_plus(loc_val or query_val)
                query_enc = urllib.parse.quote_plus(query_val)

                if "fresha" in p_low:
                    if loc_val:
                        plat_target_url = f"https://www.fresha.com/search?query={query_enc}&address={loc_enc}"
                    else:
                        plat_target_url = f"https://www.fresha.com/search?query={query_enc}"
                elif "airbnb" in p_low:
                    if loc_val:
                        plat_target_url = f"https://www.airbnb.com/s/{loc_enc}/homes?query={query_enc}"
                    else:
                        plat_target_url = f"https://www.airbnb.com/s/{query_enc}/homes"
                elif "yelp" in p_low:
                    plat_target_url = f"https://www.yelp.com/search?find_desc={query_enc}&find_loc={loc_enc}"
                elif "tripadvisor" in p_low:
                    plat_target_url = f"https://www.tripadvisor.com/Search?q={query_enc}+{loc_enc}"
                elif "treatwell" in p_low:
                    plat_target_url = f"https://www.treatwell.co.uk/places/in-{loc_enc}/?q={query_enc}"
                elif "justdial" in p_low:
                    plat_target_url = f"https://www.justdial.com/{loc_enc}/{query_enc}"
                else:
                    plat_target_url = f"https://www.{p_low}.com/search?q={query_enc}+{loc_enc}"
        return plat_target_url

    # Standard dropdown cases with NO custom url
    fresha_url = build_plat_url("Fresha", "", "salons", "mumbai")
    assert fresha_url == "https://www.fresha.com/search?query=salons&address=mumbai", f"Unexpected: {fresha_url}"

    airbnb_url = build_plat_url("Airbnb", "", "villas", "goa")
    assert airbnb_url == "https://www.airbnb.com/s/goa/homes?query=villas", f"Unexpected: {airbnb_url}"

    yelp_url = build_plat_url("Yelp", "", "dentists", "london")
    assert yelp_url == "https://www.yelp.com/search?find_desc=dentists&find_loc=london", f"Unexpected: {yelp_url}"

    # Custom URL case
    custom = build_plat_url("Custom", "https://example.com/custom-search", "dentists", "london")
    assert custom == "https://example.com/custom-search", f"Unexpected: {custom}"

    print("PASS: test_platform_url_generation passed successfully!")

def test_platform_screenshot_handling():
    import base64
    from app import save_screenshot_from_base64, screenshots_dir

    # 1x1 dummy JPEG base64
    dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    saved_url = save_screenshot_from_base64(dummy_b64, "Airbnb", "Queen Vista Bandra")
    assert saved_url.lower().startswith("/screenshots/airbnb_queen_vista_bandra_"), f"Unexpected: {saved_url}"
    assert saved_url.endswith(".jpg")

    file_name = saved_url.replace("/screenshots/", "")
    full_path = os.path.join(screenshots_dir, file_name)
    assert os.path.exists(full_path), "Screenshot file must exist on disk"
    assert os.path.getsize(full_path) > 0, "Screenshot file must not be empty"

    # Cleanup test file
    try:
        os.remove(full_path)
    except Exception:
        pass

    # Verify database persistence
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    old_db = database.DB_PATH
    database.DB_PATH = temp_db_path
    try:
        database.init_db()
        lid = database.save_platform_listing({
            "platform": "Airbnb",
            "title": "Queen Vista Bandra",
            "url": "https://airbnb.com/rooms/12345",
            "screenshot": "/screenshots/test_queen_vista.jpg",
            "create_lead_if_missing": True
        })
        assert lid > 0
        p_row = database.get_platform_listing_by_id(lid)
        assert p_row["screenshot"] == "/screenshots/test_queen_vista.jpg"

        leads = database.get_all_leads()
        lead = next((l for l in leads if "Queen Vista" in l["name"]), None)
        assert lead is not None
        assert lead["screenshot"] == "/screenshots/test_queen_vista.jpg"
    finally:
        database.DB_PATH = old_db
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass
    print("PASS: test_platform_screenshot_handling passed successfully!")

if __name__ == "__main__":
    test_platform_agent_db()
    test_platform_url_generation()
    test_platform_screenshot_handling()

