import asyncio
import json
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        print("Navigating to Fresha...")
        await page.goto("https://www.fresha.com/search?query=salon&address=London", wait_until="networkidle", timeout=30000)
        print("Page Title:", await page.title())
        print("Page URL  :", page.url)
        all_hrefs = await page.evaluate(r"""() => {
            return Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => h.includes('fresha.com'));
        }""")
        print(f"Total Fresha links found: {len(all_hrefs)}")
        print("Sample links:", all_hrefs[:10])
        
        venue_data = await page.evaluate(r"""() => {
            const links = Array.from(document.querySelectorAll('a[href*="/a/"]'));
            const cards = [];
            const seen = new Set();
            for (const a of links) {
                const url = a.href.split('?')[0];
                if (seen.has(url)) continue;
                seen.add(url);
                // Walk up to find card container with text
                let parent = a.parentElement;
                let cardText = '';
                for (let i = 0; i < 5; i++) {
                    if (parent && parent.innerText && parent.innerText.trim().length > 10) {
                        cardText = parent.innerText;
                        break;
                    }
                    if (parent) parent = parent.parentElement;
                }
                cards.push({
                    url: url,
                    text: cardText
                });
            }
            return cards.slice(0, 5);
        }""")
        for v in venue_data:
            print("Found venue card text:", v)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
