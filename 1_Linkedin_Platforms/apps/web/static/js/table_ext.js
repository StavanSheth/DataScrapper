function cleanDisplayUrl(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, '');
    const path = u.pathname.replace(/\/+$/, '');
    const shortPath = path.length > 20 ? path.substring(0, 18) + '…' : path;
    return host + shortPath;
  } catch (e) {
    return url.length > 25 ? url.substring(0, 22) + '…' : url;
  }
}
window.cleanDisplayUrl = cleanDisplayUrl;

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
window.escapeHtml = escapeHtml;

function formatDateTime(dateStr) {
  if (!dateStr || dateStr === 'N/A') return '<span class="badge badge-none">—</span>';
  try {
    const cleanStr = String(dateStr).trim().replace(' ', 'T');
    let d = new Date(cleanStr);
    if (isNaN(d.getTime())) d = new Date(cleanStr + 'Z');
    if (isNaN(d.getTime())) return `<span style="font-size:0.75rem; color:#94a3b8;">${escapeHtml(dateStr)}</span>`;
    const datePart = d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
    const timePart = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return `<div style="display:flex; flex-direction:column; gap:2px; font-size:0.75rem; white-space:nowrap;">
      <span style="color:#e2e8f0; font-weight:500;">📅 ${datePart}</span>
      <span style="color:#94a3b8; font-size:0.7rem;">🕒 ${timePart}</span>
    </div>`;
  } catch (e) {
    return `<span style="font-size:0.75rem; color:#94a3b8;">${escapeHtml(dateStr)}</span>`;
  }
}
window.formatDateTime = formatDateTime;

function getLeadWebsiteStatusTag(place) {
  if (!place) return 'In Queue';
  if (place.status_tag) return place.status_tag;

  const ws = String(place.website_status || '').toLowerCase().trim();
  const hasW = Boolean(place.website && place.website !== 'N/A' && String(place.website).trim() !== '');
  const hasE = Boolean(place.email && place.email !== 'N/A' && String(place.email).trim() !== '');
  const hasS = Boolean(
    (place.instagram && place.instagram !== 'N/A') ||
    (place.facebook && place.facebook !== 'N/A') ||
    (place.linkedin && place.linkedin !== 'N/A') ||
    (place.twitter && place.twitter !== 'N/A') ||
    (place.youtube && place.youtube !== 'N/A') ||
    (place.tiktok && place.tiktok !== 'N/A') ||
    (place.whatsapp && place.whatsapp !== 'N/A')
  );
  const bot = String(place.bot_protection || '').trim();

  if (!hasW || ws === 'no_website') return 'No Website';
  if (ws === 'pending' || (!ws && !place.website_scraped_at)) return 'In Queue';
  if (ws === 'unsafe_ssl') return 'Unsafe / SSL Error';
  if (ws === 'not_loading' || ws === 'unresponsive' || ws === 'failed') return 'Not Loading';
  if (ws === 'bot_blocked' || ((bot.includes('Denied') || bot.includes('Captcha')) && !hasE && !hasS)) return 'Bot Blocked';
  if (ws === 'bot_extracted' || ((bot.includes('Denied') || bot.includes('Captcha') || bot.includes('Cloudflare')) && (hasE || hasS))) return 'Bot Shield (Data Extracted)';
  if (ws === 'contacts_found' || ws === 'emails_found' || ws === 'socials_found' || ws === 'social' || hasE || hasS) return 'Contacts Found';
  if (ws === 'no_contacts' || ws === 'clean' || ws === 'found' || ws === 'scraped' || place.website_scraped_at) return 'No Contacts Found';
  return 'In Queue';
}
window.getLeadWebsiteStatusTag = getLeadWebsiteStatusTag;

function renderWebsiteStatusBadge(tag) {
  const t = String(tag || '').toLowerCase();
  if (t.includes('contacts found')) {
    return '<span class="badge" style="background:rgba(16,185,129,0.2); color:#34d399; border:1px solid rgba(16,185,129,0.4);">🟢 Contacts Found</span>';
  }
  if (t.includes('no contact')) {
    return '<span class="badge" style="background:rgba(59,130,246,0.2); color:#60a5fa; border:1px solid rgba(59,130,246,0.4);">🔵 No Contacts Found</span>';
  }
  if (t.includes('bot shield') || t.includes('extracted')) {
    return '<span class="badge" style="background:rgba(245,158,11,0.2); color:#fbbf24; border:1px solid rgba(245,158,11,0.4);">🟡 Bot Shield (Extracted)</span>';
  }
  if (t.includes('bot blocked')) {
    return '<span class="badge" style="background:rgba(168,85,247,0.2); color:#c084fc; border:1px solid rgba(168,85,247,0.4);">🟣 Bot Blocked</span>';
  }
  if (t.includes('not loading') || t.includes('unresponsive') || t.includes('failed')) {
    return '<span class="badge" style="background:rgba(239,68,68,0.2); color:#f87171; border:1px solid rgba(239,68,68,0.4);">🔴 Not Loading</span>';
  }
  if (t.includes('unsafe') || t.includes('ssl')) {
    return '<span class="badge" style="background:rgba(249,115,22,0.2); color:#fb923c; border:1px solid rgba(249,115,22,0.4);">🟠 Unsafe / SSL Error</span>';
  }
  if (t.includes('no website')) {
    return '<span class="badge" style="background:rgba(100,116,139,0.15); color:#64748b; border:1px solid rgba(100,116,139,0.25);">⚪ No Website</span>';
  }
  return '<span class="badge" style="background:rgba(100,116,139,0.2); color:#94a3b8; border:1px solid rgba(100,116,139,0.3);">⏳ In Queue</span>';
}
window.renderWebsiteStatusBadge = renderWebsiteStatusBadge;

function formatWebAgentDualDateTime(mapsDateStr, webDateStr, websiteStatus, websiteUrl) {
  function formatCompact(dStr) {
    if (!dStr || dStr === 'N/A' || dStr === '') return null;
    try {
      const cleanStr = String(dStr).trim().replace(' ', 'T');
      let d = new Date(cleanStr);
      if (isNaN(d.getTime())) d = new Date(cleanStr + 'Z');
      if (isNaN(d.getTime())) return null;
      const datePart = d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
      const timePart = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return { datePart, timePart };
    } catch (e) {
      return null;
    }
  }

  const mapsFormatted = formatCompact(mapsDateStr);
  const webFormatted = formatCompact(webDateStr);

  const mapsHtml = mapsFormatted
    ? `<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:3px 7px; background:rgba(56, 189, 248, 0.08); border:1px solid rgba(56, 189, 248, 0.22); border-radius:5px;" title="Maps Agent Discovered: ${escapeHtml(mapsDateStr || '')}">
         <span style="color:#38bdf8; font-weight:700; font-size:0.68rem; letter-spacing:0.3px; display:inline-flex; align-items:center; gap:3px;">
           <span>🗺️</span> Maps
         </span>
         <span style="font-size:0.72rem; color:#e2e8f0; font-weight:500; white-space:nowrap;">
           ${mapsFormatted.datePart} <span style="color:#94a3b8; font-size:0.67rem;">${mapsFormatted.timePart}</span>
         </span>
       </div>`
    : `<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:3px 7px; background:rgba(100, 116, 139, 0.08); border:1px solid rgba(100, 116, 139, 0.2); border-radius:5px;">
         <span style="color:#94a3b8; font-weight:700; font-size:0.68rem;">🗺️ Maps</span>
         <span style="color:#64748b; font-size:0.72rem;">—</span>
       </div>`;

  let webHtml = '';
  const hasWebUrl = Boolean(websiteUrl && websiteUrl !== 'N/A' && String(websiteUrl).trim() !== '');

  if (webFormatted) {
    webHtml = `<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:3px 7px; background:rgba(74, 222, 128, 0.08); border:1px solid rgba(74, 222, 128, 0.24); border-radius:5px;" title="Web Agent Inspected: ${escapeHtml(webDateStr || '')}">
         <span style="color:#4ade80; font-weight:700; font-size:0.68rem; letter-spacing:0.3px; display:inline-flex; align-items:center; gap:3px;">
           <span>🌐</span> Web
         </span>
         <span style="font-size:0.72rem; color:#bbf7d0; font-weight:500; white-space:nowrap;">
           ${webFormatted.datePart} <span style="color:#86efac; font-size:0.67rem;">${webFormatted.timePart}</span>
         </span>
       </div>`;
  } else if (!hasWebUrl) {
    webHtml = `<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:3px 7px; background:rgba(148, 163, 184, 0.06); border:1px dashed rgba(148, 163, 184, 0.2); border-radius:5px;">
         <span style="color:#94a3b8; font-weight:700; font-size:0.68rem;">🌐 Web</span>
         <span style="color:#64748b; font-size:0.70rem; font-style:italic;">No Website on Map</span>
       </div>`;
  } else if (websiteStatus === 'failed' || websiteStatus === 'not_loading' || websiteStatus === 'unresponsive') {
    webHtml = `<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:3px 7px; background:rgba(239, 68, 68, 0.08); border:1px solid rgba(239, 68, 68, 0.25); border-radius:5px;">
         <span style="color:#f87171; font-weight:700; font-size:0.68rem;">🌐 Web</span>
         <span style="color:#fca5a5; font-size:0.70rem; font-weight:600;">⚠️ Unreachable</span>
       </div>`;
  } else if (websiteStatus && websiteStatus !== 'pending') {
    // Lead is already inspected but webDateStr was null: fallback gracefully to maps date
    const fallbackDate = mapsFormatted ? `${mapsFormatted.datePart} <span style="color:#86efac; font-size:0.67rem;">${mapsFormatted.timePart}</span>` : 'Inspected';
    webHtml = `<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:3px 7px; background:rgba(74, 222, 128, 0.08); border:1px solid rgba(74, 222, 128, 0.24); border-radius:5px;" title="Web Agent Inspected">
         <span style="color:#4ade80; font-weight:700; font-size:0.68rem; letter-spacing:0.3px; display:inline-flex; align-items:center; gap:3px;">
           <span>🌐</span> Web
         </span>
         <span style="font-size:0.72rem; color:#bbf7d0; font-weight:500; white-space:nowrap;">
           ${fallbackDate}
         </span>
       </div>`;
  } else {
    webHtml = `<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:3px 7px; background:rgba(245, 158, 11, 0.08); border:1px dashed rgba(245, 158, 11, 0.3); border-radius:5px;">
         <span style="color:#fbbf24; font-weight:700; font-size:0.68rem;">🌐 Web</span>
         <span style="color:#fde68a; font-size:0.70rem;">⏳ Pending Queue</span>
       </div>`;
  }

  return `
    <div style="display:flex; flex-direction:column; gap:4px; min-width:180px; max-width:235px;">
      ${mapsHtml}
      ${webHtml}
    </div>
  `;
}
window.formatWebAgentDualDateTime = formatWebAgentDualDateTime;

function getItemTimeValue(item) {
  if (!item) return 0;
  let raw = '';
  if (window.currentTableTab === 'website' && item.website_scraped_at && item.website_scraped_at !== 'N/A') {
    raw = item.website_scraped_at;
  }
  if (!raw) {
    raw = item.created_at || item.found_datetime || item.scraped_at || item.timestamp || item.updated_at;
  }
  if (raw) {
    let cleanStr = String(raw).trim().replace(' ', 'T');
    let ms = new Date(cleanStr).getTime();
    if (isNaN(ms)) {
      ms = new Date(cleanStr + 'Z').getTime();
    }
    if (!isNaN(ms) && ms > 0) return ms;
  }
  const idNum = parseInt(item.id, 10);
  return !isNaN(idNum) && idNum > 0 ? idNum : 0;
}
window.getItemTimeValue = getItemTimeValue;

// =======================================================================
// TABLE EXTENSION & PLATFORM DIRECTORY MANAGER (LIVE 3-TABLES & MODAL)
// =======================================================================

window.currentTableTab = 'platform'; // Default active view for 1_Linkedin_Platforms
window.tablesSplitData = {
  master_leads: [],
  unmatched_maps: [],
  unmatched_platform: [],
  website_leads: [],
  linkedin_leads: [],
  counts: { master: 0, maps: 0, platform: 0, website: 0, linkedin: 0 },
  queue_progress: {}
};
window.activeTagFilter = 'All';

window.switchTableTab = function(tab) {
  window.currentTableTab = tab;
  window.activeTagFilter = 'All';
  if (window.selectedRowIds) {
    window.selectedRowIds.clear();
    if (typeof window.updateBatchBar === 'function') window.updateBatchBar();
  }
  ['master', 'maps', 'website', 'linkedin', 'platform'].forEach(t => {
    const btn = document.getElementById('btn-tab-' + t);
    if (btn) btn.classList.toggle('active', t === tab);
  });
  const titleEl = document.getElementById('current-table-title');
  if (titleEl) {
    if (tab === 'master') titleEl.innerText = '🌟 Master Normalized Leads (Cross-Verified Across Maps & Platforms)';
    else if (tab === 'maps') titleEl.innerText = '🗺️ Google Maps Leads (Fast Stream Ingestion)';
    else if (tab === 'website') titleEl.innerText = '🌐 Website Inspector Leads (Email & Anti-Bot Discovery)';
    else if (tab === 'linkedin') titleEl.innerText = '💼 LinkedIn Org Harvester (Workforce & Decision Makers)';
    else if (tab === 'platform') titleEl.innerText = '🟣 Platform Directory Listings (All Records)';
  }
  if (typeof window.renderTagFilterBar === 'function') {
    window.renderTagFilterBar();
  }
  if (typeof window.renderFiltersForCurrentTable === 'function') {
    window.renderFiltersForCurrentTable();
  }
  window.renderTable();
};


