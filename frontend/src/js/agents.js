/*
 * ClawSafe Pay — Agent Module
 * Handles agent CRUD, asset/chain selectors, key modal, edit modal.
 */

import { API, API_KEY, state } from './state.js';
import { esc, toast, formatWei, statusBadge } from './utils.js';
import { fetchAllAgentIntents } from './monitor.js';

// ── Fetch ────────────────────────────────────────────────────────────
export async function fetchAgents() {
  try {
    const r = await fetch(`${API}/api-users`, { headers: { 'X-API-Key': API_KEY } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.agents = await r.json();
    renderAgentTable();
    renderAgentStats();
    await fetchAllAgentIntents();
  } catch (e) { toast('Failed to load agents: ' + e.message, 'error'); }
}

// ── Stats ────────────────────────────────────────────────────────────
export function renderAgentStats() {
  const total  = state.agents.length;
  const active = state.agents.filter(u => u.is_active).length;
  document.getElementById('s-agents').textContent = total;
  document.getElementById('s-agents-sub').textContent = active + ' active';
  document.getElementById('agentCount').textContent = total;
}

// ── Table ────────────────────────────────────────────────────────────
export function renderAgentTable() {
  const body  = document.getElementById('agentBody');
  const empty = document.getElementById('agentEmpty');
  empty.style.display = state.agents.length ? 'none' : 'block';

  const sorted = [...state.agents].sort((a, b) => (b.is_active ? 1 : 0) - (a.is_active ? 1 : 0));

  body.innerHTML = sorted.map(u => {
    const sBadge = u.is_active
      ? '<span class="badge badge-active">\u25CF Active</span>'
      : '<span class="badge badge-inactive">\u25CF Inactive</span>';
    const tgBadge = u.telegram_chat_id_set
      ? '<span class="badge badge-active" title="Telegram Chat ID configured">\uD83D\uDCF1 TG</span>'
      : '<span class="badge badge-inactive" title="No Telegram Chat ID — uses default">📱 —</span>';
    const assets = u.allowed_assets.map(a =>
      a === '*' ? '<span class="badge badge-wildcard">\u2731 all</span>' : `<span class="badge badge-asset">${esc(a)}</span>`
    ).join('');
    const chains = u.allowed_chains.map(c =>
      c === '*' ? '<span class="badge badge-wildcard">\u2731 all</span>' : `<span class="badge badge-chain">${esc(c)}</span>`
    ).join('');
    const maxTx = u.max_amount_wei === '0' ? '\u221E' : formatWei(u.max_amount_wei);
    const daily = u.daily_limit_wei === '0' ? '\u221E' : formatWei(u.daily_limit_wei);
    const rate  = u.rate_limit === 0 ? 'def' : u.rate_limit + '/m';
    const limits = `<span class="mono" style="font-size:9px">${maxTx} / ${daily}<br>${rate}</span>`;

    return `<tr>
      <td>${sBadge}<br>${tgBadge}</td>
      <td><strong>${esc(u.name)}</strong><br><span class="mono" style="color:var(--muted);font-size:9px">${u.id.slice(0, 8)}\u2026</span></td>
      <td class="mono" style="color:var(--cyan)">${u.api_key_prefix}\u2026</td>
      <td>${assets}</td>
      <td>${chains}</td>
      <td>${limits}</td>
      <td class="actions">
        <button class="btn btn-sm btn-outline" onclick="openEdit('${u.id}')">\u270F\uFE0F</button>
        <button class="btn btn-sm btn-amber" onclick="regenKey('${u.id}','${esc(u.name)}')">\uD83D\uDD04</button>
        ${u.is_active
          ? `<button class="btn btn-sm btn-danger" onclick="deactivateAgent('${u.id}')">\uD83D\uDDD1</button>`
          : `<button class="btn btn-sm btn-outline" onclick="activateAgent('${u.id}')" style="color:var(--green);border-color:rgba(16,185,129,.2)">\u2705</button>`}
      </td>
    </tr>`;
  }).join('');
}

// ── Selector State (asset/chain presets) ─────────────────────────────
export const selectorState = { assets: new Set(['*']), chains: new Set(['*']) };

export function togglePreset(btn, group) {
  const val = btn.dataset.val;
  const st  = selectorState[group];
  if (val === '*') { st.clear(); st.add('*'); }
  else { st.delete('*'); st.has(val) ? st.delete(val) : st.add(val); if (st.size === 0) st.add('*'); }
  syncSelectorUI(group);
}

export function addCustom(group) {
  const input = document.getElementById(`ag-${group}-custom`);
  const val   = input.value.trim();
  if (!val) return;
  const st = selectorState[group];
  st.delete('*');
  st.add(group === 'chains' ? val.toLowerCase() : val.toUpperCase());
  input.value = '';
  syncSelectorUI(group);
}

export function removeSelected(group, val) {
  selectorState[group].delete(val);
  if (selectorState[group].size === 0) selectorState[group].add('*');
  syncSelectorUI(group);
}

export function syncSelectorUI(group) {
  const st      = selectorState[group];
  const area    = document.getElementById(`ag-${group}-area`);
  const hidden  = document.getElementById(`ag-${group}-val`);
  const display = document.getElementById(`ag-${group}-display`);
  area.querySelectorAll('.preset-btn').forEach(b => b.classList.toggle('selected', st.has(b.dataset.val)));
  hidden.value = JSON.stringify([...st]);
  const isAsset = group === 'assets';
  display.innerHTML = [...st].map(v => {
    if (v === '*') return '<span class="badge badge-wildcard">\u2731 ALL</span>';
    const cls = isAsset ? 'badge-asset' : 'badge-chain';
    return `<span class="badge ${cls}">${esc(v)} <span style="cursor:pointer;margin-left:3px;opacity:.5" onclick="removeSelected('${group}','${v}')">&times;</span></span>`;
  }).join('');
}

// ── Selector Init ────────────────────────────────────────────────────
export function setupSelectorInputs() {
  ['assets', 'chains'].forEach(g => {
    const input = document.getElementById(`ag-${g}-custom`);
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); addCustom(g); }
    });
  });
  syncSelectorUI('assets');
  syncSelectorUI('chains');
}

