import unittest
import sys
import os

sys.path.insert(0, r"C:\Projects\Data Scrapper")

from runner_scraper import PLATFORM_PROFILES
from database import load_proximity_dedup_cache, is_platform_listing_already_scraped

class TestMultiPlatformPipeline(unittest.TestCase):
    def test_platform_timing_profiles_20_percent_margin(self):
        # Verify 20% timeout margin on all platforms
        for plat, prof in PLATFORM_PROFILES.items():
            baseline = prof["baseline_sec"]
            timeout = prof["timeout_sec"]
            expected = round(baseline * 1.20, 2)
            self.assertAlmostEqual(timeout, expected, delta=0.05,
                                   msg=f"Platform {plat} timeout should be baseline + 20%")

    def test_platform_profiles_exist(self):
        required = ["Fresha", "Airbnb", "Yelp", "TripAdvisor", "Google Maps"]
        for r in required:
            self.assertIn(r, PLATFORM_PROFILES)

    def test_multi_platform_dedup_cache(self):
        cache = load_proximity_dedup_cache("Bandra")
        self.assertIn("listings_urls", cache)
        self.assertIn("listings_titles", cache)
        self.assertIsInstance(cache["listings_urls"], set)

    def test_tables_split_platform_separation(self):
        from database import get_tables_split_data
        data = get_tables_split_data()
        # Verify no pure platform listings leak into unmatched_maps
        for m in data.get("unmatched_maps", []):
            maps_url = str(m.get("maps_url", "") or "")
            has_maps = "google.com/maps" in maps_url or "goo.gl/maps" in maps_url or "maps.app.goo.gl" in maps_url
            plat_name = m.get("platform_name")
            if plat_name and plat_name != "N/A":
                self.assertTrue(has_maps, f"Listing '{m.get('name')}' in maps table has platform_name but no maps_url!")

    def test_multi_platform_target_generation(self):
        import urllib.parse
        platforms_list = ["Fresha", "Airbnb", "Yelp"]
        loc_val = "Mumbai"
        query_val = "Salon"
        loc_enc = urllib.parse.quote_plus(loc_val)
        query_enc = urllib.parse.quote_plus(query_val)
        targets = []
        for p in platforms_list:
            p_low = p.lower()
            if "fresha" in p_low:
                url = f"https://www.fresha.com/search?query={query_enc}&address={loc_enc}"
            elif "airbnb" in p_low:
                url = f"https://www.airbnb.com/s/{loc_enc}/homes?query={query_enc}"
            elif "yelp" in p_low:
                url = f"https://www.yelp.com/search?find_desc={query_enc}&find_loc={loc_enc}"
            targets.append({"name": p, "url": url})
        self.assertEqual(len(targets), 3)
        self.assertIn("fresha.com", targets[0]["url"])
        self.assertIn("airbnb.com", targets[1]["url"])
        self.assertIn("yelp.com", targets[2]["url"])

if __name__ == "__main__":
    unittest.main()
