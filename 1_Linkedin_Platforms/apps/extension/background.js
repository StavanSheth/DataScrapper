// ==============================================================================
// Mavon Leads Scraper - Background Service Worker (Manifest V3)
// Chrome Automation Bridge & Multi-Tab Orchestrator
// Connects live active Chrome with Dashboard, opens Maps & LinkedIn tabs,
// opens Shop Website tab on-demand, and streams live screencast frames.
// ==============================================================================

let BACKEND_PORT = 8085;

function updateBadge(connected) {
  try {
    if (chrome.action && chrome.action.setBadgeText) {
      if (connected) {
        chrome.action.setBadgeText({ text: "ON" });
        chrome.action.setBadgeBackgroundColor({ color: "#059669" });
        chrome.action.setTitle({ title: `DataScrapper Bridge (:${BACKEND_PORT}) — Connected & Ready` });
      } else {
        chrome.action.setBadgeText({ text: "OFF" });
        chrome.action.setBadgeBackgroundColor({ color: "#6b7280" });
        chrome.action.setTitle({ title: `DataScrapper Bridge (:${BACKEND_PORT}) — Offline / Reconnecting` });
      }
    }
  } catch (e) {
    // Ignore badge updates in worker headless mode
  }
}

async function getActiveBackendPort() {
  try {
    const s = await chrome.storage.local.get(["backendPort"]);
    if (s && s.backendPort) return parseInt(s.backendPort, 10);
  } catch (e) {}
  return 8085;
}

function getWsUrl() {
  return `ws://127.0.0.1:${BACKEND_PORT}/ws/extension`;
}

function getHealthUrl() {
  return `http://127.0.0.1:${BACKEND_PORT}/api/health`;
}

function getApiUrl(path) {
  return `http://127.0.0.1:${BACKEND_PORT}${path}`;
}

let ws = null;
let reconnectTimer = null;
let isConnecting = false;

// Automation Tab IDs
let mapsTabId = null;
let linkedinTabId = null;
let shopTabId = null;
let platformTabId = null;
let lastStartHarvesterTime = 0;
const attachedDebuggerTabs = new Set();

// Harvester state (Global so ABORT_HARVESTER immediately controls running loops across commands)
let isHarvesting = false;
let isMapsHarvesting = false;
let isWebsiteHarvesting = false;
let isPlatformHarvesting = false;
let isLinkedinHarvesting = false;
let abortHarvester = false;
const exploredDomainsCache = new Map();

// Check if backend is reachable before opening WebSocket
async function isBackendReachable() {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1200);
    const res = await fetch(getHealthUrl(), {
      method: "GET",
      cache: "no-store",
      headers: { "Accept": "application/json" },
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    return res.ok;
  } catch (e) {
    return false;
  }
}

// Sync user's real LinkedIn cookies with backend to preserve authenticated login
async function syncLinkedInCookies() {
  if (!chrome.cookies) return;
  try {
    const cookies = await chrome.cookies.getAll({ domain: "linkedin.com" });
    if (cookies && cookies.length > 0 && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "SYNC_COOKIES",
        domain: "linkedin.com",
        cookies: cookies.map(c => ({
          name: c.name,
          value: c.value,
          domain: c.domain,
          path: c.path,
          expires: c.expirationDate || -1,
          httpOnly: Boolean(c.httpOnly),
          secure: Boolean(c.secure),
          sameSite: c.sameSite === "no_restriction" ? "None" : (c.sameSite === "lax" ? "Lax" : "Strict")
        }))
      }));
      console.log(`[Mavon Extension] Synced ${cookies.length} LinkedIn session cookies to backend!`);
    }
  } catch (err) {
    console.warn("[Mavon Extension] Cookie sync catch:", err);
  }
}

// Connect to Dashboard WebSocket
async function connect() {
  if (isConnecting) return;
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return;
  }

  isConnecting = true;
  try {
    BACKEND_PORT = await getActiveBackendPort();
    const reachable = await isBackendReachable();
    if (!reachable) {
      updateBadge(false);
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
      return;
    }

    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return;
    }

    console.log("[DataScrapper Extension] Connecting to Dashboard WebSocket at", getWsUrl());
    ws = new WebSocket(getWsUrl());

    ws.onopen = () => {
      console.log("[DataScrapper Extension] Connected to DataScrapper Dashboard on port " + BACKEND_PORT + "!");
      updateBadge(true);
      ws.send(JSON.stringify({
        type: "HELLO",
        payload: { client: "chrome_extension", version: "3.1.0" }
      }));
      syncLinkedInCookies().catch(() => {});
    };

    ws.onmessage = async (event) => {
      let data = null;
      try {
        data = JSON.parse(event.data);
        console.log("[Mavon Extension] Received command:", data.action, data);
        const res = await handleCommand(data);
        if (ws && ws.readyState === WebSocket.OPEN && data.id) {
          ws.send(JSON.stringify({
            id: data.id,
            action: data.action,
            ...res
          }));
        }
      } catch (err) {
        console.warn("[Mavon Extension] Error handling message:", err);
        if (data && data.id && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ id: data.id, success: false, error: String(err) }));
        }
      }
    };

    ws.onerror = (e) => {
      console.log("[Mavon Extension] WS state:", ws ? ws.readyState : "null");
    };

    ws.onclose = () => {
      console.log("[Mavon Extension] Disconnected from Dashboard, retrying in 3s...");
      updateBadge(false);
      ws = null;
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };
  } catch (err) {
    console.debug("[Mavon Extension] Connection probe catch:", err);
    updateBadge(false);
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 4000);
  } finally {
    isConnecting = false;
  }
}

// Keep service worker alive
try {
  if (chrome.alarms) {
    chrome.alarms.create("keepAlive", { periodInMinutes: 0.3 });
    chrome.alarms.onAlarm.addListener(() => {
      connect();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "PING" }));
        syncLinkedInCookies().catch(() => {});
      }
    });
  }
} catch (e) {}

// Initial connection
connect();

// Focus browser window and maintain maximized state without shrinking
async function bringWindowToFront(windowId) {
  try {
    const targetId = windowId || (await chrome.windows.getCurrent().catch(() => null))?.id;
    if (targetId) {
      const win = await chrome.windows.get(targetId).catch(() => null);
      const updateInfo = { focused: true };
      if (win && win.state !== "fullscreen") {
        updateInfo.state = "maximized";
      }
      await chrome.windows.update(targetId, updateInfo);
    }
  } catch (e) {}
}

// Screencast attachment using chrome.debugger
async function ensureScreencastForTab(tabId, workerTag = "maps") {
  if (!chrome.debugger) return;
  if (attachedDebuggerTabs.has(tabId)) return;

  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    attachedDebuggerTabs.add(tabId);
    try {
      await chrome.debugger.sendCommand({ tabId }, "Page.enable");
      await chrome.debugger.sendCommand({ tabId }, "Emulation.setFocusEmulationEnabled", { enabled: true });
    } catch (e) {}
    await chrome.debugger.sendCommand({ tabId }, "Page.startScreencast", {
      format: "jpeg",
      quality: 60,
      maxWidth: 960,
      maxHeight: 720,
      everyNthFrame: 1
    });
    console.log(`[Mavon Extension] Screencast started for ${workerTag} tab:`, tabId);

    // Initial frame capture
    try {
      const shot = await chrome.debugger.sendCommand({ tabId }, "Page.captureScreenshot", {
        format: "jpeg",
        quality: 60
      });
      if (shot && shot.data && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LIVE_FRAME",
          stream_type: workerTag,
          image_base64: shot.data
        }));
      }
    } catch (e) {}
  } catch (err) {
    if (String(err?.message || err).includes("Another debugger is already attached")) {
      attachedDebuggerTabs.add(tabId);
    }
  }
}

const lastFrameSent = {};

if (chrome.debugger) {
  chrome.debugger.onEvent.addListener((source, method, params) => {
    if (method === "Page.screencastFrame" && params.data) {
      let workerTag = null;
      if (source.tabId === mapsTabId) workerTag = "maps";
      else if (source.tabId === linkedinTabId) workerTag = "linkedin";
      else if (source.tabId === shopTabId) workerTag = "website";
      else if (source.tabId === platformTabId) workerTag = "platform";

      // Always acknowledge frame immediately so Chrome pipeline doesn't back up
      chrome.debugger.sendCommand(
        { tabId: source.tabId },
        "Page.screencastFrameAck",
        { sessionId: params.sessionId }
      ).catch(() => {});

      const now = Date.now();
      if (workerTag && (!lastFrameSent[workerTag] || now - lastFrameSent[workerTag] >= 750)) {
        lastFrameSent[workerTag] = now;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "LIVE_FRAME",
            stream_type: workerTag,
            tab_id: source.tabId,
            image_base64: params.data
          }));
        }
      }
    }
  });

  chrome.debugger.onDetach.addListener((source) => {
    attachedDebuggerTabs.delete(source.tabId);
  });
}

// Clean up closed tabs
chrome.tabs.onRemoved.addListener((tabId) => {
  attachedDebuggerTabs.delete(tabId);
  if (tabId === mapsTabId) mapsTabId = null;
  if (tabId === linkedinTabId) linkedinTabId = null;
  if (tabId === shopTabId) shopTabId = null;
  if (tabId === platformTabId) platformTabId = null;
});

// Listen for messages from popup or content scripts (e.g. dashboard page)
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "GET_STATUS") {
    sendResponse({
      connected: ws !== null && ws.readyState === WebSocket.OPEN,
      wsUrl: getWsUrl(),
      healthUrl: getHealthUrl(),
      port: BACKEND_PORT,
      version: "3.1.0"
    });
    return true;
  }
  if (msg && msg.type === "RECONNECT") {
    connect().then(() => {
      sendResponse({ success: true, connected: ws !== null && ws.readyState === WebSocket.OPEN, port: BACKEND_PORT });
    });
    return true;
  }

  if (sender && sender.tab && sender.tab.windowId) {
    msg.senderWindowId = sender.tab.windowId;
  }
  handleCommand(msg).then(sendResponse).catch(err => sendResponse({ success: false, error: String(err) }));
  return true;
});

// Wait for a tab to finish loading (like in MessageV2)
function waitForTabLoaded(tabId, timeoutMs = 15000) {
  return new Promise((resolve) => {
    let resolved = false;
    const cleanup = () => {
      chrome.tabs.onUpdated.removeListener(listener);
      chrome.tabs.onRemoved.removeListener(removeListener);
    };

    const finish = () => {
      if (!resolved) {
        resolved = true;
        cleanup();
        setTimeout(resolve, 1500); // DOM hydration
      }
    };

    function removeListener(closedTabId) {
      if (closedTabId === tabId) {
        if (!resolved) {
          resolved = true;
          cleanup();
          resolve();
        }
      }
    }

    function listener(id, changeInfo, tab) {
      if (id === tabId && changeInfo.status === "complete") {
        finish();
      }
    }

    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.onRemoved.addListener(removeListener);

    chrome.tabs.get(tabId).then((t) => {
      if (t && t.status === "complete") {
        finish();
      }
    }).catch(() => {});

    setTimeout(() => {
      finish();
    }, timeoutMs);
  });
}

// Navigates an existing tab and strictly waits for its NEW navigation to complete (6s timeout)
function navigateTabAndWait(tabId, targetUrl, timeoutMs = 6000) {
  return new Promise(async (resolve) => {
    let resolved = false;
    let timer = null;

    const cleanup = () => {
      chrome.tabs.onUpdated.removeListener(listener);
      clearTimeout(timer);
    };

    const finish = () => {
      if (!resolved) {
        resolved = true;
        cleanup();
        setTimeout(resolve, 300); // Fast 300ms DOM render window
      }
    };

    function listener(id, changeInfo, tab) {
      if (id === tabId && changeInfo.status === "complete") {
        finish();
      }
    }

    chrome.tabs.onUpdated.addListener(listener);
    timer = setTimeout(finish, timeoutMs);

    try {
      await chrome.tabs.update(tabId, { url: targetUrl });
    } catch (e) {
      console.warn("[Mavon Extension] chrome.tabs.update failed:", e);
      finish();
    }
  });
}

// Clean hostname helper for domain deduplication
function getCleanDomain(url) {
  if (!url || typeof url !== "string") return "";
  try {
    let clean = url.trim();
    if (!clean.startsWith("http://") && !clean.startsWith("https://")) clean = "http://" + clean;
    const parsed = new URL(clean);
    let dom = parsed.hostname.toLowerCase();
    if (dom.startsWith("www.")) dom = dom.substring(4);
    return dom;
  } catch (e) {
    return "";
  }
}

// Robust script execution wrapper with strict timeout to prevent hangs on broken/white-screen websites
function execScriptWithTimeout(details, timeoutMs = 4500) {
  return Promise.race([
    chrome.scripting.executeScript(details),
    new Promise((_, reject) => setTimeout(() => reject(new Error("executeScript timeout")), timeoutMs))
  ]);
}

// Unified job finish notifier across WebSocket and HTTP backend
async function notifyJobFinished(total, aborted) {
  isHarvesting = false;
  isMapsHarvesting = false;
  isWebsiteHarvesting = false;
  isPlatformHarvesting = false;
  isLinkedinHarvesting = false;
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({
        type: "JOB_FINISHED",
        total: total,
        aborted: Boolean(aborted)
      }));
      ws.send(JSON.stringify({
        type: "STATUS",
        status: aborted ? "Stopped" : "Finished"
      }));
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "system",
        message: aborted ? "⏹️ Scraping stopped." : `🏁 Finished! Scraped ${total} places directly into database.`
      }));
    } catch (_) {}
  }
  try {
    await fetch("http://localhost:8085/api/job-finished", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ total: total, aborted: Boolean(aborted) })
    });
  } catch (_) {}
}

