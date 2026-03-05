/*
 * ClawSafe Pay — Agent Wallet Monitor
 * Fetches per-agent intents, renders expandable monitor cards,
 * and triggers finance widget updates.
 */

import { API, API_KEY, CHAINS, state } from './state.js';
import { esc, formatWei, statusBadge } from './utils.js';
import { renderFinanceWidgets } from './finance.js';

// ── Fetch all agent intents ──────────────────────────────────────────
export async function fetchAllAgentIntents() {
  if (!state.agents.length) {
    document.getElementById('monitorEmpty').style.display = 'block';
    document.getElementById('monitorCount').textContent = '0 txns';
    return;
  }
  state.agentIntents = {};
  const promises = state.agents.map(async u => {
    try {
      const r = await fetch(`${API}/api-users/${u.id}/intents`, { headers: { 'X-API-Key': API_KEY } });
      state.agentIntents[u.id] = r.ok ? await r.json() : [];
    } catch { state.agentIntents[u.id] = []; }
  });
  await Promise.all(promises);

  let total = 0;
  Object.values(state.agentIntents).forEach(arr => (total += arr.length));
  document.getElementById('monitorCount').textContent = total + ' txn' + (total !== 1 ? 's' : '');

  renderMonitor();
  renderFinanceWidgets();
}

// ── Render Monitor ───────────────────────────────────────────────────
export function renderMonitor() {
  const monitorEmpty = document.getElementById('monitorEmpty');
  if (!state.agents.length) { monitorEmpty.style.display = 'block'; return; }
  monitorEmpty.style.display = 'none';

  const hideEmpty = document.getElementById('hideEmptyToggle').checked;
  const active    = state.agents.filter(u =>  u.is_active);
  const inactive  = state.agents.filter(u => !u.is_active);

  document.getElementById('activeMonitors').innerHTML      = renderMonitorCards(active, hideEmpty);
  document.getElementById('deprecatedMonitors').innerHTML   = renderMonitorCards(inactive, hideEmpty, true);

  const hasDeprecated = inactive.some(u =>
    !hideEmpty || (state.agentIntents[u.id] || []).length > 0
  );
  document.getElementById('deprecatedSection').style.display =
    (inactive.length && hasDeprecated) ? 'block' : 'none';
}

// ── Cards ────────────────────────────────────────────────────────────
function renderMonitorCards(users, hideEmpty, isDeprecated = false) {
  return users.map(u => {
    const intents = state.agentIntents[u.id] || [];
    if (hideEmpty && intents.length === 0) return '';

    const depClass  = isDeprecated ? ' deprecated' : '';
    const iconClass = u.is_active ? 'active-i' : 'inactive-i';
    const iconText  = u.name.charAt(0).toUpperCase();
    const sBadge = u.is_active
      ? '<span class="badge badge-active" style="font-size:8px">Active</span>'
      : '<span class="badge badge-inactive" style="font-size:8px">Inactive</span>';

    const intentsHtml = intents.length === 0
      ? `<div class="mc-empty">No transactions for this agent.</div>`
      : `<div class="table-scroll"><table>
          <thead><tr><th>Status</th><th>Asset</th><th>Chain</th><th>Amount</th><th>To</th><th>Tx Hash</th><th>Date</th></tr></thead>
          <tbody>${intents.slice(0, 50).map(i => {
            const toAddr = i.to_address ? (i.to_address.slice(0, 8) + '\u2026' + i.to_address.slice(-6)) : '\u2014';
            const txH    = i.tx_hash ? (i.tx_hash.slice(0, 10) + '\u2026') : '<span style="color:var(--muted)">\u2014</span>';
            const dt     = i.created_at ? new Date(i.created_at).toLocaleString() : '\u2014';
            return `<tr>
              <td>${statusBadge(i.status || 'pending')}</td>
              <td><span class="badge badge-asset">${esc(i.asset || 'ETH')}</span></td>
              <td><span class="badge badge-chain">${esc(i.chain || 'sepolia')}</span></td>
              <td class="mono">${formatWei(i.amount_wei || '0')}</td>
              <td class="mono" title="${esc(i.to_address || '')}">${toAddr}</td>
              <td class="mono" title="${esc(i.tx_hash || '')}">${txH}</td>
              <td style="font-size:9px;color:var(--muted)">${dt}</td>
            </tr>`;
          }).join('')}</tbody>
        </table></div>`;

    return `<div class="monitor-card${depClass}" id="mc-${u.id}">
      <div class="mc-head" onclick="document.getElementById('mc-${u.id}').classList.toggle('open')">
        <div class="mc-info">
          <div class="mc-icon ${iconClass}">${iconText}</div>
          <div class="mc-meta">
            <h4>${esc(u.name)} ${sBadge}</h4>
            <div class="mc-sub">
              <span class="mono" style="color:var(--cyan)">${u.api_key_prefix}\u2026</span>
              <span>\u2022</span>
              <span>${u.allowed_assets.map(a => a === '*' ? 'All assets' : a).join(', ')}</span>
            </div>
          </div>
        </div>
        <div class="mc-right">
          <span class="mc-txn-count">${intents.length} txn${intents.length !== 1 ? 's' : ''}</span>
          <span class="mc-expand">\u25BC</span>
        </div>
      </div>
      <div class="mc-body">${intentsHtml}</div>
    </div>`;
  }).join('');
}

// Expose to inline onclick handlers
window.fetchAllAgentIntents = fetchAllAgentIntents;
window.renderMonitor        = renderMonitor;