window.updatePlatformSyncCard = function(breakdown, summary) {
  breakdown = breakdown || {};
  summary = summary || {};

  const bPlat = document.getElementById('sync-bar-plat');
  const sPlat = document.getElementById('sync-stat-plat');
  const cPlatScraped = document.getElementById('sync-chip-plat-scraped');
  const cPlatBooking = document.getElementById('sync-chip-plat-booking');
  const cPlatRated = document.getElementById('sync-chip-plat-rated');
  const cPlatMatched = document.getElementById('sync-chip-plat-matched');
  const cPlatPending = document.getElementById('sync-chip-plat-pending');
  const listContainer = document.getElementById('sync-platform-breakdown-list');

  // Check if Platform Scout agent toggle is active
  const platToggle = document.getElementById('agent-platform-toggle');
  const isPlatEnabled = platToggle ? platToggle.checked : true;

  if (!isPlatEnabled) {
    if (bPlat) bPlat.style.width = '0%';
    if (sPlat) sPlat.innerText = 'Agent Disabled';
    if (cPlatScraped) cPlatScraped.innerText = '✅ Scraped: 0';
    if (cPlatBooking) cPlatBooking.innerText = '🔗 Booking: 0';
    if (cPlatRated) cPlatRated.innerText = '⭐ Rated: 0';
    if (cPlatMatched) cPlatMatched.innerText = '🌟 Matched: 0';
    if (cPlatPending) cPlatPending.innerText = '⏳ In Queue: 0';
    if (listContainer) {
      listContainer.innerHTML = '<span style="font-size:0.7rem; color:#94a3b8; font-style:italic;">Platform Directory Scout is toggled OFF.</span>';
    }
    return;
  }

  // Get ONLY platforms that are currently selected in the UI checkboxes
  const selectedCbs = document.querySelectorAll('.platform-src-cb:checked');
  const selectedList = [];
  selectedCbs.forEach(cb => {
    if (cb.value) selectedList.push(cb.value);
  });
  const customCb = document.getElementById('platform-src-custom');
  if (customCb && customCb.checked && !selectedList.includes('Custom')) {
    selectedList.push('Custom');
  }

  const selectedLower = new Set(selectedList.map(s => s.toLowerCase()));

  // Filter breakdown entries strictly to the selected platforms
  const entries = Object.entries(breakdown).filter(([k]) => {
    return selectedLower.has(k.toLowerCase());
  });

  // Calculate totals strictly from the selected platforms
  let totalScraped = 0;
  let totalTarget = 0;
  let totalSkipped = 0;
  let sumBooking = 0;
  let sumRated = 0;
  let sumMatched = 0;

  entries.forEach(([k, v]) => {
    const scr = v.scraped || 0;
    const tot = v.total || scr;
    const skp = v.skipped || 0;
    totalScraped += scr;
    totalTarget += tot;
    totalSkipped += skp;
    if (v.booking_links) sumBooking += v.booking_links;
    if (v.rated_count) sumRated += v.rated_count;
    if (v.matched_count) sumMatched += v.matched_count;
  });

  const overallPct = totalTarget > 0 ? Math.min(100, Math.round(((totalScraped + totalSkipped) / totalTarget) * 100)) : (totalScraped > 0 ? 100 : 0);
  const remaining = Math.max(0, totalTarget - totalScraped);

  const pScraped = totalTarget > 0 ? (totalScraped / totalTarget) * 100 : 0;
  const pBooking = totalTarget > 0 ? (sumBooking / totalTarget) * 100 : 0;
  const pRated = totalTarget > 0 ? (sumRated / totalTarget) * 100 : 0;
  const pMatched = totalTarget > 0 ? (sumMatched / totalTarget) * 100 : 0;
  const pPending = totalTarget > 0 ? (remaining / totalTarget) * 100 : 0;

  const sPlatScraped = document.getElementById('seg-plat-scraped');
  if (sPlatScraped) sPlatScraped.style.width = `${pScraped.toFixed(1)}%`;
  const sPlatBooking = document.getElementById('seg-plat-booking');
  if (sPlatBooking) sPlatBooking.style.width = `${pBooking.toFixed(1)}%`;
  const sPlatRated = document.getElementById('seg-plat-rated');
  if (sPlatRated) sPlatRated.style.width = `${pRated.toFixed(1)}%`;
  const sPlatMatched = document.getElementById('seg-plat-matched');
  if (sPlatMatched) sPlatMatched.style.width = `${pMatched.toFixed(1)}%`;
  const sPlatPending = document.getElementById('seg-plat-pending');
  if (sPlatPending) sPlatPending.style.width = `${pPending.toFixed(1)}%`;

  if (bPlat) bPlat.style.width = `${overallPct}%`;
  if (sPlat) {
    if (selectedList.length === 0) {
      sPlat.innerText = '0% (0 / 0 - None Selected)';
    } else {
      sPlat.innerText = `${overallPct}% (${totalScraped} / ${totalTarget})`;
    }
  }

  if (cPlatScraped) cPlatScraped.innerText = `✅ Scraped: ${totalScraped}`;
  if (cPlatBooking) cPlatBooking.innerText = `🔗 Booking: ${sumBooking}`;
  if (cPlatRated) cPlatRated.innerText = `⭐ Rated: ${sumRated}`;
  if (cPlatMatched) cPlatMatched.innerText = `🌟 Matched: ${sumMatched}`;
  if (cPlatPending) cPlatPending.innerText = `⏳ In Queue: ${remaining}`;

  if (listContainer) {
    if (selectedList.length === 0) {
      listContainer.innerHTML = '<span style="font-size:0.68rem; color:#94a3b8; font-style:italic;">No platforms selected. Please check at least one platform above.</span>';
    } else if (entries.length === 0) {
      listContainer.innerHTML = selectedList.map(pName => `
        <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.7rem; padding:4px 6px; background:rgba(255,255,255,0.02); border-radius:6px; border:1px solid rgba(255,255,255,0.04);">
          <span style="font-weight:600; color:#cbd5e1;">${escapeHtml(pName)}</span>
          <span style="color:#64748b; font-size:0.65rem;">Waiting to scan...</span>
        </div>
      `).join('');
    } else {
      const colors = {
        'Fresha': '#a855f7',
        'Airbnb': '#ff385c',
        'Yelp': '#f97316',
        'TripAdvisor': '#00af87',
        'Treatwell': '#3b82f6',
        'Justdial': '#eab308',
        'Custom': '#6366f1'
      };

      listContainer.innerHTML = entries.map(([pName, item]) => {
        item = item || {};
        const col = colors[pName] || '#8b5cf6';
        const scr = item.scraped || 0;
        const tot = item.total || (scr > 0 ? scr : 0);
        const pct = item.percent !== undefined ? item.percent : (tot > 0 ? Math.min(100, Math.round((scr / tot) * 100)) : (scr > 0 ? 100 : 0));

        const pBook = item.booking_links || 0;
        const pRate = item.rated_count || 0;
        const pMatch = item.matched_count || 0;

        return `
          <div style="display:flex; flex-direction:column; gap:2px; margin-top:4px; background:rgba(255,255,255,0.02); padding:4px 6px; border-radius:6px; border:1px solid rgba(255,255,255,0.04);">
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.7rem;">
              <span style="font-weight:700; color:${col}; display:flex; align-items:center; gap:4px;">
                <span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${col};"></span>
                ${escapeHtml(pName)}
              </span>
              <span style="color:#cbd5e1; font-weight:700; font-size:0.68rem;">${scr} / ${tot} (${pct}%)</span>
            </div>
            <div style="width:100%; height:4px; background:rgba(255,255,255,0.06); border-radius:999px; overflow:hidden; margin:2px 0;">
              <div style="height:100%; width:${pct}%; background:${col}; border-radius:999px; transition:width 0.3s ease;"></div>
            </div>
            <div style="display:flex; gap:4px; flex-wrap:wrap; margin-top:2px;">
              <span class="chip-sm chip-green">✅ ${scr} Scraped</span>
              ${pBook > 0 ? `<span class="chip-sm chip-blue">🔗 ${pBook} Bookings</span>` : ''}
              ${pRate > 0 ? `<span class="chip-sm chip-orange">⭐ ${pRate} Rated</span>` : ''}
              ${pMatch > 0 ? `<span class="chip-sm chip-purple">🌟 ${pMatch} Matched</span>` : ''}
            </div>
          </div>
        `;
      }).join('');
    }
  }
};

window.updateSplitData = function(data) {
  if (!data) return;
  window.tablesSplitData = {
    master_leads: Array.isArray(data.master_leads) ? data.master_leads : [],
    unmatched_maps: Array.isArray(data.unmatched_maps) ? data.unmatched_maps : [],
    unmatched_platform: Array.isArray(data.unmatched_platform) ? data.unmatched_platform : [],
    website_leads: Array.isArray(data.website_leads) ? data.website_leads : [],
    linkedin_leads: Array.isArray(data.linkedin_leads) ? data.linkedin_leads : [],
    counts: data.counts || {},
    queue_progress: data.queue_progress || {}
  };

  // Update Website and LinkedIn tab badges
  const bWeb = document.getElementById('badge-count-website');
  if (bWeb) bWeb.innerText = window.tablesSplitData.website_leads.length;

  const bLi = document.getElementById('badge-count-linkedin');
  if (bLi) bLi.innerText = window.tablesSplitData.linkedin_leads.length;

  // Update Live Sync Progress Panel
  const qp = window.tablesSplitData.queue_progress || {};
  const totalMaps = qp.total_maps || window.tablesSplitData.unmatched_maps.length;
  const sMaps = document.getElementById('sync-stat-maps');
  if (sMaps) sMaps.innerText = `${totalMaps} places captured`;

  if (qp.maps) {
    const m = qp.maps;
    const total = Math.max(1, totalMaps);
    const withWeb = m.with_website || 0;
    const withPhone = m.with_phone || 0;
    const noWeb = m.no_website || 0;

    const sMWeb = document.getElementById('seg-maps-web');
    if (sMWeb) sMWeb.style.width = `${((withWeb / total) * 100).toFixed(1)}%`;
    const sMPhone = document.getElementById('seg-maps-phone');
    if (sMPhone) sMPhone.style.width = `${((Math.min(total - withWeb, withPhone) / total) * 100).toFixed(1)}%`;
    const sMNoWeb = document.getElementById('seg-maps-noweb');
    if (sMNoWeb) sMNoWeb.style.width = `${((noWeb / total) * 100).toFixed(1)}%`;

    const cMWeb = document.getElementById('sync-chip-maps-web');
    if (cMWeb) cMWeb.innerText = `🌐 With Web: ${withWeb}`;
    const cMNoWeb = document.getElementById('sync-chip-maps-noweb');
    if (cMNoWeb) cMNoWeb.innerText = `⚠️ No Web: ${noWeb}`;
    const cMPhone = document.getElementById('sync-chip-maps-phone');
    if (cMPhone) cMPhone.innerText = `📞 Phone: ${withPhone}`;
  }

  if (qp.website) {
    const w = qp.website;
    const total = Math.max(1, w.total || totalMaps);
    const inQueue = (w.in_queue !== undefined) ? w.in_queue : (w.pending || 0);
    const contactsFound = w.contacts_found || 0;
    const noContacts = w.no_contacts || 0;
    const botShield = w.bot_shield || 0;
    const notLoading = (w.not_loading || 0) + (w.unsafe_ssl || 0);
    const noWeb = w.no_website || 0;
    const inspected = w.inspected || 0;

    // Segment widths matching exact layman tag colors
    const pQueue = (inQueue / total) * 100;
    const pContacts = (contactsFound / total) * 100;
    const pNoContacts = (noContacts / total) * 100;
    const pBot = (botShield / total) * 100;
    const pNotLoading = (notLoading / total) * 100;
    const pNoWeb = (noWeb / total) * 100;

    const sQueue = document.getElementById('seg-web-pending');
    if (sQueue) {
      sQueue.style.width = `${pQueue.toFixed(1)}%`;
      sQueue.title = `In Queue: ${inQueue}`;
    }
    const sContacts = document.getElementById('seg-web-contacts');
    if (sContacts) {
      sContacts.style.width = `${pContacts.toFixed(1)}%`;
      sContacts.title = `Contacts Found: ${contactsFound}`;
    }
    const sNoContacts = document.getElementById('seg-web-nocontacts');
    if (sNoContacts) {
      sNoContacts.style.width = `${pNoContacts.toFixed(1)}%`;
      sNoContacts.title = `No Contacts Found: ${noContacts}`;
    }
    const sBot = document.getElementById('seg-web-bot');
    if (sBot) {
      sBot.style.width = `${pBot.toFixed(1)}%`;
      sBot.title = `Bot Shield: ${botShield}`;
    }
    const sNotLoading = document.getElementById('seg-web-notloading');
    if (sNotLoading) {
      sNotLoading.style.width = `${pNotLoading.toFixed(1)}%`;
      sNotLoading.title = `Not Loading / Unsafe: ${notLoading}`;
    }
    const sNoWeb = document.getElementById('seg-web-noweb');
    if (sNoWeb) {
      sNoWeb.style.width = `${pNoWeb.toFixed(1)}%`;
      sNoWeb.title = `No Website: ${noWeb}`;
    }

    const bW = document.getElementById('sync-bar-web');
    if (bW) bW.style.width = `${w.percent || 0}%`;

    const sW = document.getElementById('sync-stat-web');
    if (sW) sW.innerText = `${w.percent || 0}% (${inspected} / ${total})`;

    const cWQueue = document.getElementById('sync-chip-web-pending');
    if (cWQueue) cWQueue.innerText = `⏳ In Queue: ${inQueue}`;
    const cWContacts = document.getElementById('sync-chip-web-contacts');
    if (cWContacts) cWContacts.innerText = `🟢 Contacts: ${contactsFound}`;
    const cWNoContacts = document.getElementById('sync-chip-web-nocontacts');
    if (cWNoContacts) cWNoContacts.innerText = `🔵 No Contacts: ${noContacts}`;
    const cWBot = document.getElementById('sync-chip-web-bot');
    if (cWBot) cWBot.innerText = `🟡 Bot Shield: ${botShield}`;
    const cWNotLoading = document.getElementById('sync-chip-web-notloading');
    if (cWNotLoading) cWNotLoading.innerText = `🔴 Not Loading: ${notLoading}`;
    const cWNoWeb = document.getElementById('sync-chip-web-noweb');
    if (cWNoWeb) cWNoWeb.innerText = `⚪ No Web: ${noWeb}`;
  }

  if (qp.linkedin) {
    const l = qp.linkedin;
    const total = Math.max(1, l.total || totalMaps);
    const inspected = l.inspected || 0;
    const found = l.found || 0;
    const emp = l.employees_found || 0;
    const foundOnly = Math.max(0, found - emp);
    const notFound = l.not_found || 0;
    const pending = (l.pending !== undefined) ? l.pending : Math.max(0, total - inspected);

    // Segment widths matching exact tag colors (Blue = Found, Purple = Hierarchy, Red = Not Found, Gray = Pending)
    const pFound = (foundOnly / total) * 100;
    const pEmp = (emp / total) * 100;
    const pNotFound = (notFound / total) * 100;
    const pPending = (pending / total) * 100;

    const sFound = document.getElementById('seg-li-found');
    if (sFound) {
      sFound.style.width = `${pFound.toFixed(1)}%`;
      sFound.title = `Found Companies: ${found}`;
    }
    const sEmp = document.getElementById('seg-li-emp');
    if (sEmp) {
      sEmp.style.width = `${pEmp.toFixed(1)}%`;
      sEmp.title = `Hierarchy Extracted: ${emp}`;
    }
    const sNotFound = document.getElementById('seg-li-notfound');
    if (sNotFound) {
      sNotFound.style.width = `${pNotFound.toFixed(1)}%`;
      sNotFound.title = `Not Found: ${notFound}`;
    }
    const sPending = document.getElementById('seg-li-pending');
    if (sPending) {
      sPending.style.width = `${pPending.toFixed(1)}%`;
      sPending.title = `In Queue: ${pending}`;
    }

    const bL = document.getElementById('sync-bar-li');
    if (bL) bL.style.width = `${l.percent || 0}%`;

    const sL = document.getElementById('sync-stat-li');
    if (sL) sL.innerText = `${l.percent || 0}% (${inspected} / ${total})`;

    const cLFound = document.getElementById('sync-chip-li-found');
    if (cLFound) cLFound.innerText = `✅ Found: ${found}`;
    const cLEmp = document.getElementById('sync-chip-li-emp');
    if (cLEmp) cLEmp.innerText = `👥 Hierarchy: ${emp}`;
    const cLNo = document.getElementById('sync-chip-li-notfound');
    if (cLNo) cLNo.innerText = `⚠️ Not Found: ${notFound}`;
    const cLPending = document.getElementById('sync-chip-li-pending');
    if (cLPending) cLPending.innerText = `⏳ In Queue: ${pending}`;
  }

  // Update Platform Scout Progress Card & Multi-Platform Breakdown
  const platData = qp.platform || {};
  const platBreakdown = qp.platforms_breakdown || {};
  window.updatePlatformSyncCard(platBreakdown, platData);


  if (typeof placesData !== 'undefined') {
    const leadMap = new Map();
    (window.tablesSplitData.unmatched_maps || []).forEach(l => { if (l && l.id) leadMap.set(l.id, l); });
    (window.tablesSplitData.master_leads || []).forEach(l => { if (l && l.id) leadMap.set(l.id, l); });
    placesData = Array.from(leadMap.values());
  }

  // Update badge counts on tab switcher bar
  const bMaster = document.getElementById('badge-count-master');
  if (bMaster) bMaster.innerText = window.tablesSplitData.master_leads.length;

  const bMaps = document.getElementById('badge-count-maps');
  if (bMaps) bMaps.innerText = window.tablesSplitData.unmatched_maps.length;

  const bPlat = document.getElementById('badge-count-platform');
  if (bPlat) bPlat.innerText = window.tablesSplitData.unmatched_platform.length;

  // Update Top KPIs
  const statTotal = document.getElementById('stat-total');
  if (statTotal) statTotal.innerText = window.tablesSplitData.master_leads.length + window.tablesSplitData.unmatched_maps.length;

  let emailCount = 0;
  let totalEmployees = 0;
  const allLeads = [...window.tablesSplitData.master_leads, ...window.tablesSplitData.unmatched_maps];
  allLeads.forEach(p => {
    if (p.email && p.email !== 'N/A' && p.email.length > 0) emailCount++;
    if (p.employee_count) totalEmployees += parseInt(p.employee_count) || 0;
  });

  const statEmails = document.getElementById('stat-emails');
  if (statEmails) statEmails.innerText = emailCount;

  const statOrgs = document.getElementById('stat-orgs');
  if (statOrgs) statOrgs.innerText = totalEmployees;

  // Platform Listings count for KPI Card
  const platformTotal = window.tablesSplitData.master_leads.filter(m => m.platform_name && m.platform_name !== 'N/A').length + window.tablesSplitData.unmatched_platform.length;
  const statPlat = document.getElementById('stat-platform-count');
  if (statPlat) statPlat.innerText = platformTotal;

  if (typeof plotShopsOnMap === 'function') {
    plotShopsOnMap();
  }
  const tbody = document.getElementById('places-tbody');
  const hasRows = tbody && tbody.querySelectorAll('tr:not(#empty-row)').length > 0;
  if (!hasRows || !window.isScrapingRunning) {
    window.renderTable();
  }
};

