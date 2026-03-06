/*
 * ClawSafe Pay — Agent Module
 * Handles agent CRUD, asset/chain selectors, key modal, edit modal.
 */

import { API, API_KEY, state } from './state.js';
import { esc, toast, formatWei, statusBadge } from './utils.js';
import { fetchAllAgentIntents } from './monitor.js';

const BOT_POLICY_PRESETS = {
  personal: {
    label: 'Personal Assistant',
    icon: '👤',
    description: 'Full oversight — every transaction requires your explicit approval.',
    bullets: [
      'Every payment needs your sign-off before executing',
      'No automated spending under any circumstance',
      'Best for ad-hoc payments and sensitive accounts',
    ],
    goalHint: 'Personal assistant for routine payments and transfers',
    contractLabel: 'Whitelisted Recipient Addresses',
    contractPresets: [],
    approval_mode: 'always_human',
    approval_threshold_wei: '0',
    window_limit_wei: '0',
    window_seconds: 0,
  },
  ecommerce: {
    label: 'E-Commerce Bot',
    icon: '🛒',
    description: 'Auto-approves small purchases under 0.01 ETH, asks for bigger ones.',
    bullets: [
      'Small purchases auto-execute without interruption',
      'Human sign-off required above the approval threshold',
      'Daily rolling cap prevents runaway spending',
      'Good for shopping bots with a mix of small and large purchases',
    ],
    goalHint: 'E-commerce purchasing agent for online shopping',
    contractLabel: 'Whitelisted Merchant / Recipient Addresses',
    contractPresets: [],
    approval_mode: 'human_if_above_threshold',
    approval_threshold_wei: '10000000000000000',
    window_limit_wei: '100000000000000000',
    window_seconds: 86400,
  },
  spot_trader: {
    label: 'Spot Trader',
    icon: '📈',
    description: 'Executes trades autonomously within an hourly budget. Whitelist your DEX contract.',
    bullets: [
      'Fully automated — no human approval per trade',
      '0.5 ETH per-hour rolling spend cap',
      'Restrict to specific DEX contracts for safety',
      'Time-sensitive execution with no bottleneck on small trades',
    ],
    goalHint: 'Automated spot trading bot — ETH/USDC on Uniswap v3',
    contractLabel: 'Allowed DEX Contracts',
    contractPresets: [
      { label: 'Uniswap V3 Router',  address: '0xE592427A0AEce92De3Edee1F18E0157C05861564' },
      { label: 'Uniswap Universal',  address: '0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD' },
      { label: 'SushiSwap Router',   address: '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F' },
      { label: 'Curve Router',       address: '0x99a58482BD75cbab83b27EC03CA68fF489b5788f' },
    ],
    approval_mode: 'auto_within_limits',
    approval_threshold_wei: '0',
    window_limit_wei: '500000000000000000',
    window_seconds: 3600,
  },
  dca_trader: {
    label: 'DCA Trader',
    icon: '🔄',
    description: 'Dollar-cost averages automatically within a daily budget. No per-trade friction.',
    bullets: [
      'Executes scheduled buys without human approval',
      '0.5 ETH daily spend cap across all trades',
      'Predictable, low-friction cost averaging',
      'Ideal for long-term accumulation strategies',
    ],
    goalHint: 'Dollar-cost average ETH weekly using Uniswap',
    contractLabel: 'Allowed DEX / Aggregator Contracts',
    contractPresets: [
      { label: 'Uniswap V3 Router', address: '0xE592427A0AEce92De3Edee1F18E0157C05861564' },
      { label: 'CoW Protocol',      address: '0x9008D19f58AAbD9eD0D60971565AA8510560ab41' },
      { label: '1inch V5',          address: '0x1111111254EEB25477B68fb85Ed929f73A960582' },
    ],
    approval_mode: 'auto_within_limits',
    approval_threshold_wei: '0',
    window_limit_wei: '500000000000000000',
    window_seconds: 86400,
  },
  nft_sniper: {
    label: 'NFT Sniper',
    icon: '🎯',
    description: 'Snipes mints under 0.02 ETH instantly — asks you before floor-sweeping.',
    bullets: [
      'Small mints execute instantly without friction',
      'Human approval required above 0.02 ETH threshold',
      '0.2 ETH per-hour rolling cap on total spend',
      'Balances time-sensitivity with oversight on big purchases',
    ],
    goalHint: 'NFT mint sniper targeting sub-0.02 ETH drops on Blur',
    contractLabel: 'Allowed NFT Marketplace Contracts',
    contractPresets: [
      { label: 'OpenSea Seaport', address: '0x00000000000000ADc04C56Bf30aC9d3c0aAF14dC' },
      { label: 'Blur Exchange',   address: '0x000000000000Ad05Ccc4F10045630fb830B95127' },
      { label: 'LooksRare',       address: '0x59728544B08AB483533076417FbBB2fD0B17CE3a' },
    ],
    approval_mode: 'human_if_above_threshold',
    approval_threshold_wei: '20000000000000000',
    window_limit_wei: '200000000000000000',
    window_seconds: 3600,
  },
  pump_fun_sniper: {
    label: 'Pump.fun Sniper',
    icon: '🚀',
    description: 'Fully automated, tight 5-minute budget for time-critical memecoin entries.',
    bullets: [
      'Zero-friction execution — every millisecond counts',
      '0.05 ETH per-5-minute window limits max exposure',
      'High rate limit for rapid-fire entries',
      'Small position sizes contain downside risk',
    ],
    goalHint: 'Pump.fun memecoin early-entry sniper',
    contractLabel: 'Allowed Launch Platform Contracts',
    contractPresets: [
      { label: 'Pump.fun Program', address: '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P' },
    ],
    approval_mode: 'auto_within_limits',
    approval_threshold_wei: '0',
    window_limit_wei: '50000000000000000',
    window_seconds: 300,
  },
  polymarket_copytrader: {
    label: 'Polymarket Copy Trader',
    icon: '🔮',
    description: 'Copies prediction market positions within a daily budget. Tracks total exposure.',
    bullets: [
      'Automatically mirrors target trader positions',
      '0.3 ETH daily position budget',
      'No per-trade approval needed within the budget',
      'Budget exhaustion pauses activity until next window',
    ],
    goalHint: 'Copy top Polymarket traders\' prediction market positions',
    contractLabel: 'Allowed Prediction Market Contracts',
    contractPresets: [
      { label: 'Polymarket CTF Exchange', address: '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045' },
      { label: 'Polymarket Exchange',     address: '0xC5d563A36AE78145C45a50134d48A1215220f80a' },
    ],
    approval_mode: 'auto_within_limits',
    approval_threshold_wei: '0',
    window_limit_wei: '300000000000000000',
    window_seconds: 86400,
  },
  defi_borrower: {
    label: 'DeFi Borrower',
    icon: '🏦',
    description: 'Large DeFi moves require your sign-off and a bot justification.',
    bullets: [
      'Small interactions auto-approved under 0.05 ETH',
      'Above threshold: bot must explain reasoning before you approve',
      'Reviewer checks alignment with your stated bot goal',
      '0.3 ETH daily cap limits total exposure',
    ],
    goalHint: 'Aave/Compound borrowing and yield optimisation bot',
    contractLabel: 'Allowed DeFi Protocol Contracts',
    contractPresets: [
      { label: 'Aave V3 Pool',      address: '0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2' },
      { label: 'Compound V3 USDC', address: '0xc3d688B66703497DAA19211EEdff47f25384cdc3' },
      { label: 'MakerDAO DSProxy', address: '0x5ef30b9986345249bc32d8928B7ee64DE9435E39' },
    ],
    approval_mode: 'human_if_above_threshold',
    approval_threshold_wei: '50000000000000000',
    window_limit_wei: '300000000000000000',
    window_seconds: 86400,
  },
  custom: {
    label: 'Custom',
    icon: '⚙️',
    description: 'Configure every policy setting manually. No preset applied.',
    bullets: [
      'All policy fields are yours to set explicitly',
      'Choose approval mode, thresholds, and window caps',
      'Use when no standard preset fits your use case',
    ],
    goalHint: 'Custom bot with manual policy configuration',
    contractLabel: 'Allowed Contracts / Addresses',
    contractPresets: [],
    approval_mode: 'always_human',
    approval_threshold_wei: '0',
    window_limit_wei: '0',
    window_seconds: 0,
  },
};

