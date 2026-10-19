"""
Platform Directory Profiles & Search URL Generator.
Configures platform baselines, timeouts, and multi-source URL templates.
"""
import re
import urllib.parse
from typing import Dict, Any, Tuple

PLATFORM_PROFILES: Dict[str, Dict[str, Any]] = {
    "Fresha": {"baseline_sec": 5.0, "timeout_sec": 6.0, "color": "#a855f7", "icon": "🟣"},
    "Airbnb": {"baseline_sec": 6.0, "timeout_sec": 7.2, "color": "#ef4444", "icon": "🔴"},
    "Yelp": {"baseline_sec": 4.5, "timeout_sec": 5.4, "color": "#f97316", "icon": "🟠"},
    "TripAdvisor": {"baseline_sec": 5.5, "timeout_sec": 6.6, "color": "#10b981", "icon": "🟢"},
    "Treatwell": {"baseline_sec": 5.0, "timeout_sec": 6.0, "color": "#ec4899", "icon": "🌸"},
    "Justdial": {"baseline_sec": 5.0, "timeout_sec": 6.0, "color": "#eab308", "icon": "🟡"},
    "Google Maps": {"baseline_sec": 4.5, "timeout_sec": 5.4, "color": "#3b82f6", "icon": "🗺️"},
}

def build_platform_area_url(
    platform_name: str,
    category: str,
    location_name: str,
    custom_pattern: str = ""
) -> str:
    """
    Builds area/proximity search URL for ANY directory platform.
    Supports built-in platforms, custom templates ({query}, {location}, {category}, {city}),
    direct domain names, and smart fallback discovery.
    """
    p_lower = platform_name.lower().strip()
    enc_cat = urllib.parse.quote_plus(category)
    enc_loc = urllib.parse.quote_plus(location_name)
    loc_hyphen = urllib.parse.quote(re.sub(r'\s+', '-', location_name.strip()))
    cat_hyphen = urllib.parse.quote(re.sub(r'\s+', '-', category.strip()))

    # 1. Custom URL pattern with template variable replacement
    if custom_pattern and "http" in custom_pattern:
        url = custom_pattern
        url = url.replace("{query}", enc_cat).replace("{category}", enc_cat)
        url = url.replace("{location}", enc_loc).replace("{city}", enc_loc)
        url = url.replace("{loc_slug}", loc_hyphen).replace("{cat_slug}", cat_hyphen)
        if "{" not in custom_pattern and ("?" not in custom_pattern or "=" not in custom_pattern):
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}q={enc_cat}&location={enc_loc}"
        return url

    # 2. If platform_name itself is a full URL
    if p_lower.startswith("http://") or p_lower.startswith("https://"):
        url = platform_name
        if "{" in url:
            url = url.replace("{query}", enc_cat).replace("{category}", enc_cat)
            url = url.replace("{location}", enc_loc).replace("{city}", enc_loc)
        else:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}q={enc_cat}&location={enc_loc}"
        return url

    # 3. Built-in Smart Templates for known popular directories
    if "fresha" in p_lower:
        f_cat = "salon" if enc_cat.lower() in ["shops", "shop", "all", "business"] else enc_cat
        return f"https://www.fresha.com/search?query={f_cat}&address={enc_loc}"
    elif "airbnb" in p_lower:
        return f"https://www.airbnb.com/s/{loc_hyphen}/homes?query={enc_cat}"
    elif "yelp" in p_lower:
        return f"https://www.yelp.com/search?find_desc={enc_cat}&find_loc={enc_loc}"
    elif "tripadvisor" in p_lower:
        return f"https://www.tripadvisor.com/Search?q={enc_cat}+{enc_loc}"
    elif "booking" in p_lower:
        return f"https://www.booking.com/searchresults.html?ss={enc_loc}+{enc_cat}"
    elif "zomato" in p_lower:
        return f"https://www.zomato.com/{loc_hyphen.lower()}/restaurants?q={enc_cat}"
    elif "justdial" in p_lower:
        return f"https://www.justdial.com/{loc_hyphen}/{enc_cat}"
    elif "treatwell" in p_lower:
        return f"https://www.treatwell.co.uk/places/treatment-{cat_hyphen.lower()}/in-{loc_hyphen.lower()}/"
    elif "yellowpages" in p_lower:
        return f"https://www.yellowpages.com/search?search_terms={enc_cat}&geo_location_terms={enc_loc}"
    elif "opentable" in p_lower:
        return f"https://www.opentable.com/s?term={enc_cat}&near={enc_loc}"
    elif "trustpilot" in p_lower:
        return f"https://www.trustpilot.com/search?query={enc_cat}+{enc_loc}"

    # 4. If platform_name is a domain (e.g. "somedirectory.com")
    if "." in p_lower and " " not in p_lower:
        clean_dom = p_lower.replace("www.", "")
        return f"https://www.{clean_dom}/search?q={enc_cat}&location={enc_loc}"

    # 5. Fallback: Proximity site search or Google directory discovery
    return f"https://www.google.com/search?q={enc_cat}+{enc_loc}+{urllib.parse.quote_plus(platform_name)}"