window.refreshTablesSplit = async function() {
  try {
    const resp = await fetch('/api/tables-split');
    if (resp.ok) {
      const data = await resp.json();
      window.updateSplitData(data);
    }
  } catch (e) {
    console.error('Error refreshing tables split:', e);
  }
};

// =======================================================================
// DIRECTORY MANAGEMENT MODAL (TRIGGERED BY CLICKING KPI CARD)
// =======================================================================

window.openDirectoryModal = async function() {
  const modal = document.getElementById('platform-modal');
  if (modal) modal.style.display = 'flex';
  window.resetPlatformForm();
  await window.loadPlatformsList();
};

window.closeDirectoryModal = function() {
  const modal = document.getElementById('platform-modal');
  if (modal) modal.style.display = 'none';
};

window.resetPlatformForm = function() {
  const idInput = document.getElementById('edit-platform-id');
  const nameInput = document.getElementById('modal-platform-name');
  const catInput = document.getElementById('modal-platform-cat');
  const urlInput = document.getElementById('modal-platform-url');
  const title = document.getElementById('platform-form-title');

  if (idInput) idInput.value = '';
  if (nameInput) nameInput.value = '';
  if (catInput) catInput.value = '';
  if (urlInput) urlInput.value = '';
  if (title) title.innerText = '➕ Add / Edit Platform Directory';
};

window.loadPlatformsList = async function() {
  const tbody = document.getElementById('modal-platforms-tbody');
  if (!tbody) return;
  try {
    const resp = await fetch('/api/platforms');
    if (!resp.ok) return;
    const platforms = await resp.json();

    const presetSelect = document.getElementById('platform-preset-select');
    if (presetSelect) {
      const currentVal = presetSelect.value;
      const options = platforms.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)} (${escapeHtml(p.category || 'Directory')})</option>`);
      options.push('<option value="Custom">Custom Platform / Directory</option>');
      presetSelect.innerHTML = options.join('');
      if ([...presetSelect.options].some(o => o.value === currentVal)) {
        presetSelect.value = currentVal;
      }
    }

    if (!platforms || platforms.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:18px; color:#64748b;">No directories configured yet. Add one above!</td></tr>';
      return;
    }

    tbody.innerHTML = platforms.map(p => `
      <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
        <td style="padding:10px 12px; font-weight:600; color:#fff;">
          <span class="badge badge-platform">🟣 ${escapeHtml(p.name)}</span>
        </td>
        <td style="padding:10px 12px; color:#cbd5e1; font-size:0.75rem;">${escapeHtml(p.category || 'General')}</td>
        <td style="padding:10px 12px; font-family:monospace; font-size:0.72rem; color:#38bdf8; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(p.url_template)}">
          ${escapeHtml(p.url_template)}
        </td>
        <td style="padding:10px 12px; text-align:center;">
          <div style="display:flex; justify-content:center; gap:6px;">
            <button type="button" class="btn btn-secondary" style="padding:3px 8px; font-size:0.72rem;" onclick="editPlatform(${p.id}, '${escapeHtml(p.name)}', '${escapeHtml(p.category || '')}', '${escapeHtml(p.url_template)}')">✏️ Edit</button>
            <button type="button" class="btn btn-secondary" style="padding:3px 8px; font-size:0.72rem; color:#f87171;" onclick="deletePlatform(${p.id}, '${escapeHtml(p.name)}')">🗑️</button>
          </div>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    console.error('Error loading platforms:', err);
  }
};

window.editPlatform = function(id, name, cat, url) {
  const idInput = document.getElementById('edit-platform-id');
  const nameInput = document.getElementById('modal-platform-name');
  const catInput = document.getElementById('modal-platform-cat');
  const urlInput = document.getElementById('modal-platform-url');
  const title = document.getElementById('platform-form-title');

  if (idInput) idInput.value = id;
  if (nameInput) nameInput.value = name;
  if (catInput) catInput.value = cat;
  if (urlInput) urlInput.value = url;
  if (title) title.innerText = `✏️ Edit Platform Directory: ${name}`;
  nameInput.focus();
};

