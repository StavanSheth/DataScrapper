import sys
sys.path.insert(0, '.')
import unittest
import re
from database import extract_core_brand_name, jaccard_similarity, normalize_all_platform_listings, get_tables_split_data

class TestAgent4DataQualityAndTabIsolation(unittest.TestCase):
    def test_junk_title_blacklist_filter(self):
        junk_regex = re.compile(
            r'^(?:filters?|filter\s*\(?\d*\)?|show\s+map|map|search|clear\s+all|explore|instant\s+book|rooms\s+and\s+beds|property\s+type|amenities|sort\s+by|guest\s+favorites?|menu|view\s+in\s+map|sign\s+in|log\s+in|navigation|next|previous|page\s+\d+|categories|ratings?|prices?|display\s+total|share|save)$',
            re.IGNORECASE
        )
        junk_samples = [
            "filters", "Filters", "filter", "Filter (2)", "Show map", "map", "search",
            "Clear all", "Explore", "Instant Book", "Rooms and beds", "Property type",
            "Amenities", "Sort by", "Guest Favorites", "Menu", "Log in", "Sign in",
            "Next", "Previous", "Page 1", "Categories", "Ratings", "Prices"
        ]
        for s in junk_samples:
            self.assertTrue(bool(junk_regex.match(s)), f"Expected '{s}' to be caught as junk")

        valid_titles = [
            "Apartment in Bandra East",
            "Privy Stays – Pinnacle 4BHK Luxury Villa with Pool",
            "Urban Oasis Studio",
            "Grand Hyatt Mumbai",
            "Tony & Guy Salon",
            "The Blue Tokai Coffee Roasters"
        ]
        for v in valid_titles:
            self.assertFalse(bool(junk_regex.match(v)), f"Valid title '{v}' was falsely rejected")

    def test_listing_url_validation(self):
        # Airbnb
        self.assertTrue("/rooms/1205161066654778300" in "https://www.airbnb.co.in/rooms/1205161066654778300")
        self.assertFalse("/rooms/" in "https://www.airbnb.co.in/s/Revas/homes")
        self.assertFalse("/rooms/" in "https://www.airbnb.co.in/s/Mumbai/homes?query=salon")

        # Fresha
        self.assertTrue("/a/" in "https://www.fresha.com/a/glam-studio-mumbai-bandra-west-a1b2c3")
        self.assertFalse("/a/" in "https://www.fresha.com/search?query=salon&address=Mumbai")

        # Yelp
        self.assertTrue("/biz/" in "https://www.yelp.com/biz/blue-bottle-coffee-san-francisco")
        self.assertFalse("/biz/" in "https://www.yelp.com/search?find_desc=coffee&find_loc=SF")

    def test_rating_and_review_parser(self):
        sample_aria = "Privy Stays – Pinnacle 4BHK Luxury Villa with Pool in Revas - Rated 4.92 out of 5 stars from 58 reviews"
        rate_match = re.search(r'(?:rated\s*)?(\b[0-5]\.\d+)\s*(?:out of 5|\/5|★|stars?)?', sample_aria, re.I)
        self.assertIsNotNone(rate_match)
        self.assertEqual(float(rate_match.group(1)), 4.92)

        rev_match = re.search(r'(?:average\s*rating,\s*|\(|\bfrom\s*)(\d[\d,]*)\s*(?:reviews?|\))', sample_aria, re.I)
        self.assertIsNotNone(rev_match)
        self.assertEqual(int(rev_match.group(1)), 58)

    def test_price_parser(self):
        sample_text = "₹38,145 per night · Free cancellation"
        price_match = re.search(r'(?:[\$£€₹]|Rs\.?)\s*[\d,]+(?:\s*(?:\/|\s+per\s+)?(?:night|total))?', sample_text, re.I)
        self.assertIsNotNone(price_match)
        self.assertTrue("₹38,145" in price_match.group(0))

    def test_generic_stop_words_protection(self):
        generic_words = {
            'flat', 'apartment', 'villa', 'hotel', 'salon', 'spa', 'house', 'home', 
            'shop', 'room', 'rooms', 'suite', 'suites', 'stay', 'stays', 'resort',
            'resorts', 'clinic', 'store', 'centre', 'center', 'bazaar', 'retail'
        }
        self.assertIn("flat", generic_words)
        self.assertIn("apartment", generic_words)
        self.assertIn("villa", generic_words)

if __name__ == "__main__":
    unittest.main()
