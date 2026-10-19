"""
LinkedIn Professional Network Connector.
Extracts individual personnel profiles, company directory search matches, and handles session cookie injection.
"""
import json
import logging
import os
import urllib.parse
from typing import Dict, Any, List, Optional

logger = logging.getLogger("linkedin_connector")

async def inject_linkedin_cookies(context, cookies_path: str) -> int:
    """Injects saved LinkedIn session cookies into the Playwright browser context."""
    if not os.path.exists(cookies_path):
        return 0
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            raw_cookies = json.load(f)
            pw_cookies = []
            for c in raw_cookies:
                name = c.get("name")
                value = c.get("value")
                if not name or value is None:
                    continue
                pw_cookies.append({
                    "name": name,
                    "value": value,
                    "domain": c.get("domain", ".linkedin.com"),
                    "path": c.get("path", "/"),
                    "secure": c.get("secure", True),
                    "httpOnly": c.get("httpOnly", False),
                })
            if pw_cookies:
                await context.add_cookies(pw_cookies)
                return len(pw_cookies)
    except Exception as e:
        logger.warning(f"Failed to inject LinkedIn cookies from {cookies_path}: {e}")
    return 0

async def extract_single_linkedin_profile(page) -> Optional[Dict[str, Any]]:
    """Extracts profile details from an individual LinkedIn profile (/in/<username>)."""
    try:
        return await page.evaluate(r"""() => {
            const nameEl = document.querySelector('h1.inline.t-24.v-align-middle, h1.text-heading-xlarge, h1');
            const titleEl = document.querySelector('.text-body-medium.break-words, div[data-generated-suggestion-target], .pv-text-details__left-panel div.text-body-medium');
            const locEl = document.querySelector('span.text-body-small.inline.t-black--light.break-words, .pv-text-details__left-panel span.text-body-small');
            const imgEl = document.querySelector('img.pv-top-card-profile-picture__image, img[data-view-name="profile-card"], img.presence-entity__image');
            
            let rawName = nameEl ? (nameEl.innerText || nameEl.textContent || "").trim() : "";
            let rawTitle = titleEl ? (titleEl.innerText || titleEl.textContent || "").trim() : "";
            let loc = locEl ? (locEl.innerText || locEl.textContent || "").trim() : "";
            let avatar = imgEl ? imgEl.src : "";
            
            let cleanName = rawName.replace(/•\s*(1st|2nd|3rd\+?|Following|Follow)/gi, '').replace(/\(He\/Him\)|\(She\/Her\)|\(They\/Them\)/gi, '').trim();
            let cleanTitle = rawTitle.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
            
            if (cleanName && cleanName !== "LinkedIn Member" && cleanName.length > 2) {
                return {
                    full_name: cleanName,
                    title: cleanTitle || "Key Personnel",
                    linkedin_profile_url: window.location.href.split('?')[0].replace(/\/+$/, ''),
                    avatar_url: avatar,
                    location: loc
                };
            }
            return null;
        }""")
    except Exception as e:
        logger.debug(f"Error evaluating single linkedin profile: {e}")
        return None

async def search_company_directory(page, candidate_queries: List[str]) -> Optional[Dict[str, str]]:
    """Searches corporate LinkedIn directory for candidate company names and returns verified company profile."""
    for cand_query in candidate_queries:
        if not cand_query:
            continue
        encoded_cand = urllib.parse.quote(cand_query)
        search_co_url = f"https://www.linkedin.com/search/results/companies/?keywords={encoded_cand}"
        try:
            await page.goto(search_co_url, wait_until="domcontentloaded", timeout=15000)
            try:
                await page.wait_for_selector(
                    '.entity-result, li.reusable-search__result-container, .search-results-container, div[data-view-name]',
                    timeout=4000
                )
            except Exception:
                await page.wait_for_timeout(1000)

            li_result = await page.evaluate(r"""() => {
                const companyLinks = document.querySelectorAll('a[href*="/company/"]:not([href*="ads"]):not([href*="linkedin.com/help"])');
                for (const link of companyLinks) {
                    const href = link.href.split('?')[0].replace(/\/+$/, '');
                    if (href.includes('/company/') && !href.includes('/company/setup') && !href.includes('/search') && !href.includes('/feed')) {
                        const container = link.closest('.entity-result, li, div[data-view-name], .artdeco-entity-lockup, div.search-results-container') || link;
                        const titleEl = container.querySelector('.entity-result__title-text, .app-aware-link, .artdeco-entity-lockup__title, span[aria-hidden="true"], h2, h3, a') || link;
                        const rawTitle = titleEl.innerText || titleEl.textContent || "";
                        const title = rawTitle.split('\n')[0].replace(/•.*/, '').trim();
                        if (title && href.split('/company/')[1]) {
                            return { href, title };
                        }
                    }
                }
                return null;
            }""")
            if li_result and isinstance(li_result, dict):
                return li_result
        except Exception as e:
            logger.debug(f"LinkedIn search failed for '{cand_query}': {e}")
            continue
    return None