window.submitPlatformForm = async function() {
  const id = document.getElementById('edit-platform-id')?.value;
  const name = document.getElementById('modal-platform-name')?.value.trim();
  const category = document.getElementById('modal-platform-cat')?.value.trim();
  const urlTemplate = document.getElementById('modal-platform-url')?.value.trim();

  if (!name) {
    alert('Please enter a Platform Name (e.g. Treatwell, Airbnb, Yelp)');
    return;
  }
  if (!urlTemplate) {
    alert('Please enter the Search Link Template (e.g. https://www.fresha.com/search?query={query}&address={city})');
    return;
  }

  try {
    const payload = { name, category: category || 'General', url_template: urlTemplate };
    if (id) payload.id = parseInt(id);

    const resp = await fetch('/api/platforms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const res = await resp.json();
    if (resp.ok) {
      if (typeof logMessage === 'function') logMessage(`🟣 Saved platform directory template: "${name}"`);
      window.resetPlatformForm();
      await window.loadPlatformsList();
    } else {
      alert('Error saving platform: ' + (res.detail || 'Unknown error'));
    }
  } catch (err) {
    alert('Network error saving platform: ' + err.message);
  }
};

window.deletePlatform = async function(id, name) {
  if (!confirm(`Are you sure you want to delete platform "${name}"?`)) return;
  try {
    const resp = await fetch(`/api/platforms/${id}`, { method: 'DELETE' });
    if (resp.ok) {
      if (typeof logMessage === 'function') logMessage(`🟣 Removed platform directory template: "${name}"`);
      await window.loadPlatformsList();
    } else {
      alert('Error deleting platform.');
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
};

window.updateKPIs = function() {
  window.updateSplitData(window.tablesSplitData);
};

// =======================================================================
// TABLE HEADERS AND RENDERING
// =======================================================================

window.renderTableHeader = function() {
  const theadTr = document.querySelector('#places-table thead tr');
  if (!theadTr) return;
  const selectAllTh = `<th style="width: 38px; text-align: center;"><input type="checkbox" id="select-all-checkbox" onclick="window.toggleSelectAll(this.checked)" title="Select / Deselect all visible records" /></th>`;
  const actionsTh = `<th style="width: 85px; text-align: center;">Actions</th>`;

  if (window.currentTableTab === 'platform') {
    theadTr.innerHTML = `
      ${selectAllTh}
      <th style="width: 35px;">#</th>
      <th>Business Name</th>
      <th>Category</th>
      <th>Website Status</th>
      <th>Extracted Emails</th>
      <th>Social Media</th>
      <th>Platform / Booking</th>
      <th>Anti-Bot Shield</th>
      <th>Cookie Diagnostics</th>
      <th>Screenshot</th>
      <th>Notes</th>
      <th>Phone</th>
      <th>Address</th>
      <th>Rating & Reviews</th>
      <th>Website URL</th>
      <th>Maps Link</th>
      <th title="Discovered & Deep Inspected Timestamp">Found Date & Time (Maps & Web)</th>
      ${actionsTh}
    `;
  } else if (window.currentTableTab === 'maps') {
    theadTr.innerHTML = `
      ${selectAllTh}
      <th style="width: 35px;">#</th>
      <th>Business Name</th>
      <th>Category</th>
      <th>Email Address</th>
      <th>Social Media</th>
      <th>Platform / Booking</th>
      <th>Notes</th>
      <th>Phone</th>
      <th>Address</th>
      <th>Rating & Reviews</th>
      <th>Website URL</th>
      <th>Maps Link</th>
      <th>Capture Status</th>
      <th>Found Date & Time</th>
      ${actionsTh}
    `;
  } else if (window.currentTableTab === 'website') {
    theadTr.innerHTML = `
      ${selectAllTh}
      <th style="width: 35px;">#</th>
      <th>Business Name</th>
      <th>Category</th>
      <th>Website Status</th>
      <th>Extracted Emails</th>
      <th>Social Media</th>
      <th>Platform / Booking</th>
      <th>Anti-Bot Shield</th>
      <th>Cookie Diagnostics</th>
      <th>Screenshot</th>
      <th>Notes</th>
      <th>Phone</th>
      <th>Address</th>
      <th>Rating & Reviews</th>
      <th>Website URL</th>
      <th>Maps Link</th>
      <th title="Maps capture timestamp & Web Agent inspection timestamp">Found Date & Time (Maps & Web)</th>
      ${actionsTh}
    `;
  } else if (window.currentTableTab === 'linkedin') {
    theadTr.innerHTML = `
      ${selectAllTh}
      <th style="width: 35px;">#</th>
      <th>Business Name</th>
      <th>Status Tag</th>
      <th>Company LinkedIn</th>
      <th>Workforce Size</th>
      <th>Employees & Key People</th>
      <th>Org Chart View</th>
      <th>Found Date & Time</th>
      ${actionsTh}
    `;
  } else {
    // master normalized
    theadTr.innerHTML = `
      ${selectAllTh}
      <th style="width: 35px;">#</th>
      <th>Business Name</th>
      <th>Category</th>
      <th>Email Address</th>
      <th>Social Media</th>
      <th>Bot Security</th>
      <th>Cookies</th>
      <th>Team / Staff</th>
      <th>Org Chart</th>
      <th>Landing Page</th>
      <th>Phone</th>
      <th>Address</th>
      <th>Rating</th>
      <th>Platform Directory</th>
      <th>Links</th>
      <th>Found Date & Time</th>
      ${actionsTh}
    `;
  }
};


// =======================================================================
// COLUMN-SPECIFIC DATA FILTERS & MANUAL NORMALIZATION LOGIC
// =======================================================================

window.tableFilters = {
  timeSort: 'latest',
  search: '',
  category: '',
  platform: '',
  statusTag: '',
  minRating: 0,
  botSecurity: '',
  cookieStatus: '',
  pricing: '',
  hasEmail: false,
  hasPhone: false,
  hasWebsite: false,
  hasScreenshot: false,
  hasSocial: false,
  hasTeam: false,
  hasBooking: false,
  hasAddress: false
};

window.renderFiltersForCurrentTable = function() {
  const tab = window.currentTableTab;
  const searchInput = document.getElementById('filter-search-input');
  const wrapTime = document.getElementById('filter-wrapper-time');
  const wrapPlatform = document.getElementById('filter-wrapper-platform');
  const wrapStatus = document.getElementById('filter-wrapper-status');
  const wrapBot = document.getElementById('filter-wrapper-bot');
  const wrapCookie = document.getElementById('filter-wrapper-cookie');
  const wrapPrice = document.getElementById('filter-wrapper-price');

  if (wrapTime) wrapTime.style.display = 'inline-flex';

  const pillEmail = document.getElementById('filter-pill-hasEmail');
  const pillPhone = document.getElementById('filter-pill-hasPhone');
  const pillWeb = document.getElementById('filter-pill-hasWebsite');
  const pillScreen = document.getElementById('filter-pill-hasScreenshot');
  const pillSocial = document.getElementById('filter-pill-hasSocial');
  const pillTeam = document.getElementById('filter-pill-hasTeam');
  const pillBooking = document.getElementById('filter-pill-hasBooking');
  const pillAddr = document.getElementById('filter-pill-hasAddress');

  if (tab === 'website') {
    // Table: Website Inspector Leads
    if (searchInput) searchInput.placeholder = "Filter website leads by name, email, socials, status...";
    if (wrapStatus) wrapStatus.style.display = 'inline-flex';
    if (wrapPlatform) wrapPlatform.style.display = 'none';
    if (wrapBot) wrapBot.style.display = 'inline-flex';
    if (wrapCookie) wrapCookie.style.display = 'inline-flex';
    if (wrapPrice) wrapPrice.style.display = 'none';

    if (pillEmail) pillEmail.style.display = 'inline-flex';
    if (pillPhone) pillPhone.style.display = 'inline-flex';
    if (pillWeb) pillWeb.style.display = 'inline-flex';
    if (pillScreen) pillScreen.style.display = 'inline-flex';
    if (pillSocial) pillSocial.style.display = 'inline-flex';
    if (pillTeam) pillTeam.style.display = 'none';
    if (pillBooking) pillBooking.style.display = 'none';
    if (pillAddr) pillAddr.style.display = 'none';
  } else if (tab === 'platform') {
    // Table 3: Platform Directory Listings
    if (searchInput) searchInput.placeholder = "Filter platform listings by title, email, phone, category, address...";
    if (wrapStatus) wrapStatus.style.display = 'inline-flex';
    if (wrapPlatform) wrapPlatform.style.display = 'inline-flex';
    if (wrapBot) wrapBot.style.display = 'inline-flex';
    if (wrapCookie) wrapCookie.style.display = 'inline-flex';
    if (wrapPrice) wrapPrice.style.display = 'inline-flex';

    if (pillEmail) pillEmail.style.display = 'inline-flex';
    if (pillPhone) pillPhone.style.display = 'inline-flex';
    if (pillWeb) pillWeb.style.display = 'inline-flex';
    if (pillScreen) pillScreen.style.display = 'inline-flex';
    if (pillSocial) pillSocial.style.display = 'inline-flex';
    if (pillTeam) pillTeam.style.display = 'none';
    if (pillBooking) pillBooking.style.display = 'inline-flex';
    if (pillAddr) pillAddr.style.display = 'inline-flex';
  } else if (tab === 'maps') {
    // Table 2: Google Maps Leads
    if (searchInput) searchInput.placeholder = "Filter by business name, address, phone, email...";
    if (wrapStatus) wrapStatus.style.display = 'none';
    if (wrapPlatform) wrapPlatform.style.display = 'none';
    if (wrapBot) wrapBot.style.display = 'inline-flex';
    if (wrapCookie) wrapCookie.style.display = 'inline-flex';
    if (wrapPrice) wrapPrice.style.display = 'none';

    if (pillEmail) pillEmail.style.display = 'inline-flex';
    if (pillPhone) pillPhone.style.display = 'inline-flex';
    if (pillWeb) pillWeb.style.display = 'inline-flex';
    if (pillScreen) pillScreen.style.display = 'inline-flex';
    if (pillSocial) pillSocial.style.display = 'inline-flex';
    if (pillTeam) pillTeam.style.display = 'inline-flex';
    if (pillBooking) pillBooking.style.display = 'none';
    if (pillAddr) pillAddr.style.display = 'none';
  } else {
    // Table 1: Master Normalized Leads
    if (searchInput) searchInput.placeholder = "Filter master leads by name, address, phone, email...";
    if (wrapStatus) wrapStatus.style.display = 'inline-flex';
    if (wrapPlatform) wrapPlatform.style.display = 'inline-flex';
    if (wrapBot) wrapBot.style.display = 'inline-flex';
    if (wrapCookie) wrapCookie.style.display = 'inline-flex';
    if (wrapPrice) wrapPrice.style.display = 'inline-flex';

    if (pillEmail) pillEmail.style.display = 'inline-flex';
    if (pillPhone) pillPhone.style.display = 'inline-flex';
    if (pillWeb) pillWeb.style.display = 'inline-flex';
    if (pillScreen) pillScreen.style.display = 'inline-flex';
    if (pillSocial) pillSocial.style.display = 'inline-flex';
    if (pillTeam) pillTeam.style.display = 'inline-flex';
    if (pillBooking) pillBooking.style.display = 'inline-flex';
    if (pillAddr) pillAddr.style.display = 'none';
  }
};

window.onFilterChange = function() {
  const searchEl = document.getElementById('filter-search-input');
  const timeSortEl = document.getElementById('filter-time-sort-select');
  const catEl = document.getElementById('filter-category-select');
  const platEl = document.getElementById('filter-platform-select');
  const statusEl = document.getElementById('filter-status-select');
  const ratEl = document.getElementById('filter-rating-select');
  const botEl = document.getElementById('filter-bot-select');
  const cookieEl = document.getElementById('filter-cookie-select');
  const priceEl = document.getElementById('filter-price-select');
  const clearBtn = document.getElementById('filter-search-clear');

  if (searchEl) {
    window.tableFilters.search = searchEl.value.trim().toLowerCase();
    if (clearBtn) clearBtn.style.display = window.tableFilters.search ? 'inline-flex' : 'none';
  }
  if (timeSortEl) window.tableFilters.timeSort = timeSortEl.value || 'latest';
  if (catEl) window.tableFilters.category = catEl.value;
  if (platEl) window.tableFilters.platform = platEl.value;
  if (statusEl) {
    window.tableFilters.statusTag = statusEl.value;
    window.activeTagFilter = statusEl.value || 'All';
  }
  if (ratEl) window.tableFilters.minRating = parseFloat(ratEl.value) || 0;
  if (botEl) window.tableFilters.botSecurity = botEl.value;
  if (cookieEl) window.tableFilters.cookieStatus = cookieEl.value;
  if (priceEl) window.tableFilters.pricing = priceEl.value;

  window.renderTable();
};

window.filterByStatusTag = function(tag) {
  if (window.currentTableTab !== 'website' && window.currentTableTab !== 'master') {
    if (typeof window.switchTableTab === 'function') {
      window.switchTableTab('website');
    }
  }
  const statusEl = document.getElementById('filter-status-select');
  if (statusEl) {
    statusEl.value = tag || '';
  }
  window.tableFilters.statusTag = tag || '';
  window.activeTagFilter = tag || 'All';
  window.renderTable();
};

window.clearSearchInput = function() {
  const searchEl = document.getElementById('filter-search-input');
  if (searchEl) searchEl.value = '';
  window.onFilterChange();
};

window.toggleFilterPill = function(key) {
  if (typeof window.tableFilters[key] !== 'undefined') {
    window.tableFilters[key] = !window.tableFilters[key];
    const pill = document.getElementById('filter-pill-' + key);
    if (pill) pill.classList.toggle('active', window.tableFilters[key]);
    window.renderTable();
  }
};

window.resetTableFilters = function() {
  window.tableFilters = {
    timeSort: 'latest',
    search: '',
    category: '',
    platform: '',
    statusTag: '',
    minRating: 0,
    botSecurity: '',
    cookieStatus: '',
    pricing: '',
    hasEmail: false,
    hasPhone: false,
    hasWebsite: false,
    hasScreenshot: false,
    hasSocial: false,
    hasTeam: false,
    hasBooking: false,
    hasAddress: false
  };

  const searchEl = document.getElementById('filter-search-input');
  if (searchEl) searchEl.value = '';
  const clearBtn = document.getElementById('filter-search-clear');
  if (clearBtn) clearBtn.style.display = 'none';

  const timeSortEl = document.getElementById('filter-time-sort-select');
  if (timeSortEl) timeSortEl.value = 'latest';

  const catEl = document.getElementById('filter-category-select');
  if (catEl) catEl.value = '';

  const platEl = document.getElementById('filter-platform-select');
  if (platEl) platEl.value = '';

  const statusEl = document.getElementById('filter-status-select');
  if (statusEl) statusEl.value = '';
  window.activeTagFilter = 'All';

  const ratEl = document.getElementById('filter-rating-select');
  if (ratEl) ratEl.value = '0';

  const botEl = document.getElementById('filter-bot-select');
  if (botEl) botEl.value = '';

  const cookieEl = document.getElementById('filter-cookie-select');
  if (cookieEl) cookieEl.value = '';

  const priceEl = document.getElementById('filter-price-select');
  if (priceEl) priceEl.value = '';

  ['hasEmail', 'hasPhone', 'hasWebsite', 'hasScreenshot', 'hasSocial', 'hasTeam', 'hasBooking', 'hasAddress'].forEach(k => {
    const pill = document.getElementById('filter-pill-' + k);
    if (pill) pill.classList.remove('active');
  });

  window.renderTable();
};

window.populateCategoryDropdown = function(list) {
  const catEl = document.getElementById('filter-category-select');
  if (!catEl) return;
  const currentVal = window.tableFilters.category;
  const cats = new Set();
  (list || []).forEach(item => {
    const c = (item.category || '').trim();
    if (c && c !== 'N/A' && c !== 'null') cats.add(c);
  });
  const sortedCats = Array.from(cats).sort();
  const currentOptions = Array.from(catEl.options).map(o => o.value).filter(Boolean).sort().join('|');
  const newOptions = sortedCats.join('|');

  if (currentOptions !== newOptions) {
    let html = '<option value="">🏷️ All Categories</option>';
    sortedCats.forEach(cat => {
      const sel = (cat === currentVal) ? 'selected' : '';
      html += `<option value="${escapeHtml(cat)}" ${sel}>${escapeHtml(cat)}</option>`;
    });
    catEl.innerHTML = html;
  }
};

window.populatePlatformDropdown = function(list) {
  const platEl = document.getElementById('filter-platform-select');
  if (!platEl) return;
  const currentVal = window.tableFilters.platform;
  const plats = new Set(['Google Maps', 'Airbnb', 'Fresha', 'Yelp', 'TripAdvisor']);
  (list || []).forEach(item => {
    const p = (item.platform || item.platform_name || '').trim();
    if (p && p !== 'N/A' && p !== 'null' && p !== 'Platform') plats.add(p);
  });
  if (Array.isArray(window.platformsList)) {
    window.platformsList.forEach(p => { if (p && p.name) plats.add(p.name); });
  }
  const currentOptions = Array.from(platEl.options).map(o => o.value).filter(Boolean).sort().join('|');
  const sortedPlats = Array.from(plats).sort();
  const newOptions = sortedPlats.join('|');

  if (currentOptions !== newOptions) {
    let html = '<option value="">🟣 All Platforms</option>';
    sortedPlats.forEach(p => {
      const sel = (p.toLowerCase() === (currentVal || '').toLowerCase()) ? 'selected' : '';
      html += `<option value="${escapeHtml(p)}" ${sel}>${escapeHtml(p)}</option>`;
    });
    platEl.innerHTML = html;
  }
};

window.triggerManualNormalization = async function() {
  const btn = document.getElementById('btn-normalize-action');
  const originalHtml = btn ? btn.innerHTML : '<span class="btn-icon">🔄</span><span>Normalize Leads</span>';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon spinner">⏳</span><span>Normalizing...</span>';
    btn.classList.add('loading');
  }

  try {
    const resp = await fetch('/api/normalize', { method: 'POST' });
    if (resp.ok) {
      const data = await resp.json();
      const stats = data.stats || {};
      const newlyMatched = stats.newly_matched || 0;
      const tablesSplit = data.tables_split || {};
      const counts = tablesSplit.counts || {};

      if (data.tables_split) {
        window.updateSplitData(data.tables_split);
      } else {
        await window.refreshTablesSplit();
      }

      // Automatically switch to Master Normalized Leads tab so user sees result immediately
      window.switchTableTab('master');

      const msg = `✅ Normalization complete!

Merged ${newlyMatched} verified cross-platform leads into Master Table.
Master Normalized Leads: ${counts.master || 0}
Google Maps Leads (Intact): ${counts.maps || 0}
Platform Directory Listings (Intact): ${counts.platform || 0}`;
      if (typeof logMessage === 'function') {
        logMessage(`🔄 [Normalization Engine] Merged ${newlyMatched} leads. Master Table: ${counts.master || 0} leads.`);
      }
      alert(msg);
    } else {
      alert('Normalization request failed. Server returned status: ' + resp.status);
    }
  } catch (err) {
    console.error('Normalization error:', err);
    alert('Error running normalization: ' + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
      btn.classList.remove('loading');
    }
  }
};

window.buildSinglePlaceRow = function(place, index, curTab) {
  curTab = curTab || window.currentTableTab || 'maps';
  const displayName = place.name || place.title || place.company_name || 'Listing';
  const rowId = place.id || index;
  const tr = document.createElement('tr');
  tr.id = `row-${rowId}`;
  if (typeof focusShop === 'function') {
    tr.onclick = () => focusShop(rowId);
  }

  let attr = {};
  if (place.source_attribution) {
    if (typeof place.source_attribution === 'string') {
      try { attr = JSON.parse(place.source_attribution); } catch (e) { attr = {}; }
    } else if (typeof place.source_attribution === 'object') {
      attr = place.source_attribution;
    }
  }

  const getSourceBadge = (field, fallback) => {
    let src = attr[field] || fallback;
    if (!src) {
      if (field === 'phone' || field === 'website') src = place.maps_url ? 'maps' : 'web';
      else if (field === 'email') src = (place.website_status && place.website_status !== 'no_website') ? 'web' : (place.maps_url ? 'maps' : 'web');
    }
    if (src === 'maps') return '<span class="source-chip-maps" title="1st discovered by 📍 Maps Agent">📍 Maps</span>';
    if (src === 'web') return '<span class="source-chip-web" title="1st discovered by 🌐 Web Agent">🌐 Web</span>';
    if (src === 'platform') return '<span class="source-chip-plat" title="1st discovered via Directory Platform">🟣 Plat</span>';
    return '';
  };

  const getLeadOriginBadge = () => {
    if (place.maps_url && place.maps_url.includes('google.com/maps')) {
      return '<span class="source-chip-maps" title="Lead initially captured via 📍 Google Maps">📍 Maps</span>';
    }
    if (place.platform_name && place.platform_name !== 'N/A') {
      return `<span class="source-chip-plat" title="Lead initially captured via 🟣 ${escapeHtml(place.platform_name)}">🟣 ${escapeHtml(place.platform_name)}</span>`;
    }
    return '<span class="source-chip-web" title="Lead initially captured via 🌐 Website Agent">🌐 Web</span>';
  };

  const emailSrc = getSourceBadge('email');
  const emailHtml = (place.email && place.email !== 'N/A')
    ? `<div style="display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap;"><span class="badge badge-email" title="Click to copy" onclick="event.stopPropagation(); navigator.clipboard.writeText('${place.email}'); alert('Copied: ${place.email}')">✉️ ${escapeHtml(place.email)}</span>${emailSrc}</div>`
    : '<span class="badge badge-none">Not listed</span>';

  const categoryHtml = place.category
    ? `<span class="badge badge-category">${escapeHtml(place.category)}</span>`
    : '<span class="badge badge-none">Business</span>';

  const revCountVal = place.reviews_count || place.reviews || '0';
  const ratingVal = (place.rating && place.rating !== 'N/A' && place.rating != 0 && place.rating !== '0.0')
    ? place.rating
    : (place.platform_rating && place.platform_rating !== 'N/A' && place.platform_rating != 0 ? place.platform_rating : null);
  const ratingHtml = ratingVal
    ? `<span class="rating-pill">⭐ ${ratingVal} <small style="color:#94a3b8;">(${revCountVal})</small></span>`
    : '<span style="color:#64748b;">N/A</span>';

  const siteSrc = getSourceBadge('website');
  const linksHtml = `
    <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;" onclick="event.stopPropagation();">
      ${place.website && place.website !== 'N/A' ? `<div style="display:inline-flex; align-items:center; gap:4px;"><a href="${encodeURI(place.website)}" target="_blank" class="link-btn">🌐 Site</a>${siteSrc}</div>` : ''}
      ${place.maps_url ? `<a href="${encodeURI(place.maps_url)}" target="_blank" class="link-btn">🗺️ Maps</a>` : ''}
    </div>
  `;

  const socialEntries = [
    { key: 'instagram', icon: '📸', url: place.instagram, title: 'Instagram', cls: 'badge-ig' },
    { key: 'facebook', icon: '👥', url: place.facebook, title: 'Facebook', cls: 'badge-fb' },
    { key: 'linkedin', icon: '💼', url: place.linkedin, title: 'LinkedIn', cls: 'badge-li' },
    { key: 'twitter', icon: '🐦', url: place.twitter, title: 'Twitter/X', cls: 'badge-tw' },
    { key: 'youtube', icon: '▶️', url: place.youtube, title: 'YouTube', cls: 'badge-yt' },
    { key: 'tiktok', icon: '🎵', url: place.tiktok, title: 'TikTok', cls: 'badge-tt' }
  ];

  if (place.whatsapp && place.whatsapp !== 'N/A') {
    const waDigits = String(place.whatsapp).replace(/[^0-9]/g, '');
    const waUrl = place.whatsapp.startsWith('http') ? place.whatsapp : `https://wa.me/${waDigits || place.whatsapp}`;
    socialEntries.push({ key: 'whatsapp', icon: '💬', url: waUrl, title: 'WhatsApp', cls: 'badge-wa' });
  }

  const activeSocials = socialEntries.filter(s => s.url && s.url !== 'N/A' && s.url.trim() !== '');

  let socialsHtml = '<span class="badge badge-none">—</span>';
  if (activeSocials.length > 0) {
    const mapsGroup = [];
    const webGroup = [];

    activeSocials.forEach(s => {
      let src = attr[s.key];
      if (!src) {
        src = (place.website_scraped_at || (place.website_status && place.website_status !== 'no_website' && place.website_status !== 'pending')) ? 'web' : 'maps';
      }
      const iconHtml = `<a href="${encodeURI(s.url)}" target="_blank" class="badge-social ${s.cls}" title="${s.title}: ${escapeHtml(s.url)} (1st found by ${src === 'maps' ? '📍 Maps' : '🌐 Web'})" onclick="event.stopPropagation();">${s.icon}</a>`;
      if (src === 'maps') mapsGroup.push(iconHtml);
      else webGroup.push(iconHtml);
    });

    const groupParts = [];
    if (mapsGroup.length > 0) {
      groupParts.push(`
        <div class="social-source-group" title="1st found by 📍 Maps Agent">
          <div style="display:flex; gap:3px; align-items:center;">${mapsGroup.join('')}</div>
          <span class="source-chip-maps">📍 Maps</span>
        </div>
      `);
    }
    if (webGroup.length > 0) {
      groupParts.push(`
        <div class="social-source-group" title="1st found by 🌐 Web Agent">
          <div style="display:flex; gap:3px; align-items:center;">${webGroup.join('')}</div>
          <span class="source-chip-web">🌐 Web</span>
        </div>
      `);
    }
    socialsHtml = `<div style="display:flex; flex-direction:column; gap:4px;" onclick="event.stopPropagation();">${groupParts.join('')}</div>`;
  }

  // Phone & WhatsApp HTML for table cells
  const phoneParts = [];
  const phoneSrc = getSourceBadge('phone');
  if (place.phone && place.phone !== 'N/A') {
    phoneParts.push(`<div style="display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap;"><a href="tel:${place.phone}" style="color:#cbd5e1; text-decoration:none; white-space:nowrap;" onclick="event.stopPropagation();">📞 ${escapeHtml(place.phone)}</a>${phoneSrc}</div>`);
  }
  if (place.whatsapp && place.whatsapp !== 'N/A') {
    const waDigits = String(place.whatsapp).replace(/[^0-9]/g, '');
    const waUrl = place.whatsapp.startsWith('http') ? place.whatsapp : `https://wa.me/${waDigits || place.whatsapp}`;
    const waSrc = getSourceBadge('whatsapp');
    phoneParts.push(`<div style="display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap;"><a href="${encodeURI(waUrl)}" target="_blank" class="badge-wa-chip" title="Chat on WhatsApp: ${escapeHtml(place.whatsapp)}" onclick="event.stopPropagation();">💬 WhatsApp</a>${waSrc}</div>`);
  }
  const phoneHtml = phoneParts.length > 0
    ? `<div style="display:flex; flex-direction:column; gap:4px; align-items:flex-start;">${phoneParts.join('')}</div>`
    : '<span style="color:#64748b;">N/A</span>';

  // Platform & Booking badge HTML
  const platBadges = [];
  const bUrl = place.booking_url || '';
  const pName = place.platform_name || '';
  const oUrl = place.order_url || '';

  if (bUrl) {
    let label = pName ? `📅 ${escapeHtml(pName)}` : '📅 Book Table';
    platBadges.push(`<a href="${encodeURI(bUrl)}" target="_blank" class="badge-platform-pill badge-platform-booking" title="Book on ${escapeHtml(pName || 'Platform')}" onclick="event.stopPropagation();">${label}</a>`);
  } else if (pName && pName !== 'N/A') {
    platBadges.push(`<span class="badge-platform-pill badge-platform-booking">📅 ${escapeHtml(pName)}</span>`);
  }

  if (oUrl) {
    platBadges.push(`<a href="${encodeURI(oUrl)}" target="_blank" class="badge-platform-pill badge-platform-order" title="Order Online" onclick="event.stopPropagation();">🛍️ Order</a>`);
  }

  const platformBookingHtml = platBadges.length > 0 
    ? `<div style="display:flex; flex-wrap:wrap; gap:4px; align-items:center;" onclick="event.stopPropagation();">${platBadges.join('')}</div>`
    : '<span class="badge badge-none">—</span>';

  // Notes HTML (price, services, women-owned, floor info, etc.)
  const rawNotes = place.notes || (place.price && place.price !== 'N/A' ? `💰 ${place.price}` : '');
  let notesHtml = '<span class="badge badge-none">—</span>';
  if (rawNotes) {
    const noteTokens = rawNotes.split(' | ').filter(t => t.trim());
    const chips = noteTokens.map(t => {
      let trimmed = t.trim();
      let cls = 'badge-note-chip';
      if (trimmed.startsWith('💰')) cls += ' badge-note-price';
      else if (trimmed.startsWith('🍽️')) cls += ' badge-note-service';
      else if (trimmed.startsWith('💜')) cls += ' badge-note-highlight';
      else if (trimmed.startsWith('📍')) cls += ' badge-note-loc';
      return `<span class="${cls}" title="${escapeHtml(trimmed)}">${escapeHtml(trimmed)}</span>`;
    });
    notesHtml = `<div style="display:flex; flex-direction:column; gap:3px; max-width:210px;" onclick="event.stopPropagation();">${chips.join('')}</div>`;
  }

  let botHtml = '<span class="badge badge-none">N/A</span>';
  if (place.bot_protection) {
    const bp = place.bot_protection;
    if (bp.includes('Access Denied')) {
      botHtml = `<span class="badge badge-bot-denied" title="Access Denied by Anti-Bot Shield">🛑 ${escapeHtml(bp)}</span>`;
    } else if (bp.includes('Access Granted')) {
      botHtml = `<span class="badge badge-bot-granted" title="Anti-Bot Shield active but website accessed successfully">✅ ${escapeHtml(bp)}</span>`;
    } else if (bp.includes('Cloudflare')) {
      botHtml = `<span class="badge badge-bot-cloudflare">🛡️ ${escapeHtml(bp)}</span>`;
    } else if (bp.includes('Anti-Bot') || bp.includes('Captcha') || bp.includes('Datadome') || bp.includes('PerimeterX')) {
      botHtml = `<span class="badge badge-bot-challenge">⚠️ ${escapeHtml(bp)}</span>`;
    } else if (bp === 'Clean') {
      botHtml = '<span class="badge badge-bot-clean">✔️ Clean</span>';
    } else {
      botHtml = `<span class="badge badge-none">${escapeHtml(bp)}</span>`;
    }
  }

  let cookieHtml = '<span class="badge badge-none">—</span>';
  if (place.cookie_status) {
    if (place.cookie_status === 'Accepted') {
      cookieHtml = '<span class="badge badge-cookie-accepted" title="Cookie banner auto-accepted">🍪 Accepted</span>';
    } else if (place.cookie_status.includes('Unaccepted')) {
      cookieHtml = '<span class="badge badge-cookie-pending" title="Cookie banner detected (unaccepted)">🍪 Unaccepted</span>';
    } else if (place.cookie_status === 'None') {
      cookieHtml = '<span class="badge badge-none" title="No cookie banner detected">None</span>';
    } else {
      cookieHtml = `<span class="badge badge-none">${escapeHtml(place.cookie_status)}</span>`;
    }
  }

  const screenHtml = (place.screenshot && place.screenshot !== 'N/A')
    ? `
      <div class="screen-thumb-container" onclick="event.stopPropagation(); openImageModal('${encodeURI(place.screenshot)}', '${escapeHtml(displayName)}')">
        <div class="screen-thumb-box" title="Click to view full screenshot of ${escapeHtml(displayName)}">
          <img src="${encodeURI(place.screenshot)}" alt="${escapeHtml(displayName)}" onerror="handleImgError(this)">
          <div class="screen-thumb-overlay">🔍 View</div>
        </div>
        <button class="btn-screen-view" title="Expand screenshot">
          <span>🔍 View</span>
        </button>
      </div>
    `
    : '<span class="badge badge-none" style="opacity:0.6;">—</span>';

  const empCount = place.employee_count ? parseInt(place.employee_count) : 0;
  const employeeBadgeHtml = (empCount > 0)
    ? `<span class="badge badge-employees">👥 ${empCount} Members</span>`
    : '<span class="badge badge-none">—</span>';

  const orgChartBtn = `
    <button class="btn-org-tree" onclick="event.stopPropagation(); openOrgModal('${escapeHtml(place.name)}')">
      <span>🌳 Org Tree</span>
    </button>
  `;

  const isSelected = window.selectedRowIds && window.selectedRowIds.has(place.id);
  if (isSelected) tr.classList.add('row-selected');

  const checkTd = `<td style="text-align:center;" onclick="event.stopPropagation();"><input type="checkbox" class="row-select-checkbox" data-id="${place.id}" ${isSelected ? 'checked' : ''} onchange="window.onRowSelectChange()" /></td>`;
  const curType = curTab === 'platform' ? 'platform' : 'lead';
  const actionsTd = `<td style="text-align:center;" onclick="event.stopPropagation();">
    <div style="display:flex; gap:6px; justify-content:center;">
      <button class="btn-row-action btn-row-edit" onclick="window.openEditRowModal('${curType}', ${place.id})" title="Edit record">✏️</button>
      <button class="btn-row-action btn-row-delete" onclick="window.deleteSingleRow('${curType}', ${place.id}, '${escapeHtml(place.name || place.title || 'Record')}')" title="Delete record">🗑️</button>
    </div>
  </td>`;

  const originBadge = getLeadOriginBadge();
  const siteHtml = (place.website && place.website !== 'N/A')
    ? `<div style="display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap;"><a href="${encodeURI(place.website)}" target="_blank" class="link-btn" title="${escapeHtml(place.website)}" onclick="event.stopPropagation();">🌐 ${cleanDisplayUrl(place.website)}</a>${siteSrc}</div>`
    : '<span class="badge badge-none">—</span>';

  if (curTab === 'maps') {
    tr.innerHTML = `
      ${checkTd}
      <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
      <td class="shop-title"><div style="display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap;"><span>${escapeHtml(place.name)}</span>${originBadge}</div></td>
      <td>${categoryHtml}</td>
      <td>${emailHtml}</td>
      <td>${socialsHtml}</td>
      <td>${platformBookingHtml}</td>
      <td>${notesHtml}</td>
      <td>${phoneHtml}</td>
      <td style="color:#94a3b8; font-size:0.82rem; max-width:200px; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(place.address)}">${escapeHtml(place.address)}</td>
      <td>${ratingHtml}</td>
      <td>${siteHtml}</td>
      <td>${place.maps_url ? `<a href="${encodeURI(place.maps_url)}" target="_blank" class="link-btn" title="Open Google Maps listing" onclick="event.stopPropagation();">🗺️ Maps</a>` : '<span class="badge badge-none">—</span>'}</td>
      <td><span class="badge badge-verified" style="background:rgba(34,197,94,0.15); color:#4ade80; border:1px solid rgba(34,197,94,0.3);">✓ Captured</span></td>
      <td>${window.formatDateTime(place.created_at)}</td>
      ${actionsTd}
    `;
  } else if (curTab === 'website') {
    const wStatusTag = window.getLeadWebsiteStatusTag ? window.getLeadWebsiteStatusTag(place) : (place.status_tag || 'In Queue');
    const wStatusBadge = window.renderWebsiteStatusBadge ? window.renderWebsiteStatusBadge(wStatusTag) : renderWebsiteStatusBadge(wStatusTag);

    tr.innerHTML = `
      ${checkTd}
      <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
      <td class="shop-title"><div style="display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap;"><span>${escapeHtml(place.name)}</span>${originBadge}</div></td>
      <td>${categoryHtml}</td>
      <td>${wStatusBadge}</td>
      <td>${emailHtml}</td>
      <td>${socialsHtml}</td>
      <td>${platformBookingHtml}</td>
      <td>${botHtml}</td>
      <td>${cookieHtml}</td>
      <td>${screenHtml}</td>
      <td>${notesHtml}</td>
      <td>${phoneHtml}</td>
      <td style="color:#94a3b8; font-size:0.82rem; max-width:200px; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(place.address)}">${escapeHtml(place.address)}</td>
      <td>${ratingHtml}</td>
      <td>${siteHtml}</td>
      <td>${place.maps_url ? `<a href="${encodeURI(place.maps_url)}" target="_blank" class="link-btn" title="Open Google Maps listing" onclick="event.stopPropagation();">🗺️ Maps</a>` : '<span class="badge badge-none">—</span>'}</td>
      <td>${window.formatWebAgentDualDateTime(place.created_at, place.website_scraped_at, place.website_status, place.website)}</td>
      ${actionsTd}
    `;
  } else if (curTab === 'linkedin') {
    const liUrl = place.company_linkedin || place.linkedin || '';
    const liSrc = getSourceBadge('linkedin');
    let liStatusBadge = '<span class="badge badge-none">Pending</span>';
    if (empCount > 0 || place.founder_name) liStatusBadge = '<span class="badge badge-verified">🌳 Mapped</span>';
    else if (liUrl && liUrl !== 'N/A') liStatusBadge = '<span class="badge badge-category">Company Verified</span>';
    else if (place.linkedin_status === 'not_found') liStatusBadge = '<span class="badge badge-none">Not Found</span>';

    let keyPeopleHtml = '<span style="color:#64748b;">—</span>';
    if (place.founder_name) {
      keyPeopleHtml = `<span style="color:#38bdf8; font-weight:600;">👑 ${escapeHtml(place.founder_name)}</span> <small style="color:#94a3b8;">(${escapeHtml(place.founder_title || 'Decision Maker')})</small>`;
    } else if (empCount > 0) {
      keyPeopleHtml = `<span style="color:#38bdf8; font-weight:600;">${empCount} members</span> extracted`;
    }

    const companyLiHtml = (liUrl && liUrl !== 'N/A')
      ? `<div style="display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap;"><a href="${encodeURI(liUrl)}" target="_blank" class="badge-social badge-li" style="text-decoration:none; padding:4px 8px; width:auto; border-radius:6px;" title="${escapeHtml(liUrl)}" onclick="event.stopPropagation();">💼 LinkedIn Page</a>${liSrc}</div>`
      : '<span class="badge badge-none">—</span>';

    tr.innerHTML = `
      ${checkTd}
      <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
      <td class="shop-title"><div style="display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap;"><span>${escapeHtml(place.name || place.company_name)}</span>${originBadge}</div></td>
      <td>${liStatusBadge}</td>
      <td>${companyLiHtml}</td>
      <td>${employeeBadgeHtml}</td>
      <td style="font-size:0.8rem; color:#cbd5e1;">${keyPeopleHtml}</td>
      <td>${orgChartBtn}</td>
      <td>${window.formatDateTime(place.created_at)}</td>
      ${actionsTd}
    `;
  } else if (curTab === 'platform') {
    const pName = escapeHtml(place.platform || place.platform_name || 'Platform');
    const itemUrl = place.url || place.listing_url || place.platform_url || '';

    const platformColHtml = `
      <div style="display:flex; flex-direction:column; gap:4px;" onclick="event.stopPropagation();">
        <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
          ${itemUrl ? `<a href="${encodeURI(itemUrl)}" target="_blank" class="badge-platform-btn" title="Open '${escapeHtml(displayName)}' on ${pName}">🟣 ${pName} <span style="font-size:0.75rem; opacity:0.85;">↗</span></a>` : `<span class="badge badge-platform">🟣 ${pName}</span>`}
          ${(place.booking_url && place.booking_url !== 'N/A') ? `<a href="${encodeURI(place.booking_url)}" target="_blank" class="badge-social" style="color:#a855f7; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); font-size:0.72rem; padding:2px 6px; text-decoration:none; width:auto; border-radius:6px;" title="Direct Booking / Reservation URL" onclick="event.stopPropagation();">📅 Book</a>` : ''}
        </div>
        ${itemUrl ? `<a href="${encodeURI(itemUrl)}" target="_blank" class="platform-direct-link" title="${escapeHtml(itemUrl)}">🔗 ${cleanDisplayUrl(itemUrl)}</a>` : ''}
      </div>
    `;

    const wStatusTag = place.status_tag || (place.website_status === 'contacts_found' ? 'Contacts Found' : (place.website_status === 'bot_blocked' ? 'Bot Shield Active' : (place.website_status === 'no_contacts' ? 'No Contacts Found' : 'In Queue')));
    const wStatusBadge = window.renderWebsiteStatusBadge ? window.renderWebsiteStatusBadge(wStatusTag) : renderWebsiteStatusBadge(wStatusTag);

    const platActionsTd = `<td style="text-align:center;" onclick="event.stopPropagation();">
      <div style="display:flex; gap:6px; justify-content:center;">
        <button class="btn-row-action btn-row-edit" onclick="window.openEditRowModal('platform', ${place.id})" title="Edit listing">✏️</button>
        <button class="btn-row-action btn-row-delete" onclick="window.deleteSingleRow('platform', ${place.id}, '${escapeHtml(displayName)}')" title="Delete listing">🗑️</button>
      </div>
    </td>`;

    tr.innerHTML = `
      ${checkTd}
      <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
      <td class="shop-title"><div style="display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap;"><span>${escapeHtml(displayName)}</span>${originBadge}</div></td>
      <td>${categoryHtml}</td>
      <td>${wStatusBadge}</td>
      <td>${emailHtml}</td>
      <td>${socialsHtml}</td>
      <td>${platformColHtml}</td>
      <td>${botHtml}</td>
      <td>${cookieHtml}</td>
      <td>${screenHtml}</td>
      <td>${notesHtml}</td>
      <td>${phoneHtml}</td>
      <td style="color:#94a3b8; font-size:0.82rem; max-width:200px; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(place.address || 'N/A')}">${escapeHtml(place.address || 'N/A')}</td>
      <td>${ratingHtml}</td>
      <td>${siteHtml}</td>
      <td>${place.maps_url ? `<a href="${encodeURI(place.maps_url)}" target="_blank" class="link-btn" title="Open Google Maps listing" onclick="event.stopPropagation();">🗺️ Maps</a>` : '<span class="badge badge-none">—</span>'}</td>
      <td>${window.formatDateTime(place.created_at)}</td>
      ${platActionsTd}
    `;
  } else {
    // Table 1: Master Normalized
    let platformHtml = '<span class="badge badge-none">—</span>';
    if (place.platform_name && place.platform_name !== 'N/A') {
      const pName = escapeHtml(place.platform_name);
      const pUrl = place.platform_url || place.booking_url || '';
      const pRating = (place.platform_rating && place.platform_rating !== 'N/A') ? `⭐ ${place.platform_rating}` : '';
      const pReviews = (place.platform_reviews && place.platform_reviews !== 'N/A') ? `(${place.platform_reviews})` : '';
      const bookLink = (place.booking_url && place.booking_url !== 'N/A' && place.booking_url !== pUrl)
        ? `<a href="${encodeURI(place.booking_url)}" target="_blank" class="badge-social" style="color:#a855f7; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); font-size:0.72rem; padding:2px 6px; text-decoration:none; width:auto;" title="Direct Booking / Listing" onclick="event.stopPropagation();">📅 Book</a>`
        : '';
      const badgeBtn = pUrl
        ? `<a href="${encodeURI(pUrl)}" target="_blank" class="badge-platform-btn" title="Open ${escapeHtml(place.name)} on ${pName}: ${escapeHtml(pUrl)}" onclick="event.stopPropagation();">🟣 ${pName} <span style="font-size:0.75rem; opacity:0.85;">↗</span></a>`
        : `<span class="badge badge-platform">🟣 ${pName}</span>`;
      const directLink = pUrl
        ? `<a href="${encodeURI(pUrl)}" target="_blank" class="platform-direct-link" title="${escapeHtml(pUrl)}" onclick="event.stopPropagation();">🔗 ${cleanDisplayUrl(pUrl)}</a>`
        : '';

      platformHtml = `
        <div style="display:flex; flex-direction:column; gap:4px;" onclick="event.stopPropagation();">
          <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
            ${badgeBtn}
            ${bookLink}
            <span class="badge badge-verified" title="Normalized & Cross-Verified Match">✔ Verified</span>
          </div>
          ${directLink}
          ${pRating ? `<span style="font-size:0.72rem; color:#d8b4fe; white-space:nowrap;">${pRating} <small style="color:#94a3b8;">${pReviews}</small></span>` : ''}
          ${place.platform_price && place.platform_price !== 'N/A' ? `<span style="font-size:0.68rem; color:#34d399; white-space:nowrap;">💰 ${escapeHtml(place.platform_price)}</span>` : ''}
        </div>
      `;
    }

    tr.innerHTML = `
      ${checkTd}
      <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
      <td class="shop-title"><div style="display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap;"><span>${escapeHtml(place.name)}</span>${originBadge}</div></td>
      <td>${categoryHtml}</td>
      <td>${emailHtml}</td>
      <td>${socialsHtml}</td>
      <td>${botHtml}</td>
      <td>${cookieHtml}</td>
      <td>${employeeBadgeHtml}</td>
      <td>${orgChartBtn}</td>
      <td>${screenHtml}</td>
      <td>${phoneHtml}</td>
      <td style="color:#94a3b8; font-size:0.82rem; max-width:180px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(place.address)}</td>
      <td>${ratingHtml}</td>
      <td>${platformHtml}</td>
      <td>${linksHtml}</td>
      <td>${window.formatDateTime(place.created_at)}</td>
      ${actionsTd}
    `;
  }
  return tr;
};

// =======================================================================
// UNIVERSAL LIVE INCREMENTAL ROW SYNCHRONIZATION (ACROSS ALL 5 TABLES)
// =======================================================================

window.updateOrPrependLiveRow = function(tabName, item) {
  if (!item || !tabName) return;

  const tbody = document.getElementById('places-tbody');
  if (!tbody) return;

  if (!window.tablesSplitData) {
    window.tablesSplitData = {
      master_leads: [],
      unmatched_maps: [],
      unmatched_platform: [],
      website_leads: [],
      linkedin_leads: [],
      counts: {},
      queue_progress: {}
    };
  }

  let listKey = 'unmatched_maps';
  if (tabName === 'master') listKey = 'master_leads';
  else if (tabName === 'website') listKey = 'website_leads';
  else if (tabName === 'linkedin') listKey = 'linkedin_leads';
  else if (tabName === 'platform') listKey = 'unmatched_platform';

  if (!Array.isArray(window.tablesSplitData[listKey])) {
    window.tablesSplitData[listKey] = [];
  }
  const list = window.tablesSplitData[listKey];

  // Match existing record in dataset
  const matchIdx = list.findIndex(p => {
    if (item.id && p.id && String(p.id) === String(item.id)) return true;
    if (tabName === 'platform') {
      const pUrl = (p.url || p.listing_url || '').split('?')[0].toLowerCase();
      const iUrl = (item.url || item.listing_url || '').split('?')[0].toLowerCase();
      if (pUrl && iUrl && pUrl === iUrl) return true;
      const pTitle = (p.title || p.name || '').trim().toLowerCase();
      const iTitle = (item.title || item.name || '').trim().toLowerCase();
      return pTitle && iTitle && pTitle === iTitle && (p.platform === item.platform);
    }
    const pName = (p.name || p.title || '').trim().toLowerCase();
    const iName = (item.name || item.title || '').trim().toLowerCase();
    if (pName && iName && pName === iName) {
      if (!p.address || !item.address || p.address === 'N/A' || item.address === 'N/A') return true;
      return p.address.toLowerCase().includes(item.address.toLowerCase()) || item.address.toLowerCase().includes(p.address.toLowerCase());
    }
    return false;
  });

  if (matchIdx >= 0) {
    Object.assign(list[matchIdx], item);
    item = list[matchIdx];
  } else {
    list.unshift(item);
  }

  // Update tab switcher badge
  const badgeEl = document.getElementById('badge-count-' + tabName);
  if (badgeEl) badgeEl.innerText = list.length;

  // Update total database KPI
  const statTotal = document.getElementById('stat-total');
  if (statTotal && window.tablesSplitData.master_leads && window.tablesSplitData.unmatched_maps) {
    statTotal.innerText = window.tablesSplitData.master_leads.length + window.tablesSplitData.unmatched_maps.length;
  }

  // If the user is currently viewing this tab, update DOM live!
  if (window.currentTableTab === tabName) {
    if (window.tableFilters && window.tableFilters.timeSort === 'oldest') {
      window.renderTable();
      return;
    }

    const emptyRow = document.getElementById('empty-row');
    if (emptyRow) emptyRow.remove();

    const rowId = item.id;
    let existingRow = rowId ? document.getElementById(`row-${rowId}`) : null;
    if (!existingRow) {
      const itemName = (item.name || item.title || '').trim().toLowerCase();
      const allRows = tbody.querySelectorAll('tr');
      for (let r of allRows) {
        const titleEl = r.querySelector('.shop-title');
        if (titleEl && titleEl.innerText.trim().toLowerCase() === itemName) {
          existingRow = r;
          if (rowId) existingRow.id = `row-${rowId}`;
          break;
        }
      }
    }

    if (existingRow) {
      const updatedTr = window.buildSinglePlaceRow(item, 0, tabName);
      existingRow.innerHTML = updatedTr.innerHTML;
      existingRow.classList.remove('row-live-arrived');
      void existingRow.offsetWidth;
      existingRow.classList.add('row-live-arrived');
      tbody.insertBefore(existingRow, tbody.firstChild);
      setTimeout(() => existingRow.classList.remove('row-live-arrived'), 2800);
    } else {
      const newTr = window.buildSinglePlaceRow(item, 0, tabName);
      newTr.classList.add('row-live-arrived');
      tbody.insertBefore(newTr, tbody.firstChild);

      const numCells = tbody.querySelectorAll('tr > td:nth-child(2)');
      numCells.forEach((c, idx) => {
        if (idx < 50) c.innerText = idx + 1;
      });

      const tableContainer = document.querySelector('.table-responsive') || document.querySelector('.table-container') || tbody.closest('div');
      if (tableContainer) {
        tableContainer.scrollTo({ top: 0, behavior: 'smooth' });
      }

      setTimeout(() => newTr.classList.remove('row-live-arrived'), 2800);
    }

    const countBadge = document.getElementById('places-count-badge');
    if (countBadge) countBadge.innerText = `${list.length} items`;
  }
};

window.prependLivePlaceRow = function(place) {
  window.updateOrPrependLiveRow('maps', place);
};

window.renderTable = function() {
  window.renderTableHeader();
  const tbody = document.getElementById('places-tbody');
  if (!tbody) return;

  let activeList = [];
  let emptyMsg = "No places in database. Click 'Start Live Agent' to harvest leads!";
  if (window.currentTableTab === 'master') {
    activeList = window.tablesSplitData.master_leads || [];
    emptyMsg = "No normalized master leads yet. Click 'Normalize Leads' to match leads across Maps and Directories!";
  } else if (window.currentTableTab === 'maps') {
    activeList = window.tablesSplitData.unmatched_maps || [];
    emptyMsg = "No Google Maps leads found yet. Click 'Start Live Agent' to harvest leads.";
  } else if (window.currentTableTab === 'website') {
    activeList = window.tablesSplitData.website_leads || [];
    emptyMsg = "No website inspection records yet.";
  } else if (window.currentTableTab === 'linkedin') {
    activeList = window.tablesSplitData.linkedin_leads || [];
    emptyMsg = "No LinkedIn org records yet.";
  } else if (window.currentTableTab === 'platform') {
    activeList = window.tablesSplitData.unmatched_platform || [];
    emptyMsg = "No Platform Directory listings found yet. Enable Platform Scout to scrape directories.";
  }

  // Populate dynamic category dropdown
  if (typeof window.populateCategoryDropdown === 'function') {
    window.populateCategoryDropdown(activeList);
    window.populatePlatformDropdown(activeList);
  }

  // Ensure column-specific filters are adapted for active table
  if (typeof window.renderFiltersForCurrentTable === 'function') {
    window.renderFiltersForCurrentTable();
  }

  // Apply active column filters
  const f = window.tableFilters || {};
  const isFiltered = !!(
    f.search ||
    f.category ||
    f.platform ||
    f.statusTag ||
    (window.activeTagFilter && window.activeTagFilter !== 'All') ||
    (f.minRating > 0) ||
    f.botSecurity ||
    f.cookieStatus ||
    f.pricing ||
    f.hasEmail ||
    f.hasPhone ||
    f.hasWebsite ||
    f.hasScreenshot ||
    f.hasSocial ||
    f.hasTeam ||
    f.hasBooking ||
    f.hasAddress
  );

  const filteredList = activeList.filter(item => {
    // 0. Status Tag Filter (for Website, LinkedIn & Master tabs)
    const effectiveTagFilter = f.statusTag || (window.activeTagFilter !== 'All' ? window.activeTagFilter : '');
    if (effectiveTagFilter) {
      const itemTag = window.getLeadWebsiteStatusTag ? window.getLeadWebsiteStatusTag(item) : (item.status_tag || '');
      if (itemTag.toLowerCase() !== effectiveTagFilter.toLowerCase() && (item.status_tag || '').toLowerCase() !== effectiveTagFilter.toLowerCase()) {
        return false;
      }
    }
    // 1. Search keyword (matches Title/Name, Address, Phone, Email, Platform)
    if (f.search) {
      const title = (item.title || item.name || item.company_name || '').toLowerCase();
      const addr = (item.address || '').toLowerCase();
      const cat = (item.category || '').toLowerCase();
      const phone = (item.phone || '').toLowerCase();
      const email = (item.email || '').toLowerCase();
      const plat = (item.platform || item.platform_name || '').toLowerCase();
      if (!title.includes(f.search) && !addr.includes(f.search) && !cat.includes(f.search) &&
          !phone.includes(f.search) && !email.includes(f.search) && !plat.includes(f.search)) {
        return false;
      }
    }

    // 2. Column: Category
    if (f.category) {
      const c = (item.category || '').trim().toLowerCase();
      if (c !== f.category.toLowerCase()) return false;
    }

    // 3. Column: Platform Directory
    if (f.platform) {
      const p = (item.platform || item.platform_name || '').trim().toLowerCase();
      const reqP = f.platform.toLowerCase();
      if (reqP === 'google maps') {
        if (window.currentTableTab !== 'maps' && !p.includes('maps') && !item.maps_url && !item.place_id) {
          return false;
        }
      } else {
        if (!p.includes(reqP)) return false;
      }
    }

    // 4. Column: Rating & Reviews
    if (f.minRating > 0) {
      const r = parseFloat(item.rating || item.platform_rating || 0);
      if (isNaN(r) || r < f.minRating) return false;
    }

    // 5. Column: Bot Security
    if (f.botSecurity) {
      const b = (item.bot_protection || '').trim().toLowerCase();
      if (f.botSecurity === 'clean') {
        if (b !== 'clean' && b !== 'none' && b !== '') return false;
      } else if (!b.includes(f.botSecurity.toLowerCase())) {
        return false;
      }
    }

    // 6. Column: Cookies Status
    if (f.cookieStatus) {
      const c = (item.cookie_status || '').trim().toLowerCase();
      if (!c.includes(f.cookieStatus.toLowerCase())) return false;
    }

    // 7. Column: Pricing Tier
    if (f.pricing) {
      if (f.pricing === 'has_price') {
        const pr = (item.price_info || item.platform_price || item.price_range || '').trim();
        if (!pr || pr === 'N/A') return false;
      }
    }

    // 8. Quick Column Toggles
    if (f.hasEmail) {
      if (!item.email || item.email === 'N/A' || item.email.trim() === '') return false;
    }
    if (f.hasPhone) {
      if (!item.phone || item.phone === 'N/A' || item.phone.trim() === '') return false;
    }
    if (f.hasWebsite) {
      const web = (item.website || item.url || item.platform_url || '').trim();
      if (!web || web === 'N/A') return false;
    }
    if (f.hasScreenshot) {
      if (!item.screenshot || item.screenshot === 'N/A' || item.screenshot.trim() === '') return false;
    }
    if (f.hasSocial) {
      const hasSoc = Boolean(
        (item.linkedin && item.linkedin !== 'N/A') ||
        (item.instagram && item.instagram !== 'N/A') ||
        (item.facebook && item.facebook !== 'N/A') ||
        (item.twitter && item.twitter !== 'N/A') ||
        (item.youtube && item.youtube !== 'N/A') ||
        (item.tiktok && item.tiktok !== 'N/A')
      );
      if (!hasSoc) return false;
    }
    if (f.hasTeam) {
      const empCount = parseInt(item.employee_count) || 0;
      if (empCount <= 0) return false;
    }
    if (f.hasBooking) {
      const book = (item.booking_url || '').trim();
      if (!book || book === 'N/A') return false;
    }
    if (f.hasAddress) {
      const addr = (item.address || '').trim();
      if (!addr || addr === 'N/A') return false;
    }

    return true;
  });

  // Universal Time Arrangement: Latest First vs Oldest First across all tables
  const timeSortOrder = (window.tableFilters && window.tableFilters.timeSort) ? window.tableFilters.timeSort : 'latest';
  filteredList.sort((a, b) => {
    const tA = window.getItemTimeValue(a);
    const tB = window.getItemTimeValue(b);
    if (tA !== tB) {
      return timeSortOrder === 'oldest' ? tA - tB : tB - tA;
    }
    const idA = parseInt(a.id, 10) || 0;
    const idB = parseInt(b.id, 10) || 0;
    return timeSortOrder === 'oldest' ? idA - idB : idB - idA;
  });

  const countBadge = document.getElementById('places-count-badge');
  if (countBadge) {
    if (isFiltered) {
      countBadge.innerText = `${filteredList.length} of ${activeList.length} items`;
    } else {
      countBadge.innerText = `${activeList.length} items`;
    }
  }

  if (filteredList.length === 0) {
    const displayMsg = isFiltered
      ? "No records match your active filters. Click '↺ Reset' to view all items."
      : emptyMsg;
    tbody.innerHTML = `
      <tr id="empty-row">
        <td colspan="16">
          <div class="empty-state">
            <div class="empty-icon">🔍</div>
            <p>${displayMsg}</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = '';

  filteredList.forEach((place, index) => {
    tbody.appendChild(window.buildSinglePlaceRow(place, index, window.currentTableTab));
  });

  // Update header checkbox and batch bar
  const allBoxes = document.querySelectorAll('.row-select-checkbox');
  const selBox = document.getElementById('select-all-checkbox');
  if (selBox) {
    if (allBoxes.length === 0) {
      selBox.checked = false;
      selBox.indeterminate = false;
    } else {
      const checkedCount = document.querySelectorAll('.row-select-checkbox:checked').length;
      selBox.checked = checkedCount === allBoxes.length;
      selBox.indeterminate = checkedCount > 0 && checkedCount < allBoxes.length;
    }
  }
  if (typeof window.updateBatchBar === 'function') {
    window.updateBatchBar();
  }
};

// =======================================================================
// INITIALIZATION
// =======================================================================

window.addEventListener('DOMContentLoaded', () => {
  if (typeof window.switchTableTab === 'function') {
    window.switchTableTab('platform');
  }
  window.refreshTablesSplit();
});


// =======================================================================
// SELECTION, BATCH OPERATIONS & INDIVIDUAL EDIT/DELETE LOGIC
// =======================================================================

window.selectedRowIds = new Set();

window.toggleSelectAll = function(checked) {
  const visibleCheckboxes = document.querySelectorAll('#places-tbody tr:not([style*="display: none"]):not(#empty-row) .row-select-checkbox');
  visibleCheckboxes.forEach(cb => {
    cb.checked = checked;
    const id = parseInt(cb.getAttribute('data-id'), 10);
    const tr = cb.closest('tr');
    if (id) {
      if (checked) {
        window.selectedRowIds.add(id);
        if (tr) tr.classList.add('row-selected');
      } else {
        window.selectedRowIds.delete(id);
        if (tr) tr.classList.remove('row-selected');
      }
    }
  });
  window.updateBatchBar();
};

window.onRowSelectChange = function() {
  const visibleCheckboxes = document.querySelectorAll('#places-tbody tr:not([style*="display: none"]):not(#empty-row) .row-select-checkbox');
  window.selectedRowIds.clear();
  let checkedCount = 0;
  visibleCheckboxes.forEach(cb => {
    const id = parseInt(cb.getAttribute('data-id'), 10);
    const tr = cb.closest('tr');
    if (cb.checked) {
      checkedCount++;
      if (id) window.selectedRowIds.add(id);
      if (tr) tr.classList.add('row-selected');
    } else {
      if (tr) tr.classList.remove('row-selected');
    }
  });

  const selAll = document.getElementById('select-all-checkbox');
  if (selAll) {
    selAll.checked = (visibleCheckboxes.length > 0 && checkedCount === visibleCheckboxes.length);
    selAll.indeterminate = (checkedCount > 0 && checkedCount < visibleCheckboxes.length);
  }
  window.updateBatchBar();
};

window.deselectAllRows = function() {
  window.selectedRowIds.clear();
  const checkboxes = document.querySelectorAll('.row-select-checkbox');
  checkboxes.forEach(cb => {
    cb.checked = false;
    const tr = cb.closest('tr');
    if (tr) tr.classList.remove('row-selected');
  });
  const selAll = document.getElementById('select-all-checkbox');
  if (selAll) {
    selAll.checked = false;
    selAll.indeterminate = false;
  }
  window.updateBatchBar();
};

window.updateBatchBar = function() {
  const bar = document.getElementById('batch-actions-bar');
  const countEl = document.getElementById('batch-selected-count');
  const editBtn = document.getElementById('btn-edit-selected');
  const editBtnText = document.getElementById('btn-edit-selected-text');
  const deleteBtnText = document.getElementById('btn-delete-selected-text');
  const selectBtnText = document.getElementById('select-btn-text');
  const selectBtnIcon = document.getElementById('select-btn-icon');

  const count = window.selectedRowIds ? window.selectedRowIds.size : 0;
  const visibleBoxes = document.querySelectorAll('#places-tbody tr:not([style*="display: none"]):not(#empty-row) .row-select-checkbox');

  // Update top "Select All" button state
  if (selectBtnText && selectBtnIcon) {
    if (visibleBoxes.length > 0 && count >= visibleBoxes.length) {
      selectBtnIcon.innerText = '❎';
      selectBtnText.innerText = 'Deselect All';
    } else {
      selectBtnIcon.innerText = '☑️';
      selectBtnText.innerText = visibleBoxes.length > 0 ? `Select All (${visibleBoxes.length})` : 'Select All';
    }
  }

  if (!bar) return;
  if (count > 0) {
    bar.style.display = 'flex';
    if (countEl) countEl.innerText = `${count} ${count === 1 ? 'record' : 'records'} selected`;

    if (editBtn && editBtnText) {
      if (count === 1) {
        editBtnText.innerText = 'Edit Record';
        editBtn.title = 'Open full editor for this selected record';
      } else {
        editBtnText.innerText = 'Mass Edit';
        editBtn.title = `Mass edit ${count} selected records`;
      }
    }

    if (deleteBtnText) {
      deleteBtnText.innerText = count === 1 ? '🗑️ Delete Record' : `🗑️ Mass Delete Selected (${count})`;
    }
  } else {
    bar.style.display = 'none';
  }
};

window.handleEditSelectedClick = function() {
  const count = window.selectedRowIds ? window.selectedRowIds.size : 0;
  if (count === 0) {
    alert('Please select at least one record using a checkbox.');
    return;
  }
  if (count === 1) {
    const id = Array.from(window.selectedRowIds)[0];
    const curType = window.currentTableTab === 'platform' ? 'platform' : 'lead';
    window.openEditRowModal(curType, id);
  } else {
    window.openBatchEditModal();
  }
};

window.toggleSelectAllButton = function() {
  const visibleBoxes = Array.from(document.querySelectorAll('#places-tbody tr:not([style*="display: none"]):not(#empty-row) .row-select-checkbox'));
  if (visibleBoxes.length === 0) return;
  const checkedCount = visibleBoxes.filter(cb => cb.checked).length;
  const shouldSelect = checkedCount < visibleBoxes.length;
  window.toggleSelectAll(shouldSelect);

  const headerCb = document.getElementById('select-all-checkbox');
  if (headerCb) {
    headerCb.checked = shouldSelect;
    headerCb.indeterminate = false;
  }
};

window.batchDeleteSelected = async function() {
  const count = window.selectedRowIds ? window.selectedRowIds.size : 0;
  if (count === 0) return;
  const isPlatform = (window.currentTableTab === 'platform');
  const tableLabel = isPlatform ? 'Platform Directory Listings' : 'Leads';
  if (!confirm(`Are you sure you want to permanently delete ${count} selected ${tableLabel}? This action cannot be undone.`)) {
    return;
  }

  const ids = Array.from(window.selectedRowIds);
  const endpoint = isPlatform
    ? '/api/platform-listings/batch-delete'
    : '/api/leads/batch-delete';

  // Instant visual feedback: dim rows being deleted
  ids.forEach(id => {
    document.querySelectorAll(`tr#row-${id}, input.row-select-checkbox[data-id="${id}"]`).forEach(el => {
      const tr = el.closest('tr') || el;
      tr.style.opacity = '0.3';
    });
  });

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids })
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const data = await res.json();

    // Remove rows from DOM immediately
    ids.forEach(id => {
      document.querySelectorAll(`tr#row-${id}`).forEach(tr => tr.remove());
      if (window.tablesSplitData) {
        ['master_leads', 'unmatched_maps', 'website_leads', 'linkedin_leads', 'unmatched_platform'].forEach(k => {
          if (Array.isArray(window.tablesSplitData[k])) {
            window.tablesSplitData[k] = window.tablesSplitData[k].filter(item => item.id !== id);
          }
        });
      }
      if (Array.isArray(window.placesData)) {
        window.placesData = window.placesData.filter(item => item.id !== id);
      }
    });

    window.deselectAllRows();
    if (typeof window.refreshTablesSplit === 'function') {
      await window.refreshTablesSplit();
    } else if (typeof window.renderTable === 'function') {
      window.renderTable();
    }
    alert(`Successfully deleted ${data.deleted_count || count} records.`);
  } catch (err) {
    console.error('Batch delete failed:', err);
    alert('Failed to delete selected records: ' + err.message);
    if (typeof window.renderTable === 'function') window.renderTable();
  }
};