// ── Create Agent Form ────────────────────────────────────────────────
export function setupAgentForm() {
  document.getElementById('agentForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('agCreateBtn');
    btn.disabled = true;

    const body = {
      name:            document.getElementById('ag-name').value.trim(),
      telegram_chat_id: document.getElementById('ag-telegram-chat-id').value.trim(),
      allowed_assets:  JSON.parse(document.getElementById('ag-assets-val').value),
      allowed_chains:  JSON.parse(document.getElementById('ag-chains-val').value),
      max_amount_wei:  document.getElementById('ag-max-tx').value || '0',
      daily_limit_wei: document.getElementById('ag-daily').value || '0',
      rate_limit:      parseInt(document.getElementById('ag-rate').value) || 0,
    };

    try {
      const r = await fetch(`${API}/api-users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (r.ok) {
        toast('Agent created: ' + data.name, 'success');
        showKeyModal(data.name, data.api_key);
        fetchAgents();
        document.getElementById('agentForm').reset();
        selectorState.assets = new Set(['*']);
        selectorState.chains = new Set(['*']);
        syncSelectorUI('assets');
        syncSelectorUI('chains');
      } else {
        toast('Error: ' + (data.detail || JSON.stringify(data)), 'error');
      }
    } catch (err) { toast('Network error: ' + err.message, 'error'); }
    finally { btn.disabled = false; }
  });
}

// ── Key Modal ────────────────────────────────────────────────────────
export function showKeyModal(name, key) {
  document.getElementById('modal-agent-name').textContent = name;
  document.getElementById('modal-key-text').textContent   = key;
  document.getElementById('keyModal').classList.add('active');
}

export function closeKeyModal() {
  document.getElementById('keyModal').classList.remove('active');
}

export function copyKey() {
  navigator.clipboard.writeText(document.getElementById('modal-key-text').textContent)
    .then(() => toast('API key copied!', 'success'));
}

// ── Edit Modal ───────────────────────────────────────────────────────
export function openEdit(id) {
  const u = state.agents.find(x => x.id === id);
  if (!u) return;
  document.getElementById('ed-id').value     = u.id;
  document.getElementById('ed-name').value   = u.name;
  document.getElementById('ed-telegram-chat-id').value = '';  // always blank — hidden for security
  document.getElementById('ed-telegram-chat-id').placeholder =
    u.telegram_chat_id_set ? '(configured — enter new value to change)' : 'Leave empty for default';
  document.getElementById('ed-assets').value = u.allowed_assets.join(',');
  document.getElementById('ed-chains').value = u.allowed_chains.join(',');
  document.getElementById('ed-max-tx').value = u.max_amount_wei;
  document.getElementById('ed-daily').value  = u.daily_limit_wei;
  document.getElementById('ed-rate').value   = u.rate_limit;
  document.getElementById('ed-active').value = u.is_active ? 'true' : 'false';
  document.getElementById('editModal').classList.add('active');
}

export function closeEditModal() {
  document.getElementById('editModal').classList.remove('active');
}

export function setupEditForm() {
  document.getElementById('editForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('ed-id').value;
    const body = {
      name:            document.getElementById('ed-name').value.trim(),
      allowed_assets:  document.getElementById('ed-assets').value.split(',').map(s => s.trim()).filter(Boolean),
      allowed_chains:  document.getElementById('ed-chains').value.split(',').map(s => s.trim()).filter(Boolean),
      max_amount_wei:  document.getElementById('ed-max-tx').value || '0',
      daily_limit_wei: document.getElementById('ed-daily').value || '0',
      rate_limit:      parseInt(document.getElementById('ed-rate').value) || 0,
      is_active:       document.getElementById('ed-active').value === 'true',
    };
    // Only send telegram_chat_id if user entered a value (don't overwrite with empty)
    const tgVal = document.getElementById('ed-telegram-chat-id').value.trim();
    if (tgVal) {
      body.telegram_chat_id = tgVal;
    }

    try {
      const r = await fetch(`${API}/api-users/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify(body),
      });
      if (r.ok) { toast('Agent updated', 'success'); closeEditModal(); fetchAgents(); }
      else { const data = await r.json(); toast('Error: ' + (data.detail || JSON.stringify(data)), 'error'); }
    } catch (err) { toast('Network error: ' + err.message, 'error'); }
  });
}

