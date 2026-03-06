/*
 * ClawSafe Pay — Transaction Module
 * Handles transaction filtering, fetching, rendering (table + timeline),
 * form submission, and fast-polling after submit.
 */

import { API, API_KEY, DEFAULT_AGENT_KEY, CHAINS, state } from './state.js';
import {
  esc, toast, weiToDisplay, weiToEth, shortAddr,
  timeAgo, explorerLink, statusBadge, animStat, txTypeBadge, riskBadge, trustBadge,
} from './utils.js';

// ── Filtering ────────────────────────────────────────────────────────
export function setFilter(f, btn) {
  state.filter = f;
  document.querySelectorAll('.f-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderTxTable();
}

function filterData(data) {
  let out = data;
  if (state.agentFilter && state.agentFilter !== 'all') {
    out = out.filter(d => {
      const n = (d.api_user_name || (d.api_user_id ? 'Unknown Agent' : 'Admin Dashboard')).toLowerCase();
      return n === state.agentFilter.toLowerCase();
    });
  }
  if (state.filter === 'all') return out;
  const active  = ['pending', 'building', 'reviewing', 'signing', 'pending_auth', 'approved', 'broadcast'];
  const done    = ['confirmed'];
  const fail    = ['failed', 'rejected', 'expired', 'blocked', 'sign_failed'];
  if (state.filter === 'active') return out.filter(d => active.includes(d.status));
  if (state.filter === 'review') return out.filter(d => (d.policy_decision || '') === 'needs_review');
  if (state.filter === 'high_risk') return out.filter(d => ['high', 'critical'].includes((d.risk_level || '').toLowerCase()));
  if (state.filter === 'unknown') return out.filter(d => (d.trust_level || '').toLowerCase() === 'new');
  if (state.filter === 'done')   return out.filter(d => done.includes(d.status));
  if (state.filter === 'failed') return out.filter(d => fail.includes(d.status));
  return out;
}

function renderAgentFilterOptions() {
  const el = document.getElementById('tx-agent-filter');
  if (!el) return;
  const names = new Set(['Admin Dashboard']);
  state.agents.forEach(a => names.add(a.name));
  state.intents.forEach(i => {
    const n = i.api_user_name || (i.api_user_id ? 'Unknown Agent' : 'Admin Dashboard');
    if (n) names.add(n);
  });
  const current = state.agentFilter || 'all';
  const opts = ['<option value="all">All Agents</option>'];
  [...names].sort((a, b) => a.localeCompare(b)).forEach(n => {
    const selected = current.toLowerCase() === n.toLowerCase() ? ' selected' : '';
    opts.push(`<option value="${esc(n)}"${selected}>${esc(n)}</option>`);
  });
  el.innerHTML = opts.join('');
}

// ── Fetch ────────────────────────────────────────────────────────────
export async function fetchIntents() {
  try {
    const r = await fetch(`${API}/intents`, { headers: { 'X-API-Key': API_KEY } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.intents = await r.json();
    renderAgentFilterOptions();
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
    const isNew   = !state.prevStatuses[d.intent_id];
    const changed = state.prevStatuses[d.intent_id] && state.prevStatuses[d.intent_id] !== d.status;
    state.prevStatuses[d.intent_id] = d.status;
    const cls = isNew ? 'row-enter' : (changed ? 'status-update' : '');
    const err = d.error_message
      ? `<div class="error-text" title="${esc(d.error_message)}">\u26A0 ${esc(d.error_message)}</div>`
      : '<div><strong>Error:</strong> —</div>';
    const purpose = d.tx_purpose || d.note || `${d.from_user} -> ${d.to_user}`;
    const agentName = d.api_user_name || (d.api_user_id ? 'Unknown Agent' : 'Admin Dashboard');
    const reasons = d.risk_reasons || [];
    const detailId = `txd-${d.intent_id}`;
    const reasonsLine = reasons.length
      ? `<div class="note-text" title="${esc(reasons.join(', '))}">${esc(reasons.join(' · '))}</div>`
      : '';
    const detailRow = `<tr class="tx-detail-row" id="${detailId}" style="display:none">
      <td colspan="9">
        <div class="tx-detail-grid">
          <div><strong>Agent:</strong> ${esc(agentName)}</div>
          <div><strong>Policy:</strong> ${esc(d.policy_decision || 'auto_allowed')}</div>
          <div><strong>Requires Human:</strong> ${(d.requires_human ? 'yes' : 'no')}</div>
          <div><strong>Recipient:</strong> <span class="mono">${esc(d.to_address || '')}</span></div>
          <div><strong>Reason Codes:</strong> ${esc((d.risk_reasons || []).join(', ') || 'none')}</div>
          <div><strong>Note:</strong> ${esc(d.note || '—')}</div>
          <div style="grid-column:1/-1"><strong>Error:</strong> ${err.replace(/<\/?div[^>]*>/g, '')}</div>
        </div>
      </td>
    </tr>`;
    return `<tr class="${cls}">
      <td>${txTypeBadge(d.tx_type)}</td>
      <td><span class="badge badge-chain">${esc(agentName)}</span></td>
      <td>
        <div><strong>${esc(purpose)}</strong></div>
        <div class="note-text">${esc(d.from_user)} \u2192 ${esc(d.to_user)} · ${esc(d.chain || 'sepolia')}</div>
        ${reasonsLine}
        <button class="tx-detail-toggle" onclick="toggleTxDetail('${detailId}', this)">Details</button>
      </td>
      <td>${riskBadge(d.risk_level, reasons)}</td>
      <td>
        ${trustBadge(d.trust_level)}
        <div class="note-text" title="${esc(d.to_address || '')}">${shortAddr(d.to_address)}</div>
      </td>
      <td class="amount">${weiToDisplay(d.amount_wei, d.chain || 'sepolia')}</td>
      <td>${statusBadge(d.status)}</td>
      <td>${explorerLink(d.tx_hash, d.chain || 'sepolia')}</td>
      <td class="time-ago">${timeAgo(d.created_at)}</td>
    </tr>${detailRow}`;
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
  // Start on Simple Payment tab
  switchTxTab('simple');

  // Pre-fill the API key field with the default agent key if available
  const txApiKeyInput = document.getElementById('tx-api-key');
  if (txApiKeyInput && DEFAULT_AGENT_KEY) {
    txApiKeyInput.value = DEFAULT_AGENT_KEY;
  }

  // Wire up the eye-toggle button via addEventListener (more reliable than inline onclick)
  const eyeBtn = document.getElementById('tx-key-eye');
  if (eyeBtn) {
    eyeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleTxKeyVisibility();
    });
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

// ── TX Mode Tabs ──────────────────────────────────────────────────────
export function switchTxTab(mode) {
  const isAgent = mode === 'agent';
  document.getElementById('tx-panel-simple').style.display = isAgent ? 'none' : '';
  document.getElementById('tx-panel-agent').style.display  = isAgent ? '' : 'none';
  document.getElementById('tx-tab-simple').style.opacity = isAgent ? '0.5' : '1';
  document.getElementById('tx-tab-agent').style.opacity  = isAgent ? '1' : '0.5';

  if (isAgent) {
    // Pre-fill agent key + wallet from simple form
    const agentKey = document.getElementById('tx-api-key').value;
    if (agentKey) document.getElementById('ai-api-key').value = agentKey;
    const wallet = document.getElementById('tx-wallet').value;
    const aiWallet = document.getElementById('ai-wallet');
    if (aiWallet && wallet) aiWallet.value = wallet;
    // Ensure input is never stuck disabled when switching tabs
    const chatInput = document.getElementById('ai-chat-input');
    if (chatInput) chatInput.disabled = false;
    const sendBtn = document.getElementById('ai-chat-send');
    if (sendBtn) sendBtn.disabled = false;
    _initInstructionChat();
  }
}

// ── Agent Instruction Chat ────────────────────────────────────────────
const _instrState = { messages: [], plan: null };
const _INSTR_GREETING = "Hi! I'm your on-chain agent. Tell me what to do — e.g. \"buy WBTC with 0.005 ETH on Uniswap\" or \"send 0.001 ETH to alice\".";

function _initInstructionChat() {
  if (_instrState.messages.length === 0) {
    _renderInstrMessages([]);
  }
}

export async function sendInstructionMessage() {
  const input = document.getElementById('ai-chat-input');
  const msg = input.value.trim();
  if (!msg) return;

  const apiKey = document.getElementById('ai-api-key').value.trim();
  if (!apiKey) { toast('API key is required', 'error'); return; }

  input.value = '';
  input.disabled = true;
  const sendBtn = document.getElementById('ai-chat-send');
  if (sendBtn) sendBtn.disabled = true;

  // Hide plan card while processing new message
  document.getElementById('ai-plan-card').style.display = 'none';
  _instrState.plan = null;

  _renderInstrMessages([..._instrState.messages, { role: 'user', content: msg }], true);

  const fromAddress = document.getElementById('ai-wallet').value;

  try {
    const r = await fetch(`${API}/agent-instruction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
      body: JSON.stringify({
        instruction: msg,
        from_address: fromAddress,
        messages: _instrState.messages,
      }),
    });
    const data = await r.json();
    if (!r.ok) { toast('Agent error: ' + (data.detail || '?'), 'error'); _renderInstrMessages(_instrState.messages); return; }

    _instrState.messages = data.messages;
    _renderInstrMessages(_instrState.messages);

    if (data.type === 'plan' && data.plan) {
      _instrState.plan = data.plan;
      _applyPlanCard(data.plan);
    }
  } catch (err) {
    toast('Network error: ' + err.message, 'error');
    _renderInstrMessages(_instrState.messages);
  } finally {
    input.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
    input.focus();
  }
}

// Lightweight markdown → safe HTML (escape first, then convert syntax)
function _mdToHtml(text) {
  // 1. Escape HTML entities to prevent XSS
  let s = esc(text);
  // 2. Bold: **text**
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  // 3. Italic: *text* (single, not already handled)
  s = s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
  // 4. Bullet list items (- or *)
  s = s.replace(/^[-*] (.+)$/gm, '<li style="margin:2px 0">$1</li>');
  // 5. Numbered list items
  s = s.replace(/^\d+\. (.+)$/gm, '<li style="margin:2px 0">$1</li>');
  // 6. Wrap adjacent <li> blocks in <ul>
  s = s.replace(/((<li[^>]*>.*<\/li>\n?)+)/g, '<ul style="margin:4px 0;padding-left:18px">$1</ul>');
  // 7. Remaining newlines → <br>
  s = s.replace(/\n/g, '<br>');
  return s;
}

function _renderInstrMessages(messages, pending = false) {
  const container = document.getElementById('ai-chat-messages');
  if (!container) return;
  const all = [{ role: 'assistant', content: _INSTR_GREETING }, ...messages];
  container.innerHTML = all.map(m => {
    const isBot = m.role === 'assistant';
    const align = isBot ? 'flex-start' : 'flex-end';
    const bg     = isBot ? 'rgba(6,182,212,.1)'    : 'rgba(139,92,246,.15)';
    const border = isBot ? '1px solid rgba(6,182,212,.2)' : '1px solid rgba(139,92,246,.2)';
    return `<div style="display:flex;justify-content:${align};margin-bottom:8px">
      <div style="max-width:85%;background:${bg};border:${border};border-radius:10px;padding:8px 12px;font-size:12px;color:var(--fg);line-height:1.5">${_mdToHtml(m.content)}</div>
    </div>`;
  }).join('') + (pending ? `<div style="display:flex;justify-content:flex-start;margin-bottom:8px">
    <div style="background:rgba(6,182,212,.1);border:1px solid rgba(6,182,212,.2);border-radius:10px;padding:8px 12px;font-size:12px;color:var(--muted)">⏳ Thinking…</div>
  </div>` : '');
  container.scrollTop = container.scrollHeight;
}

function _applyPlanCard(plan) {
  const card = document.getElementById('ai-plan-card');
  document.getElementById('ai-plan-addr').textContent = plan.to_address || '';
  const eth = plan.value_wei ? (parseInt(plan.value_wei) / 1e18).toFixed(6) : '0';
  document.getElementById('ai-plan-amount').textContent = `${eth} ${plan.asset || 'ETH'}`;
  document.getElementById('ai-plan-note').textContent = plan.note || '';
  const humanEl = document.getElementById('ai-plan-needs-human');
  humanEl.textContent = plan.needs_human ? '⚠ Needs Approval' : '✓ Auto';
  humanEl.style.background = plan.needs_human ? 'rgba(245,158,11,.15)' : 'rgba(34,197,94,.1)';
  humanEl.style.color = plan.needs_human ? 'var(--amber)' : 'var(--green)';
  const ul = document.getElementById('ai-plan-reasoning');
  ul.innerHTML = (plan.reasoning || []).map(r => `<li>${esc(r)}</li>`).join('');
  card.style.display = '';
}

export async function submitPlannedIntent() {
  if (!_instrState.plan) return;
  const plan = _instrState.plan;

  const apiKey = document.getElementById('ai-api-key').value.trim();
  if (!apiKey) { toast('API key is required', 'error'); return; }

  const confirmBtn  = document.getElementById('ai-plan-confirm');
  const confirmText = document.getElementById('ai-plan-confirm-text');
  const confirmSpin = document.getElementById('ai-plan-confirm-spin');
  confirmBtn.disabled = true;
  confirmText.textContent = 'Submitting…';
  confirmSpin.style.display = 'inline-block';

  const fromAddress = document.getElementById('ai-wallet').value;
  state.intentCounter++;
  const intentId = `agent-${Date.now()}-${state.intentCounter}`;

  // Normalise values to pass server-side validation
  const SUPPORTED_ASSETS = new Set(['ETH', 'USDC', 'USDT', 'WBTC', 'WETH', 'DAI', 'SOL', 'BTC', 'ZEC', 'ADA']);
  const asset = SUPPORTED_ASSETS.has(plan.asset) ? plan.asset : 'ETH';
  // Ensure amount_wei is a clean positive integer string (Z.AI may return floats/sci notation)
  const amountWei = BigInt(Math.round(parseFloat(plan.value_wei || '0'))).toString();

  if (amountWei === '0') {
    toast('✗ Agent returned zero amount — ask again with a specific amount (e.g. "0.005 ETH")', 'error');
    confirmBtn.disabled = false;
    confirmText.textContent = '✅ Confirm & Submit Intent';
    confirmSpin.style.display = 'none';
    return;
  }

  const intentBody = {
    intent_id:    intentId,
    from_user:    'agent',
    to_user:      'contract',
    to_address:   plan.to_address,
    from_address: fromAddress,
    amount_wei:   amountWei,
    note:         plan.note,
    chain:        'sepolia',
    asset,
  };
  console.log('Submitting intent:', intentBody);

  try {
    const r = await fetch(`${API}/intent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
      body: JSON.stringify(intentBody),
    });
    const data = await r.json();
    if (r.ok) {
      toast(`✓ ${intentId} submitted`, 'success');
      document.getElementById('ai-plan-card').style.display = 'none';
      _instrState.plan = null;
      _instrState.messages = [];
      _renderInstrMessages([]);
      fetchIntents();
      startFastPoll();
    } else {
      const detail = data.detail;
      const msg = Array.isArray(detail)
        ? detail.map(e => `${e.loc ? e.loc.slice(-1)[0] : '?'}: ${e.msg}`).join(' | ')
        : (typeof detail === 'string' ? detail : JSON.stringify(data));
      toast('✗ ' + msg, 'error');
      console.error('422 detail:', data);
    }
  } catch (err) {
    toast('✗ Network error: ' + err.message, 'error');
  } finally {
    confirmBtn.disabled = false;
    confirmText.textContent = '✅ Confirm & Submit Intent';
    confirmSpin.style.display = 'none';
  }
}

export function toggleAiKeyVisibility() {
  const input = document.getElementById('ai-api-key');
  const eye   = document.getElementById('ai-key-eye');
  if (!input || !eye) return;
  if (input.type === 'password') { input.type = 'text'; eye.textContent = '🙈'; }
  else                           { input.type = 'password'; eye.textContent = '👁'; }
}

// Sync AI wallet dropdown with the simple form's wallet list
export function syncAiWalletDropdown() {
  const src = document.getElementById('tx-wallet');
  const dst = document.getElementById('ai-wallet');
  if (!src || !dst) return;
  dst.innerHTML = src.innerHTML;
}

// Expose to inline onclick handlers
window.setFilter              = setFilter;
window.fetchIntents           = fetchIntents;
window.switchTxTab            = switchTxTab;
window.sendInstructionMessage = sendInstructionMessage;
window.submitPlannedIntent    = submitPlannedIntent;
window.toggleAiKeyVisibility  = toggleAiKeyVisibility;

// ── TX API Key Visibility Toggle ─────────────────────────────────────
export function toggleTxKeyVisibility() {
  const input = document.getElementById('tx-api-key');
  const eye   = document.getElementById('tx-key-eye');
  if (!input || !eye) return;
  if (input.type === 'password') {
    input.type = 'text';
    eye.textContent = '\uD83D\uDE48';
  } else {
    input.type = 'password';
    eye.textContent = '\uD83D\uDC41';
  }
}
window.toggleTxKeyVisibility = toggleTxKeyVisibility;
window.setAgentFilter = (name) => {
  state.agentFilter = name || 'all';
  renderTxTable();
};
window.toggleTxDetail = (id, btn) => {
  const row = document.getElementById(id);
  if (!row) return;
  const isOpen = row.style.display !== 'none';
  row.style.display = isOpen ? 'none' : 'table-row';
  if (btn) btn.textContent = isOpen ? 'Details' : 'Hide';
};
