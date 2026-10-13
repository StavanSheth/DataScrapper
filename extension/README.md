# ⚡ Mavon Leads Scraper — Chrome Assistant Extension

A custom Chrome Extension (Manifest V3) purpose-built to accelerate and empower **Playwright automation** and manual inspection across Google Maps and visited business websites.

---

## 🎯 Core Features

1. **Automation Control & Acceleration for Playwright**:
   - Injects the `window.MavonScraper` controller into both Google Maps and shop websites.
   - `MavonScraper.scrollFeed(amount)`: Smoothly and reliably triggers the Maps feed infinite scroll.
   - `MavonScraper.getFeedPlaces()`: High-speed in-page DOM extraction of business cards without repeated CDP roundtrips.
   - `MavonScraper.clickPlace(identifier)`: Dispatches native simulated clicks directly on the card elements.
   - `MavonScraper.highlight(element, label)`: Renders high-tech glowing outlines (`#06b6d4` / `#6366f1`) so you can visually watch the agent inspect targets in real time.

2. **Visual Agent Head-Up Display (HUD)**:
   - Renders a floating status pill in the top-right corner of Chrome tabs (`⚡ MAVON AGENT: Active`).
   - Dynamically updates as the agent shifts between searching Maps and harvesting business details.

3. **In-Page Social Media & Email Harvester**:
   - `MavonScraper.extractSocialsAndEmails()`: Automatically scans DOM anchors, regex, and footers for Instagram, Facebook, LinkedIn, Twitter/X, and official contact emails.

4. **Anti-Bot & Automation Protection Bypass**:
   - Automatically masks `navigator.webdriver` on all visited pages.
   - `MavonScraper.detectAntiBot()`: Identifies Cloudflare, Turnstile, Datadome, PerimeterX, and Captchas on the fly.

5. **Extension Popup UI (`popup.html`)**:
   - Click the extension icon in the Chrome toolbar to access:
     - Active tab detector (Google Maps vs. Website).
     - One-click **Scroll Feed**.
     - One-click **Extract Places from Feed**.
     - One-click **Scan Socials & Emails**.
     - Direct launcher for the Mavon Leads Scraper Web Dashboard (`http://localhost:8080/`).

---

## 🚀 How to Install in Google Chrome

1. Open Google Chrome.
2. Navigate to `chrome://extensions/` in the URL bar.
3. Enable **Developer mode** toggle in the top-right corner.
4. Click **Load unpacked** button.
5. Select the directory:
   ```
   C:\Projects\Data Scrapper\extension
   ```
6. The extension **"Mavon Leads Scraper - Chrome Assistant"** is now active across all tabs!

---

## 🤖 Programmatic Usage with Playwright

Playwright automatically loads this extension via launch arguments:
```python
launch_args = [
    "--disable-extensions-except=C:/Projects/Data Scrapper/extension",
    "--load-extension=C:/Projects/Data Scrapper/extension",
]
```

Or injects the bridge script into any page context:
```python
await page.evaluate("() => window.MavonScraper.scrollFeed(900)")
places = await page.evaluate("() => window.MavonScraper.extractPlacesFromFeed()")
info = await page.evaluate("() => window.MavonScraper.extractSocialsAndEmails()")
```
