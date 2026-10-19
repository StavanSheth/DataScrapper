"""
Unit tests for Brand & URL Normalization.
"""
import pytest
from backend.src.datascrapper.modules.normalization.brand_cleaner import (
    clean_linkedin_url,
    clean_brand_tokens,
    extract_brand_from_domain,
    clean_social_url
)
from backend.src.datascrapper.modules.source_registry.platform_profiles import build_platform_area_url

def test_clean_linkedin_url():
    valid_company = "https://www.linkedin.com/company/google/?originalSubdomain=in"
    assert clean_linkedin_url(valid_company) == "https://www.linkedin.com/company/google"

    valid_person = "https://www.linkedin.com/in/satyanadella?trk=people-guest"
    assert clean_linkedin_url(valid_person) == "https://www.linkedin.com/in/satyanadella"

    # Reject searches and login gates
    assert clean_linkedin_url("https://www.linkedin.com/search/results/all/?keywords=tech") == ""
    assert clean_linkedin_url("https://www.linkedin.com/uas/login") == ""
    assert clean_linkedin_url("N/A") == ""

def test_clean_brand_tokens():
    assert clean_brand_tokens("Nike Factory Store Viviana Mall - Thane", city="Thane") == "Nike"
    assert clean_brand_tokens("Starbucks Coffee - Bandra West") == "Starbucks Coffee"
    assert clean_brand_tokens("Infosys Pvt. Ltd.") == "Infosys"

def test_extract_brand_from_domain():
    assert extract_brand_from_domain("https://www.superkicks.in/products") == "superkicks"
    assert extract_brand_from_domain("http://shop.theobroma.in") == "theobroma"
    assert extract_brand_from_domain("invalid-url") == ""

def test_build_platform_area_url():
    fresha_url = build_platform_area_url("Fresha", "Salons", "Bandra West")
    assert "fresha.com/search" in fresha_url
    assert "query=Salons" in fresha_url

    airbnb_url = build_platform_area_url("Airbnb", "Apartment", "Dahisar East")
    assert "airbnb.com/s/Dahisar-East/homes" in airbnb_url

    yelp_url = build_platform_area_url("Yelp", "Dentist", "Andheri")
    assert "yelp.com/search" in yelp_url

    tripadvisor_url = build_platform_area_url("TripAdvisor", "Bakery", "Colaba")
    assert "tripadvisor.com/Search" in tripadvisor_url