// Background Harvesting Loop: Drives Maps search & Website inspection quietly in user's active Chrome window
async function runMapsHarvestingLoop(payload, targetWinId) {
  if (isMapsHarvesting) {
    console.log("[Mavon Extension] Maps harvesting loop already running");
    return;
  }
  isMapsHarvesting = true;
  isHarvesting = true;
  abortHarvester = false;

  const maxPlaces = parseInt(payload.max_results || 15);
  const enableWebsite = payload.enable_website !== false;
  console.log(`[Mavon Extension] 🚀 Starting Live Harvesting Loop: max=${maxPlaces}, website=${enableWebsite}`);

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "LOG",
      agent: "maps",
      message: `🚀 Live Chrome Harvester started in your active window (Max: ${maxPlaces})`
    }));
    ws.send(JSON.stringify({
      type: "STATUS",
      status: "Harvesting live in Chrome window..."
    }));
  }

  // Wait for Google Maps tab to load and place cards to appear
  let initialCardsReady = false;
  for (let attempt = 0; attempt < 20; attempt++) {
    if (abortHarvester) break;
    try {
      const checkRes = await execScriptWithTimeout({
        target: { tabId: mapsTabId },
        func: () => {
          const backBtn = document.querySelector('button[jsaction*="pane.back"], button[jsaction*="pane.place.back"], button[aria-label="Back to results"], button[aria-label="Back to search results"]');
          if (backBtn && backBtn.offsetHeight > 0) backBtn.click();
          return document.querySelectorAll('div.Nv2PK, a.hfpxzc[href*="/maps/place/"]').length;
        }
      }, 2500).catch(() => null);
      const cardCount = (checkRes && checkRes[0] && checkRes[0].result) ? checkRes[0].result : 0;
      if (cardCount > 0) {
        initialCardsReady = true;
        break;
      }
    } catch (_) {}
    await new Promise(r => setTimeout(r, 500));
  }

  let harvested = 0;
  const seenNames = new Set();
  if (payload.skip_existing_db) {
    try {
      const existingRes = await fetch("http://localhost:8085/api/leads");
      if (existingRes.ok) {
        const existingLeads = await existingRes.json();
        if (Array.isArray(existingLeads)) {
          for (const l of existingLeads) {
            if (l.name) seenNames.add(l.name.toLowerCase().trim());
          }
        }
      }
    } catch (_) {}
  }
  let consecutiveNoNew = 0;

  while (harvested < maxPlaces && !abortHarvester) {
    // 1. Query place cards currently in feed with baseline attributes (rating, reviews, category)
    let items = [];
    try {
      const res = await execScriptWithTimeout({
        target: { tabId: mapsTabId },
        func: () => {
          // If a detail pane is open, close it so feed is exposed
          const backBtn = document.querySelector('button[jsaction*="pane.back"], button[jsaction*="pane.place.back"], button[aria-label="Back to results"], button[aria-label="Back to search results"]');
          if (backBtn && backBtn.offsetHeight > 0) backBtn.click();

          const cards = document.querySelectorAll('div.Nv2PK');
          const result = [];
          
          if (cards && cards.length > 0) {
            cards.forEach((c, idx) => {
              const titleEl = c.querySelector('div.qBF1Pd, div.fontHeadlineSmall');
              const linkEl = c.querySelector('a.hfpxzc, a[href*="/maps/place/"]');
              const title = titleEl ? titleEl.innerText.trim() : (linkEl ? (linkEl.getAttribute("aria-label") || "").trim() : "");
              if (title && !["results", "sponsored", "ad", "ads"].includes(title.toLowerCase())) {
                const ratingEl = c.querySelector('span.MW4etd');
                const rating = ratingEl ? ratingEl.innerText.trim() : "N/A";
                const revEl = c.querySelector('span.UY7F9');
                const reviews = revEl ? revEl.innerText.replace(/[(),]/g, '').trim() : "0";
                
                let category = "Business";
                let address = "N/A";
                const textSnippets = c.querySelectorAll('div.W4Efsd');
                if (textSnippets && textSnippets.length > 0) {
                  const firstSnip = textSnippets[0].innerText || "";
                  const parts = firstSnip.split('·').map(p => p.trim());
                  for (const pt of parts) {
                    if (pt && pt.length < 40 && !pt.includes('$') && !/^[0-5]\.\d/.test(pt) && !/^\(?\d+[\),]?$/.test(pt) && !pt.toLowerCase().includes("open") && !pt.toLowerCase().includes("closed")) {
                      category = pt;
                      break;
                    }
                  }
                  if (textSnippets[1]) {
                    const secondSnip = (textSnippets[1].innerText || "").replace(/[\uE000-\uF8FF]/g, '').trim();
                    if (secondSnip) address = secondSnip;
                  }
                }

                result.push({
                  index: idx,
                  name: title,
                  url: linkEl ? linkEl.href : "",
                  baseline: { rating, reviews, category, address }
                });
              }
            });
          } else {
            const links = document.querySelectorAll('a.hfpxzc[href*="/maps/place/"]');
            links.forEach((l, idx) => {
              const title = (l.getAttribute("aria-label") || l.innerText || "").trim();
              if (title && !["results", "sponsored", "ad", "ads"].includes(title.toLowerCase())) {
                result.push({
                  index: idx,
                  name: title,
                  url: l.href,
                  baseline: { rating: "N/A", reviews: "0", category: "Business", address: "N/A" }
                });
              }
            });
          }
          return result;
        }
      }, 3500);
      items = (res && res[0] && res[0].result) ? res[0].result : [];
    } catch (e) {
      console.warn("[Mavon Extension] Failed to query feed cards:", e);
    }

    let foundNew = false;
    for (const item of items) {
      if (harvested >= maxPlaces || abortHarvester) break;
      const lowerName = (item.name || "").toLowerCase().trim();
      if (!lowerName || seenNames.has(lowerName)) continue;

      foundNew = true;

      // Click card to open detail pane with full mouse event simulation
      try {
        await chrome.scripting.executeScript({
          target: { tabId: mapsTabId },
          args: [item.name, item.index],
          func: (expectedName, idx) => {
            const feed = document.querySelector('div[role="feed"]') || document.querySelector('.m6QErb[aria-label]');
            if (!feed) return false;
            const cards = feed.querySelectorAll('div.Nv2PK');
            let targetCard = null;
            for (const c of cards) {
              const t = c.querySelector('div.qBF1Pd, div.fontHeadlineSmall');
              if (t && t.innerText.trim().toLowerCase() === expectedName.toLowerCase()) {
                targetCard = c;
                break;
              }
            }
            if (!targetCard && cards[idx]) targetCard = cards[idx];

            function fireEvents(el) {
              if (!el) return;
              ['mousedown', 'mouseup', 'click'].forEach(evt => {
                el.dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true, view: window }));
              });
            }

            if (targetCard) {
              const a = targetCard.querySelector('a.hfpxzc, a[href*="/maps/place/"]');
              targetCard.scrollIntoView({ block: "center", behavior: "smooth" });
              if (a) fireEvents(a);
              fireEvents(targetCard);
              return true;
            }
            const links = feed.querySelectorAll('a.hfpxzc');
            for (const l of links) {
              if ((l.getAttribute("aria-label") || "").trim().toLowerCase() === expectedName.toLowerCase()) {
                l.scrollIntoView({ block: "center", behavior: "smooth" });
                fireEvents(l);
                return true;
              }
            }
            if (links[idx]) {
              links[idx].scrollIntoView({ block: "center", behavior: "smooth" });
              fireEvents(links[idx]);
              return true;
            }
            return false;
          }
        });
      } catch (e) {}

      // Polling (up to 2.7s) for detail pane to show clicked place and hydrate contact buttons
      let extracted = null;
      for (let attempt = 0; attempt < 9; attempt++) {
        await new Promise(r => setTimeout(r, 300));
        if (abortHarvester) break;

        try {
          const detRes = await chrome.scripting.executeScript({
            target: { tabId: mapsTabId },
            args: [item.name, item.baseline, attempt],
            func: (expectedName, baseline, attemptNum) => {
              const h1 = document.querySelector('h1.DUwDvf') || document.querySelector('.fontHeadlineLarge');
              const hText = h1 ? h1.innerText.replace(/[\uE000-\uF8FF]/g, '').trim() : "";
              const cleanExp = (expectedName || "").replace(/\.{2,}|…/g, '').trim().toLowerCase();
              const cleanH = hText.replace(/\.{2,}|…/g, '').trim().toLowerCase();

              // Tolerant match handling ellipses (...) and truncation
              const isMatch = hText && (
                cleanH.includes(cleanExp) ||
                cleanExp.includes(cleanH) ||
                (cleanExp.length >= 4 && cleanH.startsWith(cleanExp.slice(0, 4)))
              );
              if (!isMatch) {
                return { isMatch: false, currentH1: hText };
              }

              // 1. Identify the full right detail pop-up drawer
              const closeBtn = document.querySelector('button[aria-label*="Close" i], button[jsaction*="pane.close" i]');
              const drawer = closeBtn ? closeBtn.closest('div[role="main"], div.bJzME, div.e07Vkf, div.m6QErb') : (h1 ? (h1.closest('div[role="main"]') || h1.closest('div.bJzME')) : null);
              const root = drawer || (h1 ? h1.closest('div[role="main"]') : null) || document;

              // 2. Find the true scrollable container in the right pop-up and scroll it down
              let scrollable = null;
              let curr = h1;
              while (curr && curr !== document.body) {
                if (curr.scrollHeight > curr.clientHeight) {
                  const style = window.getComputedStyle(curr);
                  if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                    scrollable = curr;
                    break;
                  }
                }
                curr = curr.parentElement;
              }
              if (!scrollable && drawer) {
                const candidates = drawer.querySelectorAll('div');
                for (const c of candidates) {
                  if (c.scrollHeight > c.clientHeight + 80) {
                    const style = window.getComputedStyle(c);
                    if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                      scrollable = c;
                      break;
                    }
                  }
                }
              }
              if (scrollable && scrollable.scrollTop < 350) {
                scrollable.scrollTop = 500;
              }

              // Trigger native scrollIntoView on contact section anchor so browser scrolls drawer
              const contactAnchor = root.querySelector('button[data-item-id="address"], button[aria-label*="Address:"], button[data-item-id*="phone:"], a[data-item-id="authority"], div[data-item-id*="oh"], [data-item-id*="address"], div.R65duf');
              if (contactAnchor) {
                try {
                  contactAnchor.scrollIntoView({ block: 'center', behavior: 'smooth' });
                } catch (_) {}
              }

              // 3. Check if detail pane buttons (address, phone, website, hours) have hydrated
              const hasButtons = !!root.querySelector(
                'button[data-item-id="address"], button[aria-label*="Address:"], button[data-item-id*="phone:"], button[aria-label*="Phone:"], a[data-item-id="authority"], a[data-tooltip*="Open website"], a[data-tooltip*="website" i], div[data-item-id*="oh"], [data-item-id*="address"]'
              );

              // If buttons haven't hydrated yet and we have retry attempts remaining, keep waiting
              if (!hasButtons && attemptNum < 7) {
                return { isMatch: false, reason: "hydrating" };
              }

              let rating = (baseline && baseline.rating !== "N/A") ? baseline.rating : "N/A";
              let reviews = (baseline && baseline.reviews !== "0") ? baseline.reviews : "0";
              const starEl = root.querySelector('span[aria-label*="star"], span[role="img"][aria-label*="star"]');
              if (starEl) {
                const m = (starEl.getAttribute("aria-label") || "").match(/([0-9.]+)\s*star/i);
                if (m) rating = m[1];
              }
              const revEl = root.querySelector('span[aria-label*="review"], button[aria-label*="review"]');
              if (revEl) {
                const m = (revEl.getAttribute("aria-label") || revEl.innerText || "").match(/([\d,]+)\s*review/i);
                if (m) reviews = m[1].replace(/,/g, "");
              }

              let category = (baseline && baseline.category !== "Business") ? baseline.category : "Business";
              const catEl = root.querySelector('button.DkEaL, button[jsaction*="category"], div.fontBodyMedium button, span.YhemCb');
              if (catEl) {
                const cText = catEl.innerText.replace(/[\uE000-\uF8FF]/g, '').trim();
                if (cText && !cText.includes("Update results") && !cText.includes("Search this area") && !cText.includes("\n") && cText.length < 50) {
                  category = cText;
                }
              }

              let address = (baseline && baseline.address !== "N/A") ? baseline.address : "N/A";
              const addrEl = root.querySelector('button[data-item-id="address"], button[aria-label*="Address:"], button[data-tooltip*="Copy address"], [data-item-id*="address"]');
              if (addrEl) {
                const aText = (addrEl.getAttribute("aria-label") || addrEl.innerText || "").replace(/^Address:\s*/i, "").replace(/[\uE000-\uF8FF]/g, '').trim();
                if (aText) address = aText;
              }

              let phone = "N/A";
              const phoneEl = root.querySelector('button[data-item-id*="phone:"], button[aria-label*="Phone:"], button[data-tooltip*="Copy phone"], a[href^="tel:"]');
              if (phoneEl) {
                const pText = (phoneEl.getAttribute("aria-label") || phoneEl.innerText || "").replace(/^Phone:\s*/i, "").replace(/[\uE000-\uF8FF]/g, '').trim();
                if (pText && pText.length >= 5) phone = pText;
              }

              let website = "N/A";
              const webEl = root.querySelector('a[data-item-id="authority"], a[data-tooltip*="Open website"], [aria-label*="Website:"]');
              if (webEl && webEl.href) {
                let rawHref = webEl.href;
                if (rawHref.includes('google.com/url?') || rawHref.includes('/url?q=')) {
                  const m = rawHref.match(/[?&]q=([^&]+)/);
                  if (m) rawHref = decodeURIComponent(m[1]).split('?')[0].replace(/\/+$/, '');
                }
                if (rawHref && rawHref.startsWith("http")) website = rawHref;
              }

              let hours = "N/A";
              const hoursEl = root.querySelector('button[data-item-id*="oh"], div[data-item-id*="oh"], [aria-label*="Hours:" i], [aria-label*="Closed" i], [aria-label*="Open" i], button[data-tooltip*="hours" i], div.t39EBf');
              if (hoursEl) {
                const hRaw = (hoursEl.getAttribute("aria-label") || hoursEl.innerText || "").replace(/^Hours:\s*/i, "").replace(/[\uE000-\uF8FF]/g, '').trim();
                if (hRaw) hours = hRaw.split('\n')[0].trim();
              }

              let price = "";
              const priceEl = root.querySelector('span[aria-label*="per person" i], div[aria-label*="per person" i], [aria-label*="price" i], button[data-item-id*="price"]');
              if (priceEl) {
                price = (priceEl.getAttribute("aria-label") || priceEl.innerText || "").replace(/[\uE000-\uF8FF]/g, '').trim();
              }

              let plus_code = "";
              const plusEl = root.querySelector('button[data-item-id="oloc"], button[aria-label*="Plus code:" i], [data-tooltip*="plus code" i]');
              if (plusEl) {
                plus_code = (plusEl.getAttribute("aria-label") || plusEl.innerText || "").replace(/^Plus code:\s*/i, "").replace(/[\uE000-\uF8FF]/g, '').trim();
              }

              let order_url = "";
              const orderEl = root.querySelector('a[data-item-id*="action:order"], a[aria-label*="Order online" i], a[data-tooltip*="Order online" i], a[href*="order"], a[href*="zomato.com"], a[href*="swiggy.com"], a[href*="dotpe.in"], a[href*="thriveapp.in"], a[data-tooltip*="order" i], a[href*="table"], a[aria-label*="Reserve a table" i]');
              if (orderEl && orderEl.href) {
                let rawOrder = orderEl.href;
                if (rawOrder.includes('google.com/url?') || rawOrder.includes('/url?q=')) {
                  const m = rawOrder.match(/[?&]q=([^&]+)/);
                  if (m) rawOrder = decodeURIComponent(m[1]).split('?')[0].replace(/\/+$/, '');
                }
                order_url = rawOrder;
              }

              let email = "N/A";
              const mailA = root.querySelector('a[href^="mailto:"]');
              if (mailA && mailA.href) {
                email = mailA.href.replace(/^mailto:/i, '').split('?')[0].trim();
              }

              const socials = { instagram: "", facebook: "", linkedin: "", twitter: "" };
              root.querySelectorAll('a[href]').forEach(a => {
                let h = (a.getAttribute('href') || a.href || '').trim();
                if (h.includes('google.com/url?') || h.includes('/url?q=')) {
                  const m = h.match(/[?&]q=([^&]+)/);
                  if (m) h = decodeURIComponent(m[1]);
                }
                const low = h.toLowerCase();
                if (!socials.instagram && low.includes('instagram.com/') && !low.includes('/p/')) socials.instagram = h.split('?')[0];
                else if (!socials.facebook && (low.includes('facebook.com/') || low.includes('fb.me/')) && !low.includes('sharer')) socials.facebook = h.split('?')[0];
                else if (!socials.linkedin && low.includes('linkedin.com/')) socials.linkedin = h.split('?')[0];
                else if (!socials.twitter && (low.includes('twitter.com/') || low.includes('x.com/'))) socials.twitter = h.split('?')[0];
              });

              return {
                isMatch: true,
                name: hText || expectedName,
                rating,
                reviews,
                category,
                address,
                phone,
                website,
                hours,
                price,
                plus_code,
                order_url,
                email,
                socials,
                maps_url: window.location.href
              };
            }
          });
          const res = (detRes && detRes[0] && detRes[0].result) ? detRes[0].result : null;
          if (res && res.isMatch) {
            extracted = res;
            break;
          }
        } catch (e) {}
      }

      if (!extracted) {
        extracted = {
          name: item.name,
          rating: (item.baseline && item.baseline.rating) ? item.baseline.rating : "N/A",
          reviews: (item.baseline && item.baseline.reviews) ? item.baseline.reviews : "0",
          category: (item.baseline && item.baseline.category) ? item.baseline.category : "Business",
          address: (item.baseline && item.baseline.address) ? item.baseline.address : "N/A",
          phone: "N/A",
          website: "N/A",
          hours: "N/A",
          price: "",
          plus_code: "",
          order_url: "",
          email: "N/A",
          socials: { instagram: "", facebook: "", linkedin: "", twitter: "" },
          maps_url: item.url || window.location.href
        };
      }

      // Add to seen names
      seenNames.add(lowerName);
      if (extracted.name) seenNames.add(extracted.name.toLowerCase().trim());

      harvested++;
      const hasWebsite = extracted.website && extracted.website !== "N/A" && extracted.website.startsWith("http");
      const extSoc = extracted.socials || {};
      const orderUrl = extracted.order_url || "";
      const placeData = {
        source_agent: "maps",
        name: extracted.name || item.name,
        rating: extracted.rating || "N/A",
        reviews: extracted.reviews || "0",
        category: extracted.category || "Business",
        address: extracted.address || "N/A",
        phone: extracted.phone || "N/A",
        website: extracted.website || "N/A",
        hours: extracted.hours || "N/A",
        price: extracted.price || "",
        plus_code: extracted.plus_code || "",
        order_url: orderUrl,
        booking_url: orderUrl,
        maps_url: extracted.maps_url || item.url || window.location.href,
        website_status: hasWebsite ? "pending" : "no_website",
        email: extracted.email || "N/A",
        instagram: extSoc.instagram || "",
        facebook: extSoc.facebook || "",
        linkedin: extSoc.linkedin || "",
        twitter: extSoc.twitter || "",
        bot_protection: "Clean",
        cookie_status: "None"
      };

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LOG",
          agent: "maps",
          message: `📍 [Maps #${harvested}/${maxPlaces}] ${placeData.name} (${placeData.category}) | 📞 ${placeData.phone} | 🌐 ${placeData.website}`
        }));
      }

      if (abortHarvester) break;

      // Save Google Maps place record to backend immediately
      try {
        await fetch("http://localhost:8085/api/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(placeData)
        });
      } catch (e) {}

      // Close detail pane back to search results immediately so next card is visible and clickable
      try {
        await execScriptWithTimeout({
          target: { tabId: mapsTabId },
          func: () => {
            const backBtn = document.querySelector(
              'button[jsaction*="pane.back"], button[jsaction*="pane.place.back"], button[aria-label="Back to results"], button[aria-label="Back to search results"]'
            );
            if (backBtn && backBtn.offsetHeight > 0) backBtn.click();
          }
        }, 2000).catch(() => {});
      } catch (_) {}

      await new Promise(r => setTimeout(r, 350));
    }

    if (harvested >= maxPlaces || abortHarvester) break;

    // Ensure search feed has focus by closing any lingering detail pane and waiting for animation
    try {
      await execScriptWithTimeout({
        target: { tabId: mapsTabId },
        func: () => {
          const backBtn = document.querySelector(
            'button[jsaction*="pane.back"], button[jsaction*="pane.place.back"], button[aria-label="Back to results"], button[aria-label="Back to search results"]'
          );
          if (backBtn && backBtn.offsetHeight > 0) backBtn.click();
        }
      }, 2000).catch(() => {});
    } catch (_) {}
    await new Promise(r => setTimeout(r, 400));

    // Scroll feed down with robust end-of-list detection & jiggle scrolling
    let scrollResult = { reachedEnd: false, cardCount: 0 };
    try {
      const scrollExec = await execScriptWithTimeout({
        target: { tabId: mapsTabId },
        args: [consecutiveNoNew],
        func: (attempt) => {
          let feed = document.querySelector('div[role="feed"]');
          if (!feed) {
            const backBtn = document.querySelector(
              'button[jsaction*="pane.back"], button[jsaction*="pane.place.back"], button[aria-label="Back to results"], button[aria-label="Back to search results"]'
            );
            if (backBtn && backBtn.offsetHeight > 0) backBtn.click();
            feed = document.querySelector('div[role="feed"]') || document.querySelector('.m6QErb[aria-label]');
          }
          if (!feed) return { reachedEnd: false, cardCount: 0 };

          // 1. Identify true scrollable container in Google Maps DOM
          let scrollable = feed;
          let curr = feed;
          while (curr && curr !== document.body) {
            const style = window.getComputedStyle(curr);
            if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && curr.scrollHeight > curr.clientHeight) {
              scrollable = curr;
              break;
            }
            curr = curr.parentElement;
          }
          if (!scrollable && feed.parentElement) scrollable = feed.parentElement;

          const cards = document.querySelectorAll('div.Nv2PK, a.hfpxzc[href*="/maps/place/"]');

          // 2. Check for Google Maps end-of-feed indicator (strictly requiring at least 20 cards)
          const endEl = document.querySelector('.HlvSq, [aria-label*="reached the end" i], [aria-label*="no more results" i]');
          const feedText = (feed.innerText || "") + (scrollable.innerText || "") + (document.body.innerText || "");
          const reachedEnd = cards.length >= 20 && (
            Boolean(endEl && endEl.offsetHeight > 0) ||
            feedText.includes("You've reached the end of the list") ||
            feedText.includes("No more results for this area")
          );

          // 3. Focus scrollable & dispatch PageDown keyboard navigation
          try {
            scrollable.focus();
            scrollable.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageDown', code: 'PageDown', keyCode: 34, which: 34, bubbles: true }));
          } catch (_) {}

          // 4. Scroll last card into view
          if (cards.length > 0) {
            try {
              cards[cards.length - 1].scrollIntoView({ block: "end", behavior: "auto" });
            } catch (_) {}
          }

          // 5. Scroll container & dispatch synthetic WheelEvent (triggers Google Maps AJAX pagination)
          scrollable.scrollTop += 4500;
          feed.scrollTop += 4500;
          if (feed.parentElement) feed.parentElement.scrollTop += 4500;
          try {
            scrollable.dispatchEvent(new WheelEvent('wheel', { deltaY: 3500, deltaMode: 0, bubbles: true, cancelable: true }));
            scrollable.dispatchEvent(new Event('scroll', { bubbles: true }));
            feed.dispatchEvent(new Event('scroll', { bubbles: true }));
            if (feed.parentElement) feed.parentElement.dispatchEvent(new Event('scroll', { bubbles: true }));
          } catch (_) {}

          // 6. Jiggle-scroll if stuck (scroll back up slightly then down to re-trigger observer)
          if (attempt >= 2) {
            scrollable.scrollTop = Math.max(0, scrollable.scrollTop - 800);
            feed.scrollTop = Math.max(0, feed.scrollTop - 800);
            try {
              scrollable.dispatchEvent(new WheelEvent('wheel', { deltaY: -800, deltaMode: 0, bubbles: true }));
              scrollable.dispatchEvent(new Event('scroll', { bubbles: true }));
            } catch (_) {}
            setTimeout(() => {
              scrollable.scrollTop += 4500;
              feed.scrollTop += 4500;
              try {
                scrollable.dispatchEvent(new WheelEvent('wheel', { deltaY: 3500, deltaMode: 0, bubbles: true }));
                scrollable.dispatchEvent(new Event('scroll', { bubbles: true }));
              } catch (_) {}
            }, 100);
          }

          return { reachedEnd, cardCount: cards.length };
        }
      }, 3500);
      scrollResult = (scrollExec && scrollExec[0] && scrollExec[0].result) ? scrollExec[0].result : { reachedEnd: false, cardCount: 0 };
    } catch (e) {}

    // Wait 2.5s for Google Maps pagination response to land in DOM
    for (let i = 0; i < 10; i++) {
      await new Promise(r => setTimeout(r, 250));
      if (abortHarvester) break;
    }

    if (!foundNew) {
      consecutiveNoNew++;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LOG",
          agent: "maps",
          message: `📜 [Maps] Scrolling feed to discover more places (attempt ${consecutiveNoNew}/25, visible cards: ${scrollResult.cardCount})...`
        }));
      }
      // Only complete feed if genuinely reached end with at least 20 cards, or 25 consecutive attempts
      if ((scrollResult.reachedEnd && consecutiveNoNew >= 4 && scrollResult.cardCount >= 20) || (consecutiveNoNew >= 25 && scrollResult.cardCount >= 15)) {
        console.log(`[Mavon Extension] Search feed complete (reachedEnd=${scrollResult.reachedEnd}, cards=${scrollResult.cardCount}, attempts=${consecutiveNoNew})`);
        break;
      }
    } else {
      consecutiveNoNew = 0;
    }
  }

  isMapsHarvesting = false;
  if (!isWebsiteHarvesting && !isPlatformHarvesting && !isLinkedinHarvesting) {
    await notifyJobFinished(harvested, abortHarvester);
  } else {
    if (ws && ws.readyState === WebSocket.OPEN) {
      const reasonMsg = (harvested >= maxPlaces && maxPlaces < 999999)
        ? `🏁 [Maps] Reached places limit (${harvested}/${maxPlaces}). Web Agent is continuing to inspect pending websites...`
        : `🏁 [Maps] Completed collection of ${harvested} places (end of area results). Web Agent is continuing to inspect pending websites...`;
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "maps",
        message: reasonMsg
      }));
    }
  }
}

