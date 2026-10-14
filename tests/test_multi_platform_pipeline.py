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

if __name__ == "__main__":
    unittest.main()
