"""
Employee & Workforce Hierarchy Domain Services.
Handles seniority classifications, organizational trees, and key personnel identification.
"""
from typing import Dict, Any, List

def classify_seniority(title: str) -> str:
    """
    Classifies a job title into seniority tiers:
    - 'executive': C-level, Founder, President, Managing Director, Partner, VP
    - 'management': Head of, Manager, Team Lead, General Manager, Supervisor
    - 'staff': Specialists, Engineers, Operations, Assistants, other individual contributors
    """
    t = (title or "").lower().strip()
    exec_keywords = [
        "ceo", "founder", "co-founder", "chief", "cto", "cfo", "cmo", "coo", "cio", "cro",
        "president", "managing director", "partner", "owner", "principal", "director", "board", "vp", "vice president"
    ]
    mgmt_keywords = [
        "head of", "head", "manager", "lead", "supervisor", "team lead", "general manager",
        "operations manager", "store manager", "regional", "coordinator"
    ]
    for kw in exec_keywords:
        if kw in t or t.startswith(kw):
            return "executive"
    for kw in mgmt_keywords:
        if kw in t or t.startswith(kw):
            return "management"
    return "staff"

def build_organization_tree(employees: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Groups employees into hierarchical tiers (executive, management, staff)."""
    tiers = {
        "executive": [],
        "management": [],
        "staff": []
    }
    for emp in employees:
        tier = emp.get("seniority_level") or classify_seniority(emp.get("title", ""))
        if tier not in tiers:
            tier = "staff"
        tiers[tier].append(emp)
        
    return {
        "total": len(employees),
        "tiers": tiers,
        "executive_count": len(tiers["executive"]),
        "management_count": len(tiers["management"]),
        "staff_count": len(tiers["staff"])
    }

def filter_key_personnel(employees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filters out only high-priority decision makers (executives & managers)."""
    return [
        emp for emp in employees
        if (emp.get("seniority_level") or classify_seniority(emp.get("title", ""))) in ("executive", "management")
    ]
