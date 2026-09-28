/**
 * INTELX Vanilla UI Controller (Offline, Zero Dependencies)
 */

function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.toggle('active', content.id === tabId);
  });
}

function closeDrawer() {
  const panel = document.getElementById('citationDrawer');
  const backdrop = document.getElementById('drawerBackdrop');
  if (panel) panel.classList.remove('open');
  if (backdrop) backdrop.style.display = 'none';
}

async function openCitationDrawer(kind, token) {
  const panel = document.getElementById('citationDrawer');
  const backdrop = document.getElementById('drawerBackdrop');
  const title = document.getElementById('drawerTitle');
  const body = document.getElementById('drawerBody');

  if (!panel || !body) return;

  if (title) title.innerText = (kind === 'S' ? 'Source Reference ' : 'Claim Evidence ') + '[' + kind + ':' + token + ']';
  body.innerHTML = '<div style="color: #64748b; padding: 16px;">Loading citation data...</div>';

  if (backdrop) backdrop.style.display = 'block';
  panel.classList.add('open');

  try {
    const res = await fetch('/api/citation/' + kind + '/' + encodeURIComponent(token));
    if (!res.ok) {
      body.innerHTML = '<div style="color: #dc2626; padding: 16px;">Citation reference details not found.</div>';
      return;
    }
    const data = await res.json();
    if (kind === 'S') {
      body.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:12px;">
          <div><strong>Title:</strong> ${data.title || 'Untitled'}</div>
          <div><strong>Domain:</strong> <code>${data.domain || 'local'}</code></div>
          <div><strong>Trust Tier:</strong> <span class="tier-badge tier-${(data.trust_tier || 'standard').toLowerCase()}">${data.trust_tier}</span></div>
          <div><strong>Retrieved:</strong> ${data.retrieved_at || 'N/A'}</div>
          <div><strong>Fingerprint:</strong> <code style="font-size:11px;">${data.fingerprint || 'N/A'}</code></div>
          ${data.injection_risk ? '<div style="background:#fef2f2; color:#dc2626; padding:8px; border-radius:4px; font-weight:600;">⚠️ Potential Prompt Injection Risk Flagged</div>' : ''}
          <div style="margin-top:16px;">
            <a href="${data.location}" target="_blank" class="btn btn-secondary btn-sm">View Location / File</a>
          </div>
        </div>
      `;
    } else {
      let evRows = (data.evidence || []).map(e => `
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:10px; margin-top:8px;">
          <div style="font-size:12px; color:#64748b;">Source: <code>[S:${(e.source_id || '').substring(0, 8)}]</code></div>
          <div style="margin-top:4px; font-style:italic;">"${e.quote || ''}"</div>
        </div>
      `).join('');

      body.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:12px;">
          <div><strong>Assertion:</strong> ${data.text}</div>
          <div><strong>Type:</strong> <code>${data.claim_type}</code></div>
          <div><strong>Status:</strong> <span class="status-chip status-${(data.status || '').toLowerCase()}">${data.status}</span></div>
          <div><strong>Confidence:</strong> ${(data.confidence * 100).toFixed(1)}% (${data.confidence >= 0.8 ? 'High' : data.confidence >= 0.5 ? 'Moderate' : 'Low'})</div>
          <div style="margin-top:12px; border-top:1px solid #e2e8f0; padding-top:12px;">
            <strong>Verbatim Evidence Spans (${(data.evidence || []).length}):</strong>
            ${evRows || '<div style="color:#64748b; font-size:12px; margin-top:6px;">No linked evidence spans.</div>'}
          </div>
        </div>
      `;
    }
  } catch (err) {
    body.innerHTML = '<div style="color: #dc2626; padding: 16px;">Error loading citation details.</div>';
  }
}

