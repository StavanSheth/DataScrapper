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

// =======================================================================
// TABLE EXTENSION & PLATFORM DIRECTORY MANAGER (LIVE 3-TABLES & MODAL)
// =======================================================================

window.currentTableTab = 'master'; // 'master' | 'maps' | 'platform'
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
  window.renderTagFilterBar();
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
    const inspected = w.inspected || 0;
    const emailsFound = w.emails_found || 0;
    const noWeb = w.no_website || 0;
    const foundWebsites = Math.max(0, inspected - noWeb);
    const foundWithoutEmails = Math.max(0, foundWebsites - emailsFound);
    const pending = (w.pending !== undefined) ? w.pending : Math.max(0, total - inspected);

    // Segment widths matching exact tag colors (Green = Found, Purple = Emails, Orange = No Web, Gray = Pending)
    const pFound = (foundWithoutEmails / total) * 100;
    const pEmails = (emailsFound / total) * 100;
    const pNoWeb = (noWeb / total) * 100;
    const pPending = (pending / total) * 100;

    const sFound = document.getElementById('seg-web-found');
    if (sFound) {
      sFound.style.width = `${pFound.toFixed(1)}%`;
      sFound.title = `Found Websites: ${foundWebsites}`;
    }
    const sEmails = document.getElementById('seg-web-emails');
    if (sEmails) {
      sEmails.style.width = `${pEmails.toFixed(1)}%`;
      sEmails.title = `Emails Discovered: ${emailsFound}`;
    }
    const sNoWeb = document.getElementById('seg-web-noweb');
    if (sNoWeb) {
      sNoWeb.style.width = `${pNoWeb.toFixed(1)}%`;
      sNoWeb.title = `No Website: ${noWeb}`;
    }
    const sPending = document.getElementById('seg-web-pending');
    if (sPending) {
      sPending.style.width = `${pPending.toFixed(1)}%`;
      sPending.title = `In Queue: ${pending}`;
    }

    const bW = document.getElementById('sync-bar-web');
    if (bW) bW.style.width = `${w.percent || 0}%`;

    const sW = document.getElementById('sync-stat-web');
    if (sW) sW.innerText = `${w.percent || 0}% (${inspected} / ${total})`;

    const cWFound = document.getElementById('sync-chip-web-found');
    if (cWFound) cWFound.innerText = `✅ Found: ${foundWebsites}`;
    const cWEmail = document.getElementById('sync-chip-web-emails');
    if (cWEmail) cWEmail.innerText = `✉️ Emails: ${emailsFound}`;
    const cWNo = document.getElementById('sync-chip-web-noweb');
    if (cWNo) cWNo.innerText = `⚠️ No Web: ${noWeb}`;
    const cWPending = document.getElementById('sync-chip-web-pending');
    if (cWPending) cWPending.innerText = `⏳ In Queue: ${pending}`;
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
  window.renderTable();
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
      <th>Platform Directory</th>
      <th>Status Tag</th>
      <th>Business / Listing Title</th>
      <th>Category</th>
      <th>Screenshot / Photo</th>
      <th>Rating & Reviews</th>
      <th>Pricing Tier</th>
      <th>Phone</th>
      <th>Address / Location</th>
      <th>Direct Booking URL</th>
      <th>Listing Link</th>
      <th>Found Date & Time</th>
      ${actionsTh}
    `;
  } else if (window.currentTableTab === 'maps') {
    theadTr.innerHTML = `
      ${selectAllTh}
      <th style="width: 35px;">#</th>
      <th>Business Name</th>
      <th>Category</th>
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
      <th>Status Tag</th>
      <th>Website URL</th>
      <th>Extracted Emails</th>
      <th>Social Media</th>
      <th>Anti-Bot Shield</th>
      <th>Cookie Diagnostics</th>
      <th>Screenshot</th>
      <th>Actions</th>
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
      <th>Actions</th>
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
  search: '',
  category: '',
  platform: '',
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
  const wrapPlatform = document.getElementById('filter-wrapper-platform');
  const wrapBot = document.getElementById('filter-wrapper-bot');
  const wrapCookie = document.getElementById('filter-wrapper-cookie');
  const wrapPrice = document.getElementById('filter-wrapper-price');

  const pillEmail = document.getElementById('filter-pill-hasEmail');
  const pillPhone = document.getElementById('filter-pill-hasPhone');
  const pillWeb = document.getElementById('filter-pill-hasWebsite');
  const pillScreen = document.getElementById('filter-pill-hasScreenshot');
  const pillSocial = document.getElementById('filter-pill-hasSocial');
  const pillTeam = document.getElementById('filter-pill-hasTeam');
  const pillBooking = document.getElementById('filter-pill-hasBooking');
  const pillAddr = document.getElementById('filter-pill-hasAddress');

  if (tab === 'platform') {
    // Table 3: Platform Directory Listings
    // Columns: Platform | Title | Category | Photo | Rating & Reviews | Price | Phone | Address | Booking URL | Listing Link | Date
    if (searchInput) searchInput.placeholder = "Filter by listing title, address, phone...";
    if (wrapPlatform) wrapPlatform.style.display = 'inline-flex';
    if (wrapBot) wrapBot.style.display = 'none';
    if (wrapCookie) wrapCookie.style.display = 'none';
    if (wrapPrice) wrapPrice.style.display = 'inline-flex';

    if (pillEmail) pillEmail.style.display = 'none';
    if (pillPhone) pillPhone.style.display = 'inline-flex';
    if (pillWeb) pillWeb.style.display = 'none';
    if (pillScreen) pillScreen.style.display = 'inline-flex';
    if (pillSocial) pillSocial.style.display = 'none';
    if (pillTeam) pillTeam.style.display = 'none';
    if (pillBooking) pillBooking.style.display = 'inline-flex';
    if (pillAddr) pillAddr.style.display = 'inline-flex';
  } else if (tab === 'maps') {
    // Table 2: Google Maps Leads
    // Columns: Name | Category | Email | Social Media | Bot Security | Cookies | Team/Staff | Landing Page | Phone | Address | Rating | Maps Link | Date
    if (searchInput) searchInput.placeholder = "Filter by business name, address, phone, email...";
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
    // Columns: Name | Category | Email | Social Media | Bot Security | Cookies | Team/Staff | Landing Page | Phone | Address | Rating | Platform Directory | Links | Date
    if (searchInput) searchInput.placeholder = "Filter master leads by name, address, phone, email...";
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
  const catEl = document.getElementById('filter-category-select');
  const platEl = document.getElementById('filter-platform-select');
  const ratEl = document.getElementById('filter-rating-select');
  const botEl = document.getElementById('filter-bot-select');
  const cookieEl = document.getElementById('filter-cookie-select');
  const priceEl = document.getElementById('filter-price-select');
  const clearBtn = document.getElementById('filter-search-clear');

  if (searchEl) {
    window.tableFilters.search = searchEl.value.trim().toLowerCase();
    if (clearBtn) clearBtn.style.display = window.tableFilters.search ? 'inline-flex' : 'none';
  }
  if (catEl) window.tableFilters.category = catEl.value;
  if (platEl) window.tableFilters.platform = platEl.value;
  if (ratEl) window.tableFilters.minRating = parseFloat(ratEl.value) || 0;
  if (botEl) window.tableFilters.botSecurity = botEl.value;
  if (cookieEl) window.tableFilters.cookieStatus = cookieEl.value;
  if (priceEl) window.tableFilters.pricing = priceEl.value;

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
    search: '',
    category: '',
    platform: '',
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

  const catEl = document.getElementById('filter-category-select');
  if (catEl) catEl.value = '';

  const platEl = document.getElementById('filter-platform-select');
  if (platEl) platEl.value = '';

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
    // 0. Status Tag Filter (for Website & LinkedIn tabs)
    if (window.activeTagFilter && window.activeTagFilter !== 'All') {
      if (item.status_tag !== window.activeTagFilter) return false;
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
        (item.twitter && item.twitter !== 'N/A')
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

  function formatDateTime(dateStr) {
    if (!dateStr || dateStr === 'N/A') return '<span class="badge badge-none">—</span>';
    try {
      const d = new Date(dateStr.replace(' ', 'T'));
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

  if (window.currentTableTab === 'platform') {
    filteredList.forEach((item, index) => {
      const tr = document.createElement('tr');
      const pName = escapeHtml(item.platform || item.platform_name || 'Platform');
      const itemUrl = item.url || item.listing_url || item.platform_url || '';
      const pRating = (item.rating && item.rating !== 'N/A') ? `⭐ ${item.rating}` : '';
      const pReviews = (item.reviews_count || item.reviews) ? `(${item.reviews_count || item.reviews})` : '';

      const platformColHtml = itemUrl
        ? `
          <div style="display:flex; flex-direction:column; gap:4px;" onclick="event.stopPropagation();">
            <a href="${encodeURI(itemUrl)}" target="_blank" class="badge-platform-btn" title="Open '${escapeHtml(item.title || item.name || 'Listing')}' on ${pName}">
              🟣 ${pName} <span style="font-size:0.75rem; opacity:0.85;">↗</span>
            </a>
            <a href="${encodeURI(itemUrl)}" target="_blank" class="platform-direct-link" title="${escapeHtml(itemUrl)}">
              🔗 ${cleanDisplayUrl(itemUrl)}
            </a>
          </div>
        `
        : `<span class="badge badge-platform">🟣 ${pName}</span>`;

      const bookLink = (item.booking_url && item.booking_url !== 'N/A')
        ? `<a href="${encodeURI(item.booking_url)}" target="_blank" class="badge-social" style="color:#a855f7; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); font-size:0.72rem; padding:3px 8px; text-decoration:none; width:auto; border-radius:6px;" title="Direct Booking / Reservation URL" onclick="event.stopPropagation();">📅 Book Now</a>`
        : '<span class="badge badge-none">—</span>';

      const listLink = itemUrl
        ? `<a href="${encodeURI(itemUrl)}" target="_blank" class="link-btn" style="color:#c084fc; font-size:0.76rem;" title="View Listing Page" onclick="event.stopPropagation();">🔗 Open on ${pName}</a>`
        : '<span class="badge badge-none">—</span>';

      const screenHtml = (item.screenshot && item.screenshot !== 'N/A')
        ? `
          <div class="screen-thumb-container" onclick="event.stopPropagation(); openImageModal('${encodeURI(item.screenshot)}', '${escapeHtml(item.title || item.name || item.company_name || 'Listing')}')">
            <div class="screen-thumb-box" title="Click to view full screenshot of ${escapeHtml(item.title || item.name || item.company_name || 'Listing')}">
              <img src="${encodeURI(item.screenshot)}" alt="${escapeHtml(item.title || item.name || item.company_name || 'Listing')}" onerror="handleImgError(this)">
              <div class="screen-thumb-overlay">🔍 View</div>
            </div>
            <button class="btn-screen-view" title="Expand screenshot">
              <span>🔍 View</span>
            </button>
          </div>
        `
        : '<span class="badge badge-none" style="opacity:0.6;">—</span>';

      const isSelected = window.selectedRowIds && window.selectedRowIds.has(item.id);
      if (isSelected) tr.classList.add('row-selected');

      const checkTd = `<td style="text-align:center;" onclick="event.stopPropagation();"><input type="checkbox" class="row-select-checkbox" data-id="${item.id}" ${isSelected ? 'checked' : ''} onchange="window.onRowSelectChange()" /></td>`;
      const actionsTd = `<td style="text-align:center;" onclick="event.stopPropagation();">
        <div style="display:flex; gap:6px; justify-content:center;">
          <button class="btn-row-action btn-row-edit" onclick="window.openEditRowModal('platform', ${item.id})" title="Edit listing">✏️</button>
          <button class="btn-row-action btn-row-delete" onclick="window.deleteSingleRow('platform', ${item.id}, '${escapeHtml(item.title || 'Listing')}')" title="Delete listing">🗑️</button>
        </div>
      </td>`;

      tr.innerHTML = `
        ${checkTd}
        <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${item.id || ''}">${index + 1}</td>
        <td>${platformColHtml}</td>
        <td><span class="badge badge-verified" style="background:rgba(168,85,247,0.15); color:#c084fc; border:1px solid rgba(168,85,247,0.3);">🟣 Listed</span></td>
        <td class="shop-title">${escapeHtml(item.title || item.name || item.company_name || 'Listing')}</td>
        <td><span class="badge badge-category">${escapeHtml(item.category || 'Listing')}</span></td>
        <td>${screenHtml}</td>
        <td><span class="rating-pill">${pRating} <small style="color:#94a3b8;">${pReviews}</small></span></td>
        <td>${item.price_info || item.price_range ? `<span style="font-size:0.75rem; color:#34d399; font-weight:600;">💰 ${escapeHtml(item.price_info || item.price_range)}</span>` : '<span class="badge badge-none">—</span>'}</td>
        <td>${item.phone && item.phone !== 'N/A' ? `<a href="tel:${item.phone}" style="color:#cbd5e1; text-decoration:none;" onclick="event.stopPropagation();">📞 ${escapeHtml(item.phone)}</a>` : '<span style="color:#64748b;">N/A</span>'}</td>
        <td style="color:#94a3b8; font-size:0.8rem; max-width:200px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(item.address || 'N/A')}</td>
        <td>${bookLink}</td>
        <td>${listLink}</td>
        <td>${formatDateTime(item.created_at)}</td>
        ${actionsTd}
      `;
      tbody.appendChild(tr);
    });
    return;
  }

  filteredList.forEach((place, index) => {
    const rowId = place.id || index;
    const tr = document.createElement('tr');
    tr.id = `row-${rowId}`;
    if (typeof focusShop === 'function') {
      tr.onclick = () => focusShop(rowId);
    }

    const emailHtml = (place.email && place.email !== 'N/A')
      ? `<span class="badge badge-email" title="Click to copy" onclick="event.stopPropagation(); navigator.clipboard.writeText('${place.email}'); alert('Copied: ${place.email}')">✉️ ${escapeHtml(place.email)}</span>`
      : '<span class="badge badge-none">Not listed</span>';

    const categoryHtml = place.category
      ? `<span class="badge badge-category">${escapeHtml(place.category)}</span>`
      : '<span class="badge badge-none">Business</span>';

    const ratingHtml = (place.rating && place.rating !== 'N/A')
      ? `<span class="rating-pill">⭐ ${place.rating} <small style="color:#94a3b8;">(${place.reviews || '0'})</small></span>`
      : '<span style="color:#64748b;">N/A</span>';

    const linksHtml = `
      <div style="display:flex; gap:8px;" onclick="event.stopPropagation();">
        ${place.website && place.website !== 'N/A' ? `<a href="${encodeURI(place.website)}" target="_blank" class="link-btn">🌐 Site</a>` : ''}
        ${place.maps_url ? `<a href="${encodeURI(place.maps_url)}" target="_blank" class="link-btn">🗺️ Maps</a>` : ''}
      </div>
    `;

    const socialsList = [];
    if (place.instagram) socialsList.push(`<a href="${encodeURI(place.instagram)}" target="_blank" class="badge-social badge-ig" title="Instagram: ${escapeHtml(place.instagram)}" onclick="event.stopPropagation();">📸</a>`);
    if (place.facebook) socialsList.push(`<a href="${encodeURI(place.facebook)}" target="_blank" class="badge-social badge-fb" title="Facebook: ${escapeHtml(place.facebook)}" onclick="event.stopPropagation();">👥</a>`);
    if (place.linkedin) socialsList.push(`<a href="${encodeURI(place.linkedin)}" target="_blank" class="badge-social badge-li" title="LinkedIn: ${escapeHtml(place.linkedin)}" onclick="event.stopPropagation();">💼</a>`);
    if (place.twitter) socialsList.push(`<a href="${encodeURI(place.twitter)}" target="_blank" class="badge-social badge-tw" title="Twitter/X: ${escapeHtml(place.twitter)}" onclick="event.stopPropagation();">🐦</a>`);

    const socialsHtml = socialsList.length > 0
      ? `<div style="display:flex; gap:5px;" onclick="event.stopPropagation();">${socialsList.join('')}</div>`
      : '<span class="badge badge-none">—</span>';

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
        <div class="screen-thumb-container" onclick="event.stopPropagation(); openImageModal('${encodeURI(place.screenshot)}', '${escapeHtml(place.name)}')">
          <div class="screen-thumb-box" title="Click to view full screenshot of ${escapeHtml(place.name)}">
            <img src="${encodeURI(place.screenshot)}" alt="${escapeHtml(place.name)}" onerror="handleImgError(this)">
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
    const curType = window.currentTableTab === 'maps' ? 'maps' : 'master';
    const actionsTd = `<td style="text-align:center;" onclick="event.stopPropagation();">
      <div style="display:flex; gap:6px; justify-content:center;">
        <button class="btn-row-action btn-row-edit" onclick="window.openEditRowModal('${curType}', ${place.id})" title="Edit lead">✏️</button>
        <button class="btn-row-action btn-row-delete" onclick="window.deleteSingleRow('${curType}', ${place.id}, '${escapeHtml(place.name || 'Lead')}')" title="Delete lead">🗑️</button>
      </div>
    </td>`;

    if (window.currentTableTab === 'maps') {
      tr.innerHTML = `
        ${checkTd}
        <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
        <td class="shop-title">${escapeHtml(place.name)}</td>
        <td>${categoryHtml}</td>
        <td>${place.phone && place.phone !== 'N/A' ? `<a href="tel:${place.phone}" style="color:#cbd5e1; text-decoration:none;" onclick="event.stopPropagation();">📞 ${escapeHtml(place.phone)}</a>` : '<span style="color:#64748b;">N/A</span>'}</td>
        <td style="color:#94a3b8; font-size:0.82rem; max-width:200px; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(place.address)}">${escapeHtml(place.address)}</td>
        <td>${ratingHtml}</td>
        <td>${place.website && place.website !== 'N/A' ? `<a href="${encodeURI(place.website)}" target="_blank" class="link-btn" title="${escapeHtml(place.website)}" onclick="event.stopPropagation();">🌐 ${cleanDisplayUrl(place.website)}</a>` : '<span class="badge badge-none">—</span>'}</td>
        <td>${place.maps_url ? `<a href="${encodeURI(place.maps_url)}" target="_blank" class="link-btn" title="Open Google Maps listing" onclick="event.stopPropagation();">🗺️ Maps</a>` : '<span class="badge badge-none">—</span>'}</td>
        <td><span class="badge badge-verified" style="background:rgba(34,197,94,0.15); color:#4ade80; border:1px solid rgba(34,197,94,0.3);">✓ Captured</span></td>
        <td>${formatDateTime(place.created_at)}</td>
        ${actionsTd}
      `;
    } else if (window.currentTableTab === 'website') {
      let wStatusBadge = '<span class="badge badge-none">Pending</span>';
      if (place.website_status === 'emails_found') wStatusBadge = '<span class="badge badge-email">✉️ Emails Found</span>';
      else if (place.website_status === 'clean') wStatusBadge = '<span class="badge badge-verified">✓ Clean</span>';
      else if (place.website_status === 'social') wStatusBadge = '<span class="badge badge-social">📸 Social Profile</span>';
      else if (place.website_status === 'failed') wStatusBadge = '<span class="badge badge-bot-denied">⚠️ Failed / Blocked</span>';
      else if (place.website_status === 'no_website') wStatusBadge = '<span class="badge badge-none">No Website</span>';

      tr.innerHTML = `
        ${checkTd}
        <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
        <td class="shop-title">${escapeHtml(place.name)}</td>
        <td>${wStatusBadge}</td>
        <td>${place.website && place.website !== 'N/A' ? `<a href="${encodeURI(place.website)}" target="_blank" class="link-btn" title="${escapeHtml(place.website)}" onclick="event.stopPropagation();">🌐 ${cleanDisplayUrl(place.website)}</a>` : '<span class="badge badge-none">—</span>'}</td>
        <td>${emailHtml}</td>
        <td>${socialsHtml}</td>
        <td>${botHtml}</td>
        <td>${cookieHtml}</td>
        <td>${screenHtml}</td>
        ${actionsTd}
      `;
    } else if (window.currentTableTab === 'linkedin') {
      let liStatusBadge = '<span class="badge badge-none">Pending</span>';
      if (empCount > 0) liStatusBadge = '<span class="badge badge-verified">🌳 Mapped</span>';
      else if (place.linkedin && place.linkedin !== 'N/A') liStatusBadge = '<span class="badge badge-category">Company Verified</span>';
      else if (place.linkedin_status === 'not_found') liStatusBadge = '<span class="badge badge-none">Not Found</span>';

      tr.innerHTML = `
        ${checkTd}
        <td style="color:#64748b; font-weight:600; text-align:center;" title="Database ID #${place.id || ''}">${index + 1}</td>
        <td class="shop-title">${escapeHtml(place.name)}</td>
        <td>${liStatusBadge}</td>
        <td>${place.linkedin && place.linkedin !== 'N/A' ? `<a href="${encodeURI(place.linkedin)}" target="_blank" class="badge-social badge-li" style="text-decoration:none; padding:4px 8px; width:auto; border-radius:6px;" title="${escapeHtml(place.linkedin)}" onclick="event.stopPropagation();">💼 LinkedIn Page</a>` : '<span class="badge badge-none">—</span>'}</td>
        <td>${employeeBadgeHtml}</td>
        <td style="font-size:0.8rem; color:#cbd5e1;">${empCount > 0 ? `<span style="color:#38bdf8; font-weight:600;">${empCount} members</span> extracted` : '<span style="color:#64748b;">—</span>'}</td>
        <td>${orgChartBtn}</td>
        ${actionsTd}
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
        <td class="shop-title">${escapeHtml(place.name)}</td>
        <td>${categoryHtml}</td>
        <td>${emailHtml}</td>
        <td>${socialsHtml}</td>
        <td>${botHtml}</td>
        <td>${cookieHtml}</td>
        <td>${employeeBadgeHtml}</td>
        <td>${orgChartBtn}</td>
        <td>${screenHtml}</td>
        <td>${place.phone && place.phone !== 'N/A' ? `<a href="tel:${place.phone}" style="color:#cbd5e1; text-decoration:none;" onclick="event.stopPropagation();">📞 ${escapeHtml(place.phone)}</a>` : '<span style="color:#64748b;">N/A</span>'}</td>
        <td style="color:#94a3b8; font-size:0.82rem; max-width:180px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(place.address)}</td>
        <td>${ratingHtml}</td>
        <td>${platformHtml}</td>
        <td>${linksHtml}</td>
        <td>${formatDateTime(place.created_at)}</td>
        ${actionsTd}
      `;
    }
    tbody.appendChild(tr);
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
// REAL-TIME AUTO SYNC & WEBSOCKET LISTENER
// =======================================================================

function initTableExtRealtime() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  try {
    const extWs = new WebSocket(`${proto}//${window.location.host}/ws`);
    extWs.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'init' && msg.tables_split) {
          window.updateSplitData(msg.tables_split);
        } else if (msg.type === 'tables_split') {
          window.updateSplitData(msg.data);
        } else if (msg.type === 'db_cleared') {
          window.refreshTablesSplit();
        }
      } catch (e) {}
    };
    extWs.onclose = () => {
      setTimeout(initTableExtRealtime, 2500);
    };
  } catch (err) {}
}

window.addEventListener('DOMContentLoaded', () => {
  window.refreshTablesSplit();
  initTableExtRealtime();
});


// =======================================================================
// SELECTION, BATCH OPERATIONS & INDIVIDUAL EDIT/DELETE LOGIC
// =======================================================================

window.selectedRowIds = new Set();

window.toggleSelectAll = function(checked) {
  const checkboxes = document.querySelectorAll('.row-select-checkbox');
  checkboxes.forEach(cb => {
    cb.checked = checked;
    const id = parseInt(cb.getAttribute('data-id'));
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
  const checkboxes = document.querySelectorAll('.row-select-checkbox');
  window.selectedRowIds.clear();
  let checkedCount = 0;
  checkboxes.forEach(cb => {
    const id = parseInt(cb.getAttribute('data-id'));
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
    selAll.checked = checkedCount > 0 && checkedCount === checkboxes.length;
    selAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
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
  const allBoxes = document.querySelectorAll('.row-select-checkbox');

  // Update top "Select All" button state
  if (selectBtnText && selectBtnIcon) {
    if (allBoxes.length > 0 && count === allBoxes.length) {
      selectBtnIcon.innerText = '❎';
      selectBtnText.innerText = 'Deselect All';
    } else {
      selectBtnIcon.innerText = '☑️';
      selectBtnText.innerText = count > 0 ? `Select All (${allBoxes.length})` : 'Select All';
    }
  }

  if (!bar) return;
  if (count > 0) {
    bar.style.display = 'flex';
    if (countEl) countEl.innerText = `${count} ${count === 1 ? 'record' : 'records'} selected`;

    // Dynamic label for Edit button: single edit vs batch edit
    if (editBtn && editBtnText) {
      if (count === 1) {
        editBtnText.innerText = 'Edit Record';
        editBtn.title = 'Open full editor for this selected record';
      } else {
        editBtnText.innerText = 'Batch Edit';
        editBtn.title = `Batch edit ${count} selected records`;
      }
    }

    if (deleteBtnText) {
      deleteBtnText.innerText = count === 1 ? '🗑️ Delete Record' : `🗑️ Delete Selected (${count})`;
    }
  } else {
    bar.style.display = 'none';
  }
};

window.handleEditSelectedClick = function() {
  const count = window.selectedRowIds.size;
  if (count === 0) {
    alert('Please select at least one record using a checkbox.');
    return;
  }
  if (count === 1) {
    const id = Array.from(window.selectedRowIds)[0];
    const curType = window.currentTableTab === 'platform' ? 'platform' : (window.currentTableTab === 'maps' ? 'maps' : 'master');
    window.openEditRowModal(curType, id);
  } else {
    window.openBatchEditCategoryModal();
  }
};

window.toggleSelectAllButton = function() {
  const allBoxes = document.querySelectorAll('.row-select-checkbox');
  if (allBoxes.length === 0) return;
  const checkedCount = document.querySelectorAll('.row-select-checkbox:checked').length;
  const shouldSelect = checkedCount < allBoxes.length;
  window.toggleSelectAll(shouldSelect);

  const headerCb = document.getElementById('select-all-checkbox');
  if (headerCb) {
    headerCb.checked = shouldSelect;
    headerCb.indeterminate = false;
  }
};

window.batchDeleteSelected = async function() {
  const count = window.selectedRowIds.size;
  if (count === 0) return;
  const tableLabel = window.currentTableTab === 'platform' ? 'Platform Directory Listings' : 'Leads';
  if (!confirm(`Are you sure you want to permanently delete ${count} selected ${tableLabel}? This action cannot be undone.`)) {
    return;
  }

  const ids = Array.from(window.selectedRowIds);
  const endpoint = window.currentTableTab === 'platform'
    ? '/api/platform-listings/batch-delete'
    : '/api/leads/batch-delete';

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids })
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const data = await res.json();
    window.deselectAllRows();
    if (typeof loadDatabase === 'function') {
      await loadDatabase();
    }
    alert(`Successfully deleted ${data.deleted_count || count} records.`);
  } catch (err) {
    console.error('Batch delete failed:', err);
    alert('Failed to delete selected records: ' + err.message);
  }
};

window.openBatchEditCategoryModal = function() {
  const count = window.selectedRowIds.size;
  if (count === 0) {
    alert('Please select at least one record to update.');
    return;
  }
  const modal = document.getElementById('batch-cat-modal');
  const desc = document.getElementById('batch-cat-desc');
  const input = document.getElementById('batch-cat-input');
  if (desc) desc.innerText = `Set a new category for the ${count} selected record${count > 1 ? 's' : ''}:`;
  if (input) input.value = '';
  if (modal) modal.style.display = 'flex';
};

window.closeBatchCatModal = function() {
  const modal = document.getElementById('batch-cat-modal');
  if (modal) modal.style.display = 'none';
};

window.submitBatchCategory = async function() {
  const input = document.getElementById('batch-cat-input');
  const newCat = (input ? input.value : '').trim();
  if (!newCat) {
    alert('Please enter a valid category name.');
    return;
  }
  const ids = Array.from(window.selectedRowIds);
  const endpoint = window.currentTableTab === 'platform'
    ? '/api/platform-listings/batch-update'
    : '/api/leads/batch-update';

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids, updates: { category: newCat } })
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    window.closeBatchCatModal();
    window.deselectAllRows();
    if (typeof loadDatabase === 'function') {
      await loadDatabase();
    }
    alert(`Successfully updated category to "${newCat}" for ${ids.length} records.`);
  } catch (err) {
    console.error('Batch category update failed:', err);
    alert('Failed to update categories: ' + err.message);
  }
};

