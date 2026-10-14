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

if (chrome.debugger) {
  chrome.debugger.onEvent.addListener((source, method, params) => {
    if (method === "Page.screencastFrame" && params.data) {
      let workerTag = "maps";
      if (source.tabId === linkedinTabId) workerTag = "linkedin";
      if (source.tabId === shopTabId) workerTag = "website";

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "LIVE_FRAME",
          stream_type: workerTag,
          tab_id: source.tabId,
          image_base64: params.data
        }));
      }

      chrome.debugger.sendCommand(
        { tabId: source.tabId },
        "Page.screencastFrameAck",
        { sessionId: params.sessionId }
      ).catch(() => {});
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

  // 1. START HARVESTER: Opens by default 2 tabs: Tab 1 (Maps) and Tab 2 (LinkedIn) in user's active Chrome
  if (action === "START_HARVESTER") {
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

    // Tab 1: Google Maps (Only if enabled)
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
        await chrome.tabs.update(mapsTab.id, { url: mapsUrl, active: true });
        mapsTabId = mapsTab.id;
      } else {
        const createOpts = targetWinId ? { windowId: targetWinId, url: mapsUrl, active: true } : { url: mapsUrl, active: true };
        const t = await chrome.tabs.create(createOpts);
        mapsTabId = t.id;
      }
      ensureScreencastForTab(mapsTabId, "maps").catch(() => {});
    } else if (mapsTabId) {
      // Close Maps tab if user explicitly disabled it
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
        await chrome.tabs.update(liTab.id, { url: linkedinUrl, active: false });
        linkedinTabId = liTab.id;
      } else {
        const createOpts = targetWinId ? { windowId: targetWinId, url: linkedinUrl, active: false } : { url: linkedinUrl, active: false };
        const t2 = await chrome.tabs.create(createOpts);
        linkedinTabId = t2.id;
      }
      ensureScreencastForTab(linkedinTabId, "linkedin").catch(() => {});
    } else if (linkedinTabId) {
      // Close LinkedIn tab if user explicitly disabled it
      chrome.tabs.remove(linkedinTabId).catch(() => {});
      linkedinTabId = null;
    }

    // Tab 4: Platform Directory Scout (Only if enabled)
    if (enablePlatform && platformUrl) {
      let platTab = null;
      if (platformTabId) {
        platTab = await chrome.tabs.get(platformTabId).catch(() => null);
      }
      if (platTab) {
        await chrome.tabs.update(platTab.id, { url: platformUrl, active: false });
        platformTabId = platTab.id;
      } else {
        const createOpts = targetWinId ? { windowId: targetWinId, url: platformUrl, active: false } : { url: platformUrl, active: false };
        const t3 = await chrome.tabs.create(createOpts);
        platformTabId = t3.id;
      }
      ensureScreencastForTab(platformTabId, "platform").catch(() => {});
    } else if (platformTabId) {
      chrome.tabs.remove(platformTabId).catch(() => {});
      platformTabId = null;
    }

    // Bring Chrome window to front so user sees live what agent is doing
    const focusTabId = mapsTabId || platformTabId || linkedinTabId;
    if (focusTabId) {
      const curTab = await chrome.tabs.get(focusTabId).catch(() => null);
      const winToFocus = (curTab && curTab.windowId) ? curTab.windowId : targetWinId;
      if (winToFocus) {
        await bringWindowToFront(winToFocus);
      }
    }

    return {
      success: true,
      maps_tab_id: mapsTabId,
      linkedin_tab_id: linkedinTabId
    };
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
      await chrome.tabs.update(shopTabId, { url: shopUrl, active: false });
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
