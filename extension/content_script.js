// ==============================================================================
// Mavon Leads Scraper - Premium Chrome Assistant Content Script
// Bridges Chrome Extension API with page DOM & background worker
// ==============================================================================

(function() {
  // Inject the bridge script into the page's MAIN execution world
  function injectBridge() {
    try {
      const script = document.createElement("script");
      script.src = chrome.runtime.getURL("injected_bridge.js");
      script.onload = function() {
        this.remove();
      };
      (document.head || document.documentElement).appendChild(script);
    } catch (e) {
      console.error("[Mavon Extension] Bridge injection error:", e);
    }
  }

  injectBridge();

  // Listen for Dashboard start message so tabs open directly in this active window
  window.addEventListener("message", (event) => {
    if (event.data && event.data.source === "mavon_dashboard") {
      if (event.data.action === "START_LIVE_BROWSER_SCRAPING") {
        try {
          chrome.runtime.sendMessage({
            action: "START_HARVESTER",
            payload: {
              maps_url: event.data.url,
              linkedin_url: "https://www.linkedin.com/"
            }
          });
        } catch (e) {}
      }
    }
  });

  // 1. Cloudflare XOR email decoder
  function decodeCfEmail(hex) {
    try {
      if (!hex || hex.length < 4) return "";
      const k = parseInt(hex.substr(0, 2), 16);
      let email = "";
      for (let n = 2; n < hex.length; n += 2) {
        email += String.fromCharCode(parseInt(hex.substr(n, 2), 16) ^ k);
      }
      return email.trim();
    } catch (e) {
      return "";
    }
  }

  // 2. Extract detailed place info on Google Maps
  function extractGoogleMapsPlace() {
    const isPlace = window.location.href.includes("/maps/place/") || document.querySelector('h1.DUwDvf');
    if (!isPlace) return null;

    const titleEl = document.querySelector('h1.DUwDvf') || document.querySelector('.fontHeadlineLarge') || document.querySelector('h1');
    const name = titleEl ? titleEl.innerText.trim() : document.title.replace(/ - Google Maps.*/i, "").trim();

    let rating = "N/A";
    let reviews = "0";
    const starEl = document.querySelector('span[aria-label*="star"], span[role="img"][aria-label*="star"]');
    if (starEl) {
      const m = (starEl.getAttribute("aria-label") || "").match(/([0-9.]+)\s*star/i);
      if (m) rating = m[1];
    }
    const revEl = document.querySelector('span[aria-label*="review"], button[aria-label*="review"]');
    if (revEl) {
      const m = (revEl.getAttribute("aria-label") || revEl.innerText || "").match(/([\d,]+)\s*review/i);
      if (m) reviews = m[1].replace(/,/g, "");
    }

    // Category
    let category = "Business";
    const catEl = document.querySelector('button[jsaction*="category"], button.DkEaL, .fontBodyMedium button');
    if (catEl) category = catEl.innerText.trim() || category;

    // Address
    let address = "N/A";
    const addrEl = document.querySelector('button[data-item-id*="address"], [aria-label*="Address:"]');
    if (addrEl) {
      address = (addrEl.getAttribute("aria-label") || addrEl.innerText || "").replace(/^Address:\s*/i, "").trim();
    }

    // Phone
    let phone = "N/A";
    const phoneEl = document.querySelector('button[data-item-id*="phone"], [aria-label*="Phone:"]');
    if (phoneEl) {
      phone = (phoneEl.getAttribute("aria-label") || phoneEl.innerText || "").replace(/^Phone:\s*/i, "").trim();
    }

    // Website
    let website = "N/A";
    const webEl = document.querySelector('a[data-item-id="authority"], [aria-label*="Website:"]');
    if (webEl) {
      website = (webEl.getAttribute("href") || "").trim();
    }

    // Opening Hours
    let hours = "N/A";
    const hoursEl = document.querySelector('button[data-item-id*="oh"], [aria-label*="Hours:"]');
    if (hoursEl) {
      hours = (hoursEl.getAttribute("aria-label") || hoursEl.innerText || "").replace(/^Hours:\s*/i, "").split("\n")[0].trim();
    }

    // Plus code
    let plus_code = "N/A";
    const plusEl = document.querySelector('button[data-item-id="oloc"], [aria-label*="Plus code:"]');
    if (plusEl) {
      plus_code = (plusEl.getAttribute("aria-label") || plusEl.innerText || "").replace(/^Plus code:\s*/i, "").trim();
    }

    // Coordinates
    let lat = null, lon = null;
    const urlMatch = window.location.href.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
    if (urlMatch) {
      lat = parseFloat(urlMatch[1]);
      lon = parseFloat(urlMatch[2]);
    }

    return {
      name,
      category,
      rating,
      reviews,
      address,
      phone,
      website,
      hours,
      plus_code,
      lat,
      lon,
      maps_url: window.location.href,
      email: "N/A",
      instagram: "",
      facebook: "",
      linkedin: "",
      twitter: "",
      bot_protection: "Clean",
      cookie_status: "None"
    };
  }

  // 3. Extract Website Emails, Phones & Socials
  function extractWebsiteData() {
    const html = document.documentElement.innerHTML;
    const emailRegex = /([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)/g;
    const emailSet = new Set();

    // Standard mailto:
    document.querySelectorAll('a[href^="mailto:"]').forEach(a => {
      const email = a.href.replace(/^mailto:/i, "").split("?")[0].trim().toLowerCase();
      if (email && email.includes("@")) emailSet.add(email);
    });

    // Cloudflare decoded emails
    document.querySelectorAll('[data-cfemail]').forEach(el => {
      const decoded = decodeCfEmail(el.getAttribute('data-cfemail'));
      if (decoded && decoded.includes("@")) emailSet.add(decoded.toLowerCase());
    });
    document.querySelectorAll('a[href*="/cdn-cgi/l/email-protection#"]').forEach(a => {
      const parts = a.href.split("#");
      if (parts[1]) {
        const decoded = decodeCfEmail(parts[1]);
        if (decoded && decoded.includes("@")) emailSet.add(decoded.toLowerCase());
      }
    });

    // Regex text matching
    const matches = html.match(emailRegex) || [];
    const ignoreExts = [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".js", ".css", ".woff"];
    matches.forEach(e => {
      const lower = e.toLowerCase();
      if (!ignoreExts.some(ext => lower.endsWith(ext)) && !lower.includes("sentry") && !lower.includes("wixpress")) {
        emailSet.add(lower);
      }
    });

    // Phone numbers
    const phoneSet = new Set();
    document.querySelectorAll('a[href^="tel:"]').forEach(a => {
      const cleanPhone = a.href.replace(/^tel:/i, "").split("?")[0].trim();
      if (cleanPhone.length >= 7) phoneSet.add(cleanPhone);
    });

    // Social Media Links
    const socials = { instagram: "", facebook: "", linkedin: "", twitter: "" };
    document.querySelectorAll('a[href]').forEach(a => {
      const href = (a.href || "").trim();
      const lower = href.toLowerCase();
      if (!socials.instagram && lower.includes("instagram.com/") && !lower.includes("/p/") && !lower.includes("/explore")) {
        socials.instagram = href.split('?')[0].replace(/\/+$/, '');
      }
      if (!socials.facebook && lower.includes("facebook.com/") && !lower.includes("sharer")) {
        socials.facebook = href.split('?')[0].replace(/\/+$/, '');
      }
      if (!socials.linkedin && lower.includes("linkedin.com/")) {
        socials.linkedin = href.split('?')[0].replace(/\/+$/, '');
      }
      if (!socials.twitter && (lower.includes("twitter.com/") || lower.includes("x.com/")) && !lower.includes("intent")) {
        socials.twitter = href.split('?')[0].replace(/\/+$/, '');
      }
    });

    // Schema.org Structured Data
    document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
      try {
        const data = JSON.parse(s.innerText || "");
        const walk = (obj) => {
          if (!obj) return;
          if (typeof obj === 'string') {
            const l = obj.toLowerCase();
            if (l.includes("instagram.com/") && !socials.instagram && !l.includes("/p/")) socials.instagram = obj.split('?')[0];
            else if (l.includes("facebook.com/") && !socials.facebook && !l.includes("sharer")) socials.facebook = obj.split('?')[0];
            else if (l.includes("linkedin.com/") && !socials.linkedin) socials.linkedin = obj.split('?')[0];
            else if ((l.includes("twitter.com/") || l.includes("x.com/")) && !socials.twitter) socials.twitter = obj.split('?')[0];
            else if (obj.includes("@") && emailRegex.test(obj)) emailSet.add(obj.toLowerCase().trim());
          } else if (Array.isArray(obj)) {
            obj.forEach(walk);
          } else if (typeof obj === 'object') {
            if (obj.telephone) phoneSet.add(String(obj.telephone).trim());
            if (obj.email) emailSet.add(String(obj.email).toLowerCase().trim());
            Object.values(obj).forEach(walk);
          }
        };
        walk(data);
      } catch (e) {}
    });

    // Anti-Bot & Cookie Detection
    let bot_protection = "Clean";
    const titleLower = (document.title || "").toLowerCase();
    const htmlLower = html.toLowerCase();
    const bodyText = (document.body && document.body.innerText) ? document.body.innerText.toLowerCase() : "";
    const isHardBlocked = titleLower.includes("just a moment...") || titleLower.includes("attention required! | cloudflare") || titleLower.includes("403 forbidden") || titleLower.includes("access denied") || (bodyText.length < 500 && (titleLower.includes("security") || bodyText.includes("verify you are human")));

    if (titleLower.includes("just a moment...") || titleLower.includes("attention required! | cloudflare")) {
      bot_protection = "Cloudflare (Access Denied)";
    } else if (htmlLower.includes("cf-turnstile") || htmlLower.includes("challenges.cloudflare.com")) {
      bot_protection = isHardBlocked ? "Cloudflare Turnstile (Access Denied)" : "Cloudflare Turnstile (Access Granted)";
    } else if (htmlLower.includes("cf-ray") || htmlLower.includes("cloudflare ray id")) {
      bot_protection = isHardBlocked ? "Cloudflare (Access Denied)" : "Cloudflare (Access Granted)";
    } else if (htmlLower.includes("datadome")) {
      bot_protection = isHardBlocked ? "Datadome (Access Denied)" : "Datadome (Access Granted)";
    } else if (htmlLower.includes("perimeterx")) {
      bot_protection = isHardBlocked ? "PerimeterX (Access Denied)" : "PerimeterX (Access Granted)";
    } else if (htmlLower.includes("g-recaptcha") || htmlLower.includes("hcaptcha")) {
      bot_protection = isHardBlocked ? "Captcha Challenge (Access Denied)" : "Captcha Challenge (Access Granted)";
    } else if (isHardBlocked) {
      bot_protection = "Access Denied";
    }

    let cookie_status = "None";
    if (document.querySelector('#onetrust-banner-sdk, #CybotCookiebotDialog, .cmplz-cookiebanner, div[class*="cookie-banner" i]')) {
      cookie_status = "Detected";
    }

    const emails = Array.from(emailSet);
    const phones = Array.from(phoneSet);

    return {
      title: document.title,
      url: window.location.href,
      name: document.title.split(/[-|•:]/)[0].trim() || document.title,
      email: emails[0] || "N/A",
      emails: emails,
      phone: phones[0] || "N/A",
      phones: phones,
      socials: socials,
      bot_protection,
      cookie_status
    };
  }

  // Handle messages from Extension Popup or Background Worker
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    const action = request.action;

    if (action === "PING") {
      sendResponse({ status: "ok", url: window.location.href, title: document.title });
      return true;
    }

    if (action === "SCROLL_FEED") {
      window.dispatchEvent(new CustomEvent("mavon_scroll_feed", { detail: request.amount || 800 }));
      const feed = document.querySelector('div[role="feed"]') || document.querySelector('.m6QErb[aria-label]');
      if (feed) {
        feed.scrollBy({ top: request.amount || 800, behavior: "smooth" });
        sendResponse({ success: true, scrolled: true });
      } else {
        window.scrollBy({ top: request.amount || 800, behavior: "smooth" });
        sendResponse({ success: true, windowScrolled: true });
      }
      return true;
    }

    if (action === "EXTRACT_FEED") {
      const links = document.querySelectorAll('div[role="feed"] a.hfpxzc, a[href*="/maps/place/"]');
      const places = [];
      links.forEach((link, idx) => {
        const title = (link.getAttribute("aria-label") || link.innerText || "").trim();
        if (title) {
          places.push({
            index: idx + 1,
            name: title,
            url: link.href
          });
        }
      });
      sendResponse({ success: true, count: places.length, places: places });
      return true;
    }

    if (action === "EXTRACT_MAPS_PLACE") {
      const placeData = extractGoogleMapsPlace();
      sendResponse({ success: !!placeData, place: placeData });
      return true;
    }

    if (action === "EXTRACT_SITE_INFO") {
      const siteData = extractWebsiteData();
      sendResponse({ success: true, ...siteData });
      return true;
    }
  });

  // 4. Bridge with Mavon Dashboard on localhost:8080
  if (window.location.host === "localhost:8080" || window.location.host === "127.0.0.1:8080") {
    window.__MAVON_EXTENSION_ACTIVE__ = true;
    document.documentElement.setAttribute("data-mavon-extension", "true");
    window.dispatchEvent(new CustomEvent("mavon_extension_ready"));

    window.addEventListener("message", (event) => {
      if (event.data && event.data.source === "mavon_dashboard") {
        if (event.data.action === "START_LIVE_BROWSER_SCRAPING") {
          chrome.runtime.sendMessage({
            action: "LAUNCH_LIVE_TAB",
            url: event.data.url,
            query: event.data.query,
            max: event.data.max,
            scrapeWebsites: event.data.scrapeWebsites,
            radiusKm: event.data.radiusKm
          });
        }
      }
    });
  }

  // 5. Auto-Pilot Harvester on Google Maps
  if (window.location.hostname.includes("google.com") && window.location.pathname.includes("/maps")) {
    chrome.storage.local.get("mavon_task", (res) => {
      const task = res ? res.mavon_task : null;
      if (task && task.status === "running") {
        runMapsAutoPilot(task);
      }
    });
  }

  async function runMapsAutoPilot(task) {
    console.log("⚡ [Mavon Live Agent] Auto-pilot started on Maps:", task);
    const hud = showOnScreenHUD("Live Harvester Active", `Target: ${task.max} places for "${task.query}"`, "#6366f1");

    // Wait for feed container
    let feed = null;
    for (let i = 0; i < 30; i++) {
      feed = document.querySelector('div[role="feed"]') || document.querySelector('.m6QErb[aria-label]');
      if (feed) break;
      await new Promise(r => setTimeout(r, 600));
    }

    if (!feed) {
      updateHUD(hud, "Feed Not Found", "Please run a search or check results", "#ef4444");
      return;
    }

    let harvested = 0;
    const maxPlaces = task.max || 15;
    const seenNames = new Set();

    while (harvested < maxPlaces) {
      const links = feed.querySelectorAll('a.hfpxzc, a[href*="/maps/place/"]');
      let foundNew = false;

      for (const link of links) {
        if (harvested >= maxPlaces) break;
        const name = (link.getAttribute("aria-label") || link.innerText || "").trim();
        if (!name || seenNames.has(name)) continue;

        seenNames.add(name);
        foundNew = true;
        harvested++;

        updateHUD(hud, `Harvesting #${harvested}: ${name.substring(0, 25)}`, `Progress: ${harvested}/${maxPlaces}`, "#10b981");

        highlightElement(link);
        link.click();
        await new Promise(r => setTimeout(r, 1600));

        const placeData = extractGoogleMapsPlace();
        if (placeData) {
          try {
            await fetch("http://localhost:8080/api/save", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(placeData)
            });
          } catch (e) {}

          if (task.scrapeWebsites && placeData.website && placeData.website !== "N/A") {
            chrome.runtime.sendMessage({
              action: "OPEN_BACKGROUND_TAB",
              url: placeData.website
            });
          }
        }
      }

      if (harvested >= maxPlaces) break;

      updateHUD(hud, `Scrolling Feed...`, `Harvested ${harvested}/${maxPlaces}`, "#06b6d4");
      feed.scrollBy({ top: 1200, behavior: "smooth" });
      await new Promise(r => setTimeout(r, 2000));
    }

    updateHUD(hud, "Finished Successfully!", `Harvested ${harvested} places directly into Mavon DB`, "#10b981");
    chrome.storage.local.remove(["mavon_task"]);
    setTimeout(() => { if (hud) hud.remove(); }, 6000);
  }

  function showOnScreenHUD(title, subtitle, color) {
    let hud = document.getElementById("mavon-agent-hud");
    if (!hud) {
      hud = document.createElement("div");
      hud.id = "mavon-agent-hud";
      hud.style.position = "fixed";
      hud.style.top = "16px";
      hud.style.right = "16px";
      hud.style.zIndex = "2147483647";
      hud.style.background = "rgba(11, 15, 25, 0.94)";
      hud.style.color = "#ffffff";
      hud.style.border = `2px solid ${color}`;
      hud.style.borderRadius = "12px";
      hud.style.padding = "12px 18px";
      hud.style.fontFamily = "system-ui, -apple-system, sans-serif";
      hud.style.fontSize = "12px";
      hud.style.backdropFilter = "blur(12px)";
      hud.style.boxShadow = "0 8px 30px rgba(0, 0, 0, 0.7)";
      hud.style.pointerEvents = "none";
      document.body.appendChild(hud);
    }
    updateHUD(hud, title, subtitle, color);
    return hud;
  }

  function updateHUD(hud, title, subtitle, color) {
    if (!hud) return;
    hud.style.borderColor = color;
    hud.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; font-weight:700;">
        <span style="width:10px; height:10px; border-radius:50%; background:${color}; box-shadow:0 0 10px ${color};"></span>
        <span>⚡ MAVON LIVE AGENT: ${title}</span>
      </div>
      ${subtitle ? `<div style="margin-top:4px; font-size:11px; color:#94a3b8; font-weight:500;">${subtitle}</div>` : ""}
    `;
  }

  function highlightElement(el) {
    if (!el) return;
    document.querySelectorAll(".mavon-highlight-box").forEach(b => b.remove());
    const rect = el.getBoundingClientRect();
    const box = document.createElement("div");
    box.className = "mavon-highlight-box";
    box.style.position = "fixed";
    box.style.top = `${rect.top - 2}px`;
    box.style.left = `${rect.left - 2}px`;
    box.style.width = `${rect.width + 4}px`;
    box.style.height = `${rect.height + 4}px`;
    box.style.border = "3px solid #06b6d4";
    box.style.borderRadius = "6px";
    box.style.boxShadow = "0 0 20px rgba(6, 182, 212, 0.8)";
    box.style.pointerEvents = "none";
    box.style.zIndex = "2147483646";
    document.body.appendChild(box);
    setTimeout(() => box.remove(), 2500);
  }
})();
