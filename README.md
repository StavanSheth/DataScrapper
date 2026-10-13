# Data Scrapper - Mavon Leads & Org Intelligence 🚀

A high-performance, multi-agent lead harvesting, business intelligence, and organizational hierarchy scraping suite. Features live interactive browser automation, Google Maps scraping, dedicated shop website inspection (emails, socials, anti-bot detection), LinkedIn organization intelligence, and a modern real-time Web Dashboard.

---

## 🌟 Key Features

1. **Multi-Agent Browser Automation**:
   - **Tab 1 (Google Maps Agent)**: Discovers businesses, categories, phone numbers, ratings, plus codes, and geocoordinates.
   - **Tab 2 (LinkedIn Org Intelligence Agent)**: Resolves verified corporate profiles, employee leadership hierarchies, executive tiers, and management structures.
   - **Tab 3 (On-Demand Shop Website Agent)**: Opens dynamically to inspect landing pages, extract emails (with Cloudflare email decoding), phone numbers, Instagram, Facebook, LinkedIn, Twitter, cookie consents, and anti-bot verification (Cloudflare, Datadome, Turnstile).

2. **Active Browser & Foreground Control**:
   - Runs live directly in your active Chrome window or launched instance with foreground window focus.
   - Chrome Extension Assistant (`extension/`) connects seamlessly via WebSocket (`/ws/extension`) and content script bridge.

3. **Interactive Geofencing & Map Controls**:
   - Search locations w.r.t map via address/landmark geocoding.
   - Live bidirectional editable Latitude and Longitude coordinate inputs.
   - 🎯 "My Location" GPS button and preset city chips.
   - Dynamic Haversine distance bounding radius (1 km - 50 km).

4. **Real-time Web Dashboard**:
   - Live screencast video frames from active Chrome tabs.
   - SQLite persistent database (`leads.db`) with automatic deduplication, sequential renumbering, and CSV/JSON export.
   - Live WebSocket event log stream and visual status monitors.

---

## 🛠️ Tech Stack

- **Backend**: FastAPI, Python 3.10+, WebSockets, Playwright, BeautifulSoup4
- **Frontend**: Vanilla CSS / JavaScript, Leaflet.js, OpenStreetMap
- **Browser Extension**: Manifest V3 Chrome Extension (`extension/`)
- **Database**: SQLite3 with WAL mode

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install fastapi uvicorn playwright beautifulsoup4
playwright install chromium
```

### 2. Start the Server
```bash
python app.py
```
Open [http://localhost:8080](http://localhost:8080) in your browser.

### 3. Load Chrome Extension (Optional, for Active Browser Automation)
1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and select the `extension/` folder in this repository.

---

## 📁 Repository Structure

```text
Data Scrapper/
├── app.py                     # FastAPI backend & WebSocket server
├── database.py                # SQLite lead database & hierarchy manager
├── runner_scraper.py          # Playwright multi-agent scraper engine
├── start_chrome_debug.bat     # Helper script to launch Chrome with CDP port 9222
├── extension/                 # Manifest V3 Chrome Extension Assistant
│   ├── background.js          # Service worker & multi-tab orchestrator
│   ├── content_script.js      # DOM assistant & dashboard message bridge
│   ├── injected_bridge.js     # Page-level anti-detection & DOM inspection HUD
│   └── manifest.json          # Extension configuration & permissions
├── static/                    # Web Dashboard frontend
│   ├── index.html             # Dashboard UI
│   ├── css/app.css            # Stylesheet
│   ├── js/app.js              # Frontend logic, Leaflet map, & WebSocket client
│   └── screenshots/           # Saved store landing page screenshots
└── google-maps-scraper/       # Core Go engine & scraper components
```

---

## 📄 License
MIT License
