"""
Brand & URL Normalization Utilities.
Strips location, legal suffixes, mall descriptors, and normalizes social/domain tokens.
"""
import re
import urllib.parse
from typing import Optional

def clean_linkedin_url(url: str) -> str:
    """Validates and cleans LinkedIn URLs, strictly rejecting search/authwall/login URLs."""
    if not url or str(url).upper() in ("N/A", "NONE"):
        return ""
    u = str(url).strip()
    u_low = u.lower()
    if any(bad in u_low for bad in ["/search", "uas/login", "authwall", "checkpoint", "linkedin.com/help", "linkedin.com/feed", "linkedin.com/share"]):
        return ""
    if "linkedin.com" in u_low and ("/company/" in u_low or "/in/" in u_low):
        return u.split("?")[0].rstrip("/")
    return ""

def clean_social_url(url: str) -> str:
    """Cleans tracking query parameters, hashes, and formats social URLs."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        return ""
    return url.split("?")[0].split("#")[0].rstrip("/")

def extract_core_brand_name(name: str, city: str = "") -> str:
    """
    Extracts the clean parent brand/business name by stripping mall, branch,
    retail descriptor, and legal entity suffixes (e.g., 'Nike Factory Store Viviana Mall' -> 'Nike').
    """
    if not name:
        return ""
    # 1. Take part before explicit separators like ' - ', ' | ', ' @ ', '(', '['
    base = re.split(r'\s*[-–—|@]\s*|[(\[]', name)[0].strip()
    if not base or len(base) < 2:
        base = name.strip()

    # 2. Strip trailing punctuation
    base = re.sub(r'[\.,\-_;:\'\"]+$', '', base).strip()

    # 3. Strip legal entity suffixes from end
    legal_pat = r'\s+\b(?:pvt\.?\s*ltd\.?|private\s+limited|ltd\.?|llc|inc\.?|corp\.?|co\.?|corporation)\b\.?$'
    base = re.sub(legal_pat, '', base, flags=re.I).strip()

    # 4. Strip mall phrases with mall name, e.g. 'Viviana Mall', 'Inorbit Mall'
    mall_pat = r'\s+\b[A-Za-z0-9]+\s+(?:mall|plaza|centre|center|galleria|arcade)\b'
    base = re.sub(mall_pat, '', base, flags=re.I).strip()

    # 5. Strip retail phrases in middle/end
    retail_pat = r'\s+\b(?:factory\s+store|factory\s+outlet|flagship\s+store|retail\s+store)\b'
    base = re.sub(retail_pat, '', base, flags=re.I).strip()

    # 6. If city is provided, strip trailing city from end
    if city and len(city) >= 3:
        city_esc = re.escape(city.strip())
        base = re.sub(rf'\s+\b{city_esc}\b.*$', '', base, flags=re.I).strip()

    # 7. Standalone end suffixes
    end_suffix_pat = r'\s+\b(?:outlet|showroom|branch|mall|bazaar|supermarket|hypermarket)\b$'
    base = re.sub(end_suffix_pat, '', base, flags=re.I).strip()

    return base if len(base) >= 2 else name

clean_brand_tokens = extract_core_brand_name

def extract_brand_from_domain(url: str) -> str:
    """Extracts the brand name directly from the domain (e.g., 'https://superkicks.in' -> 'superkicks')."""
    if not url or not url.startswith("http"):
        return ""
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        netloc = re.sub(r'^(?:www\d?|m|shop|store)\.', '', netloc)
        parts = netloc.split('.')
        if len(parts) >= 2 and len(parts[0]) >= 3:
            return parts[0]
    except Exception:
        pass
    return ""

def verify_company_name_match(searched_name: str, result_title: str) -> bool:
    """
    Strictly verifies whether a candidate search result title or card text
    corresponds to the searched business brand, preventing unrelated companies from being matched.
    """
    if not searched_name or not result_title:
        return False

    clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', searched_name).lower()
    clean_title = re.sub(r'[^a-zA-Z0-9\s]', ' ', result_title).lower()

    words_search = set(clean_search.split())
    words_title = set(clean_title.split())

    # Remove generic tokens that cause false positives
    stop_words = {"pvt", "ltd", "private", "limited", "inc", "co", "corp", "llc", "the", "and", "&", "services", "solutions", "clinic", "dental", "hospital", "store", "shop"}
    meaningful_search = words_search - stop_words
    meaningful_title = words_title - stop_words

    if not meaningful_search:
        return words_search.issubset(words_title)

    overlap = meaningful_search.intersection(meaningful_title)
    return len(overlap) / len(meaningful_search) >= 0.5
