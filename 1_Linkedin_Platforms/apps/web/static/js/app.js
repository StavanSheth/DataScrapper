let placesData = [];
    let isRunning = false;
    let isActionPending = false;
    let currentMode = 'maps'; // 'maps' or 'companies'
    let leafletMap = null;
    let searchMarker = null;
    let radiusCircle = null;
    let placesLayer = null;
    let markersMap = {};
    let pollInterval = null;

    function openPipelineModal() {
      document.getElementById('pipeline-modal').style.display = 'flex';
    }

    function closePipelineModal() {
      document.getElementById('pipeline-modal').style.display = 'none';
    }

    function setMode(mode) {
      currentMode = mode;
      const mapsTab = document.getElementById('tab-mode-maps');
      const compTab = document.getElementById('tab-mode-companies');
      const webTab = document.getElementById('tab-mode-website-list');
      const mapsControls = document.getElementById('controls-maps');
      const compControls = document.getElementById('controls-companies');
      const webControls = document.getElementById('controls-website-list');
      const startBtn = document.getElementById('start-btn');

      if (mapsTab) mapsTab.classList.toggle('active', mode === 'maps');
      if (compTab) compTab.classList.toggle('active', mode === 'companies');
      if (webTab) webTab.classList.toggle('active', mode === 'website_list');

      if (mapsControls) mapsControls.style.display = (mode === 'maps') ? 'flex' : 'none';
      if (compControls) compControls.style.display = (mode === 'companies') ? 'flex' : 'none';
      if (webControls) webControls.style.display = (mode === 'website_list') ? 'flex' : 'none';

      if (mode === 'maps') {
        startBtn.className = 'btn btn-primary';
        startBtn.innerHTML = '<span>🚀 Start Maps Agent</span>';
        setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 200);
      } else if (mode === 'companies') {
        startBtn.className = 'btn btn-linkedin-theme';
        startBtn.innerHTML = '<span>💼 Launch LinkedIn Org Harvester</span>';
      } else if (mode === 'website_list') {
        startBtn.className = 'btn btn-website-theme';
        startBtn.innerHTML = '<span>🌐 Launch Direct Website Scraper</span>';
        if (typeof window.switchTableTab === 'function') {
          window.switchTableTab('website');
        }
      }
    }

    let uploadedWebsiteRows = [];

    function extractUrlsFromText(text) {
      if (!text) return [];
      const lines = text.split(/[\r\n,]+/);
      const urls = [];
      const seen = new Set();
      lines.forEach(raw => {
        let u = raw.trim();
        if (!u) return;
        u = u.replace(/^["'\[]+|["'\]]+$/g, '').trim();
        if (!u) return;
        if (!u.startsWith('http://') && !u.startsWith('https://')) {
          if (u.includes('.') && !u.includes(' ')) {
            u = 'https://' + u;
          }
        }
        if (u.startsWith('http://') || u.startsWith('https://')) {
          if (!seen.has(u.toLowerCase())) {
            seen.add(u.toLowerCase());
            urls.push(u);
          }
        }
      });
      return urls;
    }

    function onWebsiteInputChanged() {
      const textarea = document.getElementById('website-list-input');
      const badge = document.getElementById('website-count-badge');
      if (!textarea || !badge) return;
      const urls = extractUrlsFromText(textarea.value);
      const count = uploadedWebsiteRows.length > 0 ? uploadedWebsiteRows.length : urls.length;
      badge.innerText = `${count} URL${count === 1 ? '' : 's'} detected`;
      badge.style.background = count > 0 ? 'rgba(16,185,129,0.2)' : 'rgba(16,185,129,0.08)';
      badge.style.color = count > 0 ? '#10b981' : '#94a3b8';
    }

    function addWebsiteChip(url) {
      const textarea = document.getElementById('website-list-input');
      if (!textarea) return;
      const current = textarea.value.trim();
      if (current.includes(url)) return;
      textarea.value = current ? `${current}\n${url}` : url;
      uploadedWebsiteRows = [];
      onWebsiteInputChanged();
    }

    function clearWebsiteInput() {
      const textarea = document.getElementById('website-list-input');
      if (textarea) textarea.value = '';
      uploadedWebsiteRows = [];
      onWebsiteInputChanged();
    }

    function handleFileDragOver(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById('website-dropzone');
      if (dropzone) dropzone.classList.add('dragover');
    }

    function handleFileDragLeave(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById('website-dropzone');
      if (dropzone) dropzone.classList.remove('dragover');
    }

    function handleFileDrop(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById('website-dropzone');
      if (dropzone) dropzone.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        parseUploadedFile(e.dataTransfer.files[0]);
      }
    }

    function handleFileSelect(e) {
      if (e.target && e.target.files && e.target.files.length > 0) {
        parseUploadedFile(e.target.files[0]);
      }
    }

    function parseUploadedFile(file) {
      if (!file) return;
      const reader = new FileReader();
      const isCsv = file.name.toLowerCase().endsWith('.csv');
      reader.onload = function(evt) {
        const content = evt.target.result;
        if (!content) return;
        if (isCsv) {
          parseCsvContent(content, file.name);
        } else {
          parseTxtContent(content, file.name);
        }
      };
      reader.readAsText(file);
    }

    function parseTxtContent(content, filename) {
      const urls = extractUrlsFromText(content);
      uploadedWebsiteRows = urls.map(u => ({ url: u, name: '', phone: '', category: '' }));
      const textarea = document.getElementById('website-list-input');
      if (textarea) {
        textarea.value = urls.join('\n');
      }
      onWebsiteInputChanged();
      logMessage(`📄 Imported ${urls.length} target websites from '${filename}'`);
    }

    function parseCsvContent(content, filename) {
      const lines = content.split(/\r?\n/).filter(l => l.trim().length > 0);
      if (lines.length === 0) return;

      const headerLine = lines[0];
      const headers = headerLine.split(',').map(h => h.trim().replace(/^["']|["']$/g, '').toLowerCase());

      let urlColIdx = headers.findIndex(h => ['website', 'url', 'link', 'site', 'web', 'domain', 'website_url'].includes(h));
      if (urlColIdx === -1) {
        urlColIdx = headers.findIndex(h => h.includes('url') || h.includes('site') || h.includes('web'));
      }
      if (urlColIdx === -1) {
        urlColIdx = 0;
      }

      const nameColIdx = headers.findIndex(h => ['name', 'business', 'company', 'title', 'shop'].includes(h));
      const phoneColIdx = headers.findIndex(h => ['phone', 'tel', 'mobile', 'telephone', 'contact'].includes(h));
      const catColIdx = headers.findIndex(h => ['category', 'type', 'industry', 'tag'].includes(h));
      const addrColIdx = headers.findIndex(h => ['address', 'location', 'addr', 'city'].includes(h));

      const parsedRows = [];
      const urlListForPreview = [];

      for (let i = 1; i < lines.length; i++) {
        const rowCols = lines[i].split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/).map(c => c.trim().replace(/^["']|["']$/g, ''));
        const rawUrl = rowCols[urlColIdx] || '';
        let u = rawUrl.trim();
        if (!u) continue;
        if (!u.startsWith('http://') && !u.startsWith('https://')) {
          if (u.includes('.') && !u.includes(' ')) {
            u = 'https://' + u;
          }
        }
        if (u.startsWith('http://') || u.startsWith('https://')) {
          const item = {
            url: u,
            name: nameColIdx !== -1 ? (rowCols[nameColIdx] || '') : '',
            phone: phoneColIdx !== -1 ? (rowCols[phoneColIdx] || '') : '',
            category: catColIdx !== -1 ? (rowCols[catColIdx] || '') : '',
            address: addrColIdx !== -1 ? (rowCols[addrColIdx] || 'N/A') : 'N/A'
          };
          parsedRows.push(item);
          urlListForPreview.push(u);
        }
      }

      uploadedWebsiteRows = parsedRows;
      const textarea = document.getElementById('website-list-input');
      if (textarea) {
        textarea.value = urlListForPreview.join('\n');
      }
      onWebsiteInputChanged();
      logMessage(`📊 Successfully imported ${parsedRows.length} websites from CSV '${filename}' (Detected columns: URL column ${urlColIdx + 1}${nameColIdx !== -1 ? ', Name' : ''}${phoneColIdx !== -1 ? ', Phone' : ''})`);
    }

    let pendingDuplicateCheck = null;

    function closeDuplicateModal() {
      const modal = document.getElementById('duplicate-websites-modal');
      if (modal) modal.style.display = 'none';
      pendingDuplicateCheck = null;
    }
    window.closeDuplicateModal = closeDuplicateModal;

    function toggleAllDuplicates(checked) {
      const cbs = document.querySelectorAll('.dup-site-cb');
      cbs.forEach(cb => cb.checked = checked);
      updateDuplicateCounts();
    }
    window.toggleAllDuplicates = toggleAllDuplicates;

    function updateDuplicateCounts() {
      const cbs = Array.from(document.querySelectorAll('.dup-site-cb'));
      const selected = cbs.filter(cb => cb.checked).length;
      const countEl = document.getElementById('dup-selected-count');
      const btnCountEl = document.getElementById('dup-btn-count');
      if (countEl) countEl.innerText = selected;
      if (btnCountEl) btnCountEl.innerText = selected;
      const selectAll = document.getElementById('dup-select-all');
      if (selectAll && cbs.length > 0) {
        selectAll.checked = (selected === cbs.length);
        selectAll.indeterminate = (selected > 0 && selected < cbs.length);
      }
    }
    window.updateDuplicateCounts = updateDuplicateCounts;

    async function proceedDuplicateDecision(decision) {
      if (!pendingDuplicateCheck) return;
      const { existing, new_targets, visibleBrowser, deepCrawl } = pendingDuplicateCheck;
      closeDuplicateModal();

      let finalTargets = [];
      if (decision === 'rescrape_all') {
        finalTargets = [
          ...existing.map(e => ({ id: e.id, name: e.name, url: e.website, address: e.target_data?.address || "N/A" })),
          ...new_targets
        ];
      } else if (decision === 'skip_existing') {
        finalTargets = [...new_targets];
      } else if (decision === 'rescrape_selected') {
        const cbs = Array.from(document.querySelectorAll('.dup-site-cb'));
        const checkedIds = new Set(cbs.filter(cb => cb.checked).map(cb => parseInt(cb.value)));
        const selectedExisting = existing
          .filter(e => checkedIds.has(e.id))
          .map(e => ({ id: e.id, name: e.name, url: e.website, address: e.target_data?.address || "N/A" }));
        finalTargets = [...selectedExisting, ...new_targets];
      }

      if (finalTargets.length === 0) {
        alert("No websites selected to scrape. All existing sites were skipped and there are no new sites.");
        setScrapingState(false, "Ready");
        return;
      }

      await executeStartWebsiteList(finalTargets, visibleBrowser, deepCrawl, true);
    }
    window.proceedDuplicateDecision = proceedDuplicateDecision;

    async function startWebsiteListScraping() {
      const textarea = document.getElementById('website-list-input');
      const textUrls = textarea ? extractUrlsFromText(textarea.value) : [];

      let finalTargets = [];
      if (uploadedWebsiteRows.length > 0 && uploadedWebsiteRows.length === textUrls.length) {
        finalTargets = uploadedWebsiteRows;
      } else {
        finalTargets = textUrls.map(u => ({ url: u }));
      }

      if (finalTargets.length === 0) {
        alert("Please enter at least one website URL or upload a CSV/TXT file.");
        return;
      }

      const visibleBrowser = document.getElementById('visible-browser-toggle')?.checked ?? true;
      const deepCrawl = document.getElementById('website-deep-crawl-toggle')?.checked ?? true;

      // Check database for existing scraped websites
      try {
        const checkResp = await fetch('/api/leads/check-urls', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ urls: finalTargets })
        });
        if (checkResp.ok) {
          const checkData = await checkResp.json();
          const existing = checkData.existing || [];
          const newTargets = checkData.new_targets || [];

          if (existing.length > 0) {
            pendingDuplicateCheck = {
              existing: existing,
              new_targets: newTargets,
              visibleBrowser: visibleBrowser,
              deepCrawl: deepCrawl
            };

            const tbody = document.getElementById('duplicate-websites-table-body');
            if (tbody) {
              tbody.innerHTML = existing.map(item => {
                const statusBadge = item.website_status === 'contacts_found'
                  ? '<span class="status-badge status-green">Contacts Found</span>'
                  : (item.website_status === 'not_loading'
                    ? '<span class="status-badge status-red">Not Loading</span>'
                    : `<span class="status-badge">${item.website_status}</span>`);

                const contactsText = (item.email && item.email !== 'N/A')
                  ? `<span style="color:#38bdf8;">✉️ ${item.email}</span>`
                  : ((item.phone && item.phone !== 'N/A') ? `<span style="color:#a78bfa;">📞 ${item.phone}</span>` : '<span style="color:#64748b;">No contacts yet</span>');

                return `
                  <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                    <td style="padding:10px 12px; text-align:center;">
                      <input type="checkbox" class="dup-site-cb" value="${item.id}" checked onchange="updateDuplicateCounts()" style="accent-color:#0ea5e9;">
                    </td>
                    <td style="padding:10px 12px;">
                      <div style="font-weight:600; color:#f1f5f9;">${item.name || item.domain}</div>
                      <a href="${item.website}" target="_blank" style="color:#38bdf8; text-decoration:none; font-size:0.75rem;">${item.website}</a>
                    </td>
                    <td style="padding:10px 12px;">${statusBadge}</td>
                    <td style="padding:10px 12px;">${contactsText}</td>
                  </tr>
                `;
              }).join('');
            }

            const totalEl = document.getElementById('dup-total-count');
            if (totalEl) totalEl.innerText = existing.length;
            const badgeEl = document.getElementById('dup-new-count-badge');
            if (badgeEl) badgeEl.innerText = `+${newTargets.length} brand new sites will be scraped`;
            const skipBtn = document.getElementById('dup-btn-skip');
            if (skipBtn) skipBtn.innerText = `⏭️ Skip Existing (${newTargets.length} New Only)`;

            updateDuplicateCounts();

            const modal = document.getElementById('duplicate-websites-modal');
            if (modal) modal.style.display = 'flex';
            return;
          }
        }
      } catch (err) {
        console.warn("Could not check duplicate URLs:", err);
      }

      await executeStartWebsiteList(finalTargets, visibleBrowser, deepCrawl, false);
    }

    async function executeStartWebsiteList(finalTargets, visibleBrowser, deepCrawl, forceFresh = true) {
      setScrapingState(true, `Launching Tab 2 for ${finalTargets.length} websites...`);
      logMessage(`🌐 Launching Direct Website Scraper for ${finalTargets.length} targets (Deep crawl: ${deepCrawl})...`);

      if (typeof window.switchTableTab === 'function') {
        window.switchTableTab('website');
      }

      try {
        const resp = await fetch('/api/start-website-list', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            urls: finalTargets,
            visible_browser: visibleBrowser,
            deep_crawl: deepCrawl,
            force_fresh: forceFresh
          })
        });
        let res = {};
        const text = await resp.text();
        try { res = JSON.parse(text); } catch (_) { res = { detail: text || ("Status " + resp.status) }; }

        if (!resp.ok) {
          alert(res.detail || "Error starting website list scraper");
          setScrapingState(false, "Ready");
        } else if (res.status === 'already_running') {
          logMessage("ℹ️ Scraper is already running in background. Click 'Stop' if you wish to cancel.");
          setScrapingState(true, "Live Agent Running");
          setTimeout(pollStatus, 300);
        } else {
          setTimeout(pollStatus, 300);
        }
      } catch (err) {
        alert("Error connecting to server: " + err.message);
        setScrapingState(false, "Ready");
      }
    }

    function initMap() {
      const mapEl = document.getElementById('picker-map');
      if (!mapEl) return;
      if (typeof L === 'undefined') {
        setTimeout(initMap, 400);
        return;
      }
      if (leafletMap) return;

      const latInputEl = document.getElementById('lat-input');
      const lonInputEl = document.getElementById('lon-input');
      const lat = latInputEl ? parseFloat(latInputEl.value) || 19.0760 : 19.0760;
      const lon = lonInputEl ? parseFloat(lonInputEl.value) || 72.8777 : 72.8777;

      leafletMap = L.map('picker-map', {
        center: [lat, lon],
        zoom: 13,
        zoomControl: true
      });

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(leafletMap);

      const centerPinIcon = L.divIcon({
        className: "custom-center-pin-wrapper",
        html: '<div class="custom-center-pin" title="Search Center & Radius Focus"></div>',
        iconSize: [24, 24],
        iconAnchor: [12, 12]
      });
      searchMarker = L.marker([lat, lon], { draggable: true, icon: centerPinIcon, title: "Search Center Pin" }).addTo(leafletMap);
      radiusCircle = L.circle([lat, lon], {
        radius: 5000,
        color: '#06b6d4',
        fillColor: '#06b6d4',
        fillOpacity: 0.14
      }).addTo(leafletMap);

      placesLayer = L.layerGroup().addTo(leafletMap);

      searchMarker.on('drag', function(e) {
        const pos = e.target.getLatLng();
        updateCoords(pos.lat, pos.lng, false);
      });

      leafletMap.on('click', function(e) {
        searchMarker.setLatLng(e.latlng);
        updateCoords(e.latlng.lat, e.latlng.lng, true);
      });

      setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 200);
      setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 800);
    }

    // Updates inputs and visual circle when pin is dragged or map is clicked
    function updateCoords(lat, lng, pan = false) {
      const latInput = document.getElementById('lat-input');
      const lonInput = document.getElementById('lon-input');
      if (latInput) latInput.value = parseFloat(lat).toFixed(6);
      if (lonInput) lonInput.value = parseFloat(lng).toFixed(6);
      if (radiusCircle) radiusCircle.setLatLng([lat, lng]);
      if (searchMarker) searchMarker.setLatLng([lat, lng]);
      if (pan && leafletMap) leafletMap.panTo([lat, lng]);
    }

    // Called whenever user manually types, edits, or pastes Latitude or Longitude
    window.onManualCoordChange = function() {
      const latVal = parseFloat(document.getElementById('lat-input').value);
      const lonVal = parseFloat(document.getElementById('lon-input').value);

      if (!isNaN(latVal) && !isNaN(lonVal) && latVal >= -90 && latVal <= 90 && lonVal >= -180 && lonVal <= 180) {
        if (searchMarker) searchMarker.setLatLng([latVal, lonVal]);
        if (radiusCircle) radiusCircle.setLatLng([latVal, lonVal]);
        if (leafletMap) {
          leafletMap.panTo([latVal, lonVal]);
        }
      }
    };

    // Quick preset location chips
    window.setPresetLocation = function(lat, lon, label, zoom = 13) {
      updateCoords(lat, lon, true);
      if (leafletMap) leafletMap.setView([lat, lon], zoom);
      const searchBox = document.getElementById('location-search-input');
      if (searchBox) searchBox.value = label;
      logMessage(`📍 Target Location set to: ${label} (${lat}, ${lon})`);
    };

    // Search any city, address, or landmark on OpenStreetMap
    window.searchLocationOnMap = async function() {
      const input = document.getElementById('location-search-input');
      if (!input || !input.value.trim()) return;
      const query = input.value.trim();

      // Check if user entered raw coordinates in search bar (e.g. "19.0760, 72.8777")
      const coordMatch = query.match(/^([+-]?\d+(?:\.\d+)?)[,\s]+([+-]?\d+(?:\.\d+)?)$/);
      if (coordMatch) {
        const cLat = parseFloat(coordMatch[1]);
        const cLon = parseFloat(coordMatch[2]);
        if (!isNaN(cLat) && !isNaN(cLon)) {
          window.setPresetLocation(cLat, cLon, `Coords: ${cLat}, ${cLon}`, 14);
          return;
        }
      }

      logMessage(`🔍 Geocoding target location on map: "${query}"...`);
      try {
        const resp = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`, {
          headers: { 'Accept': 'application/json' }
        });
        const results = await resp.json();
        if (results && results.length > 0) {
          const loc = results[0];
          const newLat = parseFloat(loc.lat);
          const newLon = parseFloat(loc.lon);
          window.setPresetLocation(newLat, newLon, loc.display_name.split(',')[0], 14);
          logMessage(`✅ Map centered at: ${loc.display_name}`);
        } else {
          alert(`Could not find coordinates for "${query}". Try searching a city or entering Latitude & Longitude directly.`);
        }
      } catch (err) {
        console.error("Geocoding failed:", err);
        alert("Geocoding service unavailable. You can enter Latitude and Longitude directly into the inputs below.");
      }
    };

    // Locate user's live position via browser Geolocation API
    window.locateUserPosition = function() {
      if (!navigator.geolocation) {
        alert("Geolocation is not supported by your browser.");
        return;
      }
      const btn = document.getElementById('locate-me-btn');
      if (btn) btn.innerText = "⏳ Locating...";
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (btn) btn.innerText = "🎯 My Location";
          const uLat = pos.coords.latitude;
          const uLon = pos.coords.longitude;
          window.setPresetLocation(uLat, uLon, "My Current Location", 14);
          logMessage(`🎯 Found your location: (${uLat.toFixed(5)}, ${uLon.toFixed(5)})`);
        },
        (err) => {
          if (btn) btn.innerText = "🎯 My Location";
          alert("Could not access your location. Please check browser permissions or enter coordinates manually.");
        },
        { enableHighAccuracy: true, timeout: 8000 }
      );
    };

    function updateRadius(val) {
      const km = parseFloat(val);
      const slider = document.getElementById('radius-slider');
      const label = document.getElementById('radius-val');
      if (slider) slider.value = km;
      if (label) label.innerText = km;
      if (radiusCircle) {
        radiusCircle.setRadius(km * 1000);
      }
    }

    function handlePlatformToggleChange() {
      const toggle = document.getElementById('agent-platform-toggle');
      const panel = document.getElementById('platform-config-panel');
      const card = document.getElementById('card-platform');
      if (toggle && panel) {
        panel.style.display = toggle.checked ? 'block' : 'none';
      }
      if (card) {
        card.style.display = toggle.checked ? 'flex' : 'none';
      }
      handleAgentToggleChange();

      // Immediately refresh Platform Scout progress card
      if (typeof window.updatePlatformSyncCard === 'function') {
        const qp = window.tablesSplitData ? window.tablesSplitData.queue_progress : null;
        window.updatePlatformSyncCard(
          (qp && qp.platforms_breakdown) || (proximityStats && proximityStats.platforms) || null,
          (qp && qp.platform) || null
        );
      }
      if (typeof updateProximityUI === 'function') {
        updateProximityUI({});
      }
    }

    function getSelectedPlatforms() {
      const cbs = document.querySelectorAll('.platform-src-cb:checked');
      const plats = [];
      cbs.forEach(cb => {
        if (cb.value && cb.value !== 'Custom') plats.push(cb.value);
      });
      const customCb = document.getElementById('platform-src-custom');
      if (customCb && customCb.checked) plats.push('Custom');
      return plats.length > 0 ? plats : ["Fresha"];
    }

    function handlePlatformPresetChange() {
      const customCb = document.getElementById('platform-src-custom');
      const customGroup = document.getElementById('platform-custom-input-group');
      if (customGroup) {
        customGroup.style.display = (customCb && customCb.checked) ? 'block' : 'none';
      }
      handleAgentToggleChange();

      // Immediately refresh proximity UI and Platform Scout progress card for the selected platforms
      if (typeof updateProximityUI === 'function') {
        updateProximityUI({});
      }
      if (typeof window.updatePlatformSyncCard === 'function') {
        const qp = window.tablesSplitData ? window.tablesSplitData.queue_progress : null;
        window.updatePlatformSyncCard(
          (qp && qp.platforms_breakdown) || (proximityStats && proximityStats.platforms) || null,
          (qp && qp.platform) || null
        );
      }
    }

    async function runManualNormalize() {
      try {
        logMessage("🔄 Running Cross-Platform Entity Normalization...");
        const resp = await fetch('/api/normalize', { method: 'POST' });
        const res = await resp.json();
        if (res.status === 'ok') {
          logMessage(`✅ Normalization finished: ${res.stats.newly_matched} matched leads merged into Master Table.`);
          if (window.updateSplitData) window.updateSplitData(res.tables_split);
          if (window.refreshTablesSplit) window.refreshTablesSplit();
        }
      } catch (e) {
        alert("Error normalizing: " + e.message);
      }
    }

    function handleAgentToggleChange() {
      // Maps, Website, and LinkedIn agents are blocked - only Platform Directory Scout is active
      const mapsEl = document.getElementById('agent-maps-toggle');
      if (mapsEl) { mapsEl.checked = false; mapsEl.disabled = true; }
      const siteEl = document.getElementById('agent-website-toggle');
      if (siteEl) { siteEl.checked = false; siteEl.disabled = true; }
      const liEl = document.getElementById('agent-linkedin-toggle');
      if (liEl) { liEl.checked = false; liEl.disabled = true; }

      const mapsOn = false;
      const siteOn = false;
      const liOn = false;
      const platToggle = document.getElementById('agent-platform-toggle');
      if (platToggle && !platToggle.checked) {
        platToggle.checked = true;
      }
      const platOn = true;
      const startBtn = document.getElementById('start-btn');

      // Update live stream viewports to visibly show ONLY the active Platform Directory Scout
      const cardMaps = document.getElementById('card-maps');
      const cardSite = document.getElementById('card-website');
      const cardLi = document.getElementById('card-linkedin');
      const cardPlat = document.getElementById('card-platform');

      if (cardMaps) cardMaps.style.display = 'none';
      if (cardSite) cardSite.style.display = 'none';
      if (cardLi) cardLi.style.display = 'none';
      if (cardPlat) cardPlat.style.display = 'flex';

      const plats = getSelectedPlatforms();
      const parts = plats.length > 0 ? plats : ["Fresha"];

      if (startBtn && currentMode === 'maps') {
        startBtn.innerHTML = `<span>🚀 Launch Directory Scout (${parts.join(' & ')})</span>`;
      }
    }

    async function runDbDedup() {
      try {
        const resp = await fetch('/api/deduplicate', { method: 'POST' });
        const res = await resp.json();
        alert(`Database Deduplication Complete!\nMerged: ${res.merged} duplicate leads.\nTotal Clean Leads in DB: ${res.total}`);
        if (res.places) {
          placesData = res.places;
          renderTable();
          updateKPIs();
        }
      } catch (err) {
        alert("Error running deduplication: " + err.message);
      }
    }

    function setQuery(text) {
      document.getElementById('query-input').value = text;
    }

    function addCompanyChip(name) {
      const input = document.getElementById('companies-input');
      const val = input.value.trim();
      if (!val) {
        input.value = name;
      } else if (!val.includes(name)) {
        input.value = val + ', ' + name;
      }
    }


    // Infinity & Max Places Limit Controls
    let isInfinityMode = true;

    function handleMaxSliderInput(val) {
      const v = parseInt(val);
      const maxLabel = document.getElementById('max-label');
      const scrapeAllToggle = document.getElementById('scrape-all-toggle');
      if (v >= 500) {
        isInfinityMode = true;
        if (scrapeAllToggle) scrapeAllToggle.checked = true;
        if (maxLabel) maxLabel.innerHTML = '∞ <span style="font-size:0.75rem; color:#a5b4fc;">(Unlimited / Continuous)</span>';
      } else {
        isInfinityMode = false;
        if (scrapeAllToggle) scrapeAllToggle.checked = false;
        if (maxLabel) maxLabel.innerHTML = `${v} <span style="font-size:0.75rem; color:#a5b4fc;">places</span>`;
      }
    }

    function setMaxLimit(val) {
      const slider = document.getElementById('max-slider');
      const maxLabel = document.getElementById('max-label');
      const scrapeAllToggle = document.getElementById('scrape-all-toggle');
      if (val === 'infinity') {
        isInfinityMode = true;
        if (slider) slider.value = 500;
        if (scrapeAllToggle) scrapeAllToggle.checked = true;
        if (maxLabel) maxLabel.innerHTML = '∞ <span style="font-size:0.75rem; color:#a5b4fc;">(Unlimited / Continuous)</span>';
        logMessage("♾️ Max Places Limit set to Unlimited (Continuous).");
      } else {
        isInfinityMode = false;
        const numVal = parseInt(val);
        if (slider) slider.value = numVal;
        if (scrapeAllToggle) scrapeAllToggle.checked = false;
        if (maxLabel) maxLabel.innerHTML = `${numVal} <span style="font-size:0.75rem; color:#a5b4fc;">places</span>`;
        logMessage(`🎯 Max Places Limit set to ${numVal} places.`);
      }
    }

    function toggleInfinityMode() {
      if (isInfinityMode) {
        setMaxLimit(50);
      } else {
        setMaxLimit('infinity');
      }
    }

    // Toggle All Shops (Continuous)
    document.getElementById('scrape-all-toggle')?.addEventListener('change', function(e) {
      const qInput = document.getElementById('query-input');
      const maxLabel = document.getElementById('max-label');
      const slider = document.getElementById('max-slider');
      if (e.target.checked) {
        isInfinityMode = true;
        if (slider) slider.value = 500;
        if (maxLabel) maxLabel.innerHTML = '∞ <span style="font-size:0.75rem; color:#a5b4fc;">(Unlimited / Continuous)</span>';
        if (qInput && !qInput.value) qInput.placeholder = 'All Shops in Selected Area (No keyword needed)';
        logMessage("♾️ Continuous Harvesting ON: Max Places Limit set to Unlimited.");
      } else {
        isInfinityMode = false;
        const v = parseInt(slider?.value || 50);
        const targetVal = v >= 500 ? 50 : v;
        if (slider) slider.value = targetVal;
        if (maxLabel) maxLabel.innerHTML = `${targetVal} <span style="font-size:0.75rem; color:#a5b4fc;">places</span>`;
        if (qInput) qInput.placeholder = 'e.g. Barber, Bakery, Dentist';
        logMessage(`🎯 Continuous Harvesting OFF: Max Places Limit set to ${targetVal} places.`);
      }
    });

    function toggleStreamExpand(cardId) {
      const card = document.getElementById(cardId);
      if (!card) return;
      const isExpanded = card.classList.contains('expanded');
      document.querySelectorAll('.stream-card').forEach(c => c.classList.remove('expanded'));
      if (!isExpanded) {
        card.classList.add('expanded');
      }
    }

    const seenLogSignatures = new Set();

    const agentLogCounts = { maps: 0, website: 0, linkedin: 0, platform: 0 };

    function classifyAgent(rawText, explicitAgent) {
      if (explicitAgent && ['maps', 'website', 'linkedin', 'platform'].includes(explicitAgent)) {
        return explicitAgent;
      }
      const low = String(rawText || '').toLowerCase();
      if (low.includes('[maps]') || low.includes('[agent 1:') || low.includes('maps feed') || low.includes('panning') || low.includes('radius filter') || low.includes('area dedup') || low.includes('db dedup')) return 'maps';
      if (low.includes('[website]') || low.includes('[agent 2:') || low.includes('website') || low.includes('cloudflare') || low.includes('turnstile') || low.includes('anti-bot') || low.includes('email extraction')) return 'website';
      if (low.includes('[linkedin]') || low.includes('[agent 3:') || low.includes('[org intelligence]') || low.includes('linkedin') || low.includes('employee') || low.includes('personnel')) return 'linkedin';
      if (low.includes('[platform') || low.includes('[agent 4:') || low.includes('[tab 4') || low.includes('fresha') || low.includes('airbnb') || low.includes('yelp') || low.includes('tripadvisor') || low.includes('directory')) return 'platform';
      return null;
    }

    function appendAgentLog(agent, rawText, timeStr) {
      if (!agent || !['maps', 'website', 'linkedin', 'platform'].includes(agent)) return;
      const box = document.getElementById(`console-box-${agent}`);
      if (!box) return;

      const time = timeStr || new Date().toLocaleTimeString();
      const line = document.createElement('div');
      line.className = `agent-log-line ${agent}`;
      line.innerHTML = `<span class="agent-log-time">[${time}]</span> <span>${escapeHtml(rawText)}</span>`;
      box.appendChild(line);

      while (box.children.length > 200) {
        box.removeChild(box.firstChild);
      }

      agentLogCounts[agent] = (agentLogCounts[agent] || 0) + 1;
      const badge = document.getElementById(`badge-log-${agent}`);
      if (badge) {
        badge.innerText = `${agentLogCounts[agent]} logs`;
      }
      box.scrollTop = box.scrollHeight;
    }

    window.clearAgentConsole = function(agent) {
      if (!agent) return;
      const box = document.getElementById(`console-box-${agent}`);
      if (box) {
        box.innerHTML = `<div class="agent-log-line ${agent}"><span class="agent-log-time">[${new Date().toLocaleTimeString()}]</span> <span>Console cleared. Ready for next activity.</span></div>`;
      }
      agentLogCounts[agent] = 0;
      const badge = document.getElementById(`badge-log-${agent}`);
      if (badge) badge.innerText = '0 logs';
    };

    function clearAllAgentConsoles() {
      ['maps', 'website', 'linkedin', 'platform'].forEach(ag => {
        const box = document.getElementById(`console-box-${ag}`);
        if (box) box.innerHTML = '';
        agentLogCounts[ag] = 0;
        const badge = document.getElementById(`badge-log-${ag}`);
        if (badge) badge.innerText = '0 logs';
      });
    }

    function clearTerminalBox() {
      const box = document.getElementById('terminal-box');
      if (box) {
        box.innerHTML = '';
        seenLogSignatures.clear();
        updateLogCountBadge();
      }
      clearAllAgentConsoles();
    }

    window.clearTerminalLogs = function() {
      clearTerminalBox();
      logMessage("ℹ️ Terminal logs view cleared.");
    };

    function updateLogCountBadge() {
      const box = document.getElementById('terminal-box');
      const badge = document.getElementById('log-count-badge');
      if (box && badge) {
        const count = box.querySelectorAll('.log-line').length;
        badge.innerText = `${count} ${count === 1 ? 'log' : 'logs'}`;
      }
    }

    function logMessage(msg, timeStr, explicitAgent) {
      if (!msg) return;
      const box = document.getElementById('terminal-box');
      if (!box) return;

      const rawText = (typeof msg === 'string' ? msg : (msg.message || JSON.stringify(msg))).trim();
      if (!rawText) return;

      const time = timeStr || (typeof msg === 'object' && msg.time ? msg.time : new Date().toLocaleTimeString());
      const agent = explicitAgent || (typeof msg === 'object' && msg.agent ? msg.agent : null);

      // Route to dedicated agent console
      const detectedAgent = classifyAgent(rawText, agent);
      if (detectedAgent) {
        appendAgentLog(detectedAgent, rawText, time);
      }

      const sig = `${time}|${rawText}`;
      if (seenLogSignatures.has(sig)) return;
      seenLogSignatures.add(sig);

      if (seenLogSignatures.size > 2000) {
        const first = seenLogSignatures.values().next().value;
        seenLogSignatures.delete(first);
      }

      const line = document.createElement('div');
      line.className = 'log-line';

      if (rawText.includes('[Agent 1: Maps]') || rawText.includes('Tab 1') || detectedAgent === 'maps') {
        line.classList.add('log-agent-maps');
      } else if (rawText.includes('[Agent 2: Website]') || rawText.includes('Tab 2') || detectedAgent === 'website') {
        line.classList.add('log-agent-website');
      } else if (rawText.includes('[Agent 3: LinkedIn]') || rawText.includes('Tab 3') || detectedAgent === 'linkedin') {
        line.classList.add('log-agent-linkedin');
      } else if (rawText.includes('[Agent 4: Platform]') || rawText.includes('Tab 4') || detectedAgent === 'platform') {
        line.classList.add('log-agent-platform');
      } else if (rawText.includes('⚠️') || rawText.toLowerCase().includes('error')) {
        line.classList.add('log-warning');
      } else if (rawText.includes('✅') || rawText.includes('🏁') || rawText.includes('Finished')) {
        line.classList.add('log-success');
      }

      line.innerHTML = `<span class="log-time">[${time}]</span> <span class="log-text">${escapeHtml(rawText)}</span>`;
      box.appendChild(line);

      while (box.children.length > 500) {
        box.removeChild(box.firstChild);
      }

      box.scrollTop = box.scrollHeight;
      updateLogCountBadge();
    }

    function renderLogsBatch(logsList) {
      if (!Array.isArray(logsList) || logsList.length === 0) return;
      logsList.forEach(item => {
        if (typeof item === 'string') {
          logMessage(item);
        } else if (item && item.message) {
          logMessage(item.message, item.time, item.agent);
        }
      });
    }

    function syncLogsFromPoll(logsList) {
      if (!Array.isArray(logsList) || logsList.length === 0) return;
      logsList.forEach(item => {
        if (typeof item === 'string') {
          logMessage(item);
        } else if (item && item.message) {
          logMessage(item.message, item.time, item.agent);
        }
      });
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    let hasAutoCenteredMap = false;

    window.fitMapToPins = function() {
      if (!leafletMap || !placesLayer) return;
      const validPoints = [];
      placesData.forEach(p => {
        const lat = parseFloat(p.lat);
        const lon = parseFloat(p.lon);
        if (!isNaN(lat) && !isNaN(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180 && (lat !== 0 || lon !== 0)) {
          validPoints.push([lat, lon]);
        }
      });
      if (validPoints.length > 0) {
        const bounds = L.latLngBounds(validPoints);
        leafletMap.fitBounds(bounds, { padding: [35, 35], maxZoom: 16 });
      } else {
        alert("No places with valid GPS coordinates in database yet.");
      }
    };

    function plotShopsOnMap() {
      if (!leafletMap || !placesLayer) return;
      placesLayer.clearLayers();
      markersMap = {};
      let plottedCount = 0;
      const validPoints = [];

      placesData.forEach((place, index) => {
        const lat = parseFloat(place.lat);
        const lon = parseFloat(place.lon);
        if (!isNaN(lat) && !isNaN(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180 && (lat !== 0 || lon !== 0)) {
          plottedCount++;
          validPoints.push([lat, lon]);
          const rowId = place.id || (index + 1);

          const popupContent = `
            <div style="font-family:'Inter',sans-serif; min-width:230px; line-height:1.4;">
              <strong style="color:#6366f1; font-size:1.02rem; display:block; margin-bottom:2px;">${escapeHtml(place.name)}</strong>
              <span style="font-size:0.75rem; background:rgba(99,102,241,0.15); color:#a5b4fc; padding:2px 6px; border-radius:4px; font-weight:600;">${escapeHtml(place.category || 'Business')}</span>
              ${place.rating && place.rating !== 'N/A' ? `<div style="margin-top:4px; font-size:0.82rem; color:#fbbf24; font-weight:600;">⭐ ${place.rating} (${place.reviews || '0'} reviews)</div>` : ''}
              ${place.address && place.address !== 'N/A' ? `<div style="margin-top:4px; font-size:0.78rem; color:#cbd5e1;">📍 ${escapeHtml(place.address)}</div>` : ''}
              ${place.phone && place.phone !== 'N/A' ? `<div style="font-size:0.78rem; color:#cbd5e1;">📞 <a href="tel:${place.phone}" style="color:#06b6d4; text-decoration:none;">${escapeHtml(place.phone)}</a></div>` : ''}
              ${place.whatsapp && place.whatsapp !== 'N/A' ? `<div style="font-size:0.78rem; color:#4ade80; margin-top:2px;">💬 <a href="${encodeURI(place.whatsapp.startsWith('http') ? place.whatsapp : `https://wa.me/${String(place.whatsapp).replace(/[^0-9]/g, '') || place.whatsapp}`)}" target="_blank" style="color:#4ade80; font-weight:600; text-decoration:none;">WhatsApp: ${escapeHtml(place.whatsapp)}</a></div>` : ''}
              ${place.email && place.email !== 'N/A' ? `<div style="font-size:0.78rem; color:#6ee7b7; font-weight:600; margin-top:2px;">✉️ ${escapeHtml(place.email)}</div>` : ''}
              ${place.platform_name && place.platform_name !== 'N/A' ? `<div style="font-size:0.76rem; color:#c084fc; margin-top:3px;">🟣 <strong>${escapeHtml(place.platform_name)}</strong> ${place.platform_rating ? `(${place.platform_rating}★)` : ''}</div>` : ''}
              <div style="margin-top:8px; display:flex; gap:10px; border-top:1px solid rgba(255,255,255,0.1); padding-top:6px;">
                ${place.website && place.website !== 'N/A' ? `<a href="${encodeURI(place.website)}" target="_blank" style="color:#06b6d4; font-size:0.78rem; font-weight:600; text-decoration:none;">🌐 Website</a>` : ''}
                <button onclick="openOrgModal('${escapeHtml(place.name)}')" style="background:none; border:none; color:#a855f7; font-size:0.78rem; font-weight:600; cursor:pointer;">🌳 Org Tree</button>
              </div>
            </div>
          `;

          const pinIcon = L.divIcon({
            className: "custom-lead-pin-wrapper",
            html: `<div class="custom-lead-pin" title="${escapeHtml(place.name)}"><span>${rowId}</span></div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 28],
            popupAnchor: [0, -28]
          });

          const m = L.marker([lat, lon], { icon: pinIcon }).bindPopup(popupContent);
          m.addTo(placesLayer);
          markersMap[rowId] = m;
          markersMap[place.id] = m;
          markersMap[index] = m;
          m.on('click', () => { highlightTableRow(rowId); });
        }
      });

      document.getElementById('stat-plotted').innerText = plottedCount;

      // Auto-fit bounds on initial load if valid leads exist and haven't auto-centered yet
      if (!hasAutoCenteredMap && validPoints.length > 0) {
        hasAutoCenteredMap = true;
        try {
          const bounds = L.latLngBounds(validPoints);
          leafletMap.fitBounds(bounds, { padding: [35, 35], maxZoom: 15 });
        } catch (e) {}
      }
    }

    function focusShop(idOrIdx) {
      const mapEl = document.getElementById('picker-map');
      if (markersMap[idOrIdx]) {
        const m = markersMap[idOrIdx];
        if (mapEl) {
          mapEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        leafletMap.setView(m.getLatLng(), 16);
        setTimeout(() => m.openPopup(), 200);
      } else {
        const p = placesData.find((item, idx) => item.id == idOrIdx || idx == idOrIdx);
        if (p) {
          logMessage(`ℹ️ Place '${p.name}' does not have GPS coordinates to plot.`);
        }
      }
    }

    function highlightTableRow(idOrIdx) {
      const row = document.getElementById(`row-${idOrIdx}`);
      if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.style.background = 'rgba(99, 102, 241, 0.25)';
        setTimeout(() => { row.style.background = ''; }, 2000);
      }
    }

    function updateKPIs() {
      document.getElementById('stat-total').innerText = placesData.length;
      const emailsCount = placesData.filter(p => p.email && p.email !== 'N/A' && p.email.length > 0).length;
      let totalEmployees = 0;
      placesData.forEach(p => {
        if (p.employee_count) {
          totalEmployees += parseInt(p.employee_count) || 0;
        }
      });

      document.getElementById('stat-emails').innerText = emailsCount;
      document.getElementById('stat-orgs').innerText = totalEmployees;
      document.getElementById('places-count-badge').innerText = `${placesData.length} in DB`;
      plotShopsOnMap();
    }

    function renderTable() {
      if (typeof window.renderTable === 'function' && window.renderTable !== renderTable) {
        window.renderTable();
        return;
      }
      const tbody = document.getElementById('places-tbody');
      if (placesData.length === 0) {
        tbody.innerHTML = `
          <tr id="empty-row">
            <td colspan="14">
              <div class="empty-state">
                <div class="empty-icon">🔍</div>
                <p>No places in database. Click <strong>"Start Live Agent"</strong> to harvest leads and company hierarchies!</p>
              </div>
            </td>
          </tr>
        `;
        return;
      }

      tbody.innerHTML = '';
      placesData.forEach((place, index) => {
        const rowId = place.id || index;
        const tr = document.createElement('tr');
        tr.id = `row-${rowId}`;
        tr.onclick = () => focusShop(rowId);

        const emailHtml = (place.email && place.email !== 'N/A')
          ? `<span class="badge badge-email" title="Click to copy" onclick="event.stopPropagation(); navigator.clipboard.writeText('${place.email}'); alert('Copied: ${place.email}')">✉️ ${escapeHtml(place.email)}</span>`
          : `<span class="badge badge-none">Not listed</span>`;

        const categoryHtml = place.category
          ? `<span class="badge badge-category">${escapeHtml(place.category)}</span>`
          : `<span class="badge badge-none">Business</span>`;

        const ratingHtml = (place.rating && place.rating !== 'N/A')
          ? `<span class="rating-pill">★ ${place.rating} <small style="color:#94a3b8;">(${place.reviews || '0'})</small></span>`
          : `<span style="color:#64748b;">N/A</span>`;

        const linksHtml = `
          <div style="display:flex; gap:8px;" onclick="event.stopPropagation();">
            ${place.website && place.website !== 'N/A' ? `<a href="${encodeURI(place.website)}" target="_blank" class="link-btn">🌐 Site</a>` : ''}
            ${place.maps_url ? `<a href="${encodeURI(place.maps_url)}" target="_blank" class="link-btn">🗺️ Maps</a>` : ''}
          </div>
        `;

        const socialsList = [];
        if (place.instagram) socialsList.push(`<a href="${encodeURI(place.instagram)}" target="_blank" class="badge-social badge-ig" title="Instagram: ${escapeHtml(place.instagram)}" onclick="event.stopPropagation();">📸</a>`);
        if (place.facebook) socialsList.push(`<a href="${encodeURI(place.facebook)}" target="_blank" class="badge-social badge-fb" title="Facebook: ${escapeHtml(place.facebook)}" onclick="event.stopPropagation();">📘</a>`);
        if (place.linkedin) socialsList.push(`<a href="${encodeURI(place.linkedin)}" target="_blank" class="badge-social badge-li" title="LinkedIn: ${escapeHtml(place.linkedin)}" onclick="event.stopPropagation();">💼</a>`);
        if (place.twitter) socialsList.push(`<a href="${encodeURI(place.twitter)}" target="_blank" class="badge-social badge-tw" title="Twitter/X: ${escapeHtml(place.twitter)}" onclick="event.stopPropagation();">🐦</a>`);
        if (place.youtube) socialsList.push(`<a href="${encodeURI(place.youtube)}" target="_blank" class="badge-social badge-yt" title="YouTube: ${escapeHtml(place.youtube)}" onclick="event.stopPropagation();">▶️</a>`);
        if (place.tiktok) socialsList.push(`<a href="${encodeURI(place.tiktok)}" target="_blank" class="badge-social badge-tt" title="TikTok: ${escapeHtml(place.tiktok)}" onclick="event.stopPropagation();">🎵</a>`);

        const socialsHtml = socialsList.length > 0
          ? `<div style="display:flex; gap:5px;" onclick="event.stopPropagation();">${socialsList.join('')}</div>`
          : `<span class="badge badge-none">—</span>`;

        let botHtml = `<span class="badge badge-none">N/A</span>`;
        if (place.bot_protection) {
          const bp = place.bot_protection;
          if (bp.includes('Access Denied')) {
            botHtml = `<span class="badge badge-bot-denied" title="Access Denied by Anti-Bot Shield">🚫 ${escapeHtml(bp)}</span>`;
          } else if (bp.includes('Access Granted')) {
            botHtml = `<span class="badge badge-bot-granted" title="Anti-Bot Shield active but website accessed successfully">🛡️ ${escapeHtml(bp)}</span>`;
          } else if (bp.includes('Cloudflare')) {
            botHtml = `<span class="badge badge-bot-cloudflare">🛡️ ${escapeHtml(bp)}</span>`;
          } else if (bp.includes('Anti-Bot') || bp.includes('Captcha') || bp.includes('Datadome') || bp.includes('PerimeterX')) {
            botHtml = `<span class="badge badge-bot-challenge">🛡️ ${escapeHtml(bp)}</span>`;
          } else if (bp === 'Clean') {
            botHtml = `<span class="badge badge-bot-clean">✅ Clean</span>`;
          } else {
            botHtml = `<span class="badge badge-none">${escapeHtml(bp)}</span>`;
          }
        }

        let cookieHtml = `<span class="badge badge-none">—</span>`;
        if (place.cookie_status) {
          if (place.cookie_status === 'Accepted') {
            cookieHtml = `<span class="badge badge-cookie-accepted" title="Cookie banner auto-accepted">🍪 Accepted</span>`;
          } else if (place.cookie_status.includes('Unaccepted')) {
            cookieHtml = `<span class="badge badge-cookie-pending" title="Cookie banner detected (unaccepted)">🍪 Unaccepted</span>`;
          } else if (place.cookie_status === 'None') {
            cookieHtml = `<span class="badge badge-none" title="No cookie banner detected">None</span>`;
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
                <span>📸 View</span>
              </button>
            </div>
          `
          : `<span class="badge badge-none" style="opacity:0.6;">—</span>`;

        const empCount = place.employee_count ? parseInt(place.employee_count) : 0;
        const employeeBadgeHtml = (empCount > 0)
          ? `<span class="badge badge-employees">👥 ${empCount} Members</span>`
          : `<span class="badge badge-none">—</span>`;

        const orgChartBtn = `
          <button class="btn-org-tree" onclick="event.stopPropagation(); openOrgModal('${escapeHtml(place.name)}')">
            <span>🌳 Org Tree</span>
          </button>
        `;

        function formatDateTime(dateStr) {
          if (!dateStr || dateStr === 'N/A') return '<span class="badge badge-none">—</span>';
          try {
            const d = new Date(dateStr.replace(' ', 'T'));
            if (isNaN(d.getTime())) return `<span style="font-size:0.75rem; color:#94a3b8;">${escapeHtml(dateStr)}</span>`;
            const datePart = d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
            const timePart = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            return `<div style="display:flex; flex-direction:column; gap:2px; font-size:0.75rem; white-space:nowrap;">
              <span style="color:#e2e8f0; font-weight:500;">📅 ${datePart}</span>
              <span style="color:#94a3b8; font-size:0.7rem;">⏰ ${timePart}</span>
            </div>`;
          } catch (e) {
            return `<span style="font-size:0.75rem; color:#94a3b8;">${escapeHtml(dateStr)}</span>`;
          }
        }

        let platformHtml = `<span class="badge badge-none">—</span>`;
        if (place.platform_name && place.platform_name !== 'N/A') {
          const pName = escapeHtml(place.platform_name);
          const pRating = (place.platform_rating && place.platform_rating !== 'N/A') ? `★ ${place.platform_rating}` : '';
          const pReviews = (place.platform_reviews && place.platform_reviews !== 'N/A') ? `(${place.platform_reviews})` : '';
          const bookLink = (place.booking_url && place.booking_url !== 'N/A')
            ? `<a href="${encodeURI(place.booking_url)}" target="_blank" class="badge-social" style="color:#a855f7; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); font-size:0.72rem; padding:2px 6px; text-decoration:none;" title="Direct Booking / Listing" onclick="event.stopPropagation();">📅 Book</a>`
            : '';
          const listLink = (place.platform_url && place.platform_url !== 'N/A')
            ? `<a href="${encodeURI(place.platform_url)}" target="_blank" class="link-btn" style="color:#c084fc; border-color:rgba(168,85,247,0.3); font-size:0.72rem; padding:2px 6px;" title="View on ${pName}" onclick="event.stopPropagation();">📍 ${pName}</a>`
            : `<span class="badge" style="background:rgba(168,85,247,0.15); color:#d8b4fe;">📍 ${pName}</span>`;

          platformHtml = `
            <div style="display:flex; flex-direction:column; gap:4px;" onclick="event.stopPropagation();">
              <div style="display:flex; align-items:center; gap:4px;">
                ${listLink}
                ${bookLink}
              </div>
              ${pRating ? `<span style="font-size:0.72rem; color:#d8b4fe; white-space:nowrap;">${pRating} <small style="color:#94a3b8;">${pReviews}</small></span>` : ''}
              ${place.platform_price && place.platform_price !== 'N/A' ? `<span style="font-size:0.68rem; color:#cbd5e1; white-space:nowrap;">💰 ${escapeHtml(place.platform_price)}</span>` : ''}
            </div>
          `;
        }

        tr.innerHTML = `
          <td style="color:#64748b; font-weight:600;">${place.id || (index + 1)}</td>
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
        `;
        tbody.appendChild(tr);
      });
    }

    function handleImgError(el) {
      el.onerror = null;
      if (el.parentElement) {
        el.parentElement.innerHTML = '<span style="font-size:10px; color:#64748b; display:flex; align-items:center; justify-content:center; height:100%;">No Image</span>';
      }
    }

    function openImageModal(src, title) {
      if (!src) return;
      const modal = document.getElementById('image-modal');
      const img = document.getElementById('modal-img');
      const titleEl = document.getElementById('modal-title');
      const newTabBtn = document.getElementById('modal-img-newtab');
      const downloadBtn = document.getElementById('modal-img-download');

      img.src = src;
      if (newTabBtn) newTabBtn.href = src;
      if (downloadBtn) {
        downloadBtn.href = src;
        const cleanName = (title || 'screenshot').replace(/[^a-zA-Z0-9_-]/g, '_');
        downloadBtn.setAttribute('download', `${cleanName}.jpg`);
      }
      titleEl.innerText = title ? `📸 Screenshot: ${title}` : 'Landing Page Screenshot';
      modal.style.display = 'flex';
    }

    function closeImageModal() {
      const modal = document.getElementById('image-modal');
      modal.style.display = 'none';
      const img = document.getElementById('modal-img');
      if (img) img.src = '';
    }

    // INTERACTIVE HIERARCHY TREE MODAL
    async function openOrgModal(companyName) {
      if (!companyName) return;
      const modal = document.getElementById('org-modal');
      const companyEl = document.getElementById('org-modal-company');
      const linkedinLink = document.getElementById('org-modal-linkedin-link');
      const container = document.getElementById('org-tree-render');

      companyEl.innerText = companyName;
      container.innerHTML = `
        <div style="text-align:center; padding:50px; color:#94a3b8;">
          <div style="font-size:32px; animation:spin 1s linear infinite; display:inline-block;">⚡</div>
          <p style="margin-top:12px;">Loading organization hierarchy tree for <strong>${escapeHtml(companyName)}</strong>...</p>
        </div>
      `;
      modal.style.display = 'flex';

      try {
        const resp = await fetch(`/api/leads/${encodeURIComponent(companyName)}/hierarchy`);
        if (!resp.ok) {
          throw new Error("Failed to fetch hierarchy data");
        }
        const data = await resp.json();

        if (data.linkedin_url) {
          linkedinLink.href = data.linkedin_url;
          linkedinLink.style.display = 'inline';
        } else {
          linkedinLink.style.display = 'none';
        }

        const execs = (data.tiers && data.tiers.executive) || [];
        const mgmt = (data.tiers && data.tiers.management) || [];
        const staff = (data.tiers && data.tiers.staff) || [];

        document.getElementById('org-count-exec').innerText = `👑 ${execs.length} Leadership & Executives`;
        document.getElementById('org-count-mgmt').innerText = `💼 ${mgmt.length} Heads & Management`;
        document.getElementById('org-count-staff').innerText = `🛠️ ${staff.length} Staff & Operations`;

        const total = execs.length + mgmt.length + staff.length;
        if (total === 0) {
          container.innerHTML = `
            <div style="text-align:center; padding:40px; color:#94a3b8;">
              <div style="font-size:42px; opacity:0.6;">🏢</div>
              <h3 style="color:#fff; margin-top:8px;">No LinkedIn Employees Indexed Yet</h3>
              <p style="margin-top:6px; font-size:0.85rem; max-width:400px; margin-left:auto; margin-right:auto;">
                This business hasn't been scanned on LinkedIn yet. You can launch a standalone LinkedIn scan right now:
              </p>
              <button class="btn btn-linkedin-theme" style="margin:16px auto 0 auto;" onclick="triggerCompanySearch('${escapeHtml(companyName)}')">
                <span>💼 Scrape LinkedIn for ${escapeHtml(companyName)}</span>
              </button>
            </div>
          `;
          return;
        }

        let html = '';

        // TIER 1: LEADERSHIP & EXECUTIVES
        if (execs.length > 0) {
          html += `
            <div class="tier-section">
              <div class="tier-header-badge exec">👑 Level 1: Leadership & Executives (${execs.length})</div>
              <div class="tier-grid">
                ${execs.map(e => renderEmployeeCard(e, 'exec-card')).join('')}
              </div>
            </div>
          `;
        }

        if (execs.length > 0 && (mgmt.length > 0 || staff.length > 0)) {
          html += `<div class="tree-connector-line"></div>`;
        }

        // TIER 2: HEADS & MANAGEMENT
        if (mgmt.length > 0) {
          html += `
            <div class="tier-section">
              <div class="tier-header-badge mgmt">💼 Level 2: Heads & Management (${mgmt.length})</div>
              <div class="tier-grid">
                ${mgmt.map(e => renderEmployeeCard(e, 'mgmt-card')).join('')}
              </div>
            </div>
          `;
        }

        if (mgmt.length > 0 && staff.length > 0) {
          html += `<div class="tree-connector-line"></div>`;
        }

        // TIER 3: STAFF & OPERATIONS
        if (staff.length > 0) {
          html += `
            <div class="tier-section">
              <div class="tier-header-badge staff">🛠️ Level 3: Staff & Operations (${staff.length})</div>
              <div class="tier-grid">
                ${staff.map(e => renderEmployeeCard(e, 'staff-card')).join('')}
              </div>
            </div>
          `;
        }

        container.innerHTML = html;

      } catch (err) {
        container.innerHTML = `
          <div style="text-align:center; padding:40px; color:#ef4444;">
            <p>Error loading hierarchy: ${escapeHtml(err.message)}</p>
          </div>
        `;
      }
    }

    function renderEmployeeCard(emp, cardClass) {
      const avatarHtml = emp.avatar_url
        ? `<img class="emp-avatar" src="${escapeHtml(emp.avatar_url)}" alt="${escapeHtml(emp.full_name)}" />`
        : `<div class="emp-avatar">${(emp.full_name || 'U').charAt(0).toUpperCase()}</div>`;

      const liLinkHtml = emp.linkedin_profile_url
        ? `<a href="${encodeURI(emp.linkedin_profile_url)}" target="_blank" class="emp-li-btn" title="View LinkedIn Profile">💼</a>`
        : '';

      const emailBtnHtml = emp.email
        ? `<a href="mailto:${encodeURI(emp.email)}" class="emp-li-btn" style="background:rgba(16,185,129,0.2); border-color:rgba(16,185,129,0.4);" title="Send Email: ${escapeHtml(emp.email)}">✉️</a>`
        : '';

      return `
        <div class="employee-node-card ${cardClass}">
          ${avatarHtml}
          <div class="emp-info">
            <div class="emp-name" title="${escapeHtml(emp.full_name)}">${escapeHtml(emp.full_name)}</div>
            <div class="emp-title" title="${escapeHtml(emp.title)}">${escapeHtml(emp.title)}</div>
            ${emp.location ? `<div class="emp-loc">📍 ${escapeHtml(emp.location)}</div>` : ''}
            ${emp.email ? `<div class="emp-loc" style="color:#34d399; font-weight:500;" title="${escapeHtml(emp.email)}">✉️ <a href="mailto:${escapeHtml(emp.email)}" style="color:#34d399; text-decoration:none;" onclick="event.stopPropagation()">${escapeHtml(emp.email)}</a></div>` : ''}
          </div>
          <div style="display:flex; flex-direction:column; gap:4px; align-items:center;">
            ${liLinkHtml}
            ${emailBtnHtml}
          </div>
        </div>
      `;
    }

    function closeOrgModal() {
      document.getElementById('org-modal').style.display = 'none';
    }

    function triggerCompanySearch(name) {
      closeOrgModal();
      setMode('companies');
      document.getElementById('companies-input').value = name;
      startScraping();
    }

    function setScrapingState(running, statusText = '') {
      const stateChanged = (isRunning !== running);
      isRunning = running;
      window.isScrapingRunning = running;
      const startBtn = document.getElementById('start-btn');
      const stopBtn = document.getElementById('stop-btn');
      if (startBtn) {
        startBtn.style.display = running ? 'none' : 'flex';
        startBtn.disabled = false;
        if (!running && stateChanged) {
          if (currentMode === 'companies') {
            startBtn.className = 'btn btn-linkedin-theme';
            startBtn.innerHTML = '<span>💼 Launch LinkedIn Org Harvester</span>';
          } else if (currentMode === 'website_list') {
            startBtn.className = 'btn btn-website-theme';
            startBtn.innerHTML = '<span>🌐 Launch Direct Website Scraper</span>';
          } else if (typeof handleAgentToggleChange === 'function') {
            handleAgentToggleChange();
          } else {
            startBtn.className = 'btn btn-primary';
            startBtn.innerHTML = '<span>🚀 Start Live Agent</span>';
          }
        }
      }
      if (stopBtn) {
        stopBtn.style.display = running ? 'flex' : 'none';
        stopBtn.disabled = false;
        stopBtn.innerHTML = '<span>⏹️ Stop</span>';
      }
      const dot = document.getElementById('status-dot');
      if (running) {
        if (dot) dot.classList.add('active');
        const st = document.getElementById('status-text');
        if (st && statusText) st.innerText = statusText;
      } else {
        if (dot) dot.classList.remove('active');
        const st = document.getElementById('status-text');
        if (st && statusText) st.innerText = statusText;
      }
    }

    async function activateChromeTab(tabName) {
      try {
        const resp = await fetch('/api/activate-tab', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tab: tabName })
        });
        const res = await resp.json();
        if (res.status === 'success') {
          logMessage(`👁️ Switched live Chrome window to focus: [${tabName.toUpperCase()} Agent]`);
        } else {
          logMessage(`ℹ️ [${tabName.toUpperCase()}] Tab not yet active in Chrome.`);
        }
      } catch (e) {
        console.error('activateChromeTab error:', e);
      }
    }

    function updateLiveStream(frame) {
      if (!frame || !frame.image) return;
      const tab = (frame.tab || frame.stream_type || '').toLowerCase();
      let prefix = null;
      let indicatorClass = '';
      let indicatorText = '';

      if (tab === 'platform' || frame.is_platform) {
        prefix = 'platform';
        indicatorClass = 'live-indicator platform';
        indicatorText = '🟣 TAB 4: DIRECTORY LIVE';
      } else if (tab === 'linkedin' || frame.is_linkedin) {
        prefix = 'linkedin';
        indicatorClass = 'live-indicator linkedin';
        indicatorText = '🔵 TAB 3: LINKEDIN LIVE';
      } else if (tab === 'website' || frame.is_website) {
        prefix = 'website';
        indicatorClass = 'live-indicator website';
        indicatorText = '🟢 TAB 2: SHOP LIVE';
      } else if (tab === 'maps' || frame.is_maps) {
        prefix = 'maps';
        indicatorClass = 'live-indicator maps';
        indicatorText = '🔴 TAB 1: MAPS LIVE';
      } else {
        // Drop unclassified or stray frames to protect agent card isolation
        return;
      }

      const img = document.getElementById(`stream-img-${prefix}`);
      const placeholder = document.getElementById(`stream-placeholder-${prefix}`);
      const indicator = document.getElementById(`stream-indicator-${prefix}`);
      const urlEl = document.getElementById(`stream-url-${prefix}`);
      const titleEl = document.getElementById(`stream-title-${prefix}`);

      if (img) {
        img.src = frame.image;
        img.style.display = 'block';
      }
      if (placeholder) {
        placeholder.style.display = 'none';
      }
      if (indicator) {
        indicator.className = indicatorClass;
        indicator.innerText = indicatorText;
      }
      if (titleEl && frame.title) {
        titleEl.innerText = frame.title;
      }
      if (urlEl && frame.url) {
        let cleanUrl = frame.url || '';
        if (cleanUrl.startsWith('https://')) cleanUrl = cleanUrl.substring(8);
        else if (cleanUrl.startsWith('http://')) cleanUrl = cleanUrl.substring(7);
        urlEl.innerText = cleanUrl;
        urlEl.title = frame.url || '';
      }
    }

    let ws = null;
    
    // -----------------------------------------------------------------
    // Proximity Yield & Deduplication Progress State
    // -----------------------------------------------------------------
    let proximityStats = {
      scraped: 0,
      skipped: 0,
      total: 0,
      timeSaved: 0.0,
      location: ''
    };

    function updateProximityUI(data) {
      if (!data) return;
      if (!proximityStats.platforms) proximityStats.platforms = {};

      if (data.total !== undefined) proximityStats.total = data.total;
      if (data.total_estimated !== undefined) proximityStats.total = data.total_estimated;
      if (data.scraped !== undefined) proximityStats.scraped = data.scraped;
      if (data.scraped_count !== undefined) proximityStats.scraped = data.scraped_count;
      if (data.skipped !== undefined) proximityStats.skipped = data.skipped;
      if (data.skipped_count !== undefined) proximityStats.skipped = data.skipped_count;
      if (data.time_saved_sec !== undefined) proximityStats.timeSaved = data.time_saved_sec;
      if (data.location) proximityStats.location = data.location;

      // Handle single platform update
      if (data.platform) {
        const p = data.platform;
        if (!proximityStats.platforms[p]) {
          proximityStats.platforms[p] = { total: data.total || 15, scraped: data.scraped || 0, skipped: data.skipped || 0, percent: data.percent || 0 };
        } else {
          if (data.total !== undefined) proximityStats.platforms[p].total = data.total;
          if (data.scraped !== undefined) proximityStats.platforms[p].scraped = data.scraped;
          if (data.skipped !== undefined) proximityStats.platforms[p].skipped = data.skipped;
          if (data.percent !== undefined) proximityStats.platforms[p].percent = data.percent;
        }
      }

      // Handle platforms dictionary in data
      if (data.platforms && typeof data.platforms === 'object') {
        Object.assign(proximityStats.platforms, data.platforms);
      }

      // Roll up overall metrics from ONLY selected platforms
      const selectedCbs = document.querySelectorAll('.platform-src-cb:checked');
      const selectedNames = [];
      selectedCbs.forEach(cb => { if (cb.value) selectedNames.push(cb.value); });
      const customCb = document.getElementById('platform-src-custom');
      if (customCb && customCb.checked && !selectedNames.includes('Custom')) selectedNames.push('Custom');
      const selectedLower = new Set(selectedNames.map(s => s.toLowerCase()));

      const platKeys = Object.keys(proximityStats.platforms).filter(k => selectedLower.has(k.toLowerCase()));
      if (platKeys.length > 0) {
        let rolledScraped = 0, rolledSkipped = 0, rolledTotal = 0;
        platKeys.forEach(k => {
          rolledScraped += proximityStats.platforms[k].scraped || 0;
          rolledSkipped += proximityStats.platforms[k].skipped || 0;
          rolledTotal += proximityStats.platforms[k].total || 0;
        });
        proximityStats.scraped = rolledScraped;
        proximityStats.skipped = rolledSkipped;
        proximityStats.total = Math.max(rolledTotal, rolledScraped + rolledSkipped, 1);
        proximityStats.timeSaved = rolledSkipped * 3.5;
      }

      const total = Math.max(proximityStats.total || 0, proximityStats.scraped + proximityStats.skipped, 1);
      const scrapedPct = Math.min(100, (proximityStats.scraped / total) * 100);
      const skippedPct = Math.min(100 - scrapedPct, (proximityStats.skipped / total) * 100);

      // Real-time hook: update Platform Scout Sync Card and each platform breakdown
      if (typeof window.updatePlatformSyncCard === 'function') {
        window.updatePlatformSyncCard(proximityStats.platforms, {
          total: proximityStats.total,
          scraped: proximityStats.scraped,
          skipped: proximityStats.skipped,
          percent: Math.min(100, Math.round(((proximityStats.scraped + proximityStats.skipped) / Math.max(1, proximityStats.total)) * 100))
        });
      }

      const barScraped = document.getElementById("bar-scraped");
      const barSkipped = document.getElementById("bar-skipped");
      if (barScraped) barScraped.style.width = scrapedPct.toFixed(1) + "%";
      if (barSkipped) barSkipped.style.width = skippedPct.toFixed(1) + "%";

      const bScraped = document.getElementById("yield-badge-scraped");
      const bSkipped = document.getElementById("yield-badge-skipped");
      const bTotal = document.getElementById("yield-badge-total");
      const locTag = document.getElementById("proximity-location-tag");
      const timeSavedText = document.getElementById("tracker-efficiency-text");
      const statusText = document.getElementById("tracker-status-text");

      if (bScraped) bScraped.innerText = `✅ ${proximityStats.scraped} Scraped`;
      if (bSkipped) bSkipped.innerText = `⏭️ ${proximityStats.skipped} Skipped (In DB)`;
      if (bTotal) bTotal.innerText = `🎯 ~${proximityStats.total} Total in Area`;
      if (timeSavedText) timeSavedText.innerText = `⚡ Time Saved: ${proximityStats.timeSaved.toFixed(1)}s`;
      if (locTag && proximityStats.location) {
        locTag.innerHTML = `Proximity Yield: <strong>${proximityStats.location}</strong>`;
      }
      if (statusText) {
        statusText.innerText = `Scanned ${proximityStats.scraped + proximityStats.skipped} of ~${total} places in proximity feed across active platforms.`;
      }

      // Render Individual Multi-Platform Rows
      renderPlatformBarsGrid();
    }

    function renderPlatformBarsGrid() {
      const grid = document.getElementById("platform-bars-grid");
      if (!grid) return;
      const plats = proximityStats.platforms || {};

      // Filter strictly to selected platforms
      const selectedCbs = document.querySelectorAll('.platform-src-cb:checked');
      const selectedNames = [];
      selectedCbs.forEach(cb => { if (cb.value) selectedNames.push(cb.value); });
      const customCb = document.getElementById('platform-src-custom');
      if (customCb && customCb.checked && !selectedNames.includes('Custom')) selectedNames.push('Custom');
      const selectedLower = new Set(selectedNames.map(s => s.toLowerCase()));

      const keys = Object.keys(plats).filter(k => selectedLower.has(k.toLowerCase()));
      if (keys.length === 0) {
        grid.style.display = "none";
        return;
      }
      grid.style.display = "grid";

      const icons = {
        "Google Maps": "🗺️",
        "Fresha": "🟣",
        "Airbnb": "🔴",
        "Yelp": "🟠",
        "TripAdvisor": "🟢"
      };

      let html = "";
      keys.forEach(k => {
        const item = plats[k];
        const pTotal = Math.max(item.total || 0, (item.scraped || 0) + (item.skipped || 0), 1);
        const pScraped = item.scraped || 0;
        const pSkipped = item.skipped || 0;
        const sPct = Math.min(100, (pScraped / pTotal) * 100);
        const kPct = Math.min(100 - sPct, (pSkipped / pTotal) * 100);
        const icon = icons[k] || "📍";

        html += `
          <div class="platform-bar-row">
            <div class="plat-row-meta">
              <span class="plat-name">${icon} ${k}</span>
              <span class="plat-counts">${pScraped} done, ${pSkipped} skipped / ~${pTotal} total</span>
            </div>
            <div class="segmented-progress-bar sub-bar">
              <div class="bar-segment bar-segment-scraped" style="width: ${sPct.toFixed(1)}%;" title="${pScraped} Scraped"></div>
              <div class="bar-segment bar-segment-skipped" style="width: ${kPct.toFixed(1)}%;" title="${pSkipped} Skipped"></div>
            </div>
          </div>
        `;
      });
      grid.innerHTML = html;
    }

    function connectWebSocket() {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      try {
        ws = new WebSocket(`${proto}//${window.location.host}/ws`);
        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'init') {
              if (msg.frame_maps) updateLiveStream(msg.frame_maps);
              if (msg.frame_website) updateLiveStream(msg.frame_website);
              if (msg.frame_linkedin) updateLiveStream(msg.frame_linkedin);
              if (msg.frame_platform) updateLiveStream(msg.frame_platform);
              if (msg.proximity_metrics) updateProximityUI(msg.proximity_metrics);
              if (Array.isArray(msg.logs)) renderLogsBatch(msg.logs);
              if (msg.agent_logs && typeof msg.agent_logs === 'object') {
                Object.keys(msg.agent_logs).forEach(ag => {
                  const list = msg.agent_logs[ag];
                  if (Array.isArray(list) && list.length > 0) {
                    list.forEach(item => {
                      if (typeof item === 'string') appendAgentLog(ag, item);
                      else if (item && item.message) appendAgentLog(ag, item.message, item.time);
                    });
                  }
                });
              }
            } else if (msg.type === 'proximity_total') {
              updateProximityUI(msg.data || msg);
            } else if (msg.type === 'platform_progress') {
              updateProximityUI(msg.data || msg);
            } else if (msg.type === 'proximity_progress') {
              updateProximityUI(msg.data || msg);
            } else if (msg.type === 'lead_skipped') {
              updateProximityUI(msg.data || msg);
            } else if (msg.type === 'live_frame') {
              updateLiveStream(msg.data);
            } else if (msg.type === 'tables_split') {
              if (typeof window.updateSplitData === 'function') {
                window.updateSplitData(msg.data);
              }
            } else if (msg.type === 'place_scraped') {
              const place = msg.data;
              placesData.unshift(place);
              const has_w = Boolean(place.website && place.website !== 'N/A' && place.website !== '');
              const has_p = Boolean(place.phone && place.phone !== 'N/A' && place.phone !== '');
              place.has_website = has_w;
              place.has_phone = has_p;
              place.status_tag = (has_w && has_p) ? "Full Contact (Web & Phone)" : (has_w ? "Has Website" : (has_p ? "Phone Only" : "Location Only"));

              if (typeof window.updateOrPrependLiveRow === 'function') {
                window.updateOrPrependLiveRow('maps', place);
                window.updateOrPrependLiveRow('master', place);
              } else if (typeof window.renderTable === 'function') {
                window.renderTable();
              }
              updateKPIs();
            } else if (msg.type === 'place_updated') {
              const uData = msg.data;
              const target = placesData.find(p => (uData.id && p.id === uData.id) || (p.name === uData.name && (p.address === uData.address || p.address === 'N/A' || uData.address === 'N/A')));
              if (target) {
                Object.assign(target, uData);
                if (!uData.id && target.id) uData.id = target.id;
              } else {
                placesData.unshift(uData);
              }

              let w_tag = "Website Found";
              const has_e = Boolean(uData.email && uData.email !== 'N/A');
              const has_s = Boolean(uData.instagram || uData.facebook || uData.twitter || uData.linkedin || uData.youtube || uData.tiktok);
              const bot = uData.bot_protection || "";
              if (has_e) w_tag = "Emails Extracted";
              else if (has_s) w_tag = "Socials Found";
              else if (bot.includes("Denied") || bot.includes("Captcha")) w_tag = "Bot Shielded";
              else if (uData.website_status === "failed") w_tag = "Website Unreachable";
              else if (uData.website_status === "social") w_tag = "Social Profile";

              const wRow = Object.assign({}, target || uData);
              Object.assign(wRow, uData);
              wRow.status_tag = w_tag;
              wRow.has_website = Boolean(wRow.website && wRow.website !== 'N/A');
              wRow.has_email = has_e;
              wRow.has_socials = has_s;

              if (typeof window.updateOrPrependLiveRow === 'function') {
                window.updateOrPrependLiveRow('maps', target || uData);
                window.updateOrPrependLiveRow('website', wRow);
                window.updateOrPrependLiveRow('master', target || uData);
              } else if (typeof window.renderTable === 'function') {
                window.renderTable();
              }
              updateKPIs();
            } else if (msg.type === 'platform_listing_found' || msg.type === 'platform_listing_saved') {
              const listing = msg.data || {};
              const titleVal = listing.title || listing.name || listing.company_name || 'Listing';
              const urlVal = listing.url || listing.listing_url || listing.booking_url || '';
              const rCount = listing.reviews_count || listing.review_count || listing.reviews || 0;
              const ratVal = listing.rating || 0;

              const newPlatRow = {
                id: listing.id || (placesData.length + 1),
                lead_id: listing.lead_id || null,
                platform: listing.platform || 'Platform',
                platform_name: listing.platform || 'Platform',
                title: titleVal,
                name: titleVal,
                clean_brand: listing.clean_brand || titleVal,
                category: listing.category || 'Listing',
                url: urlVal,
                listing_url: urlVal,
                booking_url: listing.booking_url || urlVal,
                rating: ratVal,
                reviews_count: rCount,
                reviews: rCount,
                price_info: listing.price_info || listing.price_range || '',
                address: listing.address || "Area Proximity",
                email: listing.email || (listing.emails && listing.emails[0]) || '',
                emails_json: listing.emails ? JSON.stringify(listing.emails) : (listing.emails_json || '[]'),
                phone: listing.phone || (listing.phones && listing.phones[0]) || '',
                website: listing.website || '',
                maps_url: listing.maps_url || '',
                instagram: listing.instagram || '',
                facebook: listing.facebook || '',
                linkedin: listing.linkedin || '',
                twitter: listing.twitter || '',
                youtube: listing.youtube || '',
                tiktok: listing.tiktok || '',
                whatsapp: listing.whatsapp || '',
                bot_protection: listing.bot_protection || 'Clean',
                cookie_status: listing.cookie_status || 'None',
                website_status: listing.website_status || 'contacts_found',
                screenshot: listing.screenshot || "",
                verified: listing.verified ? 1 : 0,
                created_at: listing.created_at || new Date().toISOString()
              };

              const target = placesData.find(p => p.name === titleVal || (listing.lead_id && p.id === listing.lead_id) || (listing.matched_lead_id && p.id === listing.matched_lead_id));
              if (target) {
                target.platform_name = listing.platform;
                target.platform_url = urlVal;
                target.platform_rating = ratVal;
                target.platform_reviews = rCount;
                target.booking_url = listing.booking_url || urlVal;
                target.platform_price = listing.price_info || listing.price_range || '';
                target.platform_verified = 1;
              }

              if (typeof window.updateOrPrependLiveRow === 'function') {
                window.updateOrPrependLiveRow('platform', newPlatRow);
                if (target) {
                  window.updateOrPrependLiveRow('master', target);
                }
              } else if (typeof window.renderTable === 'function') {
                window.renderTable();
              }
              updateKPIs();
            } else if (msg.type === 'org_updated') {
              const oData = msg.data;
              const compName = (oData.company || '').toLowerCase().trim();
              const target = placesData.find(p => p.name.toLowerCase().trim() === compName);
              if (target) {
                target.employee_count = oData.employee_count;
                if (oData.linkedin_url) target.linkedin = oData.linkedin_url;
                if (!oData.id && target.id) oData.id = target.id;
              }

              const empCount = parseInt(oData.employee_count || 0);
              const li_tag = empCount > 0 ? "Employees Crawled" : (oData.linkedin_url ? "LinkedIn Found" : "Not Found on LinkedIn");

              const liRow = Object.assign({}, target || { name: oData.company, address: "N/A", category: "Business" });
              liRow.id = oData.id || (target ? target.id : undefined);
              liRow.employee_count = oData.employee_count;
              if (oData.linkedin_url) liRow.linkedin = oData.linkedin_url;
              liRow.status_tag = li_tag;
              liRow.has_linkedin = Boolean(liRow.linkedin && liRow.linkedin !== 'N/A');
              liRow.has_employees = empCount > 0;

              if (typeof window.updateOrPrependLiveRow === 'function') {
                window.updateOrPrependLiveRow('linkedin', liRow);
                if (target) {
                  window.updateOrPrependLiveRow('maps', target);
                  window.updateOrPrependLiveRow('master', target);
                }
              } else if (typeof window.renderTable === 'function') {
                window.renderTable();
              }
              updateKPIs();
            } else if (msg.type === 'status') {
              if (!isActionPending) {
                const terminalStatuses = ['Finished', 'Ready', 'Stopped', 'Idle', 'Failed', 'Failed to launch'];
                const isTerminal = terminalStatuses.includes(msg.data);
                setScrapingState(!isTerminal, msg.data);
              }
            } else if (msg.type === 'job_finished') {
              isActionPending = false;
              setScrapingState(false, 'Finished');
            } else if (msg.type === 'log') {
              logMessage(msg.data, msg.time, msg.agent);
            } else if (msg.type === 'logs_cleared') {
              clearTerminalBox();
            } else if (msg.type === 'db_cleared') {
              placesData = [];
              if (window.tablesSplitData) {
                window.tablesSplitData.master_leads = [];
                window.tablesSplitData.unmatched_maps = [];
                window.tablesSplitData.unmatched_platform = [];
                window.tablesSplitData.website_leads = [];
                window.tablesSplitData.linkedin_leads = [];
              }
              renderTable();
              updateKPIs();
            }
          } catch (e) {}
        };
        ws.onclose = () => {
          setTimeout(connectWebSocket, 2000);
        };
      } catch (err) {}
    }

    async function pollStatus() {
      if (isActionPending) return;
      try {
        const resp = await fetch('/api/status');
        if (!resp.ok) return;
        const data = await resp.json();

        if (!isActionPending) {
          setScrapingState(data.is_scraping, data.status);
        }

        if (data.frame_maps) updateLiveStream(data.frame_maps);
        if (data.frame_website) updateLiveStream(data.frame_website);
        if (data.frame_linkedin) updateLiveStream(data.frame_linkedin);
        if (data.frame_platform) updateLiveStream(data.frame_platform);
        if (!data.is_scraping && (data.status === 'Finished' || data.status === 'Ready')) {
          const indMaps = document.getElementById('stream-indicator-maps');
          if (indMaps && !indMaps.innerText.includes('IDLE')) {
            indMaps.className = 'live-indicator';
            indMaps.innerText = '⚪ MAPS IDLE';
          }
          const indSite = document.getElementById('stream-indicator-website');
          if (indSite && !indSite.innerText.includes('IDLE')) {
            indSite.className = 'live-indicator website';
            indSite.innerText = '⚪ WEBSITE IDLE';
          }
          const indLi = document.getElementById('stream-indicator-linkedin');
          if (indLi && !indLi.innerText.includes('IDLE')) {
            indLi.className = 'live-indicator linkedin';
            indLi.innerText = '⚪ LINKEDIN IDLE';
          }
          const indPlat = document.getElementById('stream-indicator-platform');
          if (indPlat && !indPlat.innerText.includes('IDLE')) {
            indPlat.className = 'live-indicator platform';
            indPlat.innerText = '⚪ PLATFORM IDLE';
          }
        }

        if (data.places && (data.places.length !== placesData.length || JSON.stringify(data.places) !== JSON.stringify(placesData))) {
          placesData = data.places;
          renderTable();
          updateKPIs();
        }

        if (data.logs && Array.isArray(data.logs)) {
          syncLogsFromPoll(data.logs);
        }
      } catch (err) {
        console.error("Poll error:", err);
      }
    }

    async function startScraping() {
      if (isActionPending) return;
      isActionPending = true;
      try {
        const visibleBrowser = document.getElementById('visible-browser-toggle').checked;

        if (currentMode === 'website_list') {
          await startWebsiteListScraping();
          return;
        }

        if (currentMode === 'companies') {
          const companies = document.getElementById('companies-input').value.trim();
          if (!companies) {
            alert("Please enter at least one company name to search on LinkedIn.");
            return;
          }

          setScrapingState(true, "Launching Tab 3 for LinkedIn Intelligence...");
          logMessage(`🏢 Launching Standalone LinkedIn Org Harvester for: "${companies}"...`);

          try {
            const resp = await fetch('/api/start-companies', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                companies: companies,
                visible_browser: visibleBrowser
              })
            });
            let res = {};
            const text = await resp.text();
            try { res = JSON.parse(text); } catch (_) { res = { detail: text || ("Status " + resp.status) }; }
            if (!resp.ok) {
              alert(res.detail || "Error starting company harvester");
              setScrapingState(false, "Ready");
            } else if (res.status === 'already_running') {
              logMessage("ℹ️ Scraper is already active in background. Click 'Stop' if you wish to restart.");
              setScrapingState(true, "Live Agent Running");
              setTimeout(pollStatus, 300);
            } else {
              setTimeout(pollStatus, 300);
            }
          } catch (err) {
            alert("Error connecting to server: " + err.message);
            setScrapingState(false, "Ready");
          }
          return;
        }

        // Maps / Multi-Agent Mode
        let query = document.getElementById('query-input').value.trim();
        const scrapeAll = document.getElementById('scrape-all-toggle').checked;
        if (!query || ['all', 'all businesses', 'all shops', '*', 'shop', 'shops', 'places'].includes(query.toLowerCase())) {
          query = "businesses";
        }

        let rawMax = parseInt(document.getElementById('max-slider')?.value || 20);
        const maxResults = (scrapeAll || isInfinityMode || rawMax >= 500) ? 999999 : rawMax;
        const lat = parseFloat(document.getElementById('lat-input').value);
        const lon = parseFloat(document.getElementById('lon-input').value);

        const locationVal = document.getElementById('location-search-input')?.value.trim() || "Mumbai";
        const radiusKm = parseFloat(document.getElementById('radius-slider').value) || 5.0;
        // Strictly block Maps, Website, and LinkedIn agents in this setup
        const agentMaps = false;
        const agentWebsite = false;
        const agentLinkedin = false;
        const agentPlatform = true;
        const selectedPlatforms = getSelectedPlatforms();
        const platformName = selectedPlatforms[0] || "Fresha";
        const platformCustomUrl = document.getElementById('platform-custom-url')?.value.trim() || "";
        const dedupArea = document.getElementById('dedup-area-toggle').checked;
        const skipExisting = document.getElementById('skip-existing-toggle').checked;

        if (!agentPlatform) {
          alert("Platform Directory Scout is required to start scraping!");
          isActionPending = false;
          return;
        }

        setScrapingState(true, "Launching Chrome window...");
        setTimeout(() => { isActionPending = false; }, 400);

        if (visibleBrowser) {
          try {
            const chk = await fetch('/api/chrome/status');
            const cData = await chk.json();
            if (cData.extension_active) {
              logMessage("⚡ Chrome Extension active: Agent tabs will open directly inside this Chrome profile.");
            } else if (cData.cdp_active) {
              logMessage("⚡ Remote Debugging active on Port 9222.");
            } else {
              const proceed = confirm(
                "⚠️ Chrome Extension is NOT connected to :8085!\n\n" +
                "To see tabs LIVE in front of you:\n" +
                "1. Open chrome://extensions in Chrome\n" +
                "2. Turn on Developer Mode (top-right)\n" +
                "3. Click 'Load unpacked' and select:\n" +
                "   c:\\Projects\\Data Scrapper\\1_Linkedin_Platforms\\apps\\extension\n" +
                "4. Check that the extension icon badge says 'ON'\n\n" +
                "Click CANCEL to connect the extension first (recommended),\n" +
                "or click OK to proceed with local background worker."
              );
              if (!proceed) {
                setScrapingState(false, "Ready");
                isActionPending = false;
                return;
              }
              logMessage("⚠️ Proceeding with local background worker without extension.");
            }
          } catch (e) {}
        }
        const parts = [];
        if (agentMaps) parts.push("Maps");
        if (agentWebsite) parts.push("Website");
        if (agentLinkedin) parts.push("LinkedIn");
        if (agentPlatform) {
          const platsStr = (selectedPlatforms && selectedPlatforms.length > 0) ? selectedPlatforms.join(', ') : platformName;
          parts.push(`Platform (${platsStr})`);
        }
        logMessage(`🚀 Launching Chrome Live Agents [${parts.join(' + ')}] for: "${query}" (Radius: ${radiusKm}km, Continuous: ${scrapeAll})...`);

        if (typeof window.switchTableTab === 'function') {
          if (agentMaps) window.switchTableTab('maps');
          else if (agentPlatform) window.switchTableTab('platform');
          else if (agentWebsite) window.switchTableTab('website');
          else if (agentLinkedin) window.switchTableTab('linkedin');
        }

        try {
          const resp = await fetch('/api/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: query,
              location: locationVal,
              max_results: maxResults,
              scrape_all: scrapeAll,
              visible_browser: visibleBrowser,
              extract_emails: agentWebsite,
              lat: lat,
              lon: lon,
              zoom: 14,
              radius_km: radiusKm,
              enable_maps: agentMaps,
              enable_website: agentWebsite,
              enable_linkedin: agentLinkedin,
              enable_platform: agentPlatform,
              platforms: selectedPlatforms,
              platform_name: platformName,
              platform_custom_url: platformCustomUrl,
              dedup_area: dedupArea,
              skip_existing_db: skipExisting
            })
          });
          let res = {};
          const text = await resp.text();
          try { res = JSON.parse(text); } catch (_) { res = { detail: text || ("Status " + resp.status) }; }
          if (!resp.ok) {
            alert(res.detail || "Error starting scraper");
            setScrapingState(false, "Ready");
          } else if (res.status === 'already_running') {
            logMessage("ℹ️ Scraper is already active in background. Click 'Stop' if you wish to restart.");
            setScrapingState(true, "Live Agent Running");
            setTimeout(pollStatus, 300);
          } else {
            setTimeout(pollStatus, 300);
          }
        } catch (err) {
          alert("Error connecting to server: " + err.message);
          setScrapingState(false, "Ready");
        }
      } finally {
        isActionPending = false;
      }
    }

    async function stopScraping() {
      if (isActionPending) return;
      isActionPending = true;
      const stopBtn = document.getElementById('stop-btn');
      if (stopBtn) {
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<span>⏳ Stopping...</span>';
      }
      try {
        const resp = await fetch('/api/stop', { method: 'POST' });
        const res = await resp.json().catch(() => ({}));
        if (res.status === 'stopping') {
          logMessage("⏹️ Stop requested: Gracefully completing current website before stopping...");
          const st = document.getElementById('status-text');
          if (st) st.innerText = "Stopping gracefully...";
        } else {
          setScrapingState(false, "Stopped");
          logMessage("⏹️ Scraping stopped.");
        }
      } catch (e) {
        console.error(e);
        setScrapingState(false, "Stopped");
      } finally {
        isActionPending = false;
      }
    }

    async function clearDb() {
      if (confirm("Are you sure you want to clear the leads database, employee records, and map pins?")) {
        await fetch('/api/clear', { method: 'POST' });
        placesData = [];
        renderTable();
        updateKPIs();
        logMessage("🗑️ Database and map markers cleared.");
      }
    }

    async function renumberDatabase() {
      try {
        logMessage("🔢 Re-indexing database sequentially & cleaning tags...");
        const resp = await fetch('/api/renumber', { method: 'POST' });
        const res = await resp.json();
        if (resp.ok) {
          placesData = res.places || [];
          renderTable();
          updateKPIs();
          logMessage(`✅ Successfully renumbered ${res.info ? res.info.leads_renumbered : placesData.length} leads sequentially (1..${placesData.length}) and cleaned bot tags!`);
        } else {
          alert("Error renumbering database: " + (res.detail || "Unknown error"));
        }
      } catch (err) {
        alert("Failed to renumber database: " + err.message);
      }
    }

    async function checkChromeDebugStatus() {
      const btn = document.getElementById('btn-chrome-cdp');
      const text = document.getElementById('chrome-cdp-text');
      const attachBtn = document.getElementById('btn-attach-primary-chrome');
      if (!btn || !text) return;

      try {
        const resp = await fetch('/api/chrome/status');
        const data = await resp.json();
        if (data.extension_active) {
          btn.className = 'btn-chrome-pill';
          text.innerText = 'Connected: Extension (:8085)';
          btn.title = 'DataScrapper Chrome Assistant is connected via WebSocket! Directory and LinkedIn tabs bridge directly here.';
          if (attachBtn) attachBtn.style.display = 'none';
        } else if (data.active && data.is_primary) {
          btn.className = 'btn-chrome-pill';
          text.innerText = 'Connected: Chrome (Port 9222)';
          btn.title = 'Scraper is attached to this Chrome window via CDP Port 9222.';
          if (attachBtn) attachBtn.style.display = 'none';
        } else if (data.active && !data.is_primary) {
          btn.className = 'btn-chrome-pill';
          text.innerText = 'Chrome CDP (Port 9222)';
          btn.title = 'Port 9222 is currently bound to a separate ChromeAutomation window.';
        } else {
          btn.className = 'btn-chrome-pill disconnected';
          text.innerText = 'Extension Standby';
          btn.title = 'Click to see how to connect the DataScrapper Chrome Assistant or attach Port 9222.';
          if (attachBtn) attachBtn.style.display = 'inline-flex';
        }
      } catch (e) {
        btn.className = 'btn-chrome-pill disconnected';
        text.innerText = 'Extension Standby';
      }
    }

    async function attachPrimaryChrome(confirmed = false) {
      if (!confirmed) {
        const ok = confirm(
          "⚡ Connect This Chrome Window (Port 9222)?\n\n" +
          "This restarts Google Chrome with Remote Debugging enabled on your active personal profile.\n" +
          "• All your existing open tabs and logins will be restored automatically.\n" +
          "• Directory and scraper tabs will open directly in this window.\n\n" +
          "Alternatively, you can simply load the unpacked extension from apps/extension without restarting Chrome!\n\n" +
          "Click OK to proceed with Port 9222 restart, or Cancel to use the Extension."
        );
        if (!ok) return;
      }

      logMessage("🔄 Restarting Chrome on Port 9222 attached to your active profile...");
      try {
        const resp = await fetch('/api/chrome/restart-with-debug', { method: 'POST' });
        const res = await resp.json();
        logMessage(`✅ ${res.message || 'Chrome restarted on Port 9222!'}`);
      } catch (err) {
        logMessage("⏳ Chrome restarting with Port 9222... please wait 2 seconds.");
      }
    }

    async function promptOrLaunchChromeDebug() {
      try {
        const resp = await fetch('/api/chrome/status');
        const data = await resp.json();
        if (data.extension_active) {
          alert("✅ DataScrapper Chrome Assistant is ACTIVE and connected on port 8085!\nTabs and scraper sessions bridge directly into this window.");
        } else if (data.active) {
          alert("✅ Chrome Remote Debugging (Port 9222) is ACTIVE.\nScraper commands attach directly to this Chrome process.");
        } else {
          alert(
            "🔌 Chrome Connection Options for 1_Linkedin_Platforms:\n\n" +
            "OPTION 1 (Recommended - Chrome Extension):\n" +
            "1. Open chrome://extensions in Chrome\n" +
            "2. Turn ON 'Developer mode' (top-right)\n" +
            "3. Click 'Load unpacked' (top-left)\n" +
            "4. Select: c:\\Projects\\Data Scrapper\\1_Linkedin_Platforms\\apps\\extension\n" +
            "5. The extension connects automatically to :8085 without restarting your browser!\n\n" +
            "OPTION 2 (Optional - Chrome Port 9222):\n" +
            "Click '⚡ Use This Chrome (Port 9222)' to restart Chrome with --remote-debugging-port=9222."
          );
        }
      } catch (e) {
        logMessage("ℹ️ Chrome assistant ready.");
      }
    }

    function exportCSV() { window.location.href = '/api/export/csv'; }
    function exportJSON() { window.location.href = '/api/export/json'; }

    window.addEventListener('DOMContentLoaded', () => {
      initMap();
      handlePlatformToggleChange();
      handleAgentToggleChange();
      connectWebSocket();
      pollStatus();
      pollInterval = setInterval(pollStatus, 1200);
      checkChromeDebugStatus();
      setInterval(checkChromeDebugStatus, 3500);
      window.addEventListener('mavon_extension_ready', checkChromeDebugStatus);
      window.addEventListener('resize', () => {
        if (leafletMap) leafletMap.invalidateSize();
      });
    });
