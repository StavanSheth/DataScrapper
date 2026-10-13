// ==============================================================================
// Mavon Leads Scraper - Injected Bridge & Automation Controller
// Injected directly into the page context (MAIN world)
// ==============================================================================

(function() {
  if (window.__mavon_bridge_loaded) return;
  window.__mavon_bridge_loaded = true;

  // 1. Anti-Detection Spoofing
  try {
    delete Object.getPrototypeOf(navigator).webdriver;
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined,
      configurable: true
    });
  } catch (e) {}

  // 2. Mavon Scraper Controller Object
  window.MavonScraper = {
    version: "1.0.0",

    // --- On-Screen Agent HUD Overlay ---
    showHUD: function(title, subtitle = "", color = "#6366f1") {
      let hud = document.getElementById("mavon-agent-hud");
      if (!hud) {
        hud = document.createElement("div");
        hud.id = "mavon-agent-hud";
        hud.style.position = "fixed";
        hud.style.top = "16px";
        hud.style.right = "16px";
        hud.style.zIndex = "2147483640";
        hud.style.background = "rgba(11, 15, 25, 0.92)";
        hud.style.color = "#ffffff";
        hud.style.border = `1.5px solid ${color}`;
        hud.style.borderRadius = "10px";
        hud.style.padding = "10px 16px";
        hud.style.fontFamily = "system-ui, -apple-system, sans-serif";
        hud.style.fontSize = "12px";
        hud.style.backdropFilter = "blur(12px)";
        hud.style.boxShadow = "0 8px 24px rgba(0, 0, 0, 0.6)";
        hud.style.pointerEvents = "none";
        hud.style.transition = "all 0.25s ease";
        document.body.appendChild(hud);
      }
      hud.style.borderColor = color;
      hud.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px; font-weight:700; letter-spacing:0.03em;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${color}; box-shadow:0 0 8px ${color};"></span>
          <span>⚡ MAVON AGENT: ${title}</span>
        </div>
        ${subtitle ? `<div style="margin-top:4px; font-size:11px; color:#94a3b8; font-weight:500;">${subtitle}</div>` : ""}
      `;
    },

    removeHUD: function() {
      const hud = document.getElementById("mavon-agent-hud");
      if (hud) hud.remove();
    },

    // --- Element Highlighter ---
    highlight: function(element, label = "") {
      if (!element) return;
      document.querySelectorAll(".mavon-highlight-box").forEach(el => el.remove());

      const rect = element.getBoundingClientRect();
      const box = document.createElement("div");
      box.className = "mavon-highlight-box";
      box.style.position = "fixed";
      box.style.top = `${rect.top - 2}px`;
      box.style.left = `${rect.left - 2}px`;
      box.style.width = `${rect.width + 4}px`;
      box.style.height = `${rect.height + 4}px`;
      box.style.border = "2px solid #06b6d4";
      box.style.borderRadius = "6px";
      box.style.boxShadow = "0 0 14px rgba(6, 182, 212, 0.6)";
      box.style.pointerEvents = "none";
      box.style.zIndex = "2147483645";
      box.style.transition = "all 0.15s ease-out";

      if (label) {
        const tag = document.createElement("div");
        tag.style.position = "absolute";
        tag.style.top = "-22px";
        tag.style.left = "0";
        tag.style.background = "#06b6d4";
        tag.style.color = "#000000";
        tag.style.padding = "2px 8px";
        tag.style.fontSize = "10px";
        tag.style.fontWeight = "bold";
        tag.style.borderRadius = "4px";
        tag.innerText = label;
        box.appendChild(tag);
      }

      document.body.appendChild(box);
      setTimeout(() => box.remove(), 2500);
    },

    // --- Google Maps Feed Controller ---
    getFeedContainer: function() {
      return document.querySelector('div[role="feed"]') || document.querySelector('.m6QErb[aria-label]');
    },

    scrollFeed: function(amount = 900) {
      const feed = this.getFeedContainer();
      if (feed) {
        const prev = feed.scrollTop;
        feed.scrollBy({ top: amount, behavior: "smooth" });
        return { success: true, scrolled: true, scrollTop: feed.scrollTop, reachedBottom: (feed.scrollTop === prev) };
      }
      return { success: false, reason: "Feed container not found" };
    },

    // --- Google Maps Places Extractor ---
    extractPlacesFromFeed: function() {
      const feed = this.getFeedContainer();
      const results = [];
      const links = feed ? feed.querySelectorAll('a.hfpxzc, a[href*="/maps/place/"]') : document.querySelectorAll('a.hfpxzc');

      links.forEach((link, idx) => {
        const title = (link.getAttribute("aria-label") || link.innerText || "").trim();
        if (!title) return;

        const href = link.href || "";
        const parent = link.closest('div[jsaction]') || link.parentElement;
        let rating = "N/A";
        let reviews = "0";
        let category = "Business";

        if (parent) {
          const ratingEl = parent.querySelector('span[aria-label*="star"], span[role="img"][aria-label*="star"]');
          if (ratingEl) {
            const rText = ratingEl.getAttribute("aria-label") || "";
            const m = rText.match(/([0-9.]+)\s*star/i);
            if (m) rating = m[1];
          }
          const textContent = parent.innerText || "";
          const lines = textContent.split("\n").map(l => l.trim()).filter(Boolean);
          if (lines.length > 2) {
            category = lines[1] || category;
          }
        }

        results.push({
          index: idx + 1,
          name: title,
          url: href,
          rating: rating,
          reviews: reviews,
          category: category
        });
      });

      return results;
    },

    // --- Click Place Card by Index or Title ---
    clickPlace: function(identifier) {
      const feed = this.getFeedContainer();
      const links = feed ? feed.querySelectorAll('a.hfpxzc, a[href*="/maps/place/"]') : document.querySelectorAll('a.hfpxzc');

      for (let i = 0; i < links.length; i++) {
        const link = links[i];
        const title = (link.getAttribute("aria-label") || "").trim();
        if (i === identifier || (typeof identifier === "string" && title.toLowerCase().includes(identifier.toLowerCase()))) {
          this.highlight(link, `Target: ${title}`);
          link.click();
          return { success: true, clicked: title, index: i };
        }
      }
      return { success: false, reason: "Place card not found" };
    },

    // --- Auto Dismiss Cookie Banners ---
    autoDismissCookies: function() {
      const selectors = [
        'button#onetrust-accept-btn-handler',
        '#onetrust-accept-btn-handler',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        '#CybotCookiebotDialogBodyButtonAccept',
        'button.cmplz-accept',
        '.cmplz-btn.cmplz-accept',
        'button.osano-cm-accept-all',
        '.qc-cmp2-summary-buttons button[mode="primary"]',
        'button:has-text("Accept All Cookies")',
        'button:has-text("Accept all cookies")',
        'button:has-text("Accept All")',
        'button:has-text("Accept all")',
        'button:has-text("Allow all cookies")',
        'button:has-text("Allow All")',
        'button:has-text("I Accept")',
        'button:has-text("I Agree")',
        'button:has-text("Agree & Close")',
        'button:has-text("Agree")',
        'button:has-text("Accept")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        'button.cookie-banner__btn',
        '#cookie-accept',
        '.cc-btn.cc-allow',
        '.cc-accept-all'
      ];
      for (const sel of selectors) {
        try {
          let btn = null;
          if (sel.includes(':has-text(')) {
            const txt = sel.match(/:has-text\("([^"]+)"\)/)[1].toLowerCase();
            const tag = sel.split(':')[0];
            const elements = document.querySelectorAll(tag);
            for (const el of elements) {
              if (el.innerText && el.innerText.trim().toLowerCase() === txt && el.offsetParent !== null) {
                btn = el;
                break;
              }
            }
          } else {
            btn = document.querySelector(sel);
          }
          if (btn && typeof btn.click === 'function') {
            btn.click();
            return true;
          }
        } catch (e) {}
      }
      return false;
    },

    // --- Detect Cookie Status ---
    detectCookieStatus: function() {
      const bannerSels = [
        '#onetrust-banner-sdk', '#onetrust-consent-sdk', '#CybotCookiebotDialog',
        'div[id*="Cookiebot" i]', '.cmplz-cookiebanner', '.osano-cm-window',
        '.qc-cmp2-container', 'div.fc-consent-root', 'div[class*="cookie-banner" i]',
        'div[class*="cookie-notice" i]', 'div[class*="cookie-consent" i]'
      ];
      let present = false;
      for (const sel of bannerSels) {
        if (document.querySelector(sel)) { present = true; break; }
      }
      const dismissed = this.autoDismissCookies();
      if (dismissed) return "Accepted";
      if (present) return "Detected (Unaccepted)";
      return "None";
    },

    // --- General Website Socials & Email Harvester ---
    extractSocialsAndEmails: function() {
      const html = document.documentElement.innerHTML;
      const text = document.body ? document.body.innerText : "";

      // 1. Emails & Phone Extraction
      const emailRegex = /([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)/g;
      const emailSet = new Set();
      const phoneSet = new Set();

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

      document.querySelectorAll('a[href^="mailto:"]').forEach(a => {
        const email = a.href.replace(/^mailto:/i, "").split("?")[0].trim().toLowerCase();
        if (email && email.includes("@")) emailSet.add(email);
      });

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

      document.querySelectorAll('a[href^="tel:"]').forEach(a => {
        const ph = a.href.replace(/^tel:/i, "").split("?")[0].trim();
        if (ph.length >= 7) phoneSet.add(ph);
      });

      const matches = html.match(emailRegex) || [];
      matches.forEach(e => {
        const lower = e.toLowerCase();
        if (!lower.endsWith(".png") && !lower.endsWith(".jpg") && !lower.endsWith(".svg") && !lower.includes("sentry")) {
          emailSet.add(lower);
        }
      });

      // 2. Social Candidates Collection
      const candidates = { instagram: [], facebook: [], linkedin: [], twitter: [] };

      // A. Scan all anchor links
      document.querySelectorAll('a[href]').forEach(a => {
        const href = (a.href || "").trim();
        const lower = href.toLowerCase();
        if (lower.includes("instagram.com/")) candidates.instagram.push(href);
        else if (lower.includes("facebook.com/")) candidates.facebook.push(href);
        else if (lower.includes("linkedin.com/")) candidates.linkedin.push(href);
        else if (lower.includes("twitter.com/") || lower.includes("x.com/")) candidates.twitter.push(href);
      });

      // B. Scan JSON-LD structured data
      document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
        try {
          const data = JSON.parse(s.innerText || "");
          const walk = (obj) => {
            if (!obj) return;
            if (typeof obj === 'string') {
              const l = obj.toLowerCase();
              if (l.includes("instagram.com/")) candidates.instagram.push(obj);
              else if (l.includes("facebook.com/")) candidates.facebook.push(obj);
              else if (l.includes("linkedin.com/")) candidates.linkedin.push(obj);
              else if (l.includes("twitter.com/") || l.includes("x.com/")) candidates.twitter.push(obj);
            } else if (Array.isArray(obj)) {
              obj.forEach(walk);
            } else if (typeof obj === 'object') {
              Object.values(obj).forEach(walk);
            }
          };
          walk(data);
        } catch (e) {}
      });

      // C. Scan meta tags
      document.querySelectorAll('meta').forEach(m => {
        const content = (m.content || "").trim();
        if (!content) return;
        const lower = content.toLowerCase();
        if (lower.includes("instagram.com/")) candidates.instagram.push(content);
        else if (lower.includes("facebook.com/")) candidates.facebook.push(content);
        else if (lower.includes("linkedin.com/")) candidates.linkedin.push(content);
        else if (lower.includes("twitter.com/") || lower.includes("x.com/")) candidates.twitter.push(content);
      });

      // D. Filter clean canonical social links
      const cleanUrl = (u) => u.split('?')[0].split('#')[0].replace(/\/+$/, '');
      const socials = { instagram: "", facebook: "", linkedin: "", twitter: "" };

      // Instagram
      for (const raw of candidates.instagram) {
        const c = cleanUrl(raw);
        const l = c.toLowerCase();
        if (!l.includes('/p/') && !l.includes('/explore') && !l.includes('/reels') && !l.includes('sharer') && !l.includes('/about')) {
          const parts = c.split('/');
          if (parts.length >= 4 && parts[parts.length - 1].length > 1) {
            socials.instagram = c;
            break;
          }
        }
      }

      // Facebook
      for (const raw of candidates.facebook) {
        const c = cleanUrl(raw);
        const l = c.toLowerCase();
        if (!l.includes('sharer') && !l.includes('/dialog') && !l.includes('/plugins') && !l.includes('/tr') && !l.includes('/policies')) {
          socials.facebook = c;
          break;
        }
      }

      // LinkedIn
      for (const raw of candidates.linkedin) {
        const c = cleanUrl(raw);
        const l = c.toLowerCase();
        if (l.includes('/company/') || l.includes('/in/')) {
          socials.linkedin = c;
          break;
        }
      }

      // Twitter / X
      for (const raw of candidates.twitter) {
        const c = cleanUrl(raw);
        const l = c.toLowerCase();
        if (!l.includes('intent') && !l.includes('share') && !l.includes('widgets') && !l.includes('privacy')) {
          socials.twitter = c;
          break;
        }
      }

      return {
        title: document.title,
        url: window.location.href,
        emails: Array.from(emailSet),
        phones: Array.from(phoneSet),
        socials: socials
      };
    },

    // --- Anti-Bot Detection ---
    detectAntiBot: function() {
      const title = (document.title || "").toLowerCase();
      const html = (document.documentElement.innerHTML || "").toLowerCase();

      if (title.includes("just a moment...") || title.includes("attention required! | cloudflare")) {
        return "Cloudflare";
      }
      if (html.includes("cf-turnstile") || html.includes("challenges.cloudflare.com")) {
        return "Cloudflare Turnstile";
      }
      if (html.includes("dd.datadome.co") || html.includes("datadome")) {
        return "Datadome";
      }
      if (html.includes("px-captcha") || html.includes("perimeterx")) {
        return "PerimeterX";
      }
      if (html.includes("g-recaptcha") || html.includes("hcaptcha")) {
        return "Captcha Challenge";
      }
      return "Clean";
    }
  };

  // Auto-dismiss cookie banners on any page after 600ms
  setTimeout(() => {
    try { window.MavonScraper.autoDismissCookies(); } catch (e) {}
  }, 600);

  // If on Google Maps or website, display subtle ready status
  if (window.location.hostname.includes("google.com") && window.location.pathname.includes("/maps")) {
    window.MavonScraper.showHUD("Google Maps Active", "Scraper bridge connected & monitoring feed", "#10b981");
  }

  console.log("⚡ [Mavon Leads Scraper] Chrome Extension Injected & Ready.");
})();
