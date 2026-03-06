/*
 * ClawSafe Pay — Transaction Module
 * Handles transaction filtering, fetching, rendering (table + timeline),
 * form submission, and fast-polling after submit.
 */

import { API, API_KEY, DEFAULT_AGENT_KEY, CHAINS, state } from './state.js';
import {
  esc, toast, weiToDisplay, weiToEth, shortAddr, shortHash,
  timeAgo, chainBadge, explorerLink, statusBadge, animStat,
} from './utils.js';

// ── Filtering ────────────────────────────────────────────────────────
export function setFilter(f, btn) {
  state.filter = f;
  document.querySelectorAll('.f-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderTxTable();
}

function filterData(data) {
  if (state.filter === 'all') return data;
  const active  = ['pending', 'building', 'reviewing', 'signing', 'pending_auth', 'approved', 'broadcast'];
  const done    = ['confirmed'];
  const fail    = ['failed', 'rejected', 'expired', 'blocked', 'sign_failed'];
  if (state.filter === 'active') return data.filter(d => active.includes(d.status));
  if (state.filter === 'done')   return data.filter(d => done.includes(d.status));
  if (state.filter === 'failed') return data.filter(d => fail.includes(d.status));
  return data;
}

// ── Fetch ────────────────────────────────────────────────────────────
export async function fetchIntents() {
  try {
    const r = await fetch(`${API}/intents`, { headers: { 'X-API-Key': API_KEY } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.intents = await r.json();
    renderTxTable();
    renderTxStats();
    renderTimeline();
  } catch (e) { console.error('Fetch intents:', e); }
}

// ── Stats Row ────────────────────────────────────────────────────────
export function renderTxStats() {
  const d = state.intents;
  const total = d.length;
  const confirmedArr = d.filter(x => x.status === 'confirmed');
  const confirmed = confirmedArr.length;
  const pending = d.filter(x =>
    ['signing', 'pending_auth', 'approved', 'pending', 'building', 'reviewing', 'broadcast'].includes(x.status)
  ).length;
  const failed = d.filter(x =>
    ['failed', 'rejected', 'expired', 'blocked'].includes(x.status)
  ).length;
  const vol = confirmedArr.reduce((s, x) => s + weiToEth(x.amount_wei), 0);

  // Burn rate
  let burnRate = 0;
  if (confirmedArr.length) {
    const dates = confirmedArr
      .map(x => x.created_at ? x.created_at.slice(0, 10) : null)
      .filter(Boolean);
    if (dates.length) {
      const sorted = [...new Set(dates)].sort();
      const firstD = new Date(sorted[0]);
      const lastD  = new Date(sorted[sorted.length - 1]);
      const activeDays = Math.max(1, Math.ceil((lastD - firstD) / 86400000) + 1);
      burnRate = vol / activeDays;
    }
  }

  // Budget utilization
  const today = new Date().toISOString().slice(0, 10);
  const todaySpend = confirmedArr
    .filter(x => x.created_at && x.created_at.slice(0, 10) === today)
    .reduce((s, x) => s + weiToEth(x.amount_wei), 0);
  const totalDailyBudget = state.agents
    .filter(a => a.is_active && a.daily_limit_wei !== '0')
    .reduce((s, a) => s + weiToEth(a.daily_limit_wei), 0);
  const budgetPct = totalDailyBudget > 0 ? (todaySpend / totalDailyBudget) * 100 : -1;

  animStat('s-total', total);
  animStat('s-confirmed', confirmed);
  animStat('s-pending', pending);
  animStat('s-failed', failed);
  document.getElementById('s-volume').textContent = vol.toFixed(3);
  document.getElementById('s-burn').textContent = burnRate.toFixed(4);
  document.getElementById('s-burn-sub').textContent = 'ETH/day';

  const pctEl = document.getElementById('s-budget-pct');
  if (budgetPct >= 0) {
    pctEl.textContent = budgetPct.toFixed(0) + '%';
    pctEl.style.color = budgetPct > 90 ? 'var(--red)' : budgetPct > 70 ? 'var(--amber)' : 'var(--green)';
    document.getElementById('s-budget-sub').textContent = 'of daily limit';
  } else {
    pctEl.textContent = '\u2014';
    document.getElementById('s-budget-sub').textContent = 'no limits set';
  }
  document.getElementById('txCount').textContent = total;
}

// ── Table ────────────────────────────────────────────────────────────
export function renderTxTable() {
  const filtered = filterData(state.intents);
  const body = document.getElementById('txBody');
  document.getElementById('txEmpty').style.display = filtered.length ? 'none' : 'block';

  body.innerHTML = filtered.map(d => {
    const chain   = d.chain || 'sepolia';
    const isNew   = !state.prevStatuses[d.intent_id];
    const changed = state.prevStatuses[d.intent_id] && state.prevStatuses[d.intent_id] !== d.status;
    state.prevStatuses[d.intent_id] = d.status;
    const cls = isNew ? 'row-enter' : (changed ? 'status-update' : '');
    const err = d.error_message
      ? `<div class="error-text" title="${esc(d.error_message)}">\u26A0 ${esc(d.error_message)}</div>`
      : '';
    return `<tr class="${cls}">
      <td>${chainBadge(chain)}</td>
      <td>${statusBadge(d.status)}${err}</td>
      <td><strong>${esc(d.from_user)}</strong> \u2192 <strong>${esc(d.to_user)}</strong></td>
      <td class="addr">${shortAddr(d.to_address)}</td>
      <td class="amount">${weiToDisplay(d.amount_wei, chain)}</td>
      <td class="note-text" title="${esc(d.note || '')}">${esc(d.note) || '\u2014'}</td>
      <td>${explorerLink(d.tx_hash, chain)}</td>
      <td class="time-ago">${timeAgo(d.created_at)}</td>
    </tr>`;
  }).join('');
}

// ── Timeline ─────────────────────────────────────────────────────────
export function renderTimeline() {
  const container = document.getElementById('timeline');
  const emptyEl   = document.getElementById('timelineEmpty');
  if (!state.intents.length) { emptyEl.style.display = 'block'; return; }
  emptyEl.style.display = 'none';

  const recent = state.intents.slice(0, 12);
  container.innerHTML = recent.map(d => {
    const chain = d.chain || 'sepolia';
    const info  = CHAINS[chain] || CHAINS.sepolia;
    let dot = 'pending';
    if (d.status === 'confirmed') dot = 'confirmed';
    else if (d.status === 'broadcast') dot = 'broadcast';
    else if (['signing', 'pending_auth', 'approved'].includes(d.status)) dot = 'signing';
    else if (['failed', 'rejected', 'expired', 'blocked'].includes(d.status)) dot = 'failed';

    return `<div class="timeline-item">
      <div class="timeline-dot ${dot}"></div>
      <div class="timeline-content">
        <div class="timeline-title">${esc(d.from_user)} \u2192 ${esc(d.to_user)} <span class="chain-tag">${info.name}</span></div>
        <div class="timeline-detail">${weiToDisplay(d.amount_wei, chain)} \u2022 ${statusBadge(d.status)}</div>
        <div class="timeline-time">${timeAgo(d.created_at)}</div>
      </div>
    </div>`;
  }).join('');
}

// ── Form Submission ──────────────────────────────────────────────────
export function setupTxForm() {
  // Pre-fill the API key field with the default agent key if available
  const txApiKeyInput = document.getElementById('tx-api-key');
  if (txApiKeyInput && DEFAULT_AGENT_KEY) {
    txApiKeyInput.value = DEFAULT_AGENT_KEY;
  }

  document.getElementById('txForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn     = document.getElementById('txBtn');
    const btnText = document.getElementById('txBtnText');
    const btnSpin = document.getElementById('txBtnSpin');

    // Require API key
    const txApiKey = document.getElementById('tx-api-key').value.trim();
    if (!txApiKey) {
      toast('\u2717 API key is required to submit transactions', 'error');
      return;
    }

    btn.disabled = true;
    btnText.textContent = 'Submitting\u2026';
    btnSpin.style.display = 'inline-block';

    const chain    = document.getElementById('tx-chain').value;
    const asset    = document.getElementById('tx-asset').value;
    const ethAmt   = parseFloat(document.getElementById('tx-amount').value);
    const amountWei = BigInt(Math.round(ethAmt * 1e18)).toString();
    state.intentCounter++;
    const intentId = `dash-${Date.now()}-${state.intentCounter}`;

    try {
      const r = await fetch(`${API}/intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': txApiKey },
        body: JSON.stringify({
          intent_id: intentId,
          from_user:    document.getElementById('tx-from').value,
          to_user:      document.getElementById('tx-to').value,
          to_address:   document.getElementById('tx-addr').value,
          from_address: document.getElementById('tx-wallet').value,
          amount_wei:   amountWei,
          note:         document.getElementById('tx-note').value,
          chain, asset,
        }),
      });
      const data = await r.json();
      if (r.ok) {
        toast(`\u2713 ${intentId} submitted on ${chain}`, 'success');
        fetchIntents();
        startFastPoll();
      } else {
        toast(`\u2717 ${data.detail || JSON.stringify(data)}`, 'error');
      }
    } catch (err) {
      toast(`\u2717 Network error: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btnText.textContent = '\u26A1 Submit';
      btnSpin.style.display = 'none';
    }
  });
}

// ── Fast Polling ─────────────────────────────────────────────────────
export function startFastPoll() {
  state.fastPollCount = 0;
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => {
    fetchIntents();
    state.fastPollCount++;
    if (state.fastPollCount > 30) {
      clearInterval(state.pollTimer);
      state.pollTimer = setInterval(fetchIntents, 10000);
    }
  }, 3000);
}

// Expose to inline onclick handlers
window.setFilter   = setFilter;
window.fetchIntents = fetchIntents;

// ── TX API Key Visibility Toggle ─────────────────────────────────────
export function toggleTxKeyVisibility() {
  const input = document.getElementById('tx-api-key');
  const eye   = document.getElementById('tx-key-eye');
  if (input.type === 'password') {
    input.type = 'text';
    eye.textContent = '\uD83D\uDE48';
  } else {
    input.type = 'password';
    eye.textContent = '\uD83D\uDC41';
  }
}
window.toggleTxKeyVisibility = toggleTxKeyVisibility;