// ── ETH Price Cache ───────────────────────────────────────────────────
let _ethPriceCache = { usd: null, ts: 0 };

async function fetchEthPrice() {
  const now = Date.now();
  if (_ethPriceCache.usd && now - _ethPriceCache.ts < 5 * 60 * 1000) return _ethPriceCache.usd;
  try {
    const r = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd');
    const d = await r.json();
    _ethPriceCache = { usd: d.ethereum.usd, ts: now };
    return _ethPriceCache.usd;
  } catch { return null; }
}

function _weiHintText(weiStr, ethPriceUsd) {
  let n;
  try { n = BigInt(weiStr || '0'); } catch { return ''; }
  if (n === 0n) return '';
  const eth = Number(n) / 1e18;
  const ethStr = eth < 0.001 ? eth.toFixed(6) : eth.toFixed(4);
  if (ethPriceUsd) {
    const usd = eth * ethPriceUsd;
    return `≈ ${ethStr} ETH  ≈ $${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(2)} USD`;
  }
  return `≈ ${ethStr} ETH`;
}

async function updateWeiHints(prefix) {
  const ethPrice = await fetchEthPrice();
  const fields = ['approval-threshold', 'window-limit', 'max-tx', 'daily'];
  for (const f of fields) {
    const input = document.getElementById(`${prefix}-${f}`);
    const hint  = document.getElementById(`${prefix}-${f}-hint`);
    if (!input || !hint) continue;
    hint.textContent = _weiHintText(input.value || '0', ethPrice);
    if (!input._hintWired) {
      input._hintWired = true;
      input.addEventListener('input', async () => {
        hint.textContent = _weiHintText(input.value || '0', await fetchEthPrice());
      });
    }
  }
}

