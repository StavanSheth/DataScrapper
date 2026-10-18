// ==============================================================================
// Mavon Leads Scraper - Premium Popup Controller
// Full two-way communication between Chrome tabs and Mavon FastAPI backend
// ==============================================================================

const API_BASE = "http://localhost:8080";

document.addEventListener("DOMContentLoaded", async () => {
  const badgeEl = document.getElementById("page-badge");
  const titleEl = document.getElementById("page-title");
  const resultsEl = document.getElementById("results");
  const serverDot = document.getElementById("server-dot");
  const serverText = document.getElementById("server-text");

  const btnScroll = document.getElementById("btn-scroll");
  const btnExtractFeed = document.getElementById("btn-extract-feed");
  const btnSaveFeed = document.getElementById("btn-save-feed");
  const btnSavePlace = document.getElementById("btn-save-place");
  const btnExtractSite = document.getElementById("btn-extract-site");
  const btnSaveSite = document.getElementById("btn-save-site");

  // 1. Check Backend Connectivity
  async function checkServerHealth() {
    try {
      const resp = await fetch(`${API_BASE}/api/status`, { method: "GET" });
      if (resp.ok) {
        const data = await resp.json();
        serverDot.classList.add("online");
        serverText.innerText = `:8080 Live (${data.count} leads)`;
        return true;
      }
    } catch (e) {}
    serverDot.classList.remove("online");
    serverText.innerText = ":8080 Offline";
    return false;
  }

  checkServerHealth();

  // 2. Detect Active Chrome Tab
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;

  const url = tab.url || "";
  const title = tab.title || "";
  titleEl.innerText = title || url;

  const isMapsPlace = url.includes("google.com/maps/place/") || url.includes("/maps/place/");
  const isMapsFeed = url.includes("google.com/maps") && !isMapsPlace;
  const isWebsite = url.startsWith("http") && !url.includes("google.com/maps");

  if (isMapsPlace) {
    badgeEl.className = "status-badge badge-place";
    badgeEl.innerText = "Maps: Place Detail";
    btnSavePlace.style.display = "flex";
    btnScroll.style.display = "none";
    btnExtractFeed.style.display = "none";
    btnSaveFeed.style.display = "none";
    btnExtractSite.style.display = "none";
    btnSaveSite.style.display = "none";
  } else if (isMapsFeed) {
    badgeEl.className = "status-badge badge-maps";
    badgeEl.innerText = "Maps: Search Feed";
    btnSavePlace.style.display = "none";
    btnScroll.style.display = "flex";
    btnExtractFeed.style.display = "flex";
    btnSaveFeed.style.display = "flex";
    btnExtractSite.style.display = "none";
    btnSaveSite.style.display = "none";
  } else if (isWebsite) {
    badgeEl.className = "status-badge badge-site";
    badgeEl.innerText = "Business Website";
    btnSavePlace.style.display = "none";
    btnScroll.style.display = "none";
    btnExtractFeed.style.display = "none";
    btnSaveFeed.style.display = "none";
    btnExtractSite.style.display = "flex";
    btnSaveSite.style.display = "flex";
  } else {
    badgeEl.className = "status-badge badge-other";
    badgeEl.innerText = "System Tab";
    btnSavePlace.style.display = "none";
    btnScroll.style.display = "none";
    btnExtractFeed.style.display = "none";
    btnSaveFeed.style.display = "none";
    btnExtractSite.style.display = "none";
    btnSaveSite.style.display = "none";
  }

  function showResults(text) {
    resultsEl.style.display = "block";
    resultsEl.innerText = text;
  }

  // Helper: Post lead to backend
  async function postLeadToBackend(lead) {
    try {
      const resp = await fetch(`${API_BASE}/api/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(lead)
      });
      const data = await resp.json();
      return resp.ok ? data : { status: "error", message: data.detail || "Server error" };
    } catch (e) {
      return { status: "error", message: "Cannot reach backend on http://localhost:8080" };
    }
  }

  // 0. Launch Live Agent in This Window
  const btnLaunchAgent = document.getElementById("btn-launch-agent");
  const agentQueryInput = document.getElementById("agent-query-input");
  if (btnLaunchAgent) {
    btnLaunchAgent.addEventListener("click", async () => {
      const q = (agentQueryInput && agentQueryInput.value.trim()) ? agentQueryInput.value.trim() : "dentist in mumbai";
      btnLaunchAgent.disabled = true;
      btnLaunchAgent.innerHTML = "<span>⏳</span> <span>Starting Agents...</span>";
      showResults(`🚀 Starting Live Agent for "${q}"...\nTriggering Mavon backend and opening tabs in this window.`);

      try {
        const resp = await fetch(`${API_BASE}/api/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: q,
            max_results: 20,
            visible_browser: true,
            enable_maps: true,
            enable_website: true,
            enable_linkedin: true
          })
        });
        const res = await resp.json();
        if (resp.ok) {
          showResults(`✅ Live Agent started for "${q}"!\nTabs are now actively running in this Chrome profile.`);
        } else {
          showResults(`⚠️ Server notice: ${res.detail || res.status || "Could not start"}`);
        }
      } catch (err) {
        showResults(`⚠️ Failed to connect to backend on ${API_BASE}. Ensure the Mavon server is running.`);
      } finally {
        btnLaunchAgent.disabled = false;
        btnLaunchAgent.innerHTML = "<span>🚀</span> <span>Launch Live Agent in This Window</span>";
      }
    });
  }

  // 3. Scroll Google Maps Feed
  btnScroll.addEventListener("click", () => {
    chrome.tabs.sendMessage(tab.id, { action: "SCROLL_FEED", amount: 900 }, (resp) => {
      if (chrome.runtime.lastError) {
        showResults("⚠️ Could not contact page. Reload the tab and try again.");
      } else {
        showResults("✅ Feed scrolled down to reveal more shops.");
      }
    });
  });

  // 4. Extract Places from Feed
  btnExtractFeed.addEventListener("click", () => {
    chrome.tabs.sendMessage(tab.id, { action: "EXTRACT_FEED" }, (resp) => {
      if (chrome.runtime.lastError || !resp) {
        showResults("⚠️ Make sure you are on a Google Maps search results page.");
      } else {
        const places = resp.places || [];
        if (places.length === 0) {
          showResults("🔍 No places found in feed yet. Try searching on Maps first.");
        } else {
          const lines = places.slice(0, 10).map(p => `#${p.index} ${p.name}`);
          showResults(`Found ${places.length} places in feed:\n` + lines.join("\n") + (places.length > 10 ? `\n...and ${places.length - 10} more` : ""));
        }
      }
    });
  });

  // 5. Save All Places in Feed to Database
  btnSaveFeed.addEventListener("click", async () => {
    showResults("⏳ Extracting places from feed...");
    chrome.tabs.sendMessage(tab.id, { action: "EXTRACT_FEED" }, async (resp) => {
      if (chrome.runtime.lastError || !resp || !resp.places || resp.places.length === 0) {
        showResults("⚠️ No places found in feed to save.");
        return;
      }
      const placesToSave = resp.places.map(p => ({
        name: p.name,
        maps_url: p.url,
        category: "Business",
        address: "N/A",
        phone: "N/A",
        website: "N/A"
      }));

      showResults(`⏳ Syncing ${placesToSave.length} places to Mavon database...`);
      try {
        const syncResp = await fetch(`${API_BASE}/api/save-batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ leads: placesToSave })
        });
        const syncData = await syncResp.json();
        if (syncResp.ok) {
          showResults(`🎉 Successfully synced ${syncData.saved} / ${placesToSave.length} places to Mavon database!\nCheck your live table at localhost:8080.`);
          checkServerHealth();
        } else {
          showResults(`⚠️ Server error: ${syncData.detail || "Failed to save"}`);
        }
      } catch (err) {
        showResults("⚠️ Could not connect to http://localhost:8080. Ensure the Mavon server is running.");
      }
    });
  });

  // 6. Save Google Maps Single Place
  btnSavePlace.addEventListener("click", () => {
    showResults("⏳ Extracting place details from DOM...");
    chrome.tabs.sendMessage(tab.id, { action: "EXTRACT_MAPS_PLACE" }, async (resp) => {
      if (chrome.runtime.lastError || !resp || !resp.place) {
        showResults("⚠️ Could not read place details. Ensure the place panel is fully loaded.");
        return;
      }
      const place = resp.place;
      showResults(`⏳ Saving '${place.name}' to database...`);
      const res = await postLeadToBackend(place);
      if (res.status === "success") {
        showResults(
          `🎉 Saved '${place.name}' to database!\n` +
          `• Phone: ${place.phone}\n` +
          `• Address: ${place.address}\n` +
          `• Website: ${place.website}\n` +
          `• Rating: ${place.rating} (${place.reviews} reviews)\n` +
          `• Plus Code: ${place.plus_code}`
        );
        checkServerHealth();
      } else {
        showResults(`⚠️ Save failed: ${res.message}`);
      }
    });
  });

  // 7. Extract Website Info (Emails, Phones & Socials)
  btnExtractSite.addEventListener("click", () => {
    chrome.tabs.sendMessage(tab.id, { action: "EXTRACT_SITE_INFO" }, (resp) => {
      if (chrome.runtime.lastError || !resp) {
        showResults("⚠️ Cannot access website content on this page.");
      } else {
        const emails = resp.emails || [];
        const phones = resp.phones || [];
        const socials = resp.socials || {};
        let output = `Emails (${emails.length}): ${emails.join(", ") || "None"}\n`;
        output += `Phones (${phones.length}): ${phones.join(", ") || "None"}\n\n`;
        output += `Socials:\n`;
        if (socials.instagram) output += `• Instagram: ${socials.instagram}\n`;
        if (socials.facebook) output += `• Facebook: ${socials.facebook}\n`;
        if (socials.linkedin) output += `• LinkedIn: ${socials.linkedin}\n`;
        if (socials.twitter) output += `• Twitter: ${socials.twitter}\n`;
        if (!socials.instagram && !socials.facebook && !socials.linkedin && !socials.twitter) {
          output += "• No social media profiles found.\n";
        }
        output += `\nShield: ${resp.bot_protection || "Clean"} | Cookies: ${resp.cookie_status || "None"}`;
        showResults(output);
      }
    });
  });

  // 8. Save Website Lead to Database
  btnSaveSite.addEventListener("click", () => {
    showResults("⏳ Scanning website and compiling lead...");
    chrome.tabs.sendMessage(tab.id, { action: "EXTRACT_SITE_INFO" }, async (resp) => {
      if (chrome.runtime.lastError || !resp) {
        showResults("⚠️ Cannot access website content on this page.");
        return;
      }
      const leadPayload = {
        name: resp.name || tab.title || "Business Lead",
        website: tab.url,
        email: resp.email || "N/A",
        phone: resp.phone || "N/A",
        category: "Website Lead",
        address: "N/A",
        instagram: resp.socials?.instagram || "",
        facebook: resp.socials?.facebook || "",
        linkedin: resp.socials?.linkedin || "",
        twitter: resp.socials?.twitter || "",
        bot_protection: resp.bot_protection || "Clean",
        cookie_status: resp.cookie_status || "None"
      };

      showResults(`⏳ Saving '${leadPayload.name}' to database...`);
      const res = await postLeadToBackend(leadPayload);
      if (res.status === "success") {
        showResults(
          `🎉 Lead saved to Mavon database!\n` +
          `• Name: ${leadPayload.name}\n` +
          `• Website: ${leadPayload.website}\n` +
          `• Email: ${leadPayload.email}\n` +
          `• Phone: ${leadPayload.phone}\n` +
          `• Socials: ${[leadPayload.instagram, leadPayload.facebook, leadPayload.linkedin, leadPayload.twitter].filter(Boolean).length} linked`
        );
        checkServerHealth();
      } else {
        showResults(`⚠️ Save failed: ${res.message}`);
      }
    });
  });
});