async function syncWithFuturis(runId) {
  const btn = document.getElementById('btn-sync-futuris');
  const statusEl = document.getElementById('status-futuris');
  if (btn) btn.disabled = true;
  const findingText = document.getElementById('sync-finding')?.value?.trim();
  if (!findingText) {
    if (statusEl) statusEl.textContent = 'Select a saved research finding first.';
    if (btn) btn.disabled = false;
    return;
  }
  if (statusEl) statusEl.innerHTML = '<span style="color:var(--color-blue);">Triggering forecast recalibration on Futuris...</span>';

  try {
    const res = await fetch('/api/v1/futuris/trigger-forecast', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        finding_text: findingText,
        run_id: runId,
        domain: 'market',
        confidence: 0.90
      })
    });
    const data = await res.json();
    if (res.ok) {
      if (statusEl) statusEl.innerHTML = `<span style="color:#16a34a; font-weight:600;">✓ Synced with Futuris (${data.status || 'delivered'})</span>`;
    } else {
      if (statusEl) statusEl.innerHTML = `<span style="color:#dc2626;">Failed: ${data.detail || res.statusText}</span>`;
    }
  } catch (err) {
    if (statusEl) statusEl.innerHTML = `<span style="color:#dc2626;">Network error syncing with Futuris: ${err.message}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function syncWithStratex(runId) {
  const btn = document.getElementById('btn-sync-stratex');
  const statusEl = document.getElementById('status-stratex');
  if (btn) btn.disabled = true;
  const findingText = document.getElementById('sync-finding')?.value?.trim();
  if (!findingText) {
    if (statusEl) statusEl.textContent = 'Select a saved research finding first.';
    if (btn) btn.disabled = false;
    return;
  }
  if (statusEl) statusEl.innerHTML = '<span style="color:var(--color-blue);">Dispatching market trade signal to StrateX...</span>';

  try {
    const res = await fetch('/api/v1/stratex/trigger-signal', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        finding_text: findingText,
        run_id: runId,
        domain: 'market',
        confidence: 0.90
      })
    });
    const data = await res.json();
    if (res.ok) {
      if (statusEl) statusEl.innerHTML = `<span style="color:#16a34a; font-weight:600;">✓ Synced with StrateX (${data.status || 'delivered'})</span>`;
    } else {
      if (statusEl) statusEl.innerHTML = `<span style="color:#dc2626;">Failed: ${data.detail || res.statusText}</span>`;
    }
  } catch (err) {
    if (statusEl) statusEl.innerHTML = `<span style="color:#dc2626;">Network error syncing with StrateX: ${err.message}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Dashboard filters only the run records rendered by the authenticated server.
(() => {
  const cards = [...document.querySelectorAll('[data-run-card]')];
  if (!cards.length) return;

  const search = document.getElementById('run-search');
  const empty = document.getElementById('filter-empty');
  const buttons = [...document.querySelectorAll('[data-run-filter]')];
  let selectedStatus = 'all';

  const applyFilters = () => {
    const query = (search?.value || '').trim().toLocaleLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      const matchesStatus = selectedStatus === 'all' || card.dataset.status === selectedStatus;
      const matchesQuery = !query || (card.dataset.search || '').includes(query);
      card.hidden = !(matchesStatus && matchesQuery);
      if (!card.hidden) visible += 1;
    });
    if (empty) empty.hidden = visible !== 0;
  };

  buttons.forEach((button) => button.addEventListener('click', () => {
    selectedStatus = button.dataset.runFilter || 'all';
    buttons.forEach((item) => {
      const active = item === button;
      item.classList.toggle('active', active);
      item.setAttribute('aria-pressed', String(active));
    });
    applyFilters();
  }));
  search?.addEventListener('input', applyFilters);
  document.querySelectorAll('[data-run-filter-link]').forEach((link) => link.addEventListener('click', () => {
    const filter = link.dataset.runFilterLink;
    buttons.find((button) => button.dataset.runFilter === filter)?.click();
    document.getElementById('runs-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
})();

// This workspace endpoint authenticates with the existing signed web-session cookie.
// The generic /api/v1 endpoints require an API key, which browser sessions do not expose.
(() => {
  const config = document.getElementById('job-poll-config');
  if (!config || config.dataset.terminal === 'true') return;

  const jobId = config.dataset.jobId;
  let lastEventId = Number(config.dataset.lastEventId || 0);
  const log = document.getElementById('eventLog');
  const indicator = document.getElementById('pollIndicator');
  const error = document.getElementById('event-error');
  const statusChip = document.getElementById('job-status-chip');
  const statusValue = document.getElementById('job-status-value');
  let polling = false;

  const appendEvent = (event) => {
    const entry = document.createElement('article');
    entry.className = 'event-entry';
    const time = document.createElement('time');
    const date = new Date(event.created_at);
    time.textContent = Number.isNaN(date.getTime()) ? 'Time unavailable' : `${date.toLocaleTimeString()} · ${Intl.DateTimeFormat().resolvedOptions().timeZone || 'local time'}`;
    const type = document.createElement('strong');
    type.textContent = event.type || 'Event';
    const payload = document.createElement('pre');
    payload.textContent = JSON.stringify(event.payload ?? {}, null, 2);
    entry.append(time, type, payload);
    log?.append(entry);
  };

  const poll = async () => {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(`/workspace/jobs/${encodeURIComponent(jobId)}/updates?after=${lastEventId}`, {
        credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.events)) throw new Error('Unexpected job update response');

      if (error) error.hidden = true;
      if (indicator) {
        indicator.dataset.state = 'online';
        indicator.querySelector('span').textContent = 'Updates connected';
      }
      const emptyState = document.getElementById('event-empty');
      data.events.forEach((event) => {
        appendEvent(event);
        lastEventId = Math.max(lastEventId, Number(event.id) || 0);
      });
      if (data.events.length && emptyState) emptyState.remove();
      if (log) log.scrollTop = log.scrollHeight;

      if (data.status && statusValue) statusValue.textContent = data.status.replaceAll('_', ' ');
      if (data.status && statusChip) {
        statusChip.textContent = data.status.replaceAll('_', ' ');
        statusChip.className = `status-chip status-${data.status.toLowerCase()}`;
      }
      if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(data.status)) window.location.reload();
    } catch (_) {
      if (error) error.hidden = false;
      if (indicator) {
        indicator.dataset.state = 'error';
        indicator.querySelector('span').textContent = 'Update check failed · retrying';
      }
    } finally {
      polling = false;
    }
  };

  poll();
  window.setInterval(poll, 5000);
})();