window.openBatchEditModal = function() {
  const count = window.selectedRowIds ? window.selectedRowIds.size : 0;
  if (count === 0) {
    alert('Please select at least one record to edit.');
    return;
  }
  const modal = document.getElementById('batch-edit-modal');
  const desc = document.getElementById('batch-edit-desc');
  if (desc) {
    desc.innerHTML = `Update fields across <strong>${count}</strong> selected records. <em>Leave any field blank to keep its existing value.</em>`;
  }
  const catInput = document.getElementById('batch-edit-category');
  if (catInput) catInput.value = '';
  const statusInput = document.getElementById('batch-edit-status');
  if (statusInput) statusInput.value = '';
  const phoneInput = document.getElementById('batch-edit-phone');
  if (phoneInput) phoneInput.value = '';
  const cityInput = document.getElementById('batch-edit-city');
  if (cityInput) cityInput.value = '';
  const notesInput = document.getElementById('batch-edit-notes');
  if (notesInput) notesInput.value = '';

  if (modal) modal.style.display = 'flex';
};

window.closeBatchEditModal = function() {
  const modal = document.getElementById('batch-edit-modal');
  if (modal) modal.style.display = 'none';
};

window.submitBatchEdit = async function(e) {
  if (e && e.preventDefault) e.preventDefault();
  const count = window.selectedRowIds ? window.selectedRowIds.size : 0;
  if (count === 0) {
    alert('No records selected.');
    return;
  }

  const catVal = (document.getElementById('batch-edit-category')?.value || '').trim();
  const statusVal = (document.getElementById('batch-edit-status')?.value || '').trim();
  const phoneVal = (document.getElementById('batch-edit-phone')?.value || '').trim();
  const cityVal = (document.getElementById('batch-edit-city')?.value || '').trim();
  const notesVal = (document.getElementById('batch-edit-notes')?.value || '').trim();

  const updates = {};
  if (catVal) updates.category = catVal;
  if (statusVal) {
    updates.status_tag = statusVal;
    updates.website_status = statusVal;
  }
  if (phoneVal) updates.phone = phoneVal;
  if (cityVal) updates.address = cityVal;
  if (notesVal) updates.notes = notesVal;

  if (Object.keys(updates).length === 0) {
    alert('Please fill in at least one field to update, or click Cancel.');
    return;
  }

  const ids = Array.from(window.selectedRowIds);
  const isPlatform = (window.currentTableTab === 'platform');
  const endpoint = isPlatform
    ? '/api/platform-listings/batch-update'
    : '/api/leads/batch-update';

  const btnSubmit = document.getElementById('btn-submit-batch-edit');
  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.innerText = 'Applying...';
  }

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids, updates: updates })
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const data = await res.json();

    window.closeBatchEditModal();
    window.deselectAllRows();
    if (typeof window.refreshTablesSplit === 'function') {
      await window.refreshTablesSplit();
    } else if (typeof window.renderTable === 'function') {
      window.renderTable();
    }
    alert(`Successfully updated ${data.updated_count || ids.length} records!`);
  } catch (err) {
    console.error('Batch update failed:', err);
    alert('Failed to update records: ' + err.message);
  } finally {
    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.innerText = 'Apply to All Selected';
    }
  }
};

