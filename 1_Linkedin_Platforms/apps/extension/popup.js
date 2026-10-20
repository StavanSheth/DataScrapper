// ==============================================================================
// DataScrapper Assistant - Popup Controller
// Fixed firmly to port 8085 (matching MessageV2 architecture).
// Active tab inspection, 1-click DOM extraction, and instant reconnect bridge.
// ==============================================================================

const BACKEND_PORT = 8085;
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/api/health`;
let currentTab = null;

const statusDot = document.getElementById("status-dot");
const serverText = document.getElementById("server-text");
const serverBadge = document.getElementById("server-badge");
const tabBadge = document.getElementById("tab-badge");
const tabTitle = document.getElementById("tab-title");
const tabUrl = document.getElementById("tab-url");
const consoleBody = document.getElementById("console-body");
const logStatus = document.getElementById("log-status");
const btnScrapeCurrent = document.getElementById("btn-scrape-current");
const btnExtractDirectory = document.getElementById("btn-extract-directory");
const btnSyncCookies = document.getElementById("btn-sync-cookies");
const dashboardLink = document.getElementById("dashboard-link");

function log(msg) {
  const t = new Date().toLocaleTimeString();
  consoleBody.innerText = `[${t}] ${msg}\n` + consoleBody.innerText.slice(0, 500);
}

// 1. Initialize Connection (Purge any legacy port overrides)
async function initBackendConnection() {
  try {
    await chrome.storage.local.remove(["backendPort"]);
  } catch (e) {}

  serverText.innerText = `:${BACKEND_PORT}`;
  dashboardLink.href = `http://localhost:${BACKEND_PORT}/`;
  dashboardLink.querySelector("span").innerText = `Open Live Dashboard (:${BACKEND_PORT})`;

  await checkHealth();
}

async function checkHealth() {
  try {
    // 1. Ask background service worker for live WS connection status
    const bgStatus = await new Promise(resolve => {
      chrome.runtime.sendMessage({ type: "GET_STATUS" }, res => {
        if (chrome.runtime.lastError || !res) resolve(null);
        else resolve(res);
      });
    });

    if (bgStatus && bgStatus.connected) {
      statusDot.className = "status-dot online";
      logStatus.innerText = "Online & Connected";
      logStatus.style.color = "#10b981";
      log(`Connected to DataScrapper Bridge on :${BACKEND_PORT}`);
      return true;
    }

    // 2. Direct HTTP probe
    const res = await fetch(HEALTH_URL, {
      cache: "no-store",
      headers: { "Accept": "application/json" }
    });
    if (res.ok) {
      statusDot.className = "status-dot online";
      logStatus.innerText = "Backend Active (Connecting WS...)";
      logStatus.style.color = "#38bdf8";
      log(`Backend reachable on :${BACKEND_PORT}. Reconnecting WebSocket...`);
      chrome.runtime.sendMessage({ type: "RECONNECT" }, () => {});
      return true;
    }
  } catch (e) {}

  statusDot.className = "status-dot";
  logStatus.innerText = "Offline";
  logStatus.style.color = "#f43f5e";
  log(`Backend offline on :${BACKEND_PORT}. Run 'py apps/api/src/server.py'`);
  return false;
}

// 2. Click on Badge triggers Reconnect probe
serverBadge.addEventListener("click", async () => {
  log("Manual reconnect triggered...");
  statusDot.className = "status-dot";
  logStatus.innerText = "Reconnecting...";
  chrome.runtime.sendMessage({ type: "RECONNECT" }, () => {
    setTimeout(checkHealth, 500);
  });
});

// 3. Inspect Current Active Tab
async function inspectActiveTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    currentTab = tab;

    tabTitle.innerText = tab.title || "Untitled Tab";
    tabUrl.innerText = tab.url || "about:blank";

    const u = (tab.url || "").toLowerCase();
    if (u.includes("fresha.com")) {
      tabBadge.innerText = "Fresha Directory";
      tabBadge.style.color = "#c084fc";
    } else if (u.includes("airbnb.")) {
      tabBadge.innerText = "Airbnb Stays";
      tabBadge.style.color = "#f43f5e";
    } else if (u.includes("yelp.")) {
      tabBadge.innerText = "Yelp Directory";
      tabBadge.style.color = "#ef4444";
    } else if (u.includes("tripadvisor.")) {
      tabBadge.innerText = "TripAdvisor";
      tabBadge.style.color = "#10b981";
    } else if (u.includes("linkedin.com")) {
      tabBadge.innerText = "LinkedIn";
      tabBadge.style.color = "#0ea5e9";
    } else if (u.includes("google.com/maps") || u.includes("/maps/")) {
      tabBadge.innerText = "Google Maps";
      tabBadge.style.color = "#3b82f6";
    } else {
      tabBadge.innerText = "Web Page";
      tabBadge.style.color = "#94a3b8";
    }
  } catch (err) {
    tabTitle.innerText = "Could not inspect tab";
  }
}

