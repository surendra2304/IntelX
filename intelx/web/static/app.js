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
