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
        payload: { client: "chrome_extension", version: "2.2.0" }
      }));
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
      }
    });
  }
} catch (e) {}

// Initial connection
connect();

// Focus browser window
async function bringWindowToFront(windowId) {
  try {
    if (windowId) {
      await chrome.windows.update(windowId, { focused: true, state: "normal" });
    } else {
      const win = await chrome.windows.getCurrent();
      if (win) {
        await chrome.windows.update(win.id, { focused: true, state: "normal" });
      }
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
      const lastFocused = await chrome.windows.getLastFocused();
      if (lastFocused) targetWinId = lastFocused.id;
    } catch (e) {}
  }

  // 1. START HARVESTER: Opens by default 2 tabs: Tab 1 (Maps) and Tab 2 (LinkedIn)
  if (action === "START_HARVESTER") {
    const mapsUrl = payload.maps_url || payload.url || "https://www.google.com/maps/search/shops?hl=en";
    const linkedinUrl = payload.linkedin_url || "https://www.linkedin.com/";

    // Tab 1: Google Maps (active, foreground)
    if (mapsTabId) {
      try {
        await chrome.tabs.update(mapsTabId, { url: mapsUrl, active: true });
      } catch (e) {
        const createOpts = targetWinId ? { windowId: targetWinId, url: mapsUrl, active: true } : { url: mapsUrl, active: true };
        const t = await chrome.tabs.create(createOpts);
        mapsTabId = t.id;
      }
    } else {
      const createOpts = targetWinId ? { windowId: targetWinId, url: mapsUrl, active: true } : { url: mapsUrl, active: true };
      const t = await chrome.tabs.create(createOpts);
      mapsTabId = t.id;
    }

    // Tab 2: LinkedIn (opened by default alongside Maps)
    if (linkedinTabId) {
      try {
        await chrome.tabs.update(linkedinTabId, { url: linkedinUrl, active: false });
      } catch (e) {
        const createOpts = targetWinId ? { windowId: targetWinId, url: linkedinUrl, active: false } : { url: linkedinUrl, active: false };
        const t2 = await chrome.tabs.create(createOpts);
        linkedinTabId = t2.id;
      }
    } else {
      const createOpts = targetWinId ? { windowId: targetWinId, url: linkedinUrl, active: false } : { url: linkedinUrl, active: false };
      const t2 = await chrome.tabs.create(createOpts);
      linkedinTabId = t2.id;
    }

    // Bring Chrome window to front so user sees live what agent is doing
    const curTab = await chrome.tabs.get(mapsTabId).catch(() => null);
    const winToFocus = (curTab && curTab.windowId) ? curTab.windowId : targetWinId;
    if (winToFocus) {
      await bringWindowToFront(winToFocus);
    }

    // Attach screencast
    ensureScreencastForTab(mapsTabId, "maps").catch(() => {});
    ensureScreencastForTab(linkedinTabId, "linkedin").catch(() => {});

    return {
      success: true,
      maps_tab_id: mapsTabId,
      linkedin_tab_id: linkedinTabId
    };
  }

  // 2. OPEN SHOP TAB: Opens dynamically when shop website is processed, live in front of user
  if (action === "OPEN_SHOP_TAB") {
    const shopUrl = payload.url || payload.website;
    if (!shopUrl || !shopUrl.startsWith("http")) {
      return { success: false, reason: "Invalid shop URL" };
    }

    if (shopTabId) {
      try {
        await chrome.tabs.update(shopTabId, { url: shopUrl, active: true });
      } catch (e) {
        const createOpts = targetWinId ? { windowId: targetWinId, url: shopUrl, active: true } : { url: shopUrl, active: true };
        const t = await chrome.tabs.create(createOpts);
        shopTabId = t.id;
      }
    } else {
      const createOpts = targetWinId ? { windowId: targetWinId, url: shopUrl, active: true } : { url: shopUrl, active: true };
      const t = await chrome.tabs.create(createOpts);
      shopTabId = t.id;
    }

    // Ensure tab is active and window in front
    try {
      await chrome.tabs.update(shopTabId, { active: true });
      const curTab = await chrome.tabs.get(shopTabId).catch(() => null);
      if (curTab && curTab.windowId) {
        await bringWindowToFront(curTab.windowId);
      }
    } catch (e) {}

    ensureScreencastForTab(shopTabId, "website").catch(() => {});
    return { success: true, shop_tab_id: shopTabId };
  }

  // 3. ACTIVATE TAB: Switch active tab to view live agent actions
  if (action === "ACTIVATE_TAB") {
    const tabName = payload.tab || payload.agent;
    let targetId = null;
    if (tabName === "maps") targetId = mapsTabId;
    else if (tabName === "website") targetId = shopTabId;
    else if (tabName === "linkedin") targetId = linkedinTabId;

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

  // 4. CLOSE SHOP TAB
  if (action === "CLOSE_SHOP_TAB") {
    if (shopTabId) {
      try {
        await chrome.tabs.remove(shopTabId);
      } catch (e) {}
      shopTabId = null;
    }
    return { success: true };
  }

  // 5. FOCUS WINDOW
  if (action === "FOCUS_WINDOW") {
    await bringWindowToFront(payload.window_id || targetWinId);
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

// Support existing popup / content script messages
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  const action = request.action;

  if (action === "LAUNCH_LIVE_TAB") {
    const targetUrl = request.url || "https://www.google.com/maps/search/shops?hl=en";
    chrome.tabs.create({ url: targetUrl, active: true }, (newTab) => {
      mapsTabId = newTab.id;
      ensureScreencastForTab(newTab.id, "maps").catch(() => {});
      sendResponse({ success: true, tabId: newTab.id });
    });
    return true;
  }

  if (action === "OPEN_BACKGROUND_TAB") {
    const targetUrl = request.url;
    if (!targetUrl || !targetUrl.startsWith("http")) {
      sendResponse({ success: false, reason: "Invalid URL" });
      return true;
    }
    chrome.tabs.create({ url: targetUrl, active: false }, (newTab) => {
      shopTabId = newTab.id;
      ensureScreencastForTab(newTab.id, "website").catch(() => {});
      sendResponse({ success: true, tabId: newTab.id });
    });
    return true;
  }

  if (action === "CLOSE_TAB") {
    if (request.tabId) {
      chrome.tabs.remove(request.tabId, () => sendResponse({ success: true }));
      return true;
    }
  }
});
