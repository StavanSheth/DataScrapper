"""
LinkedIn Workforce & Organizational Intelligence Agent (Agent 3).
Resolves corporate identities, inspects key personnel, classifies seniority tiers,
and saves organization rosters into the database.
"""
import asyncio
import logging
import urllib.parse
from typing import Dict, Any, Optional

from connectors.professional_networks.connector import (
    extract_single_linkedin_profile,
    search_company_directory,
    inject_linkedin_cookies
)
from packages.database.src.repositories.employee_repository import save_employees_batch
from backend.src.datascrapper.modules.normalization.brand_cleaner import (
    clean_brand_tokens,
    clean_linkedin_url,
    extract_brand_from_domain
)
from backend.src.datascrapper.modules.employees.services import classify_seniority

logger = logging.getLogger("professional_discovery_agent")

async def linkedin_worker(
    tab_page,
    queue: asyncio.Queue,
    done_event: asyncio.Event,
    emit_event_fn=None,
    db_path: Optional[str] = None
):
    """
    Dedicated Worker for Tab 3: Navigates company LinkedIn profiles in active Chrome session,
    extracts the employee roster, classifies job roles into seniority tiers,
    and saves the full organization hierarchy into the database.
    """
    def emit(event_type: str, data: Any):
        if emit_event_fn:
            emit_event_fn(event_type, data)
        else:
            logger.info(f"[{event_type}] {data}")

    while not done_event.is_set() or not queue.empty():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except Exception:
            break

        idx = item.get("index", 1)
        name = item.get("name", "").strip()
        address = item.get("address", "")
        website_url = item.get("website", "")
        known_linkedin = item.get("linkedin_url", "")
        lead_id = item.get("lead_id")

        if not name:
            queue.task_done()
            continue

        core_brand = clean_brand_tokens(name)
        domain_brand = extract_brand_from_domain(website_url)

        emit("log", f"💼 [Agent 3: LinkedIn] Resolving verified LinkedIn profile for #{idx} '{name}' (Brand: '{core_brand}')...")
        emit("status", f"Resolving LinkedIn profile: {core_brand}")

        try:
            verified_company_url = None
            known_person_url = None
            
            if known_linkedin:
                clean_base = clean_linkedin_url(known_linkedin)
                if clean_base and "/company/" in clean_base:
                    verified_company_url = clean_base
                    emit("log", f"🔗 [Agent 3: LinkedIn] Using verified corporate LinkedIn URL: {verified_company_url}")
                elif clean_base and "/in/" in clean_base:
                    known_person_url = clean_base
                    emit("log", f"👤 [Agent 3: LinkedIn] Detected key personnel profile from website: {known_person_url}")

            if not verified_company_url:
                search_candidates = []
                if core_brand and core_brand.lower() != name.lower():
                    search_candidates.append(core_brand)
                search_candidates.append(name)
                if domain_brand and len(domain_brand) >= 3 and domain_brand.lower() not in [c.lower() for c in search_candidates]:
                    search_candidates.append(domain_brand)

                match_result = await search_company_directory(tab_page, search_candidates)
                if match_result and isinstance(match_result, dict):
                    verified_company_url = match_result.get("href")
                    matched_title = match_result.get("title", "")
                    emit("log", f"🎯 [Agent 3: LinkedIn] Matched corporate LinkedIn company: '{matched_title}' ({verified_company_url})")

            employees_extracted = []

            # Case A: Found Corporate Company Profile -> Extract People Directory
            if verified_company_url:
                people_url = f"{verified_company_url}/people/"
                emit("log", f"👥 [Agent 3: LinkedIn] Crawling workforce roster at: {people_url}")
                emit("linkedin_navigated", {"url": people_url, "name": name})
                
                try:
                    await tab_page.goto(people_url, wait_until="domcontentloaded", timeout=15000)
                    try:
                        await tab_page.wait_for_selector(
                            '.org-people-profile-card__profile-card-spacing, li.grid__col--lg-12, div[data-view-name="profile-card"]',
                            timeout=5000
                        )
                    except Exception:
                        await tab_page.wait_for_timeout(1000)

                    # Smooth scroll to trigger lazy-loaded employee cards
                    for _ in range(3):
                        await tab_page.evaluate("window.scrollBy(0, 800)")
                        await tab_page.wait_for_timeout(600)

                    extracted_people = await tab_page.evaluate(r"""() => {
                        const results = [];
                        const cards = document.querySelectorAll(
                            '.org-people-profile-card__profile-card-spacing, li.grid__col--lg-12, div[data-view-name="profile-card"], .artdeco-entity-lockup'
                        );
                        for (const c of cards) {
                            const nameEl = c.querySelector('.org-people-profile-card__profile-title, .artdeco-entity-lockup__title, h3, a');
                            const subEl = c.querySelector('.artdeco-entity-lockup__subtitle, .org-people-profile-card__profile-subtitle, div.lt-line-clamp');
                            const linkEl = c.querySelector('a[href*="/in/"]');
                            const imgEl = c.querySelector('img');
                            
                            const rawName = nameEl ? (nameEl.innerText || nameEl.textContent || '').trim() : '';
                            const cleanName = rawName.replace(/•\s*(1st|2nd|3rd\+?|Following|Follow)/gi, '').replace(/\(He\/Him\)|\(She\/Her\)/gi, '').trim();
                            const title = subEl ? (subEl.innerText || subEl.textContent || '').trim() : 'Staff';
                            const profileUrl = linkEl ? linkEl.href.split('?')[0].replace(/\/+$/, '') : '';
                            const avatar = imgEl ? imgEl.src : '';
                            
                            if (cleanName && cleanName !== 'LinkedIn Member' && cleanName.length > 2) {
                                results.push({
                                    full_name: cleanName,
                                    title: title.replace(/[\r\n]+/g, ' ').trim(),
                                    linkedin_profile_url: profileUrl,
                                    avatar_url: avatar
                                });
                            }
                        }
                        return results;
                    }""")
                    
                    if extracted_people and isinstance(extracted_people, list):
                        employees_extracted.extend(extracted_people)
                        emit("log", f"✨ [Agent 3: LinkedIn] Successfully captured {len(extracted_people)} personnel for '{name}'.")
                except Exception as pe:
                    emit("log", f"⚠️ [Agent 3: LinkedIn] Could not inspect /people/ directory: {pe}")

            # Case B: Key personnel profile link from website
            elif known_person_url:
                emit("log", f"👤 [Agent 3: LinkedIn] Navigating individual personnel profile: {known_person_url}")
                emit("linkedin_navigated", {"url": known_person_url, "name": name})
                try:
                    await tab_page.goto(known_person_url, wait_until="domcontentloaded", timeout=12000)
                    p_info = await extract_single_linkedin_profile(tab_page)
                    if p_info:
                        employees_extracted.append(p_info)
                        emit("log", f"👤 [Agent 3: LinkedIn] Verified personnel: {p_info['full_name']} ({p_info['title']})")
                except Exception as ie:
                    emit("log", f"⚠️ [Agent 3: LinkedIn] Failed to extract key person: {ie}")

            # Save batch to database
            if employees_extracted or verified_company_url:
                saved_count = save_employees_batch(
                    company_name=name,
                    employees=employees_extracted,
                    lead_id=lead_id,
                    company_linkedin_url=verified_company_url or known_person_url or "",
                    db_path=db_path
                )
                emit("employees_saved", {
                    "company": name,
                    "count": saved_count,
                    "linkedin_url": verified_company_url or known_person_url or ""
                })
            else:
                emit("log", f"ℹ️ [Agent 3: LinkedIn] No verified LinkedIn company or personnel found for '{name}'.")

        except Exception as e:
            emit("log", f"❌ [Agent 3: LinkedIn] Error processing #{idx} '{name}': {e}")
        finally:
            queue.task_done()