// 4. One-Click Scrape Handler
btnScrapeCurrent.addEventListener("click", async () => {
  if (!currentTab || !currentTab.id) return;
  btnScrapeCurrent.disabled = true;
  document.getElementById("btn-scrape-text").innerText = "Scraping Active Page...";
  log(`Executing DOM extraction on tab #${currentTab.id}...`);

  try {
    chrome.tabs.sendMessage(currentTab.id, { action: "EXTRACT_PAGE_DATA" }, async (response) => {
      btnScrapeCurrent.disabled = false;
      document.getElementById("btn-scrape-text").innerText = "1-Click Scrape Active Page";

      if (chrome.runtime.lastError || !response) {
        log(`Injecting extractor into page directly...`);
        chrome.scripting.executeScript({
          target: { tabId: currentTab.id },
          func: () => {
            const title = document.title;
            const url = window.location.href;
            const emails = Array.from(new Set(
              (document.body.innerText.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g) || [])
            )).filter(e => !e.endsWith(".png") && !e.endsWith(".jpg"));
            const phones = Array.from(new Set(
              (document.body.innerText.match(/(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}/g) || [])
            )).filter(p => p.replace(/\D/g, "").length >= 7);

            return { title, url, emails, phones };
          }
        }, async (results) => {
          if (results && results[0] && results[0].result) {
            const data = results[0].result;
            log(`Extracted: ${data.title}`);
            log(`Found ${data.emails.length} emails, ${data.phones.length} phones.`);
            await syncToBackend(data);
          } else {
            log("No data found or page restricted.");
          }
        });
      } else {
        log(`Extraction succeeded: ${JSON.stringify(response.title || "Done")}`);
      }
    });
  } catch (e) {
    btnScrapeCurrent.disabled = false;
    document.getElementById("btn-scrape-text").innerText = "1-Click Scrape Active Page";
    log(`Error scraping page: ${e.message}`);
  }
});

// 5. Directory Card Scraper Handler
btnExtractDirectory.addEventListener("click", async () => {
  if (!currentTab || !currentTab.id) return;
  log("Extracting directory cards from active viewport...");
  
  chrome.scripting.executeScript({
    target: { tabId: currentTab.id },
    func: () => {
      const cards = [];
      const links = Array.from(document.querySelectorAll('a[href*="/a/"], a[href*="/rooms/"], a[href*="/biz/"], a[href*="/Restaurant_Review-"]'));
      const seen = new Set();
      for (const a of links) {
        const u = a.href.split("?")[0];
        if (seen.has(u) || u.includes("/help") || u.includes("/download")) continue;
        let parent = a.parentElement;
        let text = "";
        for (let i = 0; i < 6; i++) {
          if (parent && parent.innerText && parent.innerText.trim().length > 10) {
            text = parent.innerText;
            break;
          }
          if (parent) parent = parent.parentElement;
        }
        if (!text) continue;
        seen.add(u);
        const lines = text.split("\n").map(l => l.trim()).filter(l => l.length > 0 && !["deals", "featured", "sponsored", "new"].includes(l.toLowerCase()));
        const rMatch = text.match(/\b([1-5]\.[0-9])\b/);
        const revMatch = text.match(/\b(\d[\d,]*)\s+reviews?\b/i) || text.match(/\((\d[\d,]*)\)/);
        cards.push({
          title: lines[0] || a.getAttribute("aria-label") || "Listing",
          url: u,
          rating: rMatch ? parseFloat(rMatch[1]) : 0.0,
          reviews_count: revMatch ? parseInt(revMatch[1].replace(/,/g, "")) : 0
        });
      }
      return cards;
    }
  }, async (results) => {
    if (results && results[0] && results[0].result) {
      const cards = results[0].result;
      log(`Found ${cards.length} directory listings on page!`);
      if (cards.length > 0) {
        log(`Sample #1: ${cards[0].title} (${cards[0].rating}★)`);
        await syncDirectoryCardsToBackend(cards);
      }
    } else {
      log("No directory cards identified in active viewport.");
    }
  });
});

// 6. Sync Directory Cards to Backend
async function syncDirectoryCardsToBackend(cards) {
  try {
    let saved = 0;
    for (const c of cards.slice(0, 10)) {
      const res = await fetch(`http://127.0.0.1:${BACKEND_PORT}/api/platforms`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "save_listing",
          listing: {
            platform: tabBadge.innerText.split(" ")[0] || "Directory",
            title: c.title,
            clean_brand: c.title.replace(/\s+(LLC|Inc|Pvt|Branch).*$/i, "").trim(),
            category: "Scraped",
            url: c.url,
            booking_url: c.url,
            rating: c.rating,
            reviews_count: c.reviews_count,
            website_status: "captured"
          }
        })
      });
      if (res.ok) saved++;
    }
    log(`Saved ${saved} directory cards into SQLite leads.db!`);
  } catch (err) {
    log(`Failed to sync to backend: ${err.message}`);
  }
}

// 7. Sync General Lead to Backend
async function syncToBackend(data) {
  try {
    const res = await fetch(`http://127.0.0.1:${BACKEND_PORT}/api/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: data.title,
        website: data.url,
        email: data.emails && data.emails[0] ? data.emails[0] : "",
        emails_json: JSON.stringify(data.emails || []),
        phone: data.phones && data.phones[0] ? data.phones[0] : "",
        website_status: data.emails.length > 0 ? "Contacts Found" : "No Contacts Found"
      })
    });
    if (res.ok) {
      log("Saved page record to leads.db!");
    }
  } catch (err) {
    log(`Sync error: ${err.message}`);
  }
}

// 8. LinkedIn Cookie Sync
btnSyncCookies.addEventListener("click", async () => {
  log("Harvesting LinkedIn session cookies...");
  try {
    const cookies = await chrome.cookies.getAll({ domain: "linkedin.com" });
    if (!cookies || cookies.length === 0) {
      log("No active LinkedIn cookies found. Log into LinkedIn first.");
      return;
    }
    log(`Found ${cookies.length} LinkedIn cookies. Sending to bridge...`);
    chrome.runtime.sendMessage({ action: "SYNC_LINKEDIN_COOKIES", cookies }, (resp) => {
      log("LinkedIn cookies synchronized with backend!");
    });
  } catch (e) {
    log(`Cookie harvest error: ${e.message}`);
  }
});

// Run Initialization
document.addEventListener("DOMContentLoaded", async () => {
  await initBackendConnection();
  await inspectActiveTab();
  setInterval(checkHealth, 3000);
});