// ── Policy Preview Card ──────────────────────────────────────────────
function renderPolicyPreview(prefix, botType) {
  const el = document.getElementById(`${prefix}-policy-preview`);
  if (!el) return;
  const preset = BOT_POLICY_PRESETS[botType];
  if (!preset) { el.innerHTML = ''; return; }

  const modeColor = { always_human: 'var(--amber)', auto_within_limits: 'var(--green)', human_if_above_threshold: 'var(--cyan)' };
  const modeLabel = { always_human: 'Always Human', auto_within_limits: 'Auto Within Limits', human_if_above_threshold: 'Human Above Threshold' };
  const color = modeColor[preset.approval_mode] || 'var(--muted)';
  const label = modeLabel[preset.approval_mode] || preset.approval_mode;

  el.innerHTML = `
    <div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:8px;padding:14px 16px;margin:4px 0 14px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <span style="font-size:20px;line-height:1">${preset.icon}</span>
        <strong style="color:var(--fg);font-size:13px">${esc(preset.label)} Policy</strong>
        <span style="margin-left:auto;font-size:10px;color:${color};background:rgba(255,255,255,.06);padding:2px 8px;border-radius:4px">${esc(label)}</span>
      </div>
      <p style="color:var(--muted);font-size:11px;margin:0 0 8px;line-height:1.5">${esc(preset.description)}</p>
      <ul style="margin:0;padding-left:16px;color:var(--muted);font-size:10px;line-height:1.8">
        ${preset.bullets.map(b => `<li>${esc(b)}</li>`).join('')}
      </ul>
    </div>`;
}

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
    const windowLimit = (u.window_limit_wei || '0') === '0' ? '\u221E' : formatWei(u.window_limit_wei || '0');
    const windowSecs = u.window_seconds || 0;
    const windowLabel = windowSecs >= 3600 ? (windowSecs / 3600) + 'h' : windowSecs > 0 ? windowSecs + 's' : '—';
    const mode = (u.approval_mode || 'always_human')
      .replaceAll('_', ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
    const approvalThreshold = (u.approval_threshold_wei || '0') === '0'
      ? '\u2014'
      : formatWei(u.approval_threshold_wei || '0');
    const limits = `<span class="mono" style="font-size:9px">${maxTx} / ${daily}<br>${windowLimit} / ${windowLabel}<br>${rate}</span>`;

    const botPreset = BOT_POLICY_PRESETS[u.bot_type || 'personal'];
    const botIcon   = botPreset ? botPreset.icon + ' ' : '';
    const botLabel  = (u.bot_type || 'personal').replaceAll('_', ' ');
    const profile   = `<span class="badge badge-chain" style="white-space:nowrap">${botIcon}${esc(botLabel)}</span>`;
    const approval  = `<span class="mono" style="font-size:9px">${esc(mode)}<br>${approvalThreshold}</span>`;
    const goalText  = u.bot_goal
      ? `<br><span style="color:var(--cyan);font-size:9px;font-style:italic">${esc(u.bot_goal.length > 45 ? u.bot_goal.slice(0, 45) + '\u2026' : u.bot_goal)}</span>`
      : '';

    return `<tr>
      <td>${sBadge}<br>${tgBadge}</td>
      <td><strong>${esc(u.name)}</strong><br><span class="mono" style="color:var(--muted);font-size:9px">${u.id.slice(0, 8)}\u2026</span>${goalText}</td>
      <td>${profile}</td>
      <td class="mono" style="color:var(--cyan)">${u.api_key_prefix}\u2026</td>
      <td>${assets}</td>
      <td>${chains}</td>
      <td>${approval}</td>
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

// ── Create Agent Sub-Page Navigation ─────────────────────────────────
export function showCreateAgentPage() {
  document.getElementById('page-create-agent').style.display = '';
  document.getElementById('dash-grid').style.display = 'none';
  // Refresh preset + hints for current bot type selection
  const typeEl = document.getElementById('ag-bot-type');
  if (typeEl) applyBotTypePreset('ag', typeEl.value || 'personal');
}

export function hideCreateAgentPage() {
  document.getElementById('page-create-agent').style.display = 'none';
  document.getElementById('dash-grid').style.removeProperty('display');
}

// ── Selector State (asset/chain presets) ─────────────────────────────
export const selectorState = { assets: new Set(['*']), chains: new Set(['*']) };

// ── Contract Selector State ────────────────────────────────────────────
const contractState = {};

function _getContractState(prefix) {
  if (!contractState[prefix]) contractState[prefix] = new Set(['*']);
  return contractState[prefix];
}

export function toggleContract(btn, prefix) {
  const val = btn.dataset.val;
  const st  = _getContractState(prefix);
  if (val === '*') { st.clear(); st.add('*'); }
  else { st.delete('*'); st.has(val) ? st.delete(val) : st.add(val); if (st.size === 0) st.add('*'); }
  syncContractUI(prefix);
}

export function addCustomContract(prefix) {
  const input = document.getElementById(`${prefix}-contracts-custom`);
  const val   = input.value.trim();
  if (!val) return;
  const st = _getContractState(prefix);
  st.delete('*');
  st.add(val);
  input.value = '';
  syncContractUI(prefix);
}

export function removeContract(prefix, val) {
  const st = _getContractState(prefix);
  st.delete(val);
  if (st.size === 0) st.add('*');
  syncContractUI(prefix);
}

function syncContractUI(prefix) {
  const st      = _getContractState(prefix);
  const area    = document.getElementById(`${prefix}-contracts-area`);
  const hidden  = document.getElementById(`${prefix}-contracts-val`);
  const display = document.getElementById(`${prefix}-contracts-display`);
  if (!area) return;
  area.querySelectorAll('.preset-btn[data-val]').forEach(b => b.classList.toggle('selected', st.has(b.dataset.val)));
  if (hidden) hidden.value = JSON.stringify([...st]);
  if (display) {
    display.innerHTML = [...st].map(v => {
      if (v === '*') return '<span class="badge badge-wildcard">\u2731 ALL</span>';
      const short = v.length > 22 ? v.slice(0, 10) + '\u2026' + v.slice(-6) : v;
      return `<span class="badge badge-chain" style="font-family:monospace;font-size:9px">${esc(short)} <span style="cursor:pointer;margin-left:3px;opacity:.5" onclick="removeContract('${prefix}','${esc(v)}')">&times;</span></span>`;
    }).join('');
  }
}

function syncContractSelector(prefix, botType) {
  const preset    = BOT_POLICY_PRESETS[botType];
  const presetsEl = document.getElementById(`${prefix}-contracts-presets`);
  const labelEl   = document.getElementById(`${prefix}-contracts-label`);
  if (!presetsEl) return;

  if (labelEl) labelEl.textContent = preset ? preset.contractLabel : 'Allowed Contracts / Addresses';
  contractState[prefix] = new Set(['*']);

  const presets = preset ? preset.contractPresets : [];
  const wildBtn = `<span class="preset-btn wild selected" data-val="*" onclick="toggleContract(this,'${prefix}')">&#x2731; ALL</span>`;
  const presetBtns = presets.map(p =>
    `<span class="preset-btn chain" data-val="${esc(p.address)}" onclick="toggleContract(this,'${prefix}')" title="${esc(p.address)}">${esc(p.label)}</span>`
  ).join('');
  presetsEl.innerHTML = wildBtn + presetBtns;
  syncContractUI(prefix);
}

