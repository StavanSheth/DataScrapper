import asyncio
import urllib.parse
from playwright.async_api import async_playwright

async def test_airbnb():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        city = "Mumbai"
        brand = "Villa"
        url = f"https://www.airbnb.com/s/{city}/homes?query={brand}"
        print(f"Navigating to {url}...")
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            print(f"Status: {resp.status if resp else 'No resp'}")
            await page.wait_for_timeout(3000)
            title = await page.title()
            print(f"Page title: {title}")
            print(f"Current url: {page.url}")
            
            # Check cards
            cards_count = await page.evaluate("""() => {
                const cards = document.querySelectorAll(
                    'div[data-testid="card-container"], a[href*="/rooms/"], div[itemprop="itemListElement"]'
                );
                return cards.length;
            }""")
            print(f"Cards found: {cards_count}")

            # Extract card details
            details = await page.evaluate(r"""() => {
                const containers = document.querySelectorAll('div[data-testid="card-container"]');
                const out = [];
                containers.forEach(c => {
                    const link = c.querySelector('a[href*="/rooms/"]');
                    const titleEl = c.querySelector('[data-testid="listing-card-title"], div[id^="title_"], [class*="t1jqs7"]');
                    const ratingEl = c.querySelector('[aria-label*="rating"], [aria-label*="star"], span[class*="r1dxllyb"]');
                    
                    let priceText = '';
                    c.querySelectorAll('span, div').forEach(el => {
                        const txt = (el.innerText || '').trim();
                        if (txt.match(/(?:[\$£€₹]|Rs\.?)\s*[\d,]+/i) && (!priceText || txt.length < priceText.length)) {
                            priceText = txt;
                        }
                    });

                    let titleText = titleEl ? titleEl.innerText : '';
                    if (!titleText && link) {
                        const aria = link.getAttribute('aria-label') || '';
                        titleText = aria.split(' - ')[0] || aria.split(' · ')[0] || aria;
                    }
                    
                    let ratingText = ratingEl ? (ratingEl.getAttribute('aria-label') || ratingEl.innerText || '') : '';
                    if (!ratingText) {
                        const m = (c.innerText || '').match(/(?:★|star|rating)?\s*(\d\.\d+)\s*(?:\((\d+)\))?/i);
                        if (m) ratingText = m[0];
                    }

                    out.push({
                        title: titleText.replace(/[\r\n]+/g, ' ').trim(),
                        link: link ? link.href.split('?')[0] : '',
                        rating: ratingText,
                        price: priceText
                    });
                });
                return out.slice(0, 5);
            }""")
            for i, d in enumerate(details):
                t = d['title'].encode('ascii', 'replace').decode('ascii')
                r = d['rating'].encode('ascii', 'replace').decode('ascii')
                p = d['price'].encode('ascii', 'replace').decode('ascii')
                print(f"Card {i+1}: title='{t}', link='{d['link']}', rating='{r}', price='{p}'")
        except Exception as e:
            print(f"Error: {repr(e)}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_airbnb())
