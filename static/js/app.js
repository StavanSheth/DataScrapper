let placesData = [];
    let isRunning = false;
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
      const mapsControls = document.getElementById('controls-maps');
      const compControls = document.getElementById('controls-companies');
      const startBtn = document.getElementById('start-btn');

      if (mode === 'maps') {
        mapsTab.classList.add('active');
        compTab.classList.remove('active');
        mapsControls.style.display = 'flex';
        compControls.style.display = 'none';
        startBtn.className = 'btn btn-primary';
        startBtn.innerHTML = '<span>🚀 Start Maps Agent</span>';
        setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 200);
      } else {
        compTab.classList.add('active');
        mapsTab.classList.remove('active');
        mapsControls.style.display = 'none';
        compControls.style.display = 'flex';
        startBtn.className = 'btn btn-linkedin-theme';
        startBtn.innerHTML = '<span>💼 Launch LinkedIn Org Harvester</span>';
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
      const mapsOn = document.getElementById('agent-maps-toggle')?.checked || false;
      const siteOn = document.getElementById('agent-website-toggle')?.checked || false;
      const liOn = document.getElementById('agent-linkedin-toggle')?.checked || false;
      const platOn = document.getElementById('agent-platform-toggle')?.checked || false;
      const startBtn = document.getElementById('start-btn');

      // Update live stream viewports to visibly show ONLY active enabled agents
      const cardMaps = document.getElementById('card-maps');
      const cardSite = document.getElementById('card-website');
      const cardLi = document.getElementById('card-linkedin');
      const cardPlat = document.getElementById('card-platform');

      if (cardMaps) cardMaps.style.display = mapsOn ? 'flex' : 'none';
      if (cardSite) cardSite.style.display = siteOn ? 'flex' : 'none';
      if (cardLi) cardLi.style.display = liOn ? 'flex' : 'none';
      if (cardPlat) cardPlat.style.display = platOn ? 'flex' : 'none';

      if (!mapsOn && !siteOn && !liOn && !platOn) {
        alert("Warning: At least one agent must be enabled!");
        document.getElementById('agent-maps-toggle').checked = true;
        if (cardMaps) cardMaps.style.display = 'flex';
        return;
      }

      const parts = [];
      if (mapsOn) parts.push("Maps");
      if (siteOn) parts.push("Website");
      if (liOn) parts.push("LinkedIn");
      if (platOn) {
        const plats = getSelectedPlatforms();
        parts.push(plats.join(' & '));
      }

      if (startBtn && currentMode === 'maps') {
        startBtn.innerHTML = `<span>🚀 Launch Agent (${parts.join(' + ')})</span>`;
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
      if (v >= 500) {
        isInfinityMode = true;
        if (maxLabel) maxLabel.innerHTML = '∞ <span style="font-size:0.75rem; color:#a5b4fc;">(Unlimited / Infinity)</span>';
      } else {
        isInfinityMode = false;
        if (maxLabel) maxLabel.innerText = v;
      }
    }

    function setMaxLimit(val) {
      const scrapeAll = document.getElementById('scrape-all-toggle')?.checked;
      if (scrapeAll) {
        // If scrape all is active, notify user it is already infinite
        logMessage("ℹ️ 'Scrape ALL Shops (Continuous)' is ON: Scraper will already harvest all places without limits.");
        return;
      }
      const slider = document.getElementById('max-slider');
      const maxLabel = document.getElementById('max-label');
      if (val === 'infinity') {
        isInfinityMode = true;
        if (slider) slider.value = 500;
        if (maxLabel) maxLabel.innerHTML = '∞ <span style="font-size:0.75rem; color:#a5b4fc;">(Unlimited / Infinity)</span>';
        logMessage("♾️ Max Places Limit set to Unlimited / Infinity.");
      } else {
        isInfinityMode = false;
        if (slider) slider.value = val;
        if (maxLabel) maxLabel.innerText = val;
        logMessage(`🎯 Max Places Limit set to ${val} places.`);
      }
    }

    function toggleInfinityMode() {
      const scrapeAll = document.getElementById('scrape-all-toggle')?.checked;
      if (scrapeAll) return;
      if (isInfinityMode) {
        setMaxLimit(20);
      } else {
        setMaxLimit('infinity');
      }
    }

    // Toggle All Shops
    document.getElementById('scrape-all-toggle').addEventListener('change', function(e) {
      const group = document.getElementById('max-results-group');
      const qInput = document.getElementById('query-input');
      const maxLabel = document.getElementById('max-label');
      const slider = document.getElementById('max-slider');
      if (e.target.checked) {
        group.style.opacity = '0.7';
        group.style.pointerEvents = 'none';
        if (maxLabel) maxLabel.innerHTML = '∞ <span style="font-size:0.75rem; color:#a5b4fc;">(Continuous - Scraping ALL Area Shops)</span>';
        qInput.placeholder = 'All Shops in Selected Area (No keyword needed)';
        isInfinityMode = true;
      } else {
        group.style.opacity = '1';
        group.style.pointerEvents = 'auto';
        const v = parseInt(slider?.value || 20);
        if (v >= 500) {
          isInfinityMode = true;
          if (maxLabel) maxLabel.innerHTML = '∞ <span style="font-size:0.75rem; color:#a5b4fc;">(Unlimited / Infinity)</span>';
        } else {
          isInfinityMode = false;
          if (maxLabel) maxLabel.innerText = v;
        }
        qInput.placeholder = 'e.g. Barber, Bakery, Dentist';
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

    function logMessage(msg) {
      const box = document.getElementById('terminal-box');
      const time = new Date().toLocaleTimeString();
      const line = document.createElement('div');
      line.className = 'log-line';
      line.innerHTML = `<span class="log-time">[${time}]</span> <span>${escapeHtml(msg)}</span>`;
      box.appendChild(line);
      box.scrollTop = box.scrollHeight;
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
      isRunning = running;
      document.getElementById('start-btn').style.display = running ? 'none' : 'flex';
      document.getElementById('stop-btn').style.display = running ? 'flex' : 'none';
      const dot = document.getElementById('status-dot');
      if (running) {
        dot.classList.add('active');
        document.getElementById('status-text').innerText = statusText || "Live Agent Running";
      } else {
        dot.classList.remove('active');
        document.getElementById('status-text').innerText = statusText || "Ready";
      }
    }

    function updateLiveStream(frame) {
      if (!frame || !frame.image) return;
      let prefix = 'maps';
      let indicatorClass = 'live-indicator maps';
      let indicatorText = '🔴 TAB 1: MAPS LIVE';

      if (frame.tab === 'platform' || frame.is_platform) {
        prefix = 'platform';
        indicatorClass = 'live-indicator platform';
        indicatorText = '🟣 TAB 4: DIRECTORY LIVE';
      } else if (frame.tab === 'linkedin' || frame.is_linkedin) {
        prefix = 'linkedin';
        indicatorClass = 'live-indicator linkedin';
        indicatorText = '🔵 TAB 3: LINKEDIN LIVE';
      } else if (frame.tab === 'website' || frame.is_website) {
        prefix = 'website';
        indicatorClass = 'live-indicator website';
        indicatorText = '🟢 TAB 2: SHOP LIVE';
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
              if (window.tablesSplitData && Array.isArray(window.tablesSplitData.unmatched_maps)) {
                const exists = window.tablesSplitData.unmatched_maps.some(p => (place.id && p.id === place.id) || (p.name === place.name && p.address === place.address));
                if (!exists) {
                  const mRow = Object.assign({}, place);
                  const has_w = Boolean(mRow.website && mRow.website !== 'N/A' && mRow.website !== '');
                  const has_p = Boolean(mRow.phone && mRow.phone !== 'N/A' && mRow.phone !== '');
                  mRow.has_website = has_w;
                  mRow.has_phone = has_p;
                  mRow.status_tag = (has_w && has_p) ? "Full Contact (Web & Phone)" : (has_w ? "Has Website" : (has_p ? "Phone Only" : "Location Only"));
                  window.tablesSplitData.unmatched_maps.unshift(mRow);
                  const bMaps = document.getElementById('badge-count-maps');
                  if (bMaps) bMaps.innerText = window.tablesSplitData.unmatched_maps.length;
                }
              }
              if (place.platform_verified || (place.platform_name && place.platform_name !== 'N/A')) {
                if (window.tablesSplitData && Array.isArray(window.tablesSplitData.master_leads)) {
                  const existsM = window.tablesSplitData.master_leads.some(p => (place.id && p.id === place.id) || p.name === place.name);
                  if (!existsM) {
                    window.tablesSplitData.master_leads.unshift(Object.assign({}, place));
                    const bMaster = document.getElementById('badge-count-master');
                    if (bMaster) bMaster.innerText = window.tablesSplitData.master_leads.length;
                  }
                }
              }
              if (typeof window.renderTable === 'function') window.renderTable();
              updateKPIs();
            } else if (msg.type === 'place_updated') {
              const uData = msg.data;
              const target = placesData.find(p => (uData.id && p.id === uData.id) || (p.name === uData.name && (p.address === uData.address || p.address === 'N/A' || uData.address === 'N/A')));
              if (target) {
                Object.assign(target, uData);
              } else {
                placesData.unshift(uData);
              }

              if (window.tablesSplitData) {
                // Update Table 2 (Maps)
                if (Array.isArray(window.tablesSplitData.unmatched_maps)) {
                  const mMap = window.tablesSplitData.unmatched_maps.find(p => (uData.id && p.id === uData.id) || (p.name === uData.name && (p.address === uData.address || p.address === 'N/A' || uData.address === 'N/A')));
                  if (mMap) Object.assign(mMap, uData);
                }

                // Update Table 3 (Website Leads - live add or update upon inspection!)
                if (!Array.isArray(window.tablesSplitData.website_leads)) {
                  window.tablesSplitData.website_leads = [];
                }
                const wList = window.tablesSplitData.website_leads;
                const wTarget = wList.find(p => (uData.id && p.id === uData.id) || (p.name === uData.name && (p.address === uData.address || p.address === 'N/A' || uData.address === 'N/A')));

                let w_tag = "Website Found";
                const has_e = Boolean(uData.email && uData.email !== 'N/A');
                const has_s = Boolean(uData.instagram || uData.facebook || uData.twitter);
                const bot = uData.bot_protection || "";
                if (has_e) w_tag = "Emails Extracted";
                else if (has_s) w_tag = "Socials Found";
                else if (bot.includes("Denied") || bot.includes("Captcha")) w_tag = "Bot Shielded";
                else if (uData.website_status === "failed") w_tag = "Website Unreachable";
                else if (uData.website_status === "social") w_tag = "Social Profile";

                if (wTarget) {
                  Object.assign(wTarget, uData);
                  wTarget.status_tag = w_tag;
                } else {
                  const newWRow = Object.assign({}, target || uData);
                  Object.assign(newWRow, uData);
                  newWRow.status_tag = w_tag;
                  newWRow.has_website = Boolean(newWRow.website && newWRow.website !== 'N/A');
                  newWRow.has_email = has_e;
                  newWRow.has_socials = has_s;
                  wList.unshift(newWRow);
                }
                const bWeb = document.getElementById('badge-count-website');
                if (bWeb) bWeb.innerText = wList.length;

                // Update Table 1 (Master Leads)
                if (Array.isArray(window.tablesSplitData.master_leads)) {
                  const mTarget = window.tablesSplitData.master_leads.find(p => (uData.id && p.id === uData.id) || (p.name === uData.name && (p.address === uData.address || p.address === 'N/A' || uData.address === 'N/A')));
                  if (mTarget) Object.assign(mTarget, uData);
                }
              }
              if (typeof window.renderTable === 'function') window.renderTable();
              updateKPIs();
            } else if (msg.type === 'platform_listing_found') {
              const listing = msg.data;
              const target = placesData.find(p => p.name === listing.company_name || (listing.lead_id && p.id === listing.lead_id));
              if (target) {
                target.platform_name = listing.platform;
                target.platform_url = listing.listing_url;
                target.platform_rating = listing.rating;
                target.platform_reviews = listing.review_count;
                target.booking_url = listing.booking_url;
                target.platform_price = listing.price_range;
                target.platform_verified = 1;
              }

              if (window.tablesSplitData) {
                // Update Table 5 (Platform Directory)
                if (!Array.isArray(window.tablesSplitData.unmatched_platform)) {
                  window.tablesSplitData.unmatched_platform = [];
                }
                const pList = window.tablesSplitData.unmatched_platform;
                const pExists = pList.some(p => (p.url && p.url === listing.listing_url) || (p.title === listing.company_name && p.platform === listing.platform));
                if (!pExists) {
                  const newPlatRow = {
                    id: listing.id || (pList.length + 1),
                    platform: listing.platform,
                    platform_name: listing.platform,
                    title: listing.company_name,
                    name: listing.company_name,
                    url: listing.listing_url,
                    listing_url: listing.listing_url,
                    booking_url: listing.booking_url,
                    rating: listing.rating,
                    reviews_count: listing.review_count,
                    reviews: listing.review_count,
                    price_info: listing.price_range,
                    price_range: listing.price_range,
                    address: listing.address || "Area Proximity",
                    screenshot: listing.screenshot || "",
                    verified: listing.verified ? 1 : 0,
                    created_at: new Date().toISOString()
                  };
                  pList.unshift(newPlatRow);
                  const bPlat = document.getElementById('badge-count-platform');
                  if (bPlat) bPlat.innerText = pList.length;
                }

                // Update Table 1 (Master Leads - cross verified)
                if (target && Array.isArray(window.tablesSplitData.master_leads)) {
                  const mList = window.tablesSplitData.master_leads;
                  const mTarget = mList.find(p => p.name === target.name || (target.id && p.id === target.id));
                  if (mTarget) {
                    Object.assign(mTarget, target);
                  } else {
                    mList.unshift(Object.assign({}, target));
                    const bMaster = document.getElementById('badge-count-master');
                    if (bMaster) bMaster.innerText = mList.length;
                  }
                }
                // Update Table 2 (Maps)
                if (target && Array.isArray(window.tablesSplitData.unmatched_maps)) {
                  const mMap = window.tablesSplitData.unmatched_maps.find(p => p.name === target.name || (target.id && p.id === target.id));
                  if (mMap) Object.assign(mMap, target);
                }
              }
              if (typeof window.renderTable === 'function') window.renderTable();
              updateKPIs();
            } else if (msg.type === 'org_updated') {
              const oData = msg.data;
              const compName = (oData.company || '').toLowerCase().trim();
              const target = placesData.find(p => p.name.toLowerCase().trim() === compName);
              if (target) {
                target.employee_count = oData.employee_count;
                if (oData.linkedin_url) target.linkedin = oData.linkedin_url;
              }

              if (window.tablesSplitData) {
                // Update Table 4 (LinkedIn Harvester)
                if (!Array.isArray(window.tablesSplitData.linkedin_leads)) {
                  window.tablesSplitData.linkedin_leads = [];
                }
                const liList = window.tablesSplitData.linkedin_leads;
                const liTarget = liList.find(p => (p.name || '').toLowerCase().trim() === compName);

                const empCount = parseInt(oData.employee_count || 0);
                const li_tag = empCount > 0 ? "Employees Crawled" : (oData.linkedin_url ? "LinkedIn Found" : "Not Found on LinkedIn");

                if (liTarget) {
                  liTarget.employee_count = oData.employee_count;
                  if (oData.linkedin_url) liTarget.linkedin = oData.linkedin_url;
                  liTarget.status_tag = li_tag;
                  liTarget.has_linkedin = Boolean(liTarget.linkedin && liTarget.linkedin !== 'N/A');
                  liTarget.has_employees = empCount > 0;
                } else {
                  const baseLead = target || { name: oData.company, address: "N/A", category: "Business" };
                  const newLiRow = Object.assign({}, baseLead);
                  newLiRow.employee_count = oData.employee_count;
                  if (oData.linkedin_url) newLiRow.linkedin = oData.linkedin_url;
                  newLiRow.status_tag = li_tag;
                  newLiRow.has_linkedin = Boolean(newLiRow.linkedin && newLiRow.linkedin !== 'N/A');
                  newLiRow.has_employees = empCount > 0;
                  liList.unshift(newLiRow);
                }
                const bLi = document.getElementById('badge-count-linkedin');
                if (bLi) bLi.innerText = liList.length;

                // Update Master & Maps
                ['master_leads', 'unmatched_maps'].forEach(key => {
                  const list = window.tablesSplitData[key];
                  if (Array.isArray(list)) {
                    const row = list.find(p => (p.name || '').toLowerCase().trim() === compName);
                    if (row) {
                      row.employee_count = oData.employee_count;
                      if (oData.linkedin_url) row.linkedin = oData.linkedin_url;
                    }
                  }
                });
              }
              if (typeof window.renderTable === 'function') window.renderTable();
              updateKPIs();
            } else if (msg.type === 'status') {
              setScrapingState(msg.data !== 'Finished' && msg.data !== 'Ready', msg.data);
            } else if (msg.type === 'log') {
              logMessage(msg.data);
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
      try {
        const resp = await fetch('/api/status');
        if (!resp.ok) return;
        const data = await resp.json();

        setScrapingState(data.is_scraping, data.status);

        if (data.frame_maps) updateLiveStream(data.frame_maps);
        if (data.frame_website) updateLiveStream(data.frame_website);
        if (data.frame_linkedin) updateLiveStream(data.frame_linkedin);
        if (data.frame_platform) updateLiveStream(data.frame_platform);
        else if (data.live_frame) {
          updateLiveStream(data.live_frame);
        }
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

        if (data.logs && data.logs.length > 0) {
          const box = document.getElementById('terminal-box');
          const currentCount = box.children.length;
          if (data.logs.length + 1 > currentCount) {
            box.innerHTML = '';
            data.logs.forEach(item => {
              const line = document.createElement('div');
              line.className = 'log-line';
              line.innerHTML = `<span class="log-time">[Live]</span> <span>${escapeHtml(item.message)}</span>`;
              box.appendChild(line);
            });
            box.scrollTop = box.scrollHeight;
          }
        }
      } catch (err) {
        console.error("Poll error:", err);
      }
    }

    async function startScraping() {
      const visibleBrowser = document.getElementById('visible-browser-toggle').checked;

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

      const radiusKm = parseFloat(document.getElementById('radius-slider').value) || 5.0;
      const agentMaps = document.getElementById('agent-maps-toggle').checked;
      const agentWebsite = document.getElementById('agent-website-toggle').checked;
      const agentLinkedin = document.getElementById('agent-linkedin-toggle').checked;
      const agentPlatform = document.getElementById('agent-platform-toggle')?.checked || false;
      const selectedPlatforms = getSelectedPlatforms();
      const platformName = selectedPlatforms[0] || "Fresha";
      const platformCustomUrl = document.getElementById('platform-custom-url')?.value.trim() || "";
      const dedupArea = document.getElementById('dedup-area-toggle').checked;
      const skipExisting = document.getElementById('skip-existing-toggle').checked;

      if (!agentMaps && !agentWebsite && !agentLinkedin && !agentPlatform) {
        alert("Please enable at least one agent (Maps, Website, LinkedIn, or Platform) to start scraping!");
        return;
      }

      setScrapingState(true, "Launching Chrome window...");
      const parts = [];
      if (agentMaps) parts.push("Maps");
      if (agentWebsite) parts.push("Website");
      if (agentLinkedin) parts.push("LinkedIn");
      if (agentPlatform) parts.push(platformName);
      logMessage(`🚀 Launching Chrome Live Agents [${parts.join(' + ')}] for: "${query}" (Radius: ${radiusKm}km, Continuous: ${scrapeAll})...`);

      if (typeof window.switchTableTab === 'function' && window.currentTableTab === 'master') {
        const masterCount = (window.tablesSplitData && window.tablesSplitData.master_leads) ? window.tablesSplitData.master_leads.length : 0;
        if (masterCount === 0) {
          if (agentMaps) window.switchTableTab('maps');
          else if (agentPlatform) window.switchTableTab('platform');
          else if (agentWebsite) window.switchTableTab('website');
          else if (agentLinkedin) window.switchTableTab('linkedin');
        }
      }

      // Trigger Extension to open tabs live in this exact Chrome window ONLY for enabled agents
      try {
        const encoded = encodeURIComponent(query);
        const mapsUrl = (lat && lon)
          ? `https://www.google.com/maps/search/${encoded}/@${lat},${lon},14z?hl=en`
          : `https://www.google.com/maps/search/${encoded}?hl=en`;

      } catch (e) {}

      // If user wants visible browser, check if active Chrome port 9222 is available
      if (visibleBrowser) {
        let isCdpReady = false;
        try {
          const cdpCheck = await fetch('/api/chrome/status');
          const cdpJson = await cdpCheck.json();
          isCdpReady = Boolean(cdpJson && cdpJson.active);
        } catch (_) {}

        if (!isCdpReady) {
          const wantAttach = confirm(
            "Notice: Scraper is not yet attached to your active Chrome browser (Port 9222).\\n\\n" +
            "• Click OK to attach your active Chrome browser (restores all tabs & logins and runs the scraper inside your existing window).\\n" +
            "• Click Cancel to run in a separate dedicated Chrome window."
          );
          if (wantAttach) {
            try {
              const launchRes = await fetch('/api/chrome/launch', { method: 'POST' });
              const launchData = await launchRes.json();
              logMessage("🔗 " + (launchData.message || "Launching Chrome on port 9222 with session restore..."));
              await new Promise(r => setTimeout(r, 2000));
              await checkChromeDebugStatus();
            } catch (err) {
              console.warn("Could not launch Chrome on port 9222:", err);
            }
          }
        }
      }

      try {
        const resp = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: query,
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
        } else {
          setTimeout(pollStatus, 300);
        }
      } catch (err) {
        alert("Error connecting to server: " + err.message);
        setScrapingState(false, "Ready");
      }
    }

    async function stopScraping() {
      try {
        await fetch('/api/stop', { method: 'POST' });
        setScrapingState(false, "Stopped");
        logMessage("⏹️ Scraping stopped.");
      } catch (e) {
        console.error(e);
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
      if (!btn || !text) return;

      try {
        const resp = await fetch('/api/chrome/status');
        const data = await resp.json();
        if (data.active) {
          btn.className = 'btn-chrome-pill';
          text.innerText = 'Connected to Active Chrome (9222)';
          btn.title = 'Active Chrome connected on port 9222! Scraper will open tabs inside your existing browser window with all your logins.';
        } else {
          btn.className = 'btn-chrome-pill disconnected';
          text.innerText = 'Attach Active Chrome (Port 9222)';
          btn.title = 'Click to attach your open Chrome window on Port 9222 so all tabs and scraper agents run directly inside your existing browser!';
        }
      } catch (e) {
        btn.className = 'btn-chrome-pill disconnected';
        text.innerText = 'Attach Active Chrome (Port 9222)';
      }
    }

    async function promptOrLaunchChromeDebug() {
      const promptMsg = "To attach the scraper directly to your active Chrome browser (with your logins & tabs):\\n\\n" +
        "1. Chrome needs remote debugging on port 9222.\\n" +
        "2. Click OK to attempt launching Chrome on port 9222 now, or run start_chrome_debug.bat in the project folder.\\n\\n" +
        "Would you like to launch Chrome on port 9222 now?";
      const confirmLaunch = confirm(promptMsg);
      if (confirmLaunch) {
        try {
          const resp = await fetch('/api/chrome/launch', { method: 'POST' });
          const res = await resp.json();
          alert(res.message || "Chrome launched! Please wait a moment and check status.");
          setTimeout(checkChromeDebugStatus, 2500);
        } catch (e) {
          alert("Could not automatically launch Chrome: " + e.message + "\\nPlease run start_chrome_debug.bat from the project folder instead.");
        }
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