window.exportSelectedCSV = function() {
  const count = window.selectedRowIds ? window.selectedRowIds.size : 0;
  if (count === 0) {
    alert('No rows selected. Please select rows using checkboxes.');
    return;
  }
  const idsParam = Array.from(window.selectedRowIds).join(',');
  const tableParam = window.currentTableTab || 'all';
  window.location.href = `/api/export/csv?ids=${idsParam}&table=${tableParam}`;
};

// -----------------------------------------------------------------------
// Individual Edit & Delete Operations
// -----------------------------------------------------------------------

window.openEditRowModal = async function(type, id) {
  let record = null;
  const numId = parseInt(id, 10);
  const isPlatform = (type === 'platform' || window.currentTableTab === 'platform');
  const split = window.tablesSplitData || {};

  if (isPlatform) {
    record = (split.unmatched_platform || []).find(p => p.id === numId);
    if (!record && Array.isArray(window.placesData)) {
      record = window.placesData.find(p => p.id === numId && (p.platform || p.platform_name));
    }
  } else {
    record = (split.master_leads || []).find(p => p.id === numId)
          || (split.website_leads || []).find(p => p.id === numId)
          || (split.unmatched_maps || []).find(p => p.id === numId)
          || (split.linkedin_leads || []).find(p => p.id === numId);
    if (!record && Array.isArray(window.placesData)) {
      record = window.placesData.find(p => p.id === numId);
    }
  }

  // Fallback to fetch from backend if not found in memory
  if (!record) {
    try {
      const endpoint = isPlatform ? `/api/platform-listings/${numId}` : `/api/leads/${numId}`;
      const res = await fetch(endpoint);
      if (res.ok) {
        const json = await res.json();
        record = json.lead || json.listing || json.data || json;
      }
    } catch (e) {
      console.warn('Could not fetch single record from backend:', e);
    }
  }

  if (!record) {
    alert('Record not found.');
    return;
  }

  const modal = document.getElementById('edit-row-modal');
  const titleEl = document.getElementById('edit-modal-title');
  document.getElementById('edit-item-id').value = record.id;
  document.getElementById('edit-item-type').value = isPlatform ? 'platform' : 'lead';

  if (titleEl) {
    titleEl.innerText = isPlatform ? `✏️ Edit Directory Listing: #${record.id}` : `✏️ Edit Lead Details: #${record.id}`;
  }

  document.getElementById('edit-field-name').value = record.title || record.name || '';
  document.getElementById('edit-field-category').value = record.category || '';
  document.getElementById('edit-field-phone').value = (record.phone && record.phone !== 'N/A') ? record.phone : '';
  const waInput = document.getElementById('edit-field-whatsapp');
  if (waInput) {
    waInput.value = (record.whatsapp && record.whatsapp !== 'N/A') ? record.whatsapp : '';
  }
  document.getElementById('edit-field-address').value = (record.address && record.address !== 'N/A') ? record.address : '';
  document.getElementById('edit-field-rating').value = (record.rating && record.rating !== 'N/A') ? record.rating : '';

  const emailGroup = document.getElementById('edit-group-email');
  const emailInput = document.getElementById('edit-field-email');
  if (emailGroup && emailInput) {
    emailGroup.style.display = 'flex';
    emailInput.value = (record.email && record.email !== 'N/A') ? record.email : '';
  }

  const websiteGroup = document.getElementById('edit-group-website');
  const websiteInput = document.getElementById('edit-field-website');
  if (websiteGroup && websiteInput) {
    websiteGroup.style.display = 'flex';
    websiteInput.value = (record.website && record.website !== 'N/A') ? record.website : '';
  }

  const bookingGroup = document.getElementById('edit-group-booking');
  const bookingInput = document.getElementById('edit-field-booking');
  if (bookingGroup && bookingInput) {
    if (isPlatform) {
      bookingGroup.style.display = 'flex';
      bookingInput.value = (record.booking_url && record.booking_url !== 'N/A') ? record.booking_url : (record.url || '');
    } else {
      bookingGroup.style.display = (record.booking_url && record.booking_url !== 'N/A') ? 'flex' : 'none';
      bookingInput.value = (record.booking_url && record.booking_url !== 'N/A') ? record.booking_url : '';
    }
  }

  const priceInput = document.getElementById('edit-field-price');
  if (priceInput) {
    priceInput.value = (record.price_info || record.price || record.platform_price || '');
  }

  const statusInput = document.getElementById('edit-field-status');
  if (statusInput) {
    statusInput.value = record.status_tag || record.website_status || '';
  }

  const notesInput = document.getElementById('edit-field-notes');
  if (notesInput) {
    notesInput.value = record.notes || '';
  }

  if (modal) modal.style.display = 'flex';
};

