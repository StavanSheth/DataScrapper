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
        print("PASS: test_platform_agent_db passed successfully!")

    finally:
        database.DB_PATH = old_db
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass

if __name__ == "__main__":
    test_platform_agent_db()