// Background Website Queue Worker: Polls database for pending websites and inspects them in shopTabId
async function runWebsiteQueueLoop(payload, targetWinId) {
  if (isWebsiteHarvesting) {
    console.log("[Mavon Extension] Previous website queue loop running. Signaling fresh reset...");
    abortHarvester = true;
    await new Promise(r => setTimeout(r, 250));
  }
  isWebsiteHarvesting = true;
  isHarvesting = true;
  abortHarvester = false;
  console.log("[Mavon Extension] 🌐 Starting Website Queue Worker...");

  const directTargets = (payload && Array.isArray(payload.targets) && payload.targets.length > 0) ? [...payload.targets] : null;
  const isStandalone = Boolean(directTargets);
  // Solution 1: Only focus tab once on initial launch in Standalone mode. Never steal focus in Maps mode.
  const initialFocus = isStandalone;

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "LOG",
      agent: "website",
      message: isStandalone
        ? `🌐 [Website Agent] Standalone mode: Launching live tab in Chrome for ${directTargets.length} target websites...`
        : "🌐 [Website Agent] Background worker active — processing pending sites from database queue."
    }));
  }

  // Ensure shopTabId exists and is valid in Chrome
  try {
    let tabExists = false;
    if (shopTabId) {
      const tabInfo = await chrome.tabs.get(shopTabId).catch(() => null);
      if (tabInfo) tabExists = true;
    }
    if (!tabExists) {
      const createOpts = targetWinId ? { windowId: targetWinId, url: "about:blank", active: false } : { url: "about:blank", active: false };
      const st = await chrome.tabs.create(createOpts);
      shopTabId = st.id;
      ensureScreencastForTab(shopTabId, "website").catch(() => {});
    }
  } catch (e) {
    console.warn("[Mavon Extension] Error creating shopTabId:", e);
  }

  let totalInspected = 0;
  let emptyPolls = 0;

  if (directTargets) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "website",
        message: `🌐 [Website Agent] Standalone mode: Inspecting ${directTargets.length} target websites...`
      }));
    }
  }

  while (!abortHarvester) {
    let pendingLeads = [];
    if (directTargets) {
      if (directTargets.length === 0) {
        console.log("[Mavon Extension] Direct input targets queue complete.");
        break;
      }
      pendingLeads = directTargets.splice(0, 20);
    } else {
      // 1. Fetch batch of pending websites from backend database
      try {
        const res = await fetch("http://localhost:8085/api/leads/pending-websites?limit=20");
        if (res.ok) {
          const data = await res.json();
          pendingLeads = data.leads || [];
        }
      } catch (e) {
        console.warn("[Mavon Extension] Error fetching pending websites:", e);
      }
    }

    if (pendingLeads.length === 0) {
      // If Maps or Platform agent is still running, wait for more leads to be added
      if ((isMapsHarvesting || isPlatformHarvesting) && !directTargets) {
        emptyPolls++;
        if (emptyPolls % 10 === 1 && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "website",
            message: "⏳ [Website Agent] Idle: Waiting for new places with websites from Google Maps / Platform..."
          }));
        }
        for (let i = 0; i < 6; i++) {
          await new Promise(r => setTimeout(r, 500));
          if (abortHarvester) break;
        }
        if (abortHarvester) break;
        if (emptyPolls >= 40) {
          console.log("[Mavon Extension] Website queue idle timeout after 120s.");
          break;
        }
        continue;
      } else {
        console.log("[Mavon Extension] No more pending websites in queue.");
        if (ws && ws.readyState === WebSocket.OPEN && totalInspected === 0) {
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "website",
            message: "ℹ️ [Website Agent] No pending websites left in queue."
          }));
        }
        break;
      }
    } else if (totalInspected === 0 && ws && ws.readyState === WebSocket.OPEN && !directTargets) {
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "website",
        message: `🔄 [Website Agent] Found ${pendingLeads.length} leads in database queue awaiting website crawl...`
      }));
    }
    emptyPolls = 0;

    for (const lead of pendingLeads) {
      if (abortHarvester) break;
      const url = (lead.website || "").trim();
      if (!url || url === "N/A" || !url.startsWith("http")) {
        // Mark as no_website so it's not re-polled
        try {
          await fetch("http://localhost:8085/api/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id: lead.id,
              name: lead.name,
              address: lead.address,
              website: lead.website || "N/A",
              website_status: "no_website",
              source_agent: "web"
            })
          });
        } catch (e) {}
        continue;
      }

      const cleanDom = getCleanDomain(url);
      const urlLower = url.toLowerCase();
      const metaDomains = ["instagram.com", "facebook.com", "fb.me", "threads.net"];

      // 1. Instant Meta link bypass: save directly in 5ms without navigating browser tab
      if (metaDomains.some(m => urlLower.includes(m))) {
        const isIg = urlLower.includes("instagram.com");
        const plat = isIg ? "instagram" : "facebook";
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "website",
            message: `ℹ️ [Website Agent] '${lead.name}' website is an ${isIg ? 'Instagram' : 'Facebook'} profile. Recorded directly without opening tab.`
          }));
        }
        try {
          await fetch("http://localhost:8085/api/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id: lead.id,
              name: lead.name,
              address: lead.address,
              website: url,
              website_status: "contacts_found",
              source_agent: "web",
              [plat]: url,
              bot_protection: `Social Profile (${isIg ? 'Instagram' : 'Facebook'})`,
              cookie_status: "None",
              update_all_matching_domain: true
            })
          });
        } catch (e) {}
        continue;
      }

      // Check domain deduplication cache (only in Maps harvester mode, NEVER for Standalone or force_fresh)
      const forceFresh = Boolean(payload && payload.force_fresh) || isStandalone;
      if (!forceFresh && cleanDom && exploredDomainsCache.has(cleanDom)) {
        const cached = exploredDomainsCache.get(cleanDom);
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "website",
            message: `⚡ [Website Agent] Reusing verified data for '${lead.name}' (${cleanDom})`
          }));
        }

        try {
          await fetch("http://localhost:8085/api/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id: lead.id,
              name: lead.name,
              address: lead.address,
              website: url,
              website_status: cached.website_status || "contacts_found",
              source_agent: "web",
              update_all_matching_domain: true,
              email: cached.email || "N/A",
              emails: cached.emails || [],
              phone: cached.phone || "N/A",
              phones: cached.phones || [],
              instagram: cached.instagram || "",
              facebook: cached.facebook || "",
              linkedin: cached.linkedin || "",
              twitter: cached.twitter || "",
              whatsapp: cached.whatsapp || "",
              booking_url: cached.booking_url || "",
              platform_name: cached.platform_name || "",
              bot_protection: cached.bot_protection || "Clean",
              cookie_status: cached.cookie_status || "None"
            })
          });
        } catch (e) {}
        continue;
      }

      // Inspect unvisited website
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LOG",
          agent: "website",
          message: `🌐 [Website Agent] Inspecting site for ${lead.name}: ${url}`
        }));
      }

      let shopTabExists = false;
      if (shopTabId) {
        const tabInfo = await chrome.tabs.get(shopTabId).catch(() => null);
        if (tabInfo) shopTabExists = true;
      }

      if (!shopTabExists) {
        try {
          const createOpts = targetWinId ? { windowId: targetWinId, url: url, active: false } : { url: url, active: false };
          const st = await chrome.tabs.create(createOpts);
          shopTabId = st.id;
          ensureScreencastForTab(shopTabId, "website").catch(() => {});
          await waitForTabLoaded(shopTabId, 6500);
        } catch (e) {
          console.warn("[Mavon Extension] Error creating shopTabId:", e);
          continue;
        }
      } else {
        ensureScreencastForTab(shopTabId, "website").catch(() => {});
        // Never steal focus while iterating queue
        await navigateTabAndWait(shopTabId, url, 6500);
      }

      // Capture authentic landing page screenshot at top viewport
      let webScreenshotBase64 = null;
      try {
        if (chrome.debugger && shopTabId) {
          if (!attachedDebuggerTabs.has(shopTabId)) {
            try {
              await chrome.debugger.attach({ tabId: shopTabId }, "1.3");
              attachedDebuggerTabs.add(shopTabId);
            } catch (attErr) {
              if (String(attErr?.message || attErr).includes("already attached")) attachedDebuggerTabs.add(shopTabId);
            }
          }
          const shot = await chrome.debugger.sendCommand(
            { tabId: shopTabId },
            "Page.captureScreenshot",
            { format: "jpeg", quality: 75 }
          );
          if (shot && shot.data) {
            webScreenshotBase64 = shot.data;
          }
        }
      } catch (shotErr) {}

      // Two-phase smooth scroll: midpoint then bottom footer to trigger lazy loading of contact info
      try {
        await execScriptWithTimeout({
          target: { tabId: shopTabId },
          func: () => {
            window.scrollBy({ top: 600, behavior: "smooth" });
          }
        }, 2500).catch(() => {});
        await new Promise(r => setTimeout(r, 350));
        await execScriptWithTimeout({
          target: { tabId: shopTabId },
          func: () => {
            window.scrollTo({ top: document.body.scrollHeight || 3000, behavior: "smooth" });
          }
        }, 2500).catch(() => {});
        await new Promise(r => setTimeout(r, 400));
      } catch (e) {}

      if (abortHarvester) break;

      let siteData = null;
      try {
        const siteExec = await execScriptWithTimeout({
          target: { tabId: shopTabId },
          func: () => {
            const html = document.documentElement.innerHTML;
            const emailRegex = /([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)/g;
            const emailSet = new Set();
            const phoneSet = new Set();
            const socials = { instagram: "", facebook: "", linkedin: "", twitter: "", whatsapp: "" };

            function decodeCf(hex) {
              try {
                if (!hex || hex.length < 4) return "";
                const k = parseInt(hex.substr(0, 2), 16);
                let em = "";
                for (let n = 2; n < hex.length; n += 2) {
                  em += String.fromCharCode(parseInt(hex.substr(n, 2), 16) ^ k);
                }
                return em.trim();
              } catch (e) { return ""; }
            }

            const cleanSocial = (u) => u.split('?')[0].split('#')[0].replace(/\/+$/, '');

            // 1. Schema.org / JSON-LD extraction
            try {
              document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                try {
                  const raw = JSON.parse(s.innerText || s.textContent || "{}");
                  const items = Array.isArray(raw) ? raw : (raw['@graph'] || [raw]);
                  for (const it of items) {
                    if (it.email) {
                      const em = String(it.email).replace(/^mailto:/i, "").trim().toLowerCase();
                      if (em.includes("@")) emailSet.add(em);
                    }
                    if (it.telephone) {
                      const ph = String(it.telephone).replace(/^tel:/i, "").trim();
                      if (ph.length >= 7) phoneSet.add(ph);
                    }
                    if (it.sameAs) {
                      const links = Array.isArray(it.sameAs) ? it.sameAs : [it.sameAs];
                      for (const l of links) {
                        const low = String(l).toLowerCase();
                        if (!socials.instagram && low.includes("instagram.com/")) socials.instagram = cleanSocial(l);
                        if (!socials.facebook && (low.includes("facebook.com/") || low.includes("fb.me/"))) socials.facebook = cleanSocial(l);
                        if (!socials.linkedin && low.includes("linkedin.com/")) socials.linkedin = cleanSocial(l);
                        if (!socials.twitter && (low.includes("twitter.com/") || low.includes("x.com/"))) socials.twitter = cleanSocial(l);
                      }
                    }
                  }
                } catch (e) {}
              });
            } catch (e) {}

            // 2. Direct mailto links
            document.querySelectorAll('a[href^="mailto:"]').forEach(a => {
              const em = a.href.replace(/^mailto:/i, "").split("?")[0].trim().toLowerCase();
              if (em && em.includes("@")) emailSet.add(em);
            });

            // 3. Cloudflare obfuscated emails
            document.querySelectorAll('[data-cfemail]').forEach(el => {
              const dec = decodeCf(el.getAttribute('data-cfemail'));
              if (dec && dec.includes("@")) emailSet.add(dec.toLowerCase());
            });

            document.querySelectorAll('a[href*="/cdn-cgi/l/email-protection#"]').forEach(a => {
              const p = a.href.split("#");
              if (p[1]) {
                const dec = decodeCf(p[1]);
                if (dec && dec.includes("@")) emailSet.add(dec.toLowerCase());
              }
            });

            // 4. Regex fallback across HTML text
            const ignoreExts = [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".js", ".css", ".woff", ".woff2", ".ttf"];
            const matches = html.match(emailRegex) || [];
            matches.forEach(e => {
              const lower = e.toLowerCase();
              if (!ignoreExts.some(ext => lower.endsWith(ext)) && !lower.includes("sentry") && !lower.includes("wixpress") && !lower.includes("schema.org") && !lower.includes("example.com")) {
                emailSet.add(lower);
              }
            });

            // 5. Phone links
            document.querySelectorAll('a[href^="tel:"]').forEach(a => {
              const ph = a.href.replace(/^tel:/i, "").split("?")[0].trim();
              if (ph.length >= 7) phoneSet.add(ph);
            });

            // 6. Social anchors & WhatsApp
            document.querySelectorAll('a[href]').forEach(a => {
              const href = (a.href || "").trim();
              const lower = href.toLowerCase();
              if (!socials.instagram && lower.includes("instagram.com/") && !lower.includes("/p/") && !lower.includes("/explore") && !lower.includes("/reels")) {
                socials.instagram = cleanSocial(href);
              }
              if (!socials.facebook && lower.includes("facebook.com/") && !lower.includes("sharer") && !lower.includes("/dialog") && !lower.includes("/plugins")) {
                socials.facebook = cleanSocial(href);
              }
              if (!socials.linkedin && lower.includes("linkedin.com/") && (lower.includes("/company/") || lower.includes("/in/"))) {
                socials.linkedin = cleanSocial(href);
              }
              if (!socials.twitter && (lower.includes("twitter.com/") || lower.includes("x.com/")) && !lower.includes("intent") && !lower.includes("share")) {
                socials.twitter = cleanSocial(href);
              }
              if (!socials.whatsapp && (lower.includes("wa.me/") || lower.includes("api.whatsapp.com/send"))) {
                const m = href.match(/(?:wa\.me\/|phone=|\b)(\+?[0-9]{7,15})\b/);
                if (m) socials.whatsapp = m[1].replace(/[^0-9]/g, '');
              }
            });

            // 7. Booking & Directory platform link detection
            const platformMapping = {
              "airbnb.": "Airbnb",
              "fresha.com": "Fresha",
              "treatwell.": "Treatwell",
              "booksy.com": "Booksy",
              "practo.com": "Practo",
              "opentable.": "OpenTable",
              "zomato.com": "Zomato",
              "swiggy.com": "Swiggy",
              "booking.com": "Booking.com",
              "tripadvisor.": "TripAdvisor",
              "mindbodyonline.com": "Mindbody",
              "vagaro.com": "Vagaro"
            };
            let booking_url = "";
            let platform_name = "";
            for (const a of document.querySelectorAll('a[href]')) {
              const h = (a.href || "").toLowerCase();
              for (const [dom, pName] of Object.entries(platformMapping)) {
                if (h.includes(dom)) {
                  booking_url = a.href;
                  platform_name = pName;
                  break;
                }
              }
              if (booking_url) break;
            }

            let bot_protection = "Clean";
            const titleLower = (document.title || "").toLowerCase();
            const htmlLower = html.toLowerCase();
            let hasCloudflare = false;
            if (titleLower.includes("just a moment...") || titleLower.includes("attention required! | cloudflare")) {
              bot_protection = "Cloudflare";
              hasCloudflare = true;
            } else if (htmlLower.includes("cf-turnstile") || htmlLower.includes("challenges.cloudflare.com") || document.querySelector('#cf-turnstile, #challenge-running, .cf-turnstile, .g-recaptcha, iframe[src*="challenges.cloudflare.com"]')) {
              bot_protection = "Cloudflare Turnstile";
              hasCloudflare = true;
            }

            let cookie_status = "None";
            if (document.querySelector('#onetrust-banner-sdk, #CybotCookiebotDialog, .cmplz-cookiebanner, div[class*="cookie-banner" i]')) {
              cookie_status = "Detected";
            }

            // 8. Physical Address Extraction
            let foundAddress = "";
            try {
              document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                if (foundAddress) return;
                try {
                  const raw = JSON.parse(s.innerText || s.textContent || "{}");
                  const items = Array.isArray(raw) ? raw : (raw['@graph'] || [raw]);
                  for (const it of items) {
                    if (it.address) {
                      if (typeof it.address === 'object') {
                        const parts = [it.address.streetAddress, it.address.addressLocality, it.address.addressRegion, it.address.postalCode, it.address.addressCountry].filter(Boolean);
                        if (parts.length >= 2) { foundAddress = parts.join(', '); break; }
                      } else if (typeof it.address === 'string' && it.address.length > 8) {
                        foundAddress = it.address.trim(); break;
                      }
                    }
                  }
                } catch(e) {}
              });
            } catch(e) {}

            if (!foundAddress) {
              const addrEl = document.querySelector('address, footer [class*="address" i], div[class*="address" i], footer [class*="location" i], div[class*="contact" i] [class*="address" i]');
              if (addrEl) {
                const txt = (addrEl.innerText || addrEl.textContent || '').trim().replace(/\s+/g, ' ');
                if (txt.length >= 10 && txt.length <= 160 && /\d/.test(txt) && /[a-zA-Z]/.test(txt)) {
                  foundAddress = txt;
                }
              }
            }

            // 9. Discover Contact / About subpage link for deep multi-page crawl
            let candidateContactUrl = "";
            try {
              const allA = Array.from(document.querySelectorAll('a[href]'));
              const badLinks = ['facebook.com', 'instagram.com', 'twitter.com', 'linkedin.com', 'youtube.com', 'tiktok.com', 'wa.me', 'mailto:', 'tel:'];
              for (const a of allA) {
                const h = (a.href || '').trim();
                const txt = (a.innerText || a.textContent || '').trim().toLowerCase();
                const hLow = h.toLowerCase();
                if (!h.startsWith('http')) continue;
                if (badLinks.some(b => hLow.includes(b))) continue;
                if (hLow.includes('contact') || txt.includes('contact') || hLow.includes('about') || txt.includes('about') || hLow.includes('reach-us') || txt.includes('reach us')) {
                  candidateContactUrl = h;
                  if (hLow.includes('contact') || txt.includes('contact')) break;
                }
              }
            } catch(e) {}

            const bodyHeight = (document.body && document.body.clientHeight) || (document.documentElement && document.documentElement.clientHeight) || 0;

            return {
              emails: Array.from(emailSet),
              phones: Array.from(phoneSet),
              socials: socials,
              address: foundAddress,
              contactUrl: candidateContactUrl,
              booking_url: booking_url,
              platform_name: platform_name,
              bot_protection: bot_protection,
              cookie_status: cookie_status,
              hasCloudflare: hasCloudflare,
              bodyHeight: bodyHeight
            };
          }
        }, 4500).catch(err => {
          console.warn("[Mavon Extension] executeScript timed out or failed:", err);
          return null;
        });
        siteData = (siteExec && siteExec[0] && siteExec[0].result) ? siteExec[0].result : null;
      } catch (e) {
        console.warn("[Mavon Extension] Error inspecting site:", e);
      }

      let siteEmails = siteData ? (siteData.emails || []) : [];
      let sitePhones = siteData ? (siteData.phones || []) : [];
      let siteSocials = siteData ? (siteData.socials || {}) : {};
      let siteAddress = siteData ? (siteData.address || "") : "";
      const bot_protection = siteData ? (siteData.bot_protection || "Clean") : "Unresponsive / Blank Page";
      const cookie_status = siteData ? (siteData.cookie_status || "None") : "None";

      // Optional Subpage Crawling (Contact / About Us) if missing contacts or deep_crawl enabled
      if (!abortHarvester && siteData && siteData.contactUrl && (siteEmails.length === 0 || sitePhones.length === 0 || !siteAddress || payload.deep_crawl)) {
        try {
          const contactUrl = siteData.contactUrl;
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: "LOG",
              agent: "website",
              message: `🔍 [Website Agent] Deep crawling Contact/About subpage: ${contactUrl}`
            }));
          }
          await navigateTabAndWait(shopTabId, contactUrl, 6000);
          await new Promise(r => setTimeout(r, 1200));

          const subExec = await withTimeout(chrome.scripting.executeScript({
            target: { tabId: shopTabId },
            func: () => {
              const html = document.body ? (document.body.innerText + " " + document.body.innerHTML) : "";
              const emailMatches = html.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g) || [];
              const phoneMatches = html.match(/(?:\+?\d{1,4}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}/g) || [];

              let subAddr = "";
              const addrEl = document.querySelector('address, [itemprop="address"], [class*="address" i]');
              if (addrEl) subAddr = (addrEl.innerText || "").trim();

              return {
                emails: emailMatches,
                phones: phoneMatches,
                address: subAddr
              };
            }
          }), 4000).catch(() => null);

          if (subExec && subExec[0] && subExec[0].result) {
            const subRes = subExec[0].result;
            if (subRes.emails && subRes.emails.length > 0) {
              const mergedE = new Set([...siteEmails, ...subRes.emails.map(e => e.toLowerCase().trim())]);
              siteEmails = Array.from(mergedE);
            }
            if (subRes.phones && subRes.phones.length > 0) {
              const mergedP = new Set([...sitePhones, ...subRes.phones.map(p => p.trim())]);
              sitePhones = Array.from(mergedP);
            }
            if (!siteAddress && subRes.address) {
              siteAddress = subRes.address;
            }
          }
        } catch (subErr) {
          console.warn("[Mavon Extension] Error inspecting contact subpage:", subErr);
        }
      }

      const booking_url = siteData ? (siteData.booking_url || "") : "";
      const platform_name = siteData ? (siteData.platform_name || "") : "";

      let w_status = "no_contacts";
      if (!siteData) {
        let isSsl = false;
        try {
          const tabInfo = await chrome.tabs.get(shopTabId);
          const title = (tabInfo.title || "").toLowerCase();
          const tabUrl = (tabInfo.url || "").toLowerCase();
          if (title.includes("privacy") || title.includes("cert") || title.includes("ssl") || tabUrl.includes("cert") || tabUrl.includes("privacy")) {
            isSsl = true;
          }
        } catch (e) {}

        w_status = isSsl ? "unsafe_ssl" : "not_loading";
        if (shopTabId) chrome.tabs.update(shopTabId, { url: "about:blank" }).catch(() => {});
      } else {
        const hasContacts = (siteEmails.length > 0 || sitePhones.length > 0 || Object.values(siteSocials).some(Boolean));
        if (siteData.hasCloudflare) {
          w_status = hasContacts ? "bot_extracted" : "bot_blocked";
        } else if (siteData.bodyHeight < 50 && !hasContacts) {
          w_status = "not_loading";
        } else {
          w_status = hasContacts ? "contacts_found" : "no_contacts";
        }
      }

      const resolvedAddress = siteAddress || (lead.address && lead.address !== "N/A" ? lead.address : "") || "N/A";

      const cacheEntry = {
        email: siteEmails[0] || "N/A",
        emails: siteEmails,
        phone: sitePhones[0] || "N/A",
        phones: sitePhones,
        address: resolvedAddress,
        instagram: siteSocials.instagram || "",
        facebook: siteSocials.facebook || "",
        linkedin: siteSocials.linkedin || "",
        twitter: siteSocials.twitter || "",
        whatsapp: siteSocials.whatsapp || "",
        booking_url: booking_url,
        platform_name: platform_name,
        bot_protection,
        cookie_status,
        website_status: w_status
      };

      if (cleanDom) {
        exploredDomainsCache.set(cleanDom, cacheEntry);
      }

      totalInspected++;

      try {
        await fetch("http://localhost:8085/api/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: lead.id,
            name: lead.name,
            address: resolvedAddress,
            website: url,
            website_status: w_status,
            source_agent: "web",
            update_all_matching_domain: true,
            screenshot_base64: webScreenshotBase64 || null,
            ...cacheEntry
          })
        });
      } catch (e) {}

      if (ws && ws.readyState === WebSocket.OPEN) {
        if (!siteData) {
          const reasonMsg = (w_status === "unsafe_ssl") ? "SSL / Security warning" : "blank or unreachable";
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "website",
            message: `⚠️ [Website Agent] Site for '${lead.name}' was ${reasonMsg} (tagged as ${w_status}). Moving to next site...`
          }));
        } else {
          const socCount = Object.values(siteSocials).filter(Boolean).length;
          const statusLabel = (w_status === "contacts_found") ? "Contacts Found" : (w_status === "bot_extracted" ? "Bot Shield (Data Extracted)" : (w_status === "bot_blocked" ? "Bot Blocked" : "No Contacts"));
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "website",
            message: `✅ [Website] [${statusLabel}] Extracted ${siteEmails.length} emails, ${socCount} socials for ${lead.name}`
          }));
        }
      }

      // Check graceful stop after saving the current website
      if (abortHarvester) {
        console.log(`[Mavon Extension] Graceful stop: Finished saving '${lead.name}'. Exiting website queue loop...`);
        break;
      }

      await new Promise(r => setTimeout(r, 500));
    }
  }

  isWebsiteHarvesting = false;
  if (!isMapsHarvesting && !isPlatformHarvesting && !isLinkedinHarvesting) {
    await notifyJobFinished(totalInspected, abortHarvester);
  } else {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "website",
        message: `🏁 [Website Agent] Completed queue processing (${totalInspected} sites).`
      }));
    }
  }
}

// Native Extension LinkedIn Org Intelligence Harvesting Loop (Agent 3)
async function runLinkedInQueueLoop(payload, targetWinId) {
  if (isLinkedinHarvesting) {
    console.log("[Mavon Extension] LinkedIn harvesting loop already running");
    return;
  }
  isLinkedinHarvesting = true;
  isHarvesting = true;

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "LOG",
      agent: "linkedin",
      message: "💼 [Agent 3: LinkedIn] Org Intelligence Harvester active on Chrome Tab 3 (Syncing real session & employee rosters)"
    }));
  }

  let totalHarvested = 0;
  let emptyPolls = 0;

  while (!abortHarvester) {
    let pendingLeads = [];
    try {
      const res = await fetch("http://localhost:8085/api/leads/pending-linkedin?limit=15");
      if (res.ok) {
        const data = await res.json();
        pendingLeads = data.leads || [];
      }
    } catch (e) {
      console.warn("[Mavon Extension] Error fetching pending LinkedIn leads:", e);
    }

    if (pendingLeads.length === 0) {
      if (isMapsHarvesting || isWebsiteHarvesting || isPlatformHarvesting) {
        emptyPolls++;
        if (emptyPolls % 10 === 1 && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "linkedin",
            message: "⏳ [LinkedIn Agent] Waiting for companies discovered by Maps / Website..."
          }));
        }
        for (let i = 0; i < 6; i++) {
          await new Promise(r => setTimeout(r, 500));
          if (abortHarvester) break;
        }
        if (abortHarvester) break;
        if (emptyPolls >= 30) break;
        continue;
      } else {
        break;
      }
    }
    emptyPolls = 0;

    for (const lead of pendingLeads) {
      if (abortHarvester) break;
      const coName = (lead.name || "").trim();
      if (!coName) continue;

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LOG",
          agent: "linkedin",
          message: `🏢 [LinkedIn Agent] Resolving org roster for '${coName}'...`
        }));
      }

      // Check if lead already has a known company LinkedIn URL
      let targetUrl = (lead.linkedin_url && lead.linkedin_url.includes("/company/")) ? lead.linkedin_url : null;
      if (!targetUrl) {
        const cleanName = coName.replace(/\b(Pvt|Ltd|LLP|Inc|Private|Limited|Enterprises|Solutions|Services)\b/gi, '').trim() || coName;
        targetUrl = `https://www.linkedin.com/search/results/companies/?keywords=${encodeURIComponent(cleanName)}`;
      }

      try {
        await navigateTabAndWait(linkedinTabId, targetUrl, 7000);
        await new Promise(r => setTimeout(r, 1200));

        // Inject script to extract company link or employees
        const execRes = await withTimeout(chrome.scripting.executeScript({
          target: { tabId: linkedinTabId },
          func: () => {
            const results = [];
            if (window.location.href.includes("/search/results/companies/")) {
              const coLinks = document.querySelectorAll('a[href*="/company/"]:not([href*="ads"])');
              for (const l of coLinks) {
                const href = (l.href || "").split('?')[0].replace(/\/+$/, '');
                if (href.includes('/company/') && !href.includes('/setup') && !href.includes('/feed')) {
                  return { nextUrl: href + "/people/", employees: [] };
                }
              }
            }

            const cardSelectors = [
              '.org-people-profile-card', 'li.grid', '.artdeco-entity-lockup',
              '.org-people-card', 'div[data-view-name*="profile"]', '.entity-result'
            ];
            let cards = [];
            for (const sel of cardSelectors) {
              const found = document.querySelectorAll(sel);
              if (found && found.length > 0) { cards = Array.from(found); break; }
            }

            cards.forEach(card => {
              const nameEl = card.querySelector('.org-people-profile-card__profile-title, .entity-result__title-text, .artdeco-entity-lockup__title, h3, a');
              const titleEl = card.querySelector('.artdeco-entity-lockup__subtitle, .entity-result__primary-subtitle, .org-people-profile-card__profile-position, .subline');
              const linkEl = card.querySelector('a[href*="/in/"]');

              const fName = nameEl ? (nameEl.innerText || '').split('\n')[0].trim() : '';
              const jobTitle = titleEl ? (titleEl.innerText || '').split('\n')[0].trim() : 'Staff';
              const pUrl = linkEl ? linkEl.href.split('?')[0] : '';

              if (fName && fName.length >= 2 && !fName.toLowerCase().includes("linkedin member")) {
                let seniority = 'staff';
                const jt = jobTitle.toLowerCase();
                if (/ceo|founder|director|partner|owner|president|vp|chief/i.test(jt)) seniority = 'executive';
                else if (/manager|head|lead|supervisor|coordinator/i.test(jt)) seniority = 'management';

                results.push({
                  full_name: fName,
                  title: jobTitle,
                  seniority_level: seniority,
                  linkedin_profile_url: pUrl
                });
              }
            });

            return { nextUrl: null, employees: results };
          }
        }), 5000).catch(() => null);

        let resData = (execRes && execRes[0] && execRes[0].result) ? execRes[0].result : { employees: [] };

        if (resData.nextUrl && !abortHarvester) {
          await navigateTabAndWait(linkedinTabId, resData.nextUrl, 7000);
          await new Promise(r => setTimeout(r, 1500));

          const peopleExec = await withTimeout(chrome.scripting.executeScript({
            target: { tabId: linkedinTabId },
            func: () => {
              const results = [];
              const cardEls = document.querySelectorAll('.org-people-profile-card, li.grid, .artdeco-entity-lockup, div[data-view-name*="profile"]');
              cardEls.forEach(card => {
                const nameEl = card.querySelector('.org-people-profile-card__profile-title, .artdeco-entity-lockup__title, h3, a');
                const titleEl = card.querySelector('.artdeco-entity-lockup__subtitle, .org-people-profile-card__profile-position');
                const linkEl = card.querySelector('a[href*="/in/"]');
                const fName = nameEl ? (nameEl.innerText || '').split('\n')[0].trim() : '';
                const jobTitle = titleEl ? (titleEl.innerText || '').split('\n')[0].trim() : 'Staff';
                const pUrl = linkEl ? linkEl.href.split('?')[0] : '';
                if (fName && fName.length >= 2 && !fName.toLowerCase().includes("linkedin member")) {
                  let seniority = 'staff';
                  const jt = jobTitle.toLowerCase();
                  if (/ceo|founder|director|partner|owner|president|vp|chief/i.test(jt)) seniority = 'executive';
                  else if (/manager|head|lead|supervisor/i.test(jt)) seniority = 'management';
                  results.push({ full_name: fName, title: jobTitle, seniority_level: seniority, linkedin_profile_url: pUrl });
                }
              });
              return results;
            }
          }), 5000).catch(() => []);
          resData.employees = (peopleExec && peopleExec[0] && peopleExec[0].result) ? peopleExec[0].result : [];
        }

        const employees = resData.employees || [];
        totalHarvested += employees.length;

        if (employees.length > 0) {
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: "LINKEDIN_EMPLOYEES_FOUND",
              data: {
                company_name: coName,
                lead_id: lead.id,
                company_linkedin_url: resData.nextUrl ? resData.nextUrl.replace('/people/', '') : targetUrl,
                employees: employees
              }
            }));
            ws.send(JSON.stringify({
              type: "LOG",
              agent: "linkedin",
              message: `✅ [LinkedIn Agent] Extracted ${employees.length} personnel profiles for '${coName}'`
            }));
          }
        } else {
          try {
            await fetch("http://localhost:8085/api/save_employees", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ company_name: coName, lead_id: lead.id, employees: [] })
            });
          } catch(e){}
        }
      } catch (err) {
        console.warn(`[Mavon Extension] Error inspecting LinkedIn for ${coName}:`, err);
      }

      await new Promise(r => setTimeout(r, 600));
    }
  }

  isLinkedinHarvesting = false;
  if (!isMapsHarvesting && !isWebsiteHarvesting && !isPlatformHarvesting) {
    await notifyJobFinished(totalHarvested, abortHarvester);
  }
}

// Universal Modal & Overlay Cleanser for platform directories
async function dismissPlatformPopups(tabId) {
  if (!tabId) return;
  try {
    await execScriptWithTimeout({
      target: { tabId },
      func: () => {
        // 1. Dismiss standard close buttons
        const dismissSelectors = [
          'button[aria-label="Close"]', 'button[aria-label*="close" i]', 'button[aria-label*="dismiss" i]',
          'button[data-testid*="modal-close"]', 'button[data-testid="modal-container-close"]',
          '.modal-close', 'button.close', '[data-qa*="close"]', 'button[aria-label="Dismiss"]',
          '[data-qa="cookie-consent-accept"]', '#onetrust-accept-btn-handler', '.accept-cookies-button',
          'button[data-testid="cross-button"]', 'button[aria-label="Dismiss banner"]',
          'div[aria-label="Close"]', 'span[aria-label="Close"]'
        ];
        dismissSelectors.forEach(sel => {
          document.querySelectorAll(sel).forEach(el => { try { el.click(); } catch(e){} });
        });

        // 2. Click consent / agreement / confirmation buttons
        document.querySelectorAll('button, a[role="button"]').forEach(b => {
          const t = (b.innerText || '').toLowerCase().trim();
          if (['accept', 'accept all', 'agree', 'allow all', 'ok', 'continue without supporting', 'got it', 'not now', 'maybe later'].includes(t)) {
            try { b.click(); } catch(e){}
          }
        });

        // 3. Remove blocking fixed backdrops
        document.querySelectorAll('div[class*="backdrop" i], div[class*="overlay" i]').forEach(el => {
          try {
            const style = window.getComputedStyle(el);
            if (style.position === 'fixed' && !el.querySelector('article, [class*="card"]')) {
              el.remove();
            }
          } catch(e){}
        });
      }
    }, 2000).catch(() => {});
  } catch (e) {}
}

// Native Extension Single Platform Scraper Task (Agent 4)
async function scrapeSinglePlatformTab(platInfo, maxListings, locationName, targetWinId, platIdx) {
  const pName = platInfo.name || "Platform";
  const pUrl = platInfo.url;
  if (!pUrl) return 0;

  if (platformTabId) {
    try {
      await chrome.tabs.update(platformTabId, { active: true }).catch(() => {});
      if (targetWinId) await bringWindowToFront(targetWinId);
    } catch (_) {}
  }

  if (platIdx > 0) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "platform",
        message: `🔄 [Agent 4: Platform] Transitioning Tab 4 to Platform #${platIdx + 1}: ${pName} (${pUrl})...`
      }));
    }
    await navigateTabAndWait(platformTabId, pUrl, 12000);
    await new Promise(r => setTimeout(r, 1500));
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "LOG",
      agent: "platform",
      message: `🟣 [Agent 4: Platform - ${pName}] Live Directory Harvester active on Chrome Tab 4 (Target: ${maxListings} listings)`
    }));
  }

  // Handle cookie consent and dismissals in Tab 4
  await dismissPlatformPopups(platformTabId);

  // Wait for initial SPA hydration (venues/listings to render into DOM)
  let hydrated = false;
  for (let waitSec = 0; waitSec < 15; waitSec++) {
    if (abortHarvester) break;
    await dismissPlatformPopups(platformTabId);
    try {
      const checkRes = await execScriptWithTimeout({
        target: { tabId: platformTabId },
        func: () => {
          // Synthetic interaction to unthrottle React/Next.js background state
          try {
            window.dispatchEvent(new Event('focus'));
            window.dispatchEvent(new Event('resize'));
            window.scrollBy({ top: 10, behavior: 'instant' });
          } catch (_) {}

          const cards = document.querySelectorAll(
            'div[data-qa="venue-card"], div.venue-card, a[href*="/a/"], a[href*="/v/"], ' +
            'div[data-testid="card-container"], a[href*="/rooms/"], ' +
            'div[data-testid="serp-ia-card"], a[href*="/biz/"], ' +
            'div.listing_details, a[href*="_Review-"], article, [role="article"]'
          );
          return cards.length;
        }
      }, 2000).catch(() => null);
      const count = (checkRes && checkRes[0] && checkRes[0].result) ? checkRes[0].result : 0;
      if (count > 0) {
        hydrated = true;
        break;
      }
      if (waitSec === 3 && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LOG",
          agent: "platform",
          message: `⏳ [Agent 4: Platform - ${pName}] Waiting for directory cards to hydrate on Tab 4...`
        }));
      }
    } catch (_) {}
    await new Promise(r => setTimeout(r, 1000));
  }

  const seenUrls = new Set();
  const discoveredListings = [];
  let harvestedCount = 0;
  let consecutiveStagnant = 0;
  const maxScrollPasses = Math.max(60, Math.min(400, Math.ceil(maxListings / 5) * 3 + 12));

  // =========================================================================
  // PHASE 1: DIRECTORY SCROLL & LISTING CARD DISCOVERY
  // =========================================================================
  for (let scrollPass = 1; scrollPass <= maxScrollPasses; scrollPass++) {
    if (abortHarvester || harvestedCount >= maxListings) break;

    let batchResults = [];
    try {
      const execRes = await execScriptWithTimeout({
        target: { tabId: platformTabId },
        args: [locationName, pName],
        func: (locName, platformType) => {
          const results = [];
          const currUrl = window.location.href;
          const isAirbnb = currUrl.includes('airbnb');
          const isFresha = currUrl.includes('fresha');
          const isYelp = currUrl.includes('yelp');
          const isTripAdvisor = currUrl.includes('tripadvisor');

          let cardSelectors = [];
          if (isAirbnb) {
            cardSelectors = ['div[data-testid="card-container"]', 'div[itemprop="itemListElement"]', 'div[aria-labelledby*="title_"]', 'a[href*="/rooms/"]'];
          } else if (isFresha) {
            cardSelectors = ['div[data-qa="venue-card"]', 'div.venue-card', 'a[href*="/a/"]', 'a[href*="/v/"]', 'article'];
          } else if (isYelp) {
            cardSelectors = ['div[data-testid="serp-ia-card"]', 'li.border-color--default__09f24__Nrmcg', 'div[class*="container__"]'];
          } else if (isTripAdvisor) {
            cardSelectors = ['div.listing_details', 'div.listItem', 'div.result-card'];
          } else {
            cardSelectors = ['article', '[role="article"]', 'div[data-testid*="card"]', 'div[data-testid*="listing"]', 'div.search-result', 'div.venue-card', 'div.listing-card'];
          }

          let cards = Array.from(document.querySelectorAll(cardSelectors.join(', ')));
          if (cards.length === 0) {
            const hLinks = document.querySelectorAll('main h2 a, main h3 a, #root h2 a, body h2 a');
            const seen = new Set();
            hLinks.forEach(hl => {
              const cont = hl.closest('article, [class*="card"], li, div');
              if (cont && !seen.has(cont) && cont !== document.body) {
                seen.add(cont);
                cards.push(cont);
              }
            });
          }

          const seenUrlsOnPage = new Set();
          cards.forEach((initialCard, c_idx) => {
            let linkEl = initialCard.matches('a[href]') ? initialCard : initialCard.querySelector('a[href]');
            if (!linkEl || !linkEl.href) return;

            let href = linkEl.href.split('?')[0].replace(/\/+$/, '');
            if (isAirbnb && !href.includes('/rooms/')) return;
            if (isFresha && !href.match(/\/(?:a|v|b|salon|venue|providers)\//i) && !initialCard.querySelector('[data-qa="venue-card"]')) return;
            if (isYelp && !href.includes('/biz/')) return;
            if (isTripAdvisor && !href.includes('_Review-')) return;
            if (href === currUrl.split('?')[0] || href.match(/\/(?:login|signin|signup|terms|privacy|cookie)\b/i)) return;

            if (seenUrlsOnPage.has(href)) return;
            seenUrlsOnPage.add(href);

            let card = initialCard;
            if (card.matches('a') || (card.innerText || '').trim().length < 5) {
              let parent = linkEl.closest('article, [class*="card"], li, div') || linkEl.parentElement;
              while (parent && parent.parentElement && (parent.innerText || '').trim().length < 5) {
                parent = parent.parentElement;
              }
              if (parent && (parent.innerText || '').trim().length >= 5) card = parent;
            }

            // Title
            let title = '';
            const titleEl = card.querySelector('[data-testid="listing-card-title"], div[id^="title_"], [data-qa="venue-name"], h2, h3, h4, .title, a.booking-link');
            if (titleEl) title = (titleEl.innerText || titleEl.textContent || '').trim();
            const aria = (linkEl.getAttribute('aria-label') || card.getAttribute('aria-label') || '').trim();
            if (!title && aria) title = aria.split(' - ')[0].split(' · ')[0].split(', rated')[0].trim();
            if (!title) {
              const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(s => s.length >= 3);
              if (lines.length > 0) title = lines[0];
            }
            if (!title || title.length < 3) return;

            const textToScan = (aria + ' ' + (card.innerText || '')).replace(/\s+/g, ' ');

            // Rating
            let ratingVal = 0.0;
            let mRate = textToScan.match(/(?:rated\s+|rating:?\s*|score:?\s*|★\s*)([0-5](?:\.\d+)?)/i);
            if (!mRate) mRate = textToScan.match(/\b([0-5](?:\.\d+)?)\s*(?:★|\/5\b|out of 5\b|\bstar(?:s)?\b)/i);
            if (mRate) ratingVal = parseFloat(mRate[1]);

            // Reviews
            let revCount = 0;
            const revEl = card.querySelector('[data-qa="reviews-count"], .review-count, [class*="review"]');
            const revText = revEl ? (revEl.innerText || '') : '';
            const revScan = revText + ' ' + textToScan;
            const mRev = revScan.match(/(?:from\s*|\(|\b)(\d[\d,]*)\s*(?:reviews?|ratings?)\b/i);
            if (mRev) revCount = parseInt(mRev[1].replace(/,/g, ''), 10);

            // Price
            let priceText = '';
            const priceEl = card.querySelector('[data-testid*="price"], [data-qa="price"], .price, [class*="price"]');
            if (priceEl) priceText = (priceEl.innerText || '').trim();

            // Address
            let address = locName;
            const addrEl = card.querySelector('address, [data-qa="venue-address"], [class*="address"]');
            if (addrEl) address = (addrEl.innerText || '').replace(/[\r\n]+/g, ' ').trim();

            // Category
            let cat = 'Directory';
            const catEl = card.querySelector('[data-qa*="category"], .category, [class*="category"]');
            if (catEl) cat = (catEl.innerText || '').trim();

            // Initial Hero Image
            let hero = '';
            const imgEl = card.querySelector('img[src^="http"]');
            if (imgEl && imgEl.src && !imgEl.src.includes('avatar') && !imgEl.src.includes('icon')) {
              hero = imgEl.src;
            }

            results.push({
              title: title.replace(/[\r\n]+/g, ' ').trim(),
              url: href,
              booking_url: href,
              address: address,
              category: cat,
              rating: ratingVal,
              reviews_count: revCount,
              price_info: priceText,
              screenshot: '',
              website_status: 'pending'
            });
          });

          return results;
        }
      }, 5000);
      batchResults = (execRes && execRes[0] && execRes[0].result) ? execRes[0].result : [];
    } catch (e) {
      console.warn("[Mavon Extension] Error extracting platform cards:", e);
    }

    let newInPass = 0;
    for (const item of batchResults) {
      if (seenUrls.has(item.url)) continue;
      seenUrls.add(item.url);
      discoveredListings.push(item);
      harvestedCount++;
      newInPass++;

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "PLATFORM_LISTING_FOUND",
          data: {
            platform: pName,
            ...item
          }
        }));
      }

      if (harvestedCount >= maxListings) break;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "platform",
        message: `📜 [Agent 4: Platform - ${pName}] Phase 1 Scroll Pass ${scrollPass}: Discovered ${harvestedCount}/${maxListings} listings (${newInPass} new).`
      }));
      ws.send(JSON.stringify({
        type: "PLATFORM_PROGRESS",
        data: {
          platform: pName,
          scraped: harvestedCount,
          total: maxListings,
          percent: Math.min(50, Math.round((harvestedCount / Math.max(1, maxListings)) * 50))
        }
      }));
    }

    if (newInPass === 0) {
      consecutiveStagnant++;

      // Try pagination if stagnant after multiple scroll passes
      if (consecutiveStagnant >= 2 && harvestedCount < maxListings) {
        let pageChanged = false;
        try {
          const pageRes = await execScriptWithTimeout({
            target: { tabId: platformTabId },
            func: () => {
              const u = new URL(window.location.href);
              const host = (window.location.hostname || "").toLowerCase();
              const isAirbnb = host.includes('airbnb');

              // 0. Ensure we scroll to the bottom so pagination footers are hydrated
              try {
                window.scrollTo(0, document.body.scrollHeight || document.documentElement.scrollHeight);
              } catch (_) {}

              // 1. Next button by selector (including Airbnb pagination nav)
              const nextSelectors = [
                'nav[aria-label*="pagination" i] a[aria-label*="next" i]',
                'nav[aria-label*="pagination" i] a[aria-label="Next"]',
                'nav[aria-label*="pagination" i] a:last-child',
                'nav[data-testid*="pagination" i] a[aria-label*="next" i]',
                'a[aria-label="Next"]', 'a[aria-label="Next page"]',
                'button[aria-label="Next"]', 'button[aria-label="Next page"]',
                'a[aria-label*="next" i]', 'button[aria-label*="next" i]',
                '[data-testid*="pagination-next"]', 'button[data-testid*="next"]',
                'a[rel="next"]', 'li.next a', 'a[class*="next" i]',
                '[data-qa*="pagination-next"]', 'a[data-qa="next-page"]'
              ];
              for (const sel of nextSelectors) {
                const btn = document.querySelector(sel);
                if (btn && !btn.disabled && !btn.getAttribute('aria-disabled')) {
                  try {
                    btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                    btn.click();
                    return true;
                  } catch (_) {}
                }
              }

              // 2. Numeric pagination - find current page + 1
              const activePageEl = document.querySelector('[aria-current="page"], .active[class*="page"], [class*="pagination"] [class*="selected"]');
              if (activePageEl) {
                const curPageNum = parseInt(activePageEl.innerText.trim(), 10);
                if (!isNaN(curPageNum)) {
                  const nextPageEl = Array.from(document.querySelectorAll('a, button')).find(el => el.innerText.trim() === String(curPageNum + 1));
                  if (nextPageEl) {
                    try {
                      nextPageEl.scrollIntoView({ behavior: 'instant', block: 'center' });
                      nextPageEl.click();
                      return true;
                    } catch (_) {}
                  }
                }
              }

              // 3. Platform-specific URL query parameter fallback
              if (isAirbnb) {
                try {
                  const curOffset = parseInt(u.searchParams.get("items_offset") || "0", 10);
                  const nextOffset = curOffset + 18;
                  u.searchParams.set("items_offset", String(nextOffset));
                  u.searchParams.set("pagination_search", "true");
                  window.location.href = u.toString();
                  return true;
                } catch (_) {}
              }

              // 4. Generic URL query parameter fallback
              try {
                const curPage = parseInt(u.searchParams.get("page") || "1", 10);
                u.searchParams.set("page", String(curPage + 1));
                window.location.href = u.toString();
                return true;
              } catch (_) {}

              return false;
            }
          }, 4000).catch(() => null);

          pageChanged = (pageRes && pageRes[0] && pageRes[0].result) ? true : false;
        } catch (_) {}

        if (pageChanged) {
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: "LOG",
              agent: "platform",
              message: `📄 [Agent 4: Platform - ${pName}] Next page navigation triggered (found: ${harvestedCount}/${maxListings}), hydrating new listings...`
            }));
          }
          await waitForTabLoaded(platformTabId, 8000);
          await new Promise(r => setTimeout(r, 2000));
          await dismissPlatformPopups(platformTabId);
          consecutiveStagnant = 0;
          scrollPass = Math.max(1, scrollPass - 2);
          continue;
        }
      }

      if (consecutiveStagnant >= 6) {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "platform",
            message: `🏁 [Agent 4: Platform - ${pName}] Phase 1 complete: Reached end of directory scroll (${harvestedCount} listings found).`
          }));
        }
        break;
      }
    } else {
      consecutiveStagnant = 0;
    }

    // Dismiss any popups that appeared after scrolling
    await dismissPlatformPopups(platformTabId);

    // Multi-container infinite scroll
    try {
      await execScriptWithTimeout({
        target: { tabId: platformTabId },
        func: () => {
          // 1. Scroll window and documentElement
          window.scrollBy({ top: 1400, behavior: "instant" });
          if (document.documentElement) document.documentElement.scrollTop += 1400;
          if (document.scrollingElement) document.scrollingElement.scrollTop += 1400;

          // 2. Dispatch synthetic wheel events
          try {
            window.dispatchEvent(new WheelEvent('wheel', { deltaY: 1200, bubbles: true }));
            document.dispatchEvent(new WheelEvent('wheel', { deltaY: 1200, bubbles: true }));
          } catch (_) {}

          // 3. Scroll any inner scrollable container (e.g. main, role=feed)
          const scrollables = document.querySelectorAll('main, [role="feed"], div[class*="list" i], div[class*="result" i], div[class*="scroll" i]');
          scrollables.forEach(s => {
            if (s.scrollHeight > s.clientHeight + 40) {
              s.scrollTop += 1400;
              try { s.dispatchEvent(new WheelEvent('wheel', { deltaY: 1200, bubbles: true })); } catch (_) {}
            }
          });
        }
      }, 2000).catch(() => {});
      await new Promise(r => setTimeout(r, 1500));
    } catch (e) {}
  }

  // =========================================================================
  // PHASE 2: INDIVIDUAL PAGE DEEP EXTRACTION (REPLICATING WEB AGENT IN TAB 4)
  // Sequentially visits each listing's direct URL to deeply extract emails,
  // phones, social links, official website, Google Maps link, anti-bot shield,
  // cookie diagnostics, and screenshot.
  // =========================================================================
  const totalDiscovered = discoveredListings.length;
  if (!abortHarvester && totalDiscovered > 0) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "platform",
        message: `🔍 [Agent 4: Platform - ${pName}] Launching Phase 2: Sequential Deep Page Inspection for ${totalDiscovered} listings...`
      }));
    }

    for (let idx = 0; idx < totalDiscovered; idx++) {
      if (abortHarvester) break;
      const listing = discoveredListings[idx];
      if (!listing.url || listing.url.startsWith("about:")) continue;

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LOG",
          agent: "platform",
          message: `🟣 [Agent 4: Platform] Deep inspecting (${idx + 1}/${totalDiscovered}): '${listing.title}'...`
        }));
      }

      try {
        ensureScreencastForTab(platformTabId, "platform").catch(() => {});
        await navigateTabAndWait(platformTabId, listing.url, 7000);
        await new Promise(r => setTimeout(r, 800));

        // Dismiss cookie banners & popups
        try {
          await execScriptWithTimeout({
            target: { tabId: platformTabId },
            func: () => {
              const dismissSelectors = [
                'button[aria-label="Close"]', 'button[aria-label*="close" i]',
                'button[data-testid*="modal-close"]', 'button[data-testid="modal-container-close"]',
                '.modal-close', 'button.close', '[data-qa*="close"]', 'button[aria-label="Dismiss"]'
              ];
              dismissSelectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => { try { el.click(); } catch(e){} });
              });
              document.querySelectorAll('button').forEach(b => {
                const t = (b.innerText || '').toLowerCase().trim();
                if (t === 'accept' || t === 'agree' || t === 'ok' || t === 'continue without supporting') {
                  try { b.click(); } catch(e){}
                }
              });
            }
          }, 2000).catch(() => {});
        } catch (e) {}

        // Ensure scroll is at top so header, photo collage & booking details are in full view
        try {
          await execScriptWithTimeout({
            target: { tabId: platformTabId },
            func: () => { window.scrollTo(0, 0); }
          }, 1000).catch(() => {});
          await new Promise(r => setTimeout(r, 400));
        } catch (e) {}

        // Capture actual visible webpage screenshot (header, photo collage, prices, booking box)
        let capturedPageScreenshotBase64 = null;
        try {
          if (chrome.debugger && platformTabId) {
            if (!attachedDebuggerTabs.has(platformTabId)) {
              try {
                await chrome.debugger.attach({ tabId: platformTabId }, "1.3");
                attachedDebuggerTabs.add(platformTabId);
              } catch (attErr) {
                if (String(attErr?.message || attErr).includes("already attached")) {
                  attachedDebuggerTabs.add(platformTabId);
                }
              }
            }
            const shot = await chrome.debugger.sendCommand(
              { tabId: platformTabId },
              "Page.captureScreenshot",
              { format: "jpeg", quality: 75 }
            );
            if (shot && shot.data) {
              capturedPageScreenshotBase64 = shot.data;
            }
          }
        } catch (shotErr) {
          console.warn("[Mavon Extension] Page.captureScreenshot error:", shotErr);
        }

        if (!capturedPageScreenshotBase64) {
          try {
            const tabInfo = await chrome.tabs.get(platformTabId).catch(() => null);
            if (tabInfo && tabInfo.active) {
              const dataUrl = await new Promise(res => {
                chrome.tabs.captureVisibleTab(tabInfo.windowId, { format: "jpeg", quality: 75 }, (u) => {
                  if (chrome.runtime.lastError || !u) res(null);
                  else res(u);
                });
              });
              if (dataUrl && dataUrl.includes(",")) {
                capturedPageScreenshotBase64 = dataUrl.split(",")[1];
              }
            }
          } catch (e) {}
        }

        // Scroll to trigger lazy loading of contact blocks
        try {
          await execScriptWithTimeout({
            target: { tabId: platformTabId },
            func: () => { window.scrollBy({ top: 500, behavior: 'smooth' }); }
          }, 1500).catch(() => {});
          await new Promise(r => setTimeout(r, 350));
        } catch (e) {}

        // In-page deep extraction replicating Web Agent logic
        const detailExec = await execScriptWithTimeout({
          target: { tabId: platformTabId },
          func: () => {
            const html = document.documentElement.innerHTML;
            const emailRegex = /([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)/g;
            const emailSet = new Set();
            const phoneSet = new Set();
            const socials = { instagram: "", facebook: "", linkedin: "", twitter: "", youtube: "", tiktok: "", whatsapp: "" };

            function decodeCf(hex) {
              try {
                if (!hex || hex.length < 4) return "";
                const k = parseInt(hex.substr(0, 2), 16);
                let em = "";
                for (let n = 2; n < hex.length; n += 2) {
                  em += String.fromCharCode(parseInt(hex.substr(n, 2), 16) ^ k);
                }
                return em.trim();
              } catch (e) { return ""; }
            }

            const cleanSocial = (u) => u.split('?')[0].split('#')[0].replace(/\/+$/, '');

            // 1. JSON-LD / schema extraction
            let foundAddress = "";
            let mapsUrl = "";
            let heroImage = "";
            let extWebsite = "";

            try {
              document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                try {
                  const raw = JSON.parse(s.innerText || s.textContent || "{}");
                  const items = Array.isArray(raw) ? raw : (raw['@graph'] || [raw]);
                  for (const it of items) {
                    if (it.email) {
                      const em = String(it.email).replace(/^mailto:/i, "").trim().toLowerCase();
                      if (em.includes("@")) emailSet.add(em);
                    }
                    if (it.telephone) {
                      const ph = String(it.telephone).replace(/^tel:/i, "").trim();
                      if (ph.length >= 7) phoneSet.add(ph);
                    }
                    if (it.url && typeof it.url === 'string') {
                      const uLow = it.url.toLowerCase();
                      if (!uLow.includes(window.location.hostname) && !uLow.includes('fresha.') && !uLow.includes('airbnb.') && !uLow.includes('yelp.') && !uLow.includes('tripadvisor.')) {
                        if (!extWebsite && it.url.startsWith('http')) extWebsite = it.url;
                      }
                    }
                    if (it.image) {
                      const imgVal = Array.isArray(it.image) ? it.image[0] : (typeof it.image === 'object' ? it.image.url : it.image);
                      if (imgVal && typeof imgVal === 'string' && imgVal.startsWith('http')) heroImage = imgVal;
                    }
                    if (it.hasMap && typeof it.hasMap === 'string') {
                      mapsUrl = it.hasMap;
                    }
                    if (it.geo && it.geo.latitude && it.geo.longitude) {
                      if (!mapsUrl) mapsUrl = `https://www.google.com/maps?q=${it.geo.latitude},${it.geo.longitude}`;
                    }
                    if (it.address && !foundAddress) {
                      if (typeof it.address === 'object') {
                        const parts = [it.address.streetAddress, it.address.addressLocality, it.address.addressRegion, it.address.postalCode].filter(Boolean);
                        if (parts.length >= 2) foundAddress = parts.join(', ');
                      } else if (typeof it.address === 'string' && it.address.length > 8) {
                        foundAddress = it.address.trim();
                      }
                    }
                    if (it.sameAs) {
                      const links = Array.isArray(it.sameAs) ? it.sameAs : [it.sameAs];
                      for (const l of links) {
                        const low = String(l).toLowerCase();
                        if (!socials.instagram && low.includes("instagram.com/")) socials.instagram = cleanSocial(l);
                        if (!socials.facebook && (low.includes("facebook.com/") || low.includes("fb.me/"))) socials.facebook = cleanSocial(l);
                        if (!socials.linkedin && low.includes("linkedin.com/")) socials.linkedin = cleanSocial(l);
                        if (!socials.twitter && (low.includes("twitter.com/") || low.includes("x.com/"))) socials.twitter = cleanSocial(l);
                        if (!socials.youtube && low.includes("youtube.com/")) socials.youtube = cleanSocial(l);
                        if (!socials.tiktok && low.includes("tiktok.com/")) socials.tiktok = cleanSocial(l);
                      }
                    }
                  }
                } catch(e) {}
              });
            } catch(e) {}

            // 2. Direct mailto links
            document.querySelectorAll('a[href^="mailto:"]').forEach(a => {
              const em = a.href.replace(/^mailto:/i, "").split("?")[0].trim().toLowerCase();
              if (em && em.includes("@") && !em.includes("sentry") && !em.includes("example.com")) emailSet.add(em);
            });

            // 3. Cloudflare protected emails
            document.querySelectorAll('a[href*="/cdn-cgi/l/email-protection#"]').forEach(a => {
              const p = a.href.split("#");
              if (p[1]) {
                const dec = decodeCf(p[1]);
                if (dec && dec.includes("@")) emailSet.add(dec.toLowerCase());
              }
            });

            // 4. Regex email extraction across HTML
            const ignoreExts = [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".js", ".css", ".woff", ".woff2", ".ttf"];
            const matches = html.match(emailRegex) || [];
            matches.forEach(e => {
              const lower = e.toLowerCase();
              if (!ignoreExts.some(ext => lower.endsWith(ext)) && !lower.includes("sentry") && !lower.includes("wixpress") && !lower.includes("schema.org") && !lower.includes("example.com") && !lower.includes("webpack")) {
                emailSet.add(lower);
              }
            });

            // 5. Phone numbers: tel links & text regex
            document.querySelectorAll('a[href^="tel:"]').forEach(a => {
              const ph = a.href.replace(/^tel:/i, "").split("?")[0].trim();
              if (ph.length >= 7) phoneSet.add(ph);
            });

            // 6. Social Media & External Website detection across anchors
            const platformHosts = ['fresha.com', 'airbnb.com', 'yelp.com', 'tripadvisor.com', 'treatwell.co', 'justdial.com', 'google.com', 'apple.com', 'play.google'];
            const allLinks = Array.from(document.querySelectorAll('a[href]'));

            allLinks.forEach(a => {
              const href = (a.href || '').trim();
              const lower = href.toLowerCase();
              if (!lower.startsWith('http')) return;

              if (!socials.instagram && lower.includes("instagram.com/") && !lower.includes("/p/") && !lower.includes("/explore") && !lower.includes("/reels")) {
                socials.instagram = cleanSocial(href);
              }
              if (!socials.facebook && (lower.includes("facebook.com/") || lower.includes("fb.com/")) && !lower.includes("sharer") && !lower.includes("/dialog")) {
                socials.facebook = cleanSocial(href);
              }
              if (!socials.linkedin && lower.includes("linkedin.com/") && (lower.includes("/company/") || lower.includes("/in/"))) {
                socials.linkedin = cleanSocial(href);
              }
              if (!socials.twitter && (lower.includes("twitter.com/") || lower.includes("x.com/")) && !lower.includes("intent") && !lower.includes("share")) {
                socials.twitter = cleanSocial(href);
              }
              if (!socials.youtube && lower.includes("youtube.com/") && !lower.includes("watch")) {
                socials.youtube = cleanSocial(href);
              }
              if (!socials.tiktok && lower.includes("tiktok.com/")) {
                socials.tiktok = cleanSocial(href);
              }
              if (!socials.whatsapp && (lower.includes("wa.me/") || lower.includes("api.whatsapp.com/send"))) {
                const m = href.match(/(?:wa\.me\/|phone=|\b)(\+?[0-9]{7,15})\b/);
                if (m) socials.whatsapp = m[1].replace(/[^0-9]/g, '');
              }

              // Google Maps Link
              if (!mapsUrl && (lower.includes('maps.google.') || lower.includes('goo.gl/maps') || lower.includes('maps.app.goo.gl') || lower.includes('/maps/place/'))) {
                mapsUrl = href;
              }

              // External Official Website
              if (!extWebsite) {
                const isPlatform = platformHosts.some(ph => lower.includes(ph));
                const isSocial = ['instagram.com', 'facebook.com', 'twitter.com', 'x.com', 'linkedin.com', 'youtube.com', 'tiktok.com', 'wa.me'].some(sh => lower.includes(sh));
                if (!isPlatform && !isSocial) {
                  const txt = (a.innerText || a.getAttribute('aria-label') || '').toLowerCase().trim();
                  if (txt.includes('website') || txt.includes('visit site') || txt.includes('official site') || a.querySelector('svg, i[class*="globe"], i[class*="web"]')) {
                    extWebsite = href;
                  }
                }
              }
            });

            // 7. Anti-Bot Shield & Cookie Diagnostics
            let bot_protection = "Clean";
            const titleLower = (document.title || "").toLowerCase();
            const htmlLower = html.toLowerCase();
            let hasBotChallenge = false;
            if (titleLower.includes("just a moment...") || titleLower.includes("attention required! | cloudflare")) {
              bot_protection = "Cloudflare";
              hasBotChallenge = true;
            } else if (htmlLower.includes("cf-turnstile") || htmlLower.includes("challenges.cloudflare.com") || document.querySelector('#cf-turnstile, #challenge-running, .cf-turnstile, .g-recaptcha, iframe[src*="challenges.cloudflare.com"]')) {
              bot_protection = "Cloudflare Turnstile";
              hasBotChallenge = true;
            } else if (titleLower.includes("datadome") || htmlLower.includes("datadome")) {
              bot_protection = "Datadome Challenge";
              hasBotChallenge = true;
            } else if (titleLower.includes("perimeterx") || htmlLower.includes("px-captcha")) {
              bot_protection = "PerimeterX";
              hasBotChallenge = true;
            }

            let cookie_status = "None";
            if (document.querySelector('#onetrust-banner-sdk, #CybotCookiebotDialog, .cmplz-cookiebanner, div[class*="cookie-banner" i], [id*="cookie" i]')) {
              cookie_status = "Accepted";
            }

            // 8. Screenshot is captured directly from visible viewport via Page.captureScreenshot

            // 9. Website Status
            const hasContacts = (emailSet.size > 0 || phoneSet.size > 0 || Object.values(socials).some(Boolean));
            let website_status = "no_contacts";
            if (hasBotChallenge) {
              website_status = hasContacts ? "bot_extracted" : "bot_blocked";
            } else if (hasContacts) {
              website_status = "contacts_found";
            } else {
              website_status = "clean";
            }

            return {
              emails: Array.from(emailSet),
              phones: Array.from(phoneSet),
              socials: socials,
              website: extWebsite,
              maps_url: mapsUrl,
              address: foundAddress,
              screenshot: "",
              bot_protection: bot_protection,
              cookie_status: cookie_status,
              website_status: website_status
            };
          }
        }, 5500).catch(err => {
          console.warn("[Mavon Extension] Error in deep inspection script:", err);
          return null;
        });

        const details = (detailExec && detailExec[0] && detailExec[0].result) ? detailExec[0].result : null;
        if (details) {
          if (details.emails && details.emails.length > 0) {
            listing.emails = details.emails;
            listing.email = details.emails[0];
          }
          if (details.phones && details.phones.length > 0) {
            listing.phones = details.phones;
            listing.phone = details.phones[0];
          }
          if (details.website && !listing.website) listing.website = details.website;
          if (details.maps_url && !listing.maps_url) listing.maps_url = details.maps_url;
          if (details.address && (!listing.address || listing.address.length < details.address.length)) listing.address = details.address;
          if (capturedPageScreenshotBase64) {
            listing.screenshot_base64 = capturedPageScreenshotBase64;
          }

          if (details.socials) {
            if (details.socials.instagram) listing.instagram = details.socials.instagram;
            if (details.socials.facebook) listing.facebook = details.socials.facebook;
            if (details.socials.linkedin) listing.linkedin = details.socials.linkedin;
            if (details.socials.twitter) listing.twitter = details.socials.twitter;
            if (details.socials.youtube) listing.youtube = details.socials.youtube;
            if (details.socials.tiktok) listing.tiktok = details.socials.tiktok;
            if (details.socials.whatsapp) listing.whatsapp = details.socials.whatsapp;
          }

          listing.bot_protection = details.bot_protection || "Clean";
          listing.cookie_status = details.cookie_status || "None";
          listing.website_status = details.website_status || "clean";
        }

        // Send enriched listing update to backend
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "PLATFORM_LISTING_FOUND",
            data: {
              platform: pName,
              ...listing,
              screenshot_base64: capturedPageScreenshotBase64 || null
            }
          }));
          const eCount = (listing.emails || []).length;
          const socFound = [listing.instagram, listing.facebook, listing.linkedin, listing.twitter, listing.youtube, listing.tiktok, listing.whatsapp].filter(Boolean).length;
          ws.send(JSON.stringify({
            type: "LOG",
            agent: "platform",
            message: `✅ [Agent 4: Platform] Deep Inspected '${listing.title}' -> Status: ${listing.website_status} | Emails: ${eCount} | Socials: ${socFound} | Phone: ${listing.phone || 'N/A'}`
          }));
          ws.send(JSON.stringify({
            type: "PLATFORM_PROGRESS",
            data: {
              platform: pName,
              scraped: idx + 1,
              total: totalDiscovered,
              percent: Math.min(100, Math.round(50 + ((idx + 1) / totalDiscovered) * 50))
            }
          }));
        }
      } catch (inspectErr) {
        console.warn(`[Mavon Extension] Error deep inspecting platform listing ${listing.url}:`, inspectErr);
      }
      await new Promise(r => setTimeout(r, 600));
    }
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "LOG",
      agent: "platform",
      message: `🏁 [Agent 4: Platform - ${pName}] Platform run complete: ${totalDiscovered} listings inspected.`
    }));
  }

  return totalDiscovered;
}

// Master Platform Directory Harvesting Loop (Agent 4) - Iterates across all selected platforms sequentially
async function runPlatformHarvestingLoop(payload, targetWinId) {
  if (isPlatformHarvesting) {
    console.log("[Mavon Extension] Platform harvesting loop already running");
    return;
  }
  isPlatformHarvesting = true;
  isHarvesting = true;

  const maxListings = parseInt(payload.max_results || 20);
  const locationName = payload.location || payload.query || "area";
  const platformsToScrape = (Array.isArray(payload.platforms) && payload.platforms.length > 0)
    ? payload.platforms
    : [{ name: payload.platform_name || "Platform", url: payload.platform_url }];

  let grandHarvestedCount = 0;
  try {
    for (let platIdx = 0; platIdx < platformsToScrape.length; platIdx++) {
      if (abortHarvester) break;
      const platInfo = platformsToScrape[platIdx];
      const harvested = await scrapeSinglePlatformTab(platInfo, maxListings, locationName, targetWinId, platIdx);
      grandHarvestedCount += (harvested || 0);
    }
  } catch (loopErr) {
    console.error("[Mavon Extension] Error in runPlatformHarvestingLoop:", loopErr);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "LOG",
        agent: "platform",
        message: `⚠️ [Agent 4: Platform] Harvesting error: ${loopErr.message || loopErr}`
      }));
    }
  } finally {
    isPlatformHarvesting = false;
    if (!isMapsHarvesting && !isWebsiteHarvesting && !isLinkedinHarvesting) {
      await notifyJobFinished(grandHarvestedCount, abortHarvester);
    }
  }
}

// Command dispatcher from backend or content scripts
async function handleCommand(msg) {
  const action = msg.action || msg.type;
  const payload = msg.payload || msg.data || {};

  if (action === "PING") {
    return { success: true, pong: true };
  }

  // Hot-reload extension worker upon request from backend or UI
  if (action === "RELOAD_EXTENSION") {
    console.log("[Mavon Extension] Hot-reload signal received, restarting runtime...");
    setTimeout(() => {
      try { chrome.runtime.reload(); } catch (e) {}
    }, 150);
    return { success: true, reloaded: true };
  }

  // Determine current active user window so tabs open in FRONT of user
  let targetWinId = msg.senderWindowId || null;
  if (!targetWinId) {
    try {
      const lastFocused = await chrome.windows.getLastFocused({ windowTypes: ['normal'] }).catch(() => null);
      if (lastFocused && lastFocused.id) {
        targetWinId = lastFocused.id;
      } else {
        const wins = await chrome.windows.getAll({ windowTypes: ['normal'] }).catch(() => []);
        if (wins && wins.length > 0) targetWinId = wins[0].id;
      }
    } catch (e) {}
  }

  // 1. START HARVESTER: Standardized across ALL agents (Maps, Website, LinkedIn, Platform)
  // Opens persistent tabs quietly (active: false) and drives live harvesting in active Chrome window
  if (action === "START_HARVESTER") {
    abortHarvester = false;
    isPlatformHarvesting = false;
    const now = Date.now();
    if (now - lastStartHarvesterTime < 1500 && (mapsTabId || platformTabId || shopTabId)) {
      console.log("[Mavon Extension] START_HARVESTER debounced (preventing duplicate tabs)");
      return { success: true, debounced: true };
    }
    lastStartHarvesterTime = now;

    // Proactively sync live LinkedIn session cookies so scraper never asks for login
    syncLinkedInCookies().catch(() => {});

    const enableMaps = payload.enable_maps !== false && Boolean(payload.maps_url || payload.url);
    const enableWebsite = payload.enable_website !== false;
    const enableLinkedin = payload.enable_linkedin === true || (payload.enable_linkedin !== false && Boolean(payload.linkedin_url));
    const enablePlatform = payload.enable_platform === true || (payload.enable_platform !== false && Boolean(payload.platform_url || (payload.platforms && payload.platforms.length > 0)));

    const mapsUrl = enableMaps ? (payload.maps_url || payload.url) : null;
    const linkedinUrl = enableLinkedin ? (payload.linkedin_url || "https://www.linkedin.com/") : null;
    let platformUrl = null;
    if (enablePlatform) {
      if (payload.platform_url) {
        platformUrl = payload.platform_url;
      } else if (payload.platforms && payload.platforms.length > 0 && payload.platforms[0].url) {
        platformUrl = payload.platforms[0].url;
      } else {
        const pLow = (payload.platform_name || "fresha").toLowerCase();
        const lEnc = encodeURIComponent(payload.location || "Mumbai");
        if (pLow.includes("fresha")) {
          platformUrl = `https://www.fresha.com/search?address=${lEnc}`;
        } else if (pLow.includes("airbnb")) {
          platformUrl = `https://www.airbnb.com/s/${lEnc}/homes`;
        } else if (pLow.includes("yelp")) {
          platformUrl = `https://www.yelp.com/search?find_loc=${lEnc}`;
        } else if (pLow.includes("tripadvisor")) {
          platformUrl = `https://www.tripadvisor.com/Search?q=${lEnc}`;
        } else if (pLow.includes("treatwell")) {
          platformUrl = `https://www.treatwell.co.uk/places/in-${lEnc}/`;
        } else if (pLow.includes("justdial")) {
          platformUrl = `https://www.justdial.com/${lEnc}`;
        } else {
          platformUrl = `https://www.${pLow}.com/search?q=${lEnc}`;
        }
      }
    }

    const initTasks = [];

    // Tab 1: Google Maps (Only if enabled) - Opened quietly with active: false in same window
    if (enableMaps && mapsUrl) {
      initTasks.push((async () => {
        let mapsTab = null;
        if (mapsTabId) {
          mapsTab = await chrome.tabs.get(mapsTabId).catch(() => null);
        }
        if (!mapsTab) {
          const allMaps = await chrome.tabs.query({ url: "*://*.google.com/maps/*" });
          if (allMaps.length > 0) {
            mapsTab = allMaps[0];
            mapsTabId = mapsTab.id;
            for (let i = 1; i < allMaps.length; i++) {
              chrome.tabs.remove(allMaps[i].id).catch(() => {});
            }
          }
        }
        if (mapsTab) {
          await navigateTabAndWait(mapsTab.id, mapsUrl, 10000);
          mapsTabId = mapsTab.id;
        } else {
          const createOpts = targetWinId ? { windowId: targetWinId, url: mapsUrl, active: false } : { url: mapsUrl, active: false };
          const t = await chrome.tabs.create(createOpts);
          mapsTabId = t.id;
          await waitForTabLoaded(mapsTabId, 12000);
        }
        ensureScreencastForTab(mapsTabId, "maps").catch(() => {});
      })());
    } else if (mapsTabId) {
      chrome.tabs.remove(mapsTabId).catch(() => {});
      mapsTabId = null;
    }

    // Tab 2: Dedicated Shop Website Tab (Persistent worker tab, opened quietly with active: false)
    if (enableWebsite) {
      initTasks.push((async () => {
        let siteTab = null;
        if (shopTabId) {
          siteTab = await chrome.tabs.get(shopTabId).catch(() => null);
        }
        if (!siteTab) {
          const createOpts = targetWinId ? { windowId: targetWinId, url: "about:blank", active: false } : { url: "about:blank", active: false };
          const tSite = await chrome.tabs.create(createOpts);
          shopTabId = tSite.id;
        }
        ensureScreencastForTab(shopTabId, "website").catch(() => {});
      })());
    } else if (shopTabId) {
      chrome.tabs.remove(shopTabId).catch(() => {});
      shopTabId = null;
    }

    // Tab 3: LinkedIn (Only if enabled) - Opened quietly with active: false
    if (enableLinkedin && linkedinUrl) {
      initTasks.push((async () => {
        let liTab = null;
        if (linkedinTabId) {
          liTab = await chrome.tabs.get(linkedinTabId).catch(() => null);
        }
        if (!liTab) {
          const allLi = await chrome.tabs.query({ url: "*://*.linkedin.com/*" });
          if (allLi.length > 0) {
            liTab = allLi[0];
            linkedinTabId = liTab.id;
            for (let i = 1; i < allLi.length; i++) {
              chrome.tabs.remove(allLi[i].id).catch(() => {});
            }
          }
        }
        if (liTab) {
          await chrome.tabs.update(liTab.id, { url: linkedinUrl });
          linkedinTabId = liTab.id;
        } else {
          const createOpts = targetWinId ? { windowId: targetWinId, url: linkedinUrl, active: false } : { url: linkedinUrl, active: false };
          const t2 = await chrome.tabs.create(createOpts);
          linkedinTabId = t2.id;
        }
        ensureScreencastForTab(linkedinTabId, "linkedin").catch(() => {});
      })());
    } else if (linkedinTabId) {
      chrome.tabs.remove(linkedinTabId).catch(() => {});
      linkedinTabId = null;
    }

    // Tab 4: Platform Directory Scout (Only if enabled) - Opened quietly with active: false
    if (enablePlatform && platformUrl) {
      initTasks.push((async () => {
        let platTab = null;
        if (platformTabId) {
          platTab = await chrome.tabs.get(platformTabId).catch(() => null);
        }
        if (!platTab) {
          const allPlats = await chrome.tabs.query({ url: ["*://*.fresha.com/*", "*://*.airbnb.com/*", "*://*.yelp.com/*", "*://*.tripadvisor.com/*"] }).catch(() => []);
          if (allPlats.length > 0) {
            platTab = allPlats[0];
            platformTabId = platTab.id;
            for (let i = 1; i < allPlats.length; i++) {
              chrome.tabs.remove(allPlats[i].id).catch(() => {});
            }
          }
        }
        if (platTab) {
          await navigateTabAndWait(platTab.id, platformUrl, 10000);
          platformTabId = platTab.id;
          await chrome.tabs.update(platformTabId, { active: true }).catch(() => {});
          if (targetWinId) await bringWindowToFront(targetWinId);
        } else {
          const createOpts = targetWinId ? { windowId: targetWinId, url: platformUrl, active: true } : { url: platformUrl, active: true };
          const t4 = await chrome.tabs.create(createOpts);
          platformTabId = t4.id;
          if (targetWinId) await bringWindowToFront(targetWinId);
          await waitForTabLoaded(platformTabId, 12000);
        }
        ensureScreencastForTab(platformTabId, "platform").catch(() => {});
      })());
    } else if (platformTabId) {
      chrome.tabs.remove(platformTabId).catch(() => {});
      platformTabId = null;
    }

    // Initialize all enabled tabs concurrently without blocking each other
    await Promise.allSettled(initTasks);

    // Launch harvesting loops asynchronously in background
    if (enableMaps && mapsTabId) {
      runMapsHarvestingLoop(payload, targetWinId).catch(err => {
        console.error("[Mavon Extension] Error in runMapsHarvestingLoop:", err);
      });
    }
    if (enableWebsite && shopTabId) {
      runWebsiteQueueLoop(payload, targetWinId).catch(err => {
        console.error("[Mavon Extension] Error in runWebsiteQueueLoop:", err);
      });
    }
    if (enableLinkedin && linkedinTabId) {
      runLinkedInQueueLoop(payload, targetWinId).catch(err => {
        console.error("[Mavon Extension] Error in runLinkedInQueueLoop:", err);
      });
    }
    if (enablePlatform && platformTabId) {
      runPlatformHarvestingLoop(payload, targetWinId).catch(err => {
        console.error("[Mavon Extension] Error in runPlatformHarvestingLoop:", err);
      });
    }

    return {
      success: true,
      harvesting: true,
      maps_tab_id: mapsTabId,
      website_tab_id: shopTabId,
      linkedin_tab_id: linkedinTabId,
      platform_tab_id: platformTabId
    };
  }

  // 1B. ABORT HARVESTER: Stops all running agent loops and cleans up all 4 persistent tabs cleanly
  if (action === "ABORT_HARVESTER" || action === "ABORT_CURRENT_ACTION") {
    console.log("[Mavon Extension] ABORT received! Setting abortHarvester = true...");
    abortHarvester = true;
    if (mapsTabId) {
      chrome.tabs.remove(mapsTabId).catch(() => {});
      mapsTabId = null;
    }
    if (linkedinTabId) {
      chrome.tabs.remove(linkedinTabId).catch(() => {});
      linkedinTabId = null;
    }
    if (platformTabId) {
      chrome.tabs.remove(platformTabId).catch(() => {});
      platformTabId = null;
    }
    if (shopTabId) {
      chrome.tabs.remove(shopTabId).catch(() => {});
      shopTabId = null;
    }
    await notifyJobFinished(0, true);
    return { success: true, aborted: true };
  }

  // 2B. NAVIGATE PLATFORM: Updates the Platform Directory tab in the user's active Chrome live
  if (action === "NAVIGATE_PLATFORM") {
    const targetUrl = payload.url;
    if (targetUrl) {
      let platTab = null;
      if (platformTabId) {
        platTab = await chrome.tabs.get(platformTabId).catch(() => null);
      }
      if (platTab) {
        await chrome.tabs.update(platTab.id, { url: targetUrl });
        platformTabId = platTab.id;
      } else {
        const createOpts = targetWinId ? { windowId: targetWinId, url: targetUrl, active: false } : { url: targetUrl, active: false };
        const t3 = await chrome.tabs.create(createOpts);
        platformTabId = t3.id;
      }
      ensureScreencastForTab(platformTabId, "platform").catch(() => {});
    }
    return { success: true, platform_tab_id: platformTabId };
  }

  // 2. NAVIGATE LINKEDIN: Updates the LinkedIn tab in the user's active Chrome live
  if (action === "NAVIGATE_LINKEDIN") {
    const targetUrl = payload.url;
    if (targetUrl) {
      let liTab = null;
      if (linkedinTabId) {
        liTab = await chrome.tabs.get(linkedinTabId).catch(() => null);
      }
      if (!liTab) {
        const allLi = await chrome.tabs.query({ url: "*://*.linkedin.com/*" });
        if (allLi.length > 0) {
          liTab = allLi[0];
          linkedinTabId = liTab.id;
        }
      }

      if (liTab) {
        await chrome.tabs.update(liTab.id, { url: targetUrl });
        linkedinTabId = liTab.id;
      } else {
        const createOpts = targetWinId ? { windowId: targetWinId, url: targetUrl, active: false } : { url: targetUrl, active: false };
        const t2 = await chrome.tabs.create(createOpts);
        linkedinTabId = t2.id;
      }
      ensureScreencastForTab(linkedinTabId, "linkedin").catch(() => {});
    }
    return { success: true, linkedin_tab_id: linkedinTabId };
  }

  // 3. OPEN SHOP TAB: Opens dynamically when shop website is processed, reuse single tab in background
  if (action === "OPEN_SHOP_TAB") {
    const shopUrl = payload.url || payload.website;
    if (!shopUrl || !shopUrl.startsWith("http")) {
      return { success: false, reason: "Invalid shop URL" };
    }

    let existingShopTab = null;
    if (shopTabId) {
      existingShopTab = await chrome.tabs.get(shopTabId).catch(() => null);
    }

    if (existingShopTab) {
      await chrome.tabs.update(shopTabId, { url: shopUrl });
    } else {
      const createOpts = targetWinId ? { windowId: targetWinId, url: shopUrl, active: false } : { url: shopUrl, active: false };
      const t = await chrome.tabs.create(createOpts);
      shopTabId = t.id;
    }

    ensureScreencastForTab(shopTabId, "website").catch(() => {});
    return { success: true, shop_tab_id: shopTabId };
  }

  // 4. ACTIVATE TAB: Switch active tab to view live agent actions
  if (action === "ACTIVATE_TAB") {
    const tabName = payload.tab || payload.agent;
    let targetId = null;
    if (tabName === "maps") targetId = mapsTabId;
    else if (tabName === "website") targetId = shopTabId;
    else if (tabName === "linkedin") targetId = linkedinTabId;
    else if (tabName === "platform") targetId = platformTabId;

    if (targetId) {
      try {
        await chrome.tabs.update(targetId, { active: true });
        const curTab = await chrome.tabs.get(targetId).catch(() => null);
        if (curTab && curTab.windowId) {
          await bringWindowToFront(curTab.windowId);
        }
      } catch (e) {}
    }
    return { success: true };
  }

  // 5. CLOSE SHOP TAB
  if (action === "CLOSE_SHOP_TAB") {
    if (shopTabId) {
      try {
        await chrome.tabs.remove(shopTabId);
      } catch (e) {}
      shopTabId = null;
    }
    return { success: true };
  }

  // 6. FOCUS WINDOW
  if (action === "FOCUS_WINDOW") {
    await bringWindowToFront(payload.window_id || targetWinId);
    return { success: true };
  }

  // 7. POPUP & CONTENT SCRIPT COMPATIBILITY ACTIONS
  if (action === "LAUNCH_LIVE_TAB") {
    const targetUrl = payload.url || msg.url || "https://www.google.com/maps/search/shops?hl=en";
    const createOpts = targetWinId ? { windowId: targetWinId, url: targetUrl, active: true } : { url: targetUrl, active: true };
    const newTab = await chrome.tabs.create(createOpts);
    mapsTabId = newTab.id;
    ensureScreencastForTab(newTab.id, "maps").catch(() => {});
    return { success: true, tabId: newTab.id };
  }

  if (action === "OPEN_BACKGROUND_TAB") {
    const targetUrl = payload.url || msg.url;
    if (!targetUrl || !targetUrl.startsWith("http")) return { success: false, reason: "Invalid URL" };
    const createOpts = targetWinId ? { windowId: targetWinId, url: targetUrl, active: false } : { url: targetUrl, active: false };
    const newTab = await chrome.tabs.create(createOpts);
    shopTabId = newTab.id;
    ensureScreencastForTab(newTab.id, "website").catch(() => {});
    return { success: true, tabId: newTab.id };
  }

  if (action === "CLOSE_TAB") {
    const tabIdToClose = payload.tabId || msg.tabId;
    if (tabIdToClose) {
      await chrome.tabs.remove(tabIdToClose).catch(() => {});
    }
    return { success: true };
  }

  return { success: true };
}

// Badge status on tab change
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url) {
    if (tab.url.includes("google.com/maps")) {
      chrome.action.setBadgeText({ tabId: tabId, text: "MAPS" });
      chrome.action.setBadgeBackgroundColor({ tabId: tabId, color: "#6366f1" });
    } else if (tab.url.includes("linkedin.com")) {
      chrome.action.setBadgeText({ tabId: tabId, text: "ORG" });
      chrome.action.setBadgeBackgroundColor({ tabId: tabId, color: "#818cf8" });
    } else if (tab.url.startsWith("http")) {
      chrome.action.setBadgeText({ tabId: tabId, text: "LIVE" });
      chrome.action.setBadgeBackgroundColor({ tabId: tabId, color: "#10b981" });
    } else {
      chrome.action.setBadgeText({ tabId: tabId, text: "" });
    }
  }
});