// ── Generate Policy (Z.AI) ────────────────────────────────────────────
export async function generatePolicy(prefix) {
  const btn  = document.getElementById(`${prefix}-generate-btn`);
  const goal = document.getElementById(`${prefix}-bot-goal`).value.trim();
  if (!goal || goal.length < 10) { toast('Add a more detailed bot goal first (10+ chars)', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '\u23F3 Generating\u2026';

  let allowed_assets = ['*'];
  let allowed_chains = ['*'];
  const assetsVal = document.getElementById(`${prefix}-assets-val`);
  const chainsVal = document.getElementById(`${prefix}-chains-val`);
  if (assetsVal) {
    try { allowed_assets = JSON.parse(assetsVal.value); } catch { /**/ }
  } else {
    const el = document.getElementById(`${prefix}-assets`);
    if (el) allowed_assets = el.value.split(',').map(s => s.trim()).filter(Boolean);
  }
  if (chainsVal) {
    try { allowed_chains = JSON.parse(chainsVal.value); } catch { /**/ }
  } else {
    const el = document.getElementById(`${prefix}-chains`);
    if (el) allowed_chains = el.value.split(',').map(s => s.trim()).filter(Boolean);
  }

  const body = {
    bot_goal: goal,
    bot_type: document.getElementById(`${prefix}-bot-type`).value,
    allowed_assets,
    allowed_chains,
  };

  try {
    const r = await fetch(`${API}/api-users/generate-policy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) { toast('Generation failed: ' + (data.detail || '?'), 'error'); return; }

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    set(`${prefix}-approval-mode`,      data.approval_mode);
    set(`${prefix}-approval-threshold`, data.approval_threshold_wei);
    set(`${prefix}-window-limit`,       data.window_limit_wei);
    set(`${prefix}-window-seconds`,     data.window_seconds);
    set(`${prefix}-max-tx`,             data.max_amount_wei);
    set(`${prefix}-daily`,              data.daily_limit_wei);

    // Update contract selector with AI suggestions
    const st = _getContractState(prefix);
    st.clear();
    (data.allowed_contracts || ['*']).forEach(c => st.add(c));

    const presetsEl = document.getElementById(`${prefix}-contracts-presets`);
    if (presetsEl) {
      const botType   = document.getElementById(`${prefix}-bot-type`).value;
      const botPreset = BOT_POLICY_PRESETS[botType];
      const existingPresets = botPreset ? botPreset.contractPresets : [];
      const existingAddrs   = new Set(existingPresets.map(p => p.address));
      const aiAddresses     = (data.allowed_contracts || []).filter(a => a !== '*');
      const allPresets      = [...existingPresets];
      aiAddresses.forEach(addr => {
        if (!existingAddrs.has(addr)) allPresets.push({ label: addr.slice(0, 10) + '\u2026', address: addr });
      });
      const wildSel = st.has('*') ? ' selected' : '';
      const wildBtn = `<span class="preset-btn wild${wildSel}" data-val="*" onclick="toggleContract(this,'${prefix}')">&#x2731; ALL</span>`;
      const presetBtns = allPresets.map(p => {
        const sel = st.has(p.address) ? ' selected' : '';
        return `<span class="preset-btn chain${sel}" data-val="${esc(p.address)}" onclick="toggleContract(this,'${prefix}')" title="${esc(p.address)}">${esc(p.label)}</span>`;
      }).join('');
      presetsEl.innerHTML = wildBtn + presetBtns;
    }
    syncContractUI(prefix);

    // Also update ed-contracts text field if present (edit modal simple input)
    const contractsText = document.getElementById(`${prefix}-contracts`);
    if (contractsText) {
      const vals = [..._getContractState(prefix)];
      contractsText.value = vals.join(',');
    }

    // Update allowed_assets
    if (data.allowed_assets) {
      const assetsValEl = document.getElementById(`${prefix}-assets-val`);
      if (assetsValEl) {
        // Create form: update selector state
        selectorState.assets = new Set(data.allowed_assets);
        syncSelectorUI('assets');
      } else {
        const assetsEl = document.getElementById(`${prefix}-assets`);
        if (assetsEl) assetsEl.value = data.allowed_assets.join(',');
      }
    }

    // Update allowed_chains
    if (data.allowed_chains) {
      const chainsValEl = document.getElementById(`${prefix}-chains-val`);
      if (chainsValEl) {
        selectorState.chains = new Set(data.allowed_chains);
        syncSelectorUI('chains');
      } else {
        const chainsEl = document.getElementById(`${prefix}-chains`);
        if (chainsEl) chainsEl.value = data.allowed_chains.join(',');
      }
    }

    renderAIGeneratedPreview(prefix, data);
    updateWeiHints(prefix);
    toast('Policy generated by ' + data.model_used, 'success');
  } catch (err) {
    toast('Network error: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '\u2728 Generate Policy';
  }
}

function renderAIGeneratedPreview(prefix, data) {
  const el = document.getElementById(`${prefix}-policy-preview`);
  if (!el) return;
  el.innerHTML = `
    <div style="background:rgba(6,182,212,.07);border:1px solid rgba(6,182,212,.25);border-radius:8px;padding:14px 16px;margin:4px 0 14px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <span style="font-size:16px">\u2728</span>
        <strong style="color:var(--cyan);font-size:13px">AI Generated Policy</strong>
        <span style="margin-left:auto;font-size:9px;color:var(--muted);background:rgba(255,255,255,.06);padding:2px 7px;border-radius:4px">${esc(data.model_used)}</span>
      </div>
      <p style="color:var(--fg);font-size:11px;margin:0 0 8px;line-height:1.5">${esc(data.policy_summary)}</p>
      <ul style="margin:0;padding-left:16px;color:var(--muted);font-size:10px;line-height:1.8">
        ${(data.reasoning || []).map(r => `<li>${esc(r)}</li>`).join('')}
      </ul>
    </div>`;
}

// ── Policy Chat ───────────────────────────────────────────────────────────────
const _chatState = { messages: [] };
const _CHAT_BOT_GREETING = "Hi! I'm your policy advisor. Let's set up your agent — what would you like to name it, and what type of bot is it? (e.g. trading bot, personal assistant, NFT sniper…)";

export function openPolicyChat() {
  _chatState.messages = [];
  document.getElementById('ag-chat-panel').style.display = '';
  _renderChatMessages(_chatState.messages);
  const inp = document.getElementById('ag-chat-input');
  if (inp) inp.focus();
}

export function closePolicyChat() {
  _chatState.messages = [];
  document.getElementById('ag-chat-panel').style.display = 'none';
}

export async function sendChatMessage() {
  const input = document.getElementById('ag-chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  input.disabled = true;

  const sendBtn = document.getElementById('ag-chat-send');
  if (sendBtn) sendBtn.disabled = true;

  // Optimistically show user message + thinking indicator
  _renderChatMessages([..._chatState.messages, { role: 'user', content: msg }], true);

  try {
    const r = await fetch(`${API}/api-users/policy-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
      body: JSON.stringify({ messages: _chatState.messages, user_message: msg }),
    });
    const data = await r.json();
    if (!r.ok) { toast('Chat error: ' + (data.detail || '?'), 'error'); _renderChatMessages(_chatState.messages); return; }

    _chatState.messages = data.messages;
    _renderChatMessages(_chatState.messages);

    if (data.type === 'draft') {
      _applyPolicyDraft(data.draft);
      toast('Agent policy ready! Review the form below.', 'success');
    }
  } catch (err) {
    toast('Network error: ' + err.message, 'error');
    _renderChatMessages(_chatState.messages);
  } finally {
    input.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
    input.focus();
  }
}

function _renderChatMessages(messages, pending = false) {
  const container = document.getElementById('ag-chat-messages');
  if (!container) return;

  const all = [{ role: 'assistant', content: _CHAT_BOT_GREETING }, ...messages];
  container.innerHTML = all.map(m => {
    const isBot = m.role === 'assistant';
    const align = isBot ? 'flex-start' : 'flex-end';
    const bg     = isBot ? 'rgba(6,182,212,.1)' : 'rgba(139,92,246,.15)';
    const border = isBot ? '1px solid rgba(6,182,212,.2)' : '1px solid rgba(139,92,246,.2)';
    return `<div style="display:flex;justify-content:${align};margin-bottom:8px">
      <div style="max-width:85%;background:${bg};border:${border};border-radius:10px;padding:8px 12px;font-size:12px;color:var(--fg);line-height:1.5">${esc(m.content)}</div>
    </div>`;
  }).join('') + (pending ? `<div style="display:flex;justify-content:flex-start;margin-bottom:8px">
    <div style="background:rgba(6,182,212,.1);border:1px solid rgba(6,182,212,.2);border-radius:10px;padding:8px 12px;font-size:12px;color:var(--muted)">⏳ Thinking…</div>
  </div>` : '');
  container.scrollTop = container.scrollHeight;
}

function _applyPolicyDraft(draft) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };

  if (draft.name) set('ag-name', draft.name);
  if (draft.bot_type) {
    set('ag-bot-type', draft.bot_type);
    applyBotTypePreset('ag', draft.bot_type);
  }
  if (draft.bot_goal) set('ag-bot-goal', draft.bot_goal);

  set('ag-approval-mode',      draft.approval_mode || 'always_human');
  set('ag-approval-threshold', draft.approval_threshold_wei || '0');
  set('ag-window-limit',       draft.window_limit_wei || '0');
  set('ag-window-seconds',     draft.window_seconds ?? 0);
  set('ag-max-tx',             draft.max_amount_wei || '0');
  set('ag-daily',              draft.daily_limit_wei || '0');

  if (draft.allowed_assets) {
    selectorState.assets = new Set(draft.allowed_assets);
    syncSelectorUI('assets');
  }
  if (draft.allowed_chains) {
    selectorState.chains = new Set(draft.allowed_chains);
    syncSelectorUI('chains');
  }
  if (draft.allowed_contracts) {
    const st = _getContractState('ag');
    st.clear();
    draft.allowed_contracts.forEach(c => st.add(c));
    syncContractUI('ag');
  }
  if (draft.reasoning || draft.policy_summary) {
    renderAIGeneratedPreview('ag', {
      model_used: 'Z.AI Chat',
      policy_summary: draft.policy_summary || '',
      reasoning: draft.reasoning || [],
    });
  }
  updateWeiHints('ag');
}

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
  setupBotTypePresetSync();
  document.getElementById('agentForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('agCreateBtn');
    btn.disabled = true;

    const body = {
      name:            document.getElementById('ag-name').value.trim(),
      telegram_chat_id: document.getElementById('ag-telegram-chat-id').value.trim(),
      bot_type:        document.getElementById('ag-bot-type').value,
      bot_goal:        document.getElementById('ag-bot-goal').value.trim(),
      allowed_assets:     JSON.parse(document.getElementById('ag-assets-val').value),
      allowed_chains:     JSON.parse(document.getElementById('ag-chains-val').value),
      allowed_contracts:  JSON.parse(document.getElementById('ag-contracts-val').value || '["*"]'),
      max_amount_wei:  document.getElementById('ag-max-tx').value || '0',
      daily_limit_wei: document.getElementById('ag-daily').value || '0',
      rate_limit:      parseInt(document.getElementById('ag-rate').value) || 0,
      approval_mode:   document.getElementById('ag-approval-mode').value,
      approval_threshold_wei: document.getElementById('ag-approval-threshold').value || '0',
      window_limit_wei: document.getElementById('ag-window-limit').value || '0',
      window_seconds: parseInt(document.getElementById('ag-window-seconds').value) || 0,
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
        hideCreateAgentPage();
        document.getElementById('agentForm').reset();
        applyBotTypePreset('ag', 'personal');
        selectorState.assets = new Set(['*']);
        selectorState.chains = new Set(['*']);
        syncSelectorUI('assets');
        syncSelectorUI('chains');
        syncContractSelector('ag', 'personal');
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
  document.getElementById('ed-bot-type').value = u.bot_type || 'personal';
  document.getElementById('ed-bot-goal').value = u.bot_goal || '';
  document.getElementById('ed-assets').value     = u.allowed_assets.join(',');
  document.getElementById('ed-chains').value     = u.allowed_chains.join(',');
  document.getElementById('ed-contracts').value  = (u.allowed_contracts || ['*']).join(',');
  document.getElementById('ed-max-tx').value = u.max_amount_wei;
  document.getElementById('ed-daily').value  = u.daily_limit_wei;
  document.getElementById('ed-rate').value   = u.rate_limit;
  document.getElementById('ed-approval-mode').value = u.approval_mode || 'always_human';
  document.getElementById('ed-approval-threshold').value = u.approval_threshold_wei || '0';
  document.getElementById('ed-window-limit').value = u.window_limit_wei || '0';
  document.getElementById('ed-window-seconds').value = u.window_seconds || 0;
  document.getElementById('ed-active').value = u.is_active ? 'true' : 'false';
  // Show policy preview and USD hints for the loaded values (no preset override)
  renderPolicyPreview('ed', u.bot_type || 'personal');
  updateWeiHints('ed');
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
      bot_type:        document.getElementById('ed-bot-type').value,
      bot_goal:        document.getElementById('ed-bot-goal').value.trim(),
      allowed_assets:     document.getElementById('ed-assets').value.split(',').map(s => s.trim()).filter(Boolean),
      allowed_chains:     document.getElementById('ed-chains').value.split(',').map(s => s.trim()).filter(Boolean),
      allowed_contracts:  document.getElementById('ed-contracts').value.split(',').map(s => s.trim()).filter(Boolean),
      max_amount_wei:  document.getElementById('ed-max-tx').value || '0',
      daily_limit_wei: document.getElementById('ed-daily').value || '0',
      rate_limit:      parseInt(document.getElementById('ed-rate').value) || 0,
      approval_mode:   document.getElementById('ed-approval-mode').value,
      approval_threshold_wei: document.getElementById('ed-approval-threshold').value || '0',
      window_limit_wei: document.getElementById('ed-window-limit').value || '0',
      window_seconds:  parseInt(document.getElementById('ed-window-seconds').value) || 0,
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

// ── Preset Helpers ───────────────────────────────────────────────────
function applyBotTypePreset(prefix, botType) {
  const preset = BOT_POLICY_PRESETS[botType];
  if (!preset) return;

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
  set(`${prefix}-approval-mode`,      preset.approval_mode);
  set(`${prefix}-approval-threshold`, preset.approval_threshold_wei);
  set(`${prefix}-window-limit`,       preset.window_limit_wei);
  set(`${prefix}-window-seconds`,     preset.window_seconds);

  // Auto-populate goal hint if blank or still matches another preset's hint
  const goalEl = document.getElementById(`${prefix}-bot-goal`);
  if (goalEl && preset.goalHint) {
    const current = goalEl.value.trim();
    const isPresetDefault = !current || Object.values(BOT_POLICY_PRESETS).some(p => p.goalHint === current);
    if (isPresetDefault) goalEl.value = preset.goalHint;
  }

  renderPolicyPreview(prefix, botType);
  updateWeiHints(prefix);
  syncContractSelector(prefix, botType);
}

function setupBotTypePresetSync() {
  // Create form
  const agEl = document.getElementById('ag-bot-type');
  if (agEl) {
    applyBotTypePreset('ag', agEl.value || 'personal');
    agEl.addEventListener('change', () => applyBotTypePreset('ag', agEl.value));
  }
  // Edit modal — auto-apply on type change
  const edEl = document.getElementById('ed-bot-type');
  if (edEl) {
    edEl.addEventListener('change', () => applyBotTypePreset('ed', edEl.value));
  }
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
window.fetchAgents         = fetchAgents;
window.togglePreset        = togglePreset;
window.addCustom           = addCustom;
window.removeSelected      = removeSelected;
window.toggleContract      = toggleContract;
window.addCustomContract   = addCustomContract;
window.removeContract      = removeContract;
window.generatePolicy      = generatePolicy;
window.openPolicyChat      = openPolicyChat;
window.closePolicyChat     = closePolicyChat;
window.sendChatMessage     = sendChatMessage;
window.openEdit            = openEdit;
window.closeEditModal      = closeEditModal;
window.closeKeyModal       = closeKeyModal;
window.copyKey             = copyKey;
window.regenKey            = regenKey;
window.deactivateAgent     = deactivateAgent;
window.activateAgent       = activateAgent;
window.showCreateAgentPage = showCreateAgentPage;
window.hideCreateAgentPage = hideCreateAgentPage;