// ── Regen Key ────────────────────────────────────────────────────────
export async function regenKey(id, name) {
  if (!confirm(`Regenerate API key for "${name}"? The old key stops working immediately.`)) return;
  try {
    const r = await fetch(`${API}/api-users/${id}/regenerate-key`, {
      method: 'POST', headers: { 'X-API-Key': API_KEY },
    });
    const data = await r.json();
    if (r.ok) { showKeyModal(data.name, data.api_key); fetchAgents(); }
    else toast('Error: ' + (data.detail || JSON.stringify(data)), 'error');
  } catch (err) { toast('Network error: ' + err.message, 'error'); }
}

// ── Deactivate / Activate ────────────────────────────────────────────
export async function deactivateAgent(id) {
  if (!confirm('Deactivate this agent? Its API key will stop working.')) return;
  try {
    const r = await fetch(`${API}/api-users/${id}`, { method: 'DELETE', headers: { 'X-API-Key': API_KEY } });
    if (r.ok) { toast('Agent deactivated', 'success'); fetchAgents(); }
  } catch (err) { toast('Error: ' + err.message, 'error'); }
}

export async function activateAgent(id) {
  try {
    const r = await fetch(`${API}/api-users/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
      body: JSON.stringify({ is_active: true }),
    });
    if (r.ok) { toast('Agent reactivated', 'success'); fetchAgents(); }
  } catch (err) { toast('Error: ' + err.message, 'error'); }
}

// Expose to inline onclick handlers
window.fetchAgents      = fetchAgents;
window.togglePreset     = togglePreset;
window.addCustom        = addCustom;
window.removeSelected   = removeSelected;
window.openEdit         = openEdit;
window.closeEditModal   = closeEditModal;
window.closeKeyModal    = closeKeyModal;
window.copyKey          = copyKey;
window.regenKey         = regenKey;
window.deactivateAgent  = deactivateAgent;
window.activateAgent    = activateAgent;
