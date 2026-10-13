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

      searchMarker = L.marker([lat, lon], { draggable: true, title: "Search Center Pin" }).addTo(leafletMap);
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

    function handleAgentToggleChange() {
      const mapsOn = document.getElementById('agent-maps-toggle').checked;
      const siteOn = document.getElementById('agent-website-toggle').checked;
      const liOn = document.getElementById('agent-linkedin-toggle').checked;
      const startBtn = document.getElementById('start-btn');

      if (!mapsOn && !siteOn && !liOn) {
        alert("Warning: At least one agent must be enabled!");
        document.getElementById('agent-maps-toggle').checked = true;
        return;
      }

      const parts = [];
      if (mapsOn) parts.push("Maps");
      if (siteOn) parts.push("Website");
      if (liOn) parts.push("LinkedIn");

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

    // Toggle All Shops
    document.getElementById('scrape-all-toggle').addEventListener('change', function(e) {
      const group = document.getElementById('max-results-group');
      const qInput = document.getElementById('query-input');
      if (e.target.checked) {
        group.style.opacity = '0.4';
        group.style.pointerEvents = 'none';
        qInput.placeholder = 'All Shops in Selected Area (No keyword needed)';
      } else {
        group.style.opacity = '1';
        group.style.pointerEvents = 'auto';
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

    function plotShopsOnMap() {
      if (!leafletMap || !placesLayer) return;
      placesLayer.clearLayers();
      markersMap = {};
      let plottedCount = 0;

      placesData.forEach((place, index) => {
        if (place.lat && place.lon) {
          plottedCount++;
          const popupContent = `
            <div style="font-family:'Inter',sans-serif; min-width:220px; line-height:1.4;">
              <strong style="color:#6366f1; font-size:1.05rem; display:block; margin-bottom:2px;">${escapeHtml(place.name)}</strong>
              <span style="font-size:0.8rem; background:rgba(99,102,241,0.15); color:#a5b4fc; padding:2px 6px; border-radius:4px; font-weight:600;">${escapeHtml(place.category || 'Business')}</span>
              ${place.rating && place.rating !== 'N/A' ? `<div style="margin-top:4px; font-size:0.85rem; color:#fbbf24; font-weight:600;">⭐ ${place.rating} (${place.reviews || '0'} reviews)</div>` : ''}
              ${place.address && place.address !== 'N/A' ? `<div style="margin-top:4px; font-size:0.8rem; color:#cbd5e1;">📍 ${escapeHtml(place.address)}</div>` : ''}
              ${place.phone && place.phone !== 'N/A' ? `<div style="font-size:0.8rem; color:#cbd5e1;">📞 <a href="tel:${place.phone}" style="color:#06b6d4; text-decoration:none;">${escapeHtml(place.phone)}</a></div>` : ''}
              ${place.email && place.email !== 'N/A' ? `<div style="font-size:0.8rem; color:#6ee7b7; font-weight:600; margin-top:2px;">✉️ ${escapeHtml(place.email)}</div>` : ''}
              <div style="margin-top:8px; display:flex; gap:10px; border-top:1px solid rgba(255,255,255,0.1); padding-top:6px;">
                ${place.website && place.website !== 'N/A' ? `<a href="${encodeURI(place.website)}" target="_blank" style="color:#06b6d4; font-size:0.8rem; font-weight:600; text-decoration:none;">🌐 Website</a>` : ''}
                <button onclick="openOrgModal('${escapeHtml(place.name)}')" style="background:none; border:none; color:#a855f7; font-size:0.8rem; font-weight:600; cursor:pointer;">🌳 Org Tree</button>
              </div>
            </div>
          `;

          const m = L.marker([place.lat, place.lon]).bindPopup(popupContent);
          m.addTo(placesLayer);
          markersMap[place.id || index] = m;
          m.on('click', () => { highlightTableRow(place.id || index); });
        }
      });

      document.getElementById('stat-plotted').innerText = plottedCount;
    }

    function focusShop(idOrIdx) {
      if (markersMap[idOrIdx]) {
        const m = markersMap[idOrIdx];
        leafletMap.setView(m.getLatLng(), 16);
        m.openPopup();
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

      if (frame.tab === 'linkedin' || frame.is_linkedin) {
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
            } else if (msg.type === 'live_frame') {
              updateLiveStream(msg.data);
            } else if (msg.type === 'place_scraped') {
              placesData.unshift(msg.data);
              renderTable();
              updateKPIs();
            } else if (msg.type === 'place_updated') {
              const target = placesData.find(p => p.name === msg.data.name && (p.address === msg.data.address || p.address === 'N/A' || msg.data.address === 'N/A'));
              if (target) {
                Object.assign(target, msg.data);
              } else {
                placesData.unshift(msg.data);
              }
              renderTable();
              updateKPIs();
            } else if (msg.type === 'org_updated') {
              const target = placesData.find(p => p.name.toLowerCase() === msg.data.company.toLowerCase());
              if (target) {
                target.employee_count = msg.data.employee_count;
                if (msg.data.linkedin_url) target.linkedin = msg.data.linkedin_url;
              }
              renderTable();
              updateKPIs();
            } else if (msg.type === 'status') {
              setScrapingState(msg.data !== 'Finished' && msg.data !== 'Ready', msg.data);
            } else if (msg.type === 'log') {
              logMessage(msg.data);
            } else if (msg.type === 'db_cleared') {
              placesData = [];
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

        if (data.live_frame) {
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
          const res = await resp.json();
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
      if (!query) query = "shops";

      const maxResults = parseInt(document.getElementById('max-slider').value);
      const lat = parseFloat(document.getElementById('lat-input').value);
      const lon = parseFloat(document.getElementById('lon-input').value);

      const radiusKm = parseFloat(document.getElementById('radius-slider').value) || 5.0;
      const agentMaps = document.getElementById('agent-maps-toggle').checked;
      const agentWebsite = document.getElementById('agent-website-toggle').checked;
      const agentLinkedin = document.getElementById('agent-linkedin-toggle').checked;
      const dedupArea = document.getElementById('dedup-area-toggle').checked;
      const skipExisting = document.getElementById('skip-existing-toggle').checked;

      if (!agentMaps && !agentWebsite && !agentLinkedin) {
        alert("Please enable at least one agent (Maps, Website, or LinkedIn) to start scraping!");
        return;
      }

      setScrapingState(true, "Launching Chrome window...");
      const parts = [];
      if (agentMaps) parts.push("Maps");
      if (agentWebsite) parts.push("Website");
      if (agentLinkedin) parts.push("LinkedIn");
      logMessage(`🚀 Launching Chrome Live Agents [${parts.join(' + ')}] for: "${query}" (Radius: ${radiusKm}km, Continuous: ${scrapeAll})...`);

      // Trigger Extension to open tab live in this exact Chrome window if installed
      try {
        const encoded = encodeURIComponent(query);
        const mapsUrl = (lat && lon)
          ? `https://www.google.com/maps/search/${encoded}/@${lat},${lon},14z?hl=en`
          : `https://www.google.com/maps/search/${encoded}?hl=en`;

        window.postMessage({
          source: "mavon_dashboard",
          action: "START_LIVE_BROWSER_SCRAPING",
          url: mapsUrl,
          query: query,
          max: maxResults,
          scrapeWebsites: agentWebsite,
          radiusKm: radiusKm
        }, "*");
      } catch (e) {}

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
            dedup_area: dedupArea,
            skip_existing_db: skipExisting
          })
        });
        const res = await resp.json();
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

      const hasExt = window.__MAVON_EXTENSION_ACTIVE__ === true || document.documentElement.getAttribute("data-mavon-extension") === "true";
      if (hasExt) {
        btn.className = 'btn-chrome-pill';
        text.innerText = 'Active Browser Ready (Extension v2.1)';
        btn.title = 'Mavon Chrome Extension is active in this browser! Live tabs will open directly inside this window.';
      }

      try {
        const resp = await fetch('/api/chrome/status');
        const data = await resp.json();
        if (data.active) {
          btn.className = 'btn-chrome-pill';
          text.innerText = 'Connected to Active Chrome (9222)';
          btn.title = 'Active Chrome connected on port 9222! Scraper will open tabs inside your personal browser window with all your logins.';
        } else if (hasExt || window.__MAVON_EXTENSION_ACTIVE__ || document.documentElement.getAttribute("data-mavon-extension") === "true") {
          btn.className = 'btn-chrome-pill';
          text.innerText = 'Active Browser Ready (Extension v2.1)';
          btn.title = 'Mavon Chrome Extension is active in this browser! Live tabs will open directly inside this window.';
        } else {
          btn.className = 'btn-chrome-pill disconnected';
          text.innerText = 'Chrome Port 9222 Idle (Click to Attach)';
          btn.title = 'Click to launch your Google Chrome with port 9222 enabled, or run start_chrome_debug.bat to attach your personal browser.';
        }
      } catch (e) {
        if (!hasExt) {
          btn.className = 'btn-chrome-pill disconnected';
          text.innerText = 'Chrome Port 9222 Idle (Click to Attach)';
        }
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
