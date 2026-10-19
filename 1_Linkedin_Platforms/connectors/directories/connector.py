"""
Cross-Platform Directory Connector.
Supports parsing proximity listings, total census counters, and card inspection
for Fresha, Airbnb, Yelp, TripAdvisor, Treatwell, and Justdial.
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger("directory_connector")

async def extract_platform_total_count(platform_page, platform_name: str) -> int:
    """Parses exact count badge rendered by directory platforms on proximity search."""
    try:
        return await platform_page.evaluate(r"""(p) => {
            const text = document.body.innerText || '';
            if (p === 'Airbnb') {
                const counter = document.querySelector('[data-testid="results-counter"], h1 span, [class*="results-counter"]');
                if (counter) {
                    const m = counter.innerText.match(/(\d[\d,]*)\s+(?:stays?|places?|homes?)/i);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
            } else if (p === 'Yelp') {
                const el = document.querySelector('[class*="pagination-results-count"], span.css-1122ukr');
                if (el) {
                    const m = el.innerText.match(/of\s+(\d[\d,]*)/i);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
            } else if (p === 'TripAdvisor') {
                const el = document.querySelector('.geos_widget_title, [class*="result-count"]');
                if (el) {
                    const m = el.innerText.match(/(\d[\d,]*)\s+(?:places?|properties|restaurants)/i);
                    if (m) return parseInt(m[1].replace(/,/g, ''));
                }
            }
            const gen = text.match(/\b(\d[\d,]*)\s+(?:results?|listings?|places?|venues?)\b/i);
            return gen ? parseInt(gen[1].replace(/,/g, '')) : 0;
        }""", platform_name)
    except Exception as e:
        logger.debug(f"Failed to extract platform total count for {platform_name}: {e}")
        return 0

async def extract_platform_listing_cards(platform_page, platform_name: str) -> List[Dict[str, Any]]:
    """Extracts candidate directory listing cards visible in the search viewport."""
    try:
        return await platform_page.evaluate(r"""(p) => {
            const cards = [];
            const seen = new Set();

            // 1. Target direct venue / listing links
            const candidateLinks = Array.from(document.querySelectorAll(
                'a[href*="/a/"], a[href*="/rooms/"], a[href*="/biz/"], a[href*="/Restaurant_Review-"], a[href*="/place/"]'
            ));

            for (const a of candidateLinks) {
                const url = a.href.split('?')[0];
                if (seen.has(url) || url.includes('/help') || url.includes('/user-flow') || url.includes('/download')) continue;

                // Walk up to card container with content
                let parent = a.parentElement;
                let cardText = '';
                for (let i = 0; i < 6; i++) {
                    if (parent && parent.innerText && parent.innerText.trim().length > 10) {
                        cardText = parent.innerText;
                        break;
                    }
                    if (parent) parent = parent.parentElement;
                }

                if (!cardText) continue;
                seen.add(url);

                const badgeWords = ['deals', 'featured', 'sponsored', 'ad', 'promoted', 'new', 'rating'];
                const lines = cardText.split('\n')
                    .map(l => l.trim())
                    .filter(l => l.length > 0 && !l.toLowerCase().includes('mi away') && !badgeWords.includes(l.toLowerCase()));
                const title = lines[0] || a.getAttribute('aria-label') || '';
                
                // Parse rating (e.g. 4.8)
                let rating = 0.0;
                const rMatch = cardText.match(/\b([1-5]\.[0-9])\b/);
                if (rMatch) rating = parseFloat(rMatch[1]);

                // Parse reviews count (e.g. 514 reviews or (21))
                let reviews = 0;
                const revMatch = cardText.match(/\b(\d[\d,]*)\s+reviews?\b/i) || cardText.match(/\((\d[\d,]*)\)/);
                if (revMatch) reviews = parseInt(revMatch[1].replace(/,/g, ''));

                // Parse price info if available
                let price = '';
                const priceMatch = cardText.match(/(\${1,4}|₹{1,4}|€{1,4}|£{1,4}|\bfrom\s+[\$₹€£]\d+)/i);
                if (priceMatch) price = priceMatch[0];

                if (title && title.length > 1 && !title.toLowerCase().includes('cookie') && !title.toLowerCase().includes('login')) {
                    cards.push({
                        title: title,
                        url: url,
                        rating: rating,
                        reviews_count: reviews,
                        price_info: price
                    });
                }
            }

            // 2. Fallback to generic card container query if no links found
            if (cards.length === 0) {
                const cardElements = document.querySelectorAll(
                    'div[data-testid="card-container"], div[data-qa="venue-card"], div[data-testid="serp-ia-card"], article, [role="article"], .listing_details'
                );
                for (const el of cardElements) {
                    const linkEl = el.querySelector('a[href*="/a/"], a[href*="/v/"], a[href*="/rooms/"], a[href*="/biz/"], a');
                    const titleEl = el.querySelector('h2, h3, [data-qa="venue-name"], [data-testid="title"], .listing-title') || linkEl;
                    const title = titleEl ? (titleEl.innerText || '').trim() : '';
                    const href = linkEl ? linkEl.href.split('?')[0] : '';
                    if (title && href && !seen.has(href)) {
                        seen.add(href);
                        cards.push({
                            title: title.split('\n')[0].trim(),
                            url: href,
                            rating: 0.0,
                            reviews_count: 0,
                            price_info: ''
                        });
                    }
                }
            }
            return cards;
        }""", platform_name)
    except Exception as e:
        logger.debug(f"Error extracting cards for {platform_name}: {e}")
        return []
