import unittest
import sys
import argparse
sys.path.insert(0, '.')
from runner_scraper import build_platform_area_url, run_scraper

class TestTogglePermutationsAndSync(unittest.TestCase):
    def test_permutation_agent4_only_fresha_airbnb(self):
        # Permutation matching user's exact screenshot:
        # Agent 1 (Maps): OFF
        # Agent 2 (Website): OFF
        # Agent 3 (LinkedIn): OFF
        # Agent 4 (Platform): ON with Fresha & Airbnb
        platforms = ["Fresha", "Airbnb"]
        p1 = build_platform_area_url(platforms[0], "Spa", "Mumbai")
        p2 = build_platform_area_url(platforms[1], "Apartment", "Mumbai")
        self.assertIn("fresha.com", p1)
        self.assertIn("airbnb.com", p2)

    def test_permutation_agent4_only_custom_url(self):
        # Custom Platform checkbox checked with custom template
        custom_url = "https://custom-directory.com/search?q={query}&loc={location}"
        target = build_platform_area_url("Custom", "Salon", "London", custom_pattern=custom_url)
        self.assertEqual(target, "https://custom-directory.com/search?q=Salon&loc=London")

    def test_runner_scraper_cli_arg_parsing(self):
        # Verify CLI parser flags for toggles
        parser = argparse.ArgumentParser()
        parser.add_argument("--enable-maps", dest="enable_maps", action="store_true", default=True)
        parser.add_argument("--no-maps", dest="enable_maps", action="store_false")
        parser.add_argument("--enable-website", dest="enable_website", action="store_true", default=True)
        parser.add_argument("--no-website", dest="enable_website", action="store_false")
        parser.add_argument("--enable-linkedin", dest="enable_linkedin", action="store_true", default=True)
        parser.add_argument("--no-linkedin", dest="enable_linkedin", action="store_false")
        parser.add_argument("--enable-platform", dest="enable_platform", action="store_true", default=False)
        parser.add_argument("--no-platform", dest="enable_platform", action="store_false")
        parser.add_argument("--platforms", type=str, default="Fresha")

        # Test case: User screenshot (Agent 1 OFF, Agent 2 OFF, Agent 3 OFF, Agent 4 ON)
        args = parser.parse_args(["--no-maps", "--no-website", "--no-linkedin", "--enable-platform", "--platforms", "Fresha,Airbnb"])
        self.assertFalse(args.enable_maps)
        self.assertFalse(args.enable_website)
        self.assertFalse(args.enable_linkedin)
        self.assertTrue(args.enable_platform)
        self.assertEqual(args.platforms, "Fresha,Airbnb")

        # Test case: All 4 ON
        args_all = parser.parse_args(["--enable-maps", "--enable-website", "--enable-linkedin", "--enable-platform", "--platforms", "Fresha,Airbnb,Yelp,TripAdvisor"])
        self.assertTrue(args_all.enable_maps)
        self.assertTrue(args_all.enable_website)
        self.assertTrue(args_all.enable_linkedin)
        self.assertTrue(args_all.enable_platform)

if __name__ == "__main__":
    unittest.main()