window.exportSelectedCSV = function() {
  const count = window.selectedRowIds.size;
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

window.openEditRowModal = function(type, id) {
  let record = null;
  const numId = parseInt(id);
  if (type === 'platform') {
    record = (window.tablesSplitData.unmatched_platform || []).find(p => p.id === numId);
  } else if (type === 'maps') {
    record = (window.tablesSplitData.unmatched_maps || []).find(p => p.id === numId);
  } else {
    record = (window.tablesSplitData.master_leads || []).find(p => p.id === numId);
  }

  if (!record) {
    alert('Record not found.');
    return;
  }

  const modal = document.getElementById('edit-row-modal');
  const titleEl = document.getElementById('edit-modal-title');
  document.getElementById('edit-item-id').value = record.id;
  document.getElementById('edit-item-type').value = type;

  const isPlatform = type === 'platform';
  if (titleEl) {
    titleEl.innerText = isPlatform ? `✏️ Edit Directory Listing: #${record.id}` : `✏️ Edit Lead Details: #${record.id}`;
  }

  document.getElementById('edit-field-name').value = record.title || record.name || '';
  document.getElementById('edit-field-category').value = record.category || '';
  document.getElementById('edit-field-phone').value = (record.phone && record.phone !== 'N/A') ? record.phone : '';
  document.getElementById('edit-field-address').value = (record.address && record.address !== 'N/A') ? record.address : '';
  document.getElementById('edit-field-rating').value = (record.rating && record.rating !== 'N/A') ? record.rating : '';

  const emailGroup = document.getElementById('edit-group-email');
  const emailInput = document.getElementById('edit-field-email');
  if (emailGroup && emailInput) {
    if (isPlatform) {
      emailGroup.style.display = 'none';
      emailInput.value = '';
    } else {
      emailGroup.style.display = 'flex';
      emailInput.value = (record.email && record.email !== 'N/A') ? record.email : '';
    }
  }

  const websiteGroup = document.getElementById('edit-group-website');
  const websiteInput = document.getElementById('edit-field-website');
  if (websiteGroup && websiteInput) {
    if (isPlatform) {
      websiteGroup.style.display = 'none';
      websiteInput.value = '';
    } else {
      websiteGroup.style.display = 'flex';
      websiteInput.value = (record.website && record.website !== 'N/A') ? record.website : '';
    }
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

  if (modal) modal.style.display = 'flex';
};

window.closeEditRowModal = function() {
  const modal = document.getElementById('edit-row-modal');
  if (modal) modal.style.display = 'none';
};

window.saveRowEdit = async function(e) {
  e.preventDefault();
  const id = parseInt(document.getElementById('edit-item-id').value);
  const type = document.getElementById('edit-item-type').value;
  if (!id) return;

  const isPlatform = type === 'platform';
  const nameVal = document.getElementById('edit-field-name').value.trim();
  const catVal = document.getElementById('edit-field-category').value.trim();
  const phoneVal = document.getElementById('edit-field-phone').value.trim();
  const addrVal = document.getElementById('edit-field-address').value.trim();
  const ratingVal = document.getElementById('edit-field-rating').value.trim();
  const priceVal = document.getElementById('edit-field-price').value.trim();

  let payload = {};
  let endpoint = '';

  if (isPlatform) {
    const bookingVal = document.getElementById('edit-field-booking').value.trim();
    payload = {
      title: nameVal,
      category: catVal,
      phone: phoneVal,
      address: addrVal,
      rating: ratingVal ? parseFloat(ratingVal) || 0.0 : 0.0,
      price_info: priceVal,
      booking_url: bookingVal
    };
    endpoint = `/api/platform-listings/${id}`;
  } else {
    const emailVal = document.getElementById('edit-field-email').value.trim();
    const websiteVal = document.getElementById('edit-field-website').value.trim();
    payload = {
      name: nameVal,
      category: catVal,
      phone: phoneVal,
      email: emailVal,
      address: addrVal,
      rating: ratingVal,
      price: priceVal,
      website: websiteVal
    };
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
    if (typeof loadDatabase === 'function') {
      await loadDatabase();
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
  const isPlatform = type === 'platform';
  const label = isPlatform ? 'Directory Listing' : 'Lead';
  if (!confirm(`Are you sure you want to delete the ${label} "${title || '#' + id}"?`)) {
    return;
  }

  const endpoint = isPlatform ? `/api/platform-listings/${id}` : `/api/leads/${id}`;
  try {
    const res = await fetch(endpoint, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    if (window.selectedRowIds) window.selectedRowIds.delete(id);
    if (typeof loadDatabase === 'function') {
      await loadDatabase();
    }
  } catch (err) {
    console.error('Failed to delete row:', err);
    alert('Failed to delete record: ' + err.message);
  }
};
