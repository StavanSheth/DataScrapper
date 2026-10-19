"""
Employee Repository.
Manages persistent organization personnel, seniority tiers, and LinkedIn intelligence.
"""
import logging
from typing import Dict, Any, List, Optional
import sqlite3

from packages.database.src.adapters.sqlite.connection import get_connection

logger = logging.getLogger("employee_repository")

def classify_seniority(title: str) -> str:
    """Classifies a job title into seniority tiers: executive, management, or staff."""
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

def save_employees_batch(
    company_name: str,
    employees: List[Dict[str, Any]],
    lead_id: Optional[int] = None,
    company_linkedin_url: str = "",
    linkedin_status: str = "",
    db_path: Optional[str] = None
) -> int:
    """Save a batch of employees, updating lead count and LinkedIn URL in leads table."""
    if not company_name:
        return 0

    company_linkedin_url = clean_linkedin_url(company_linkedin_url)
    if not company_linkedin_url and employees:
        for emp in employees:
            purl = clean_linkedin_url(emp.get("linkedin_profile_url", ""))
            if purl and "/in/" in purl:
                company_linkedin_url = purl
                break

    saved_count = 0
    with get_connection(db_path) as conn:
        if not isinstance(lead_id, int):
            lead_id = None
        if not lead_id:
            row = conn.execute(
                "SELECT id FROM leads WHERE lower(trim(name)) = lower(trim(?)) ORDER BY id ASC LIMIT 1",
                (company_name,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id FROM leads WHERE lower(name) LIKE ? ORDER BY id ASC LIMIT 1",
                    (f"%{company_name.lower()}%",)
                ).fetchone()
            if row:
                lead_id = row[0]

        if employees:
            for emp in employees:
                fname = str(emp.get("full_name", "")).strip()
                title = str(emp.get("title", "")).strip()
                if not fname:
                    continue
                seniority = emp.get("seniority_level") or classify_seniority(title)
                purl = clean_linkedin_url(str(emp.get("linkedin_profile_url", "")).strip())
                em = str(emp.get("email", "")).strip()
                loc = str(emp.get("location", "")).strip()
                av = str(emp.get("avatar_url", "")).strip()

                try:
                    conn.execute("""
                        INSERT INTO employees (lead_id, company_name, full_name, title, seniority_level, linkedin_profile_url, email, location, avatar_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(company_name, full_name, title) DO UPDATE SET
                            seniority_level = excluded.seniority_level,
                            linkedin_profile_url = CASE WHEN excluded.linkedin_profile_url != '' THEN excluded.linkedin_profile_url ELSE employees.linkedin_profile_url END,
                            email = CASE WHEN excluded.email != '' THEN excluded.email ELSE employees.email END,
                            location = CASE WHEN excluded.location != '' THEN excluded.location ELSE employees.location END,
                            avatar_url = CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE employees.avatar_url END
                    """, (lead_id, company_name, fname, title, seniority, purl, em, loc, av))
                    saved_count += 1
                except Exception as e:
                    logger.debug(f"Error inserting employee {fname}: {e}")

        total_emp_row = conn.execute("SELECT COUNT(*) FROM employees WHERE company_name = ?", (company_name,)).fetchone()
        total_emp = total_emp_row[0] if total_emp_row else 0

        if not linkedin_status:
            if company_linkedin_url and "/company/" in company_linkedin_url:
                linkedin_status = "verified"
            elif total_emp > 0 or (company_linkedin_url and "/in/" in company_linkedin_url):
                linkedin_status = "personnel_verified"
            elif company_linkedin_url:
                linkedin_status = "verified"
            else:
                linkedin_status = "no_profile"

        try:
            conn.execute("""
                UPDATE leads SET
                    employee_count = ?,
                    org_scraped = 1,
                    linkedin = CASE WHEN ? != '' THEN ? ELSE linkedin END,
                    linkedin_url = CASE WHEN ? != '' THEN ? ELSE linkedin_url END,
                    linkedin_status = ?
                WHERE name = ? OR (id = ? AND ? IS NOT NULL)
            """, (str(total_emp), company_linkedin_url, company_linkedin_url, company_linkedin_url, company_linkedin_url, linkedin_status, company_name, lead_id, lead_id))
        except Exception:
            pass

        conn.commit()
    return saved_count

def get_company_hierarchy(company_name: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Returns the organization tree for a company grouped by seniority: executive, management, staff."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, title, seniority_level, linkedin_profile_url, email, location, avatar_url
            FROM employees
            WHERE company_name = ?
            ORDER BY
                CASE seniority_level
                    WHEN 'executive' THEN 1
                    WHEN 'management' THEN 2
                    ELSE 3
                END,
                full_name ASC
        """, (company_name,))
        rows = [dict(r) for r in cursor.fetchall()]

        lead_row = None
        try:
            lead_row = conn.execute(
                "SELECT id, name, category, website, linkedin, employee_count FROM leads WHERE name = ? LIMIT 1",
                (company_name,)
            ).fetchone()
        except Exception:
            pass

        company_info = dict(lead_row) if lead_row else {"name": company_name}

        return {
            "company": company_name,
            "info": company_info,
            "total_employees": len(rows),
            "tiers": {
                "executive": [r for r in rows if r["seniority_level"] == "executive"],
                "management": [r for r in rows if r["seniority_level"] == "management"],
                "staff": [r for r in rows if r["seniority_level"] == "staff"],
            },
            "all_employees": rows
        }

def get_employees_by_lead_id(lead_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all personnel records associated with a specific lead_id."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT id, lead_id, company_name, full_name, title, seniority_level, linkedin_profile_url, email, location, avatar_url, created_at
            FROM employees
            WHERE lead_id = ?
            ORDER BY
                CASE seniority_level
                    WHEN 'executive' THEN 1
                    WHEN 'management' THEN 2
                    ELSE 3
                END,
                full_name ASC
        """, (lead_id,)).fetchall()
        return [dict(r) for r in rows]

def get_pending_linkedin_leads(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches leads with a valid website that are still pending LinkedIn inspection."""
    with get_connection(db_path) as conn:
        try:
            rows = conn.execute("""
                SELECT id, name, address, website, linkedin, linkedin_url
                FROM leads
                WHERE (linkedin_status = 'pending' OR linkedin_status IS NULL OR linkedin_status = '')
                  AND (org_scraped = 0 OR org_scraped IS NULL)
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []
