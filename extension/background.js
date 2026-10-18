// ==============================================================================
// Mavon Leads Scraper - Background Service Worker (Manifest V3)
// Chrome Automation Bridge & Multi-Tab Orchestrator
// Connects live active Chrome with Dashboard, opens Maps & LinkedIn tabs,
// opens Shop Website tab on-demand, and streams live screencast frames.
// ==============================================================================

const WS_URL = "ws://127.0.0.1:8080/ws/extension";
const HEALTH_URL = "http://127.0.0.1:8080/api/health";

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
let abortHarvester = false;
const exploredDomainsCache = new Map();

// Check if backend is reachable before opening WebSocket
async function isBackendReachable() {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1200);
    const res = await fetch(HEALTH_URL, {
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
    const reachable = await isBackendReachable();
    if (!reachable) {
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
      return;
    }

    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return;
    }

    console.log("[Mavon Extension] Connecting to Dashboard WebSocket at", WS_URL);
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("[Mavon Extension] Connected to Mavon Dashboard!");
      ws.send(JSON.stringify({
        type: "HELLO",
        payload: { client: "chrome_extension", version: "2.2.2" }
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
      ws = null;
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };
  } catch (err) {
    console.debug("[Mavon Extension] Connection probe catch:", err);
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

// Listen for messages from content scripts (e.g. dashboard page)
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
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
    await fetch("http://localhost:8080/api/job-finished", {
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
      const existingRes = await fetch("http://localhost:8080/api/leads");
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
        await fetch("http://localhost:8080/api/save", {
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
  if (!isWebsiteHarvesting) {
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
        const res = await fetch("http://localhost:8080/api/leads/pending-websites?limit=20");
        if (res.ok) {
          const data = await res.json();
          pendingLeads = data.leads || [];
        }
      } catch (e) {
        console.warn("[Mavon Extension] Error fetching pending websites:", e);
      }
    }

    if (pendingLeads.length === 0) {
      // If Maps agent is still running, wait for more leads to be added
      if (isMapsHarvesting && !directTargets) {
        emptyPolls++;
        for (let i = 0; i < 8; i++) {
          await new Promise(r => setTimeout(r, 250));
          if (abortHarvester) break;
        }
        if (abortHarvester) break;
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
          await fetch("http://localhost:8080/api/save", {
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
          await fetch("http://localhost:8080/api/save", {
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
          await fetch("http://localhost:8080/api/save", {
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
        await fetch("http://localhost:8080/api/save", {
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
  if (shopTabId && !isMapsHarvesting) {
    chrome.tabs.remove(shopTabId).catch(() => {});
    shopTabId = null;
  }

  if (!isMapsHarvesting) {
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

// Command dispatcher from backend or content scripts
async function handleCommand(msg) {
  const action = msg.action || msg.type;
  const payload = msg.payload || msg.data || {};

  if (action === "PING") {
    return { success: true, pong: true };
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

  // 1. START HARVESTER: Opens Maps tab quietly (active: false) and drives live harvesting in active Chrome window
  if (action === "START_HARVESTER") {
    abortHarvester = false;
    const now = Date.now();
    if (now - lastStartHarvesterTime < 1500 && mapsTabId) {
      console.log("[Mavon Extension] START_HARVESTER debounced (preventing duplicate tabs)");
      return { success: true, debounced: true };
    }
    lastStartHarvesterTime = now;

    // Proactively sync live LinkedIn session cookies so scraper never asks for login
    syncLinkedInCookies().catch(() => {});

    const enableMaps = payload.enable_maps !== false && Boolean(payload.maps_url || payload.url);
    const enableLinkedin = payload.enable_linkedin === true || (payload.enable_linkedin !== false && Boolean(payload.linkedin_url));
    const enablePlatform = payload.enable_platform === true || (payload.enable_platform !== false && Boolean(payload.platform_url));

    const mapsUrl = enableMaps ? (payload.maps_url || payload.url) : null;
    const linkedinUrl = enableLinkedin ? (payload.linkedin_url || "https://www.linkedin.com/") : null;
    const platformUrl = enablePlatform ? payload.platform_url : null;

    // Tab 1: Google Maps (Only if enabled) - Opened quietly with active: false in same window
    if (enableMaps && mapsUrl) {
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
    } else if (mapsTabId) {
      chrome.tabs.remove(mapsTabId).catch(() => {});
      mapsTabId = null;
    }

    // Tab 2: LinkedIn (Only if enabled)
    if (enableLinkedin && linkedinUrl) {
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
    } else if (linkedinTabId) {
      chrome.tabs.remove(linkedinTabId).catch(() => {});
      linkedinTabId = null;
    }

    // Launch harvesting loops asynchronously in background
    if (enableMaps && mapsTabId) {
      runMapsHarvestingLoop(payload, targetWinId).catch(err => {
        console.error("[Mavon Extension] Error in runMapsHarvestingLoop:", err);
      });
    }
    if (payload.enable_website) {
      runWebsiteQueueLoop(payload, targetWinId).catch(err => {
        console.error("[Mavon Extension] Error in runWebsiteQueueLoop:", err);
      });
    }

    return {
      success: true,
      harvesting: true,
      maps_tab_id: mapsTabId,
      linkedin_tab_id: linkedinTabId
    };
  }

  // 1B. ABORT HARVESTER: Stops in-flight operations with graceful completion for current website
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

    // If website queue worker is not actively running, clean up and notify immediately.
    // If it is running, it will finish saving the current in-flight website, close shopTabId, and call notifyJobFinished.
    if (!isWebsiteHarvesting) {
      if (shopTabId) {
        chrome.tabs.remove(shopTabId).catch(() => {});
        shopTabId = null;
      }
      await notifyJobFinished(0, true);
    } else {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LOG",
          agent: "website",
          message: "⏳ [Website Agent] Stop requested: Gracefully completing current website before closing tab..."
        }));
      }
    }
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
