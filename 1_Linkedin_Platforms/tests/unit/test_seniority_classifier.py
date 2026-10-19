"""
Unit tests for Employee Seniority Tier Classifier.
"""
import pytest
from backend.src.datascrapper.modules.employees.services import classify_seniority, build_organization_tree

def test_classify_executives():
    assert classify_seniority("Chief Executive Officer") == "executive"
    assert classify_seniority("CEO & Founder") == "executive"
    assert classify_seniority("Managing Director") == "executive"
    assert classify_seniority("Co-Founder & VP of Product") == "executive"
    assert classify_seniority("Partner") == "executive"

def test_classify_management():
    assert classify_seniority("Head of Sales") == "management"
    assert classify_seniority("General Manager") == "management"
    assert classify_seniority("Operations Manager") == "management"
    assert classify_seniority("Engineering Team Lead") == "management"
    assert classify_seniority("Store Supervisor") == "management"

def test_classify_staff():
    assert classify_seniority("Dental Assistant") == "staff"
    assert classify_seniority("Frontend Developer") == "staff"
    assert classify_seniority("Customer Success Specialist") == "staff"
    assert classify_seniority("Accountant") == "staff"
    assert classify_seniority("") == "staff"

def test_build_organization_tree():
    roster = [
        {"full_name": "Alice Smith", "title": "Founder & CEO"},
        {"full_name": "Bob Jones", "title": "Head of Operations"},
        {"full_name": "Charlie Brown", "title": "Dental Hygienist"}
    ]
    tree = build_organization_tree(roster)
    assert tree["total"] == 3
    assert tree["executive_count"] == 1
    assert tree["management_count"] == 1
    assert tree["staff_count"] == 1
    assert tree["tiers"]["executive"][0]["full_name"] == "Alice Smith"