window.closeEditRowModal = function() {
  const modal = document.getElementById('edit-row-modal');
  if (modal) modal.style.display = 'none';
};

window.saveRowEdit = async function(e) {
  e.preventDefault();
  const id = parseInt(document.getElementById('edit-item-id').value, 10);
  const type = document.getElementById('edit-item-type').value;
  if (!id) return;

  const isPlatform = (type === 'platform');
  const nameVal = document.getElementById('edit-field-name').value.trim();
  const catVal = document.getElementById('edit-field-category').value.trim();
  const phoneVal = document.getElementById('edit-field-phone').value.trim();
  const waVal = document.getElementById('edit-field-whatsapp') ? document.getElementById('edit-field-whatsapp').value.trim() : '';
  const addrVal = document.getElementById('edit-field-address').value.trim();
  const ratingVal = document.getElementById('edit-field-rating').value.trim();
  const priceVal = document.getElementById('edit-field-price').value.trim();
  const statusVal = document.getElementById('edit-field-status') ? document.getElementById('edit-field-status').value.trim() : '';
  const notesVal = document.getElementById('edit-field-notes') ? document.getElementById('edit-field-notes').value.trim() : '';

  let payload = {};
  let endpoint = '';

  if (isPlatform) {
    const bookingVal = document.getElementById('edit-field-booking') ? document.getElementById('edit-field-booking').value.trim() : '';
    const emailVal = document.getElementById('edit-field-email') ? document.getElementById('edit-field-email').value.trim() : '';
    const websiteVal = document.getElementById('edit-field-website') ? document.getElementById('edit-field-website').value.trim() : '';
    payload = {
      title: nameVal,
      category: catVal,
      phone: phoneVal,
      whatsapp: waVal,
      email: emailVal,
      website: websiteVal,
      address: addrVal,
      rating: ratingVal ? parseFloat(ratingVal) || 0.0 : 0.0,
      price_info: priceVal,
      booking_url: bookingVal
    };
    if (statusVal) payload.website_status = statusVal;
    if (notesVal !== undefined) payload.notes = notesVal;
    endpoint = `/api/platform-listings/${id}`;
  } else {
    const emailVal = document.getElementById('edit-field-email').value.trim();
    const websiteVal = document.getElementById('edit-field-website').value.trim();
    payload = {
      name: nameVal,
      category: catVal,
      phone: phoneVal,
      whatsapp: waVal,
      email: emailVal,
      address: addrVal,
      rating: ratingVal,
      price: priceVal,
      website: websiteVal
    };
    if (statusVal) {
      payload.website_status = statusVal;
      payload.status_tag = statusVal;
    }
    if (notesVal !== undefined) {
      payload.notes = notesVal;
    }
    endpoint = `/api/leads/${id}`;
  }

  const btnSave = document.getElementById('btn-save-edit');
  if (btnSave) {
    btnSave.disabled = true;
    btnSave.innerText = '💾 Saving...';
  }

  try {
    const res = await fetch(endpoint, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    window.closeEditRowModal();
    if (typeof window.refreshTablesSplit === 'function') {
      await window.refreshTablesSplit();
    } else if (typeof window.renderTable === 'function') {
      window.renderTable();
    }
  } catch (err) {
    console.error('Failed to save edit:', err);
    alert('Error saving changes: ' + err.message);
  } finally {
    if (btnSave) {
      btnSave.disabled = false;
      btnSave.innerText = '💾 Save Changes';
    }
  }
};

window.deleteSingleRow = async function(type, id, title) {
  const isPlatform = (type === 'platform' || window.currentTableTab === 'platform');
  const label = isPlatform ? 'Directory Listing' : 'Lead';
  const numId = parseInt(id, 10);
  if (!confirm(`Are you sure you want to delete the ${label} "${title || '#' + numId}"?`)) {
    return;
  }

  // Visual feedback: dim row immediately
  const matchingRows = document.querySelectorAll(`tr#row-${numId}, input.row-select-checkbox[data-id="${numId}"]`);
  matchingRows.forEach(el => {
    const tr = el.closest('tr') || el;
    tr.style.opacity = '0.3';
  });

  const endpoint = isPlatform ? `/api/platform-listings/${numId}` : `/api/leads/${numId}`;
  try {
    const res = await fetch(endpoint, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    if (window.selectedRowIds) window.selectedRowIds.delete(numId);

    // Remove row from DOM
    matchingRows.forEach(el => {
      const tr = el.closest('tr') || el;
      tr.remove();
    });

    // Remove from in-memory arrays
    if (window.tablesSplitData) {
      ['master_leads', 'unmatched_maps', 'website_leads', 'linkedin_leads', 'unmatched_platform'].forEach(k => {
        if (Array.isArray(window.tablesSplitData[k])) {
          window.tablesSplitData[k] = window.tablesSplitData[k].filter(item => item.id !== numId);
        }
      });
    }
    if (Array.isArray(window.placesData)) {
      window.placesData = window.placesData.filter(item => item.id !== numId);
    }

    if (typeof window.updateBatchBar === 'function') window.updateBatchBar();

    if (typeof window.refreshTablesSplit === 'function') {
      await window.refreshTablesSplit();
    } else if (typeof window.renderTable === 'function') {
      window.renderTable();
    }
  } catch (err) {
    console.error('Failed to delete row:', err);
    alert('Failed to delete record: ' + err.message);
    if (typeof window.renderTable === 'function') window.renderTable();
  }
};

