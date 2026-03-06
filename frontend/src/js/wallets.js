/*
 * ClawSafe Pay — Wallet Module
 * Wallet management (add, delete, set default) and balance display.
 */

import { API, API_KEY, state } from './state.js';
import { esc, toast, shortAddr, weiToEth } from './utils.js';

// ── Fetch wallets (for tx form dropdown) ─────────────────────────────
export async function fetchWallets() {
  try {
    const r = await fetch(`${API}/wallets`, { headers: { 'X-API-Key': API_KEY } });
    if (!r.ok) return;
    const data = await r.json();
    const sel  = document.getElementById('tx-wallet');
    sel.innerHTML = '';
    if (data.wallets && data.wallets.length) {
      data.wallets.forEach(addr => {
        const opt  = document.createElement('option');
        opt.value  = addr;
        const isDef = addr.toLowerCase() === (data.default || '').toLowerCase();
        opt.textContent = shortAddr(addr) + (isDef ? ' (default)' : '');
        if (isDef) opt.selected = true;
        sel.appendChild(opt);
      });
    } else {
      sel.innerHTML = '<option value="">Default wallet</option>';
    }
    // Keep agent instruction dropdown in sync
    const aiSel = document.getElementById('ai-wallet');
    if (aiSel) aiSel.innerHTML = sel.innerHTML;
  } catch (e) { console.error('Fetch wallets:', e); }
}

// ── Managed Wallets ──────────────────────────────────────────────────
export async function fetchManagedWallets() {
  try {
    const r = await fetch(`${API}/wallets/managed`, { headers: { 'X-API-Key': API_KEY } });
    if (!r.ok) return;
    state.managedWallets = await r.json();
    renderWalletList();
  } catch (e) { console.error('Fetch managed wallets:', e); }
}

export function renderWalletList() {
  const container = document.getElementById('walletList');
  const empty     = document.getElementById('walletEmpty');
  const count     = document.getElementById('walletCount');
  count.textContent = state.managedWallets.length;

  if (!state.managedWallets.length) {
    empty.style.display = 'block';
    container.innerHTML = '';
    container.appendChild(empty);
    return;
  }
  empty.style.display = 'none';

  container.innerHTML = state.managedWallets.map(w => `
    <div class="wallet-card ${w.is_default ? 'is-default' : ''}">
      <div class="wallet-icon">\uD83D\uDC5B</div>
      <div class="wallet-info">
        <div class="wallet-addr">${esc(w.address)}</div>
        <div class="wallet-meta">
          ${w.label ? `<span class="wallet-label-tag">${esc(w.label)}</span>` : ''}
          ${w.is_default ? '<span class="wallet-default-tag">\u2605 DEFAULT</span>' : ''}
          <span>${esc(w.chain)}</span>
        </div>
      </div>
      <div class="wallet-actions">
        ${!w.is_default ? `<button class="w-btn" onclick="setDefaultWallet('${esc(w.id)}')" title="Set as default">\u2605</button>` : ''}
        <button class="w-btn" onclick="deleteWallet('${esc(w.id)}')" title="Delete" style="color:var(--red)">\u2715</button>
      </div>
    </div>
  `).join('');
}

// ── Add Wallet Form ──────────────────────────────────────────────────
export function setupWalletForm() {
  document.getElementById('walletForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('wlAddBtn');
    btn.disabled = true;
    btn.textContent = 'Adding\u2026';

    try {
      const r = await fetch(`${API}/wallets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify({
          address:     document.getElementById('wl-address').value.trim(),
          private_key: document.getElementById('wl-privkey').value.trim(),
          label:       document.getElementById('wl-label').value.trim(),
          chain:       document.getElementById('wl-chain').value,
        }),
      });
      const data = await r.json();
      if (r.ok) {
        toast('\u2713 Wallet added', 'success');
        document.getElementById('walletForm').reset();
        fetchManagedWallets();
        fetchWallets();
        fetchWalletBalances();
      } else {
        toast(`\u2717 ${data.detail || JSON.stringify(data)}`, 'error');
      }
    } catch (err) {
      toast(`\u2717 Network error: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '\uD83D\uDC5B Add Wallet';
    }
  });
}

// ── Delete / Default ─────────────────────────────────────────────────
export async function deleteWallet(walletId) {
  if (!confirm('Delete this wallet? This cannot be undone.')) return;
  try {
    const r = await fetch(`${API}/wallets/${walletId}`, {
      method: 'DELETE', headers: { 'X-API-Key': API_KEY },
    });
    if (r.ok) {
      toast('Wallet deleted', 'success');
      fetchManagedWallets();
      fetchWallets();
      fetchWalletBalances();
    } else {
      const data = await r.json();
      toast(`\u2717 ${data.detail || 'Delete failed'}`, 'error');
    }
  } catch (err) { toast(`\u2717 ${err.message}`, 'error'); }
}

export async function setDefaultWallet(walletId) {
  try {
    const r = await fetch(`${API}/wallets/${walletId}/set-default`, {
      method: 'POST', headers: { 'X-API-Key': API_KEY },
    });
    if (r.ok) {
      toast('Default wallet updated', 'success');
      fetchManagedWallets();
      fetchWallets();
    } else {
      const data = await r.json();
      toast(`\u2717 ${data.detail || 'Failed'}`, 'error');
    }
  } catch (err) { toast(`\u2717 ${err.message}`, 'error'); }
}

// ── Private Key Visibility Toggle ────────────────────────────────────
export function togglePrivKeyVisibility() {
  const input = document.getElementById('wl-privkey');
  const eye   = document.getElementById('wl-eye');
  if (input.type === 'password') {
    input.type = 'text';
    eye.textContent = '\uD83D\uDE48';
  } else {
    input.type = 'password';
    eye.textContent = '\uD83D\uDC41';
  }
}

// ── Wallet Balances ──────────────────────────────────────────────────
export async function fetchWalletBalances() {
  try {
    const r = await fetch(`${API}/wallets/balances`, { headers: { 'X-API-Key': API_KEY } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const balances = await r.json();
    renderWalletBalances(balances);
  } catch (e) {
    console.error('Fetch balances:', e);
    const el = document.getElementById('balancesList');
    el.innerHTML = '<div class="empty-state"><div class="icon">\u26A0\uFE0F</div><p>Could not load balances</p></div>';
  }
}

export function renderWalletBalances(balances) {
  const el    = document.getElementById('balancesList');
  const empty = document.getElementById('balancesEmpty');

  if (!balances.length) {
    empty.style.display = 'block';
    el.innerHTML = '';
    el.appendChild(empty);
    return;
  }
  empty.style.display = 'none';

  let totalEth = 0;
  balances.forEach(b => {
    if (b.balance_display !== 'error') totalEth += parseFloat(b.balance_display);
  });

  let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:4px 0;border-bottom:1px solid var(--border)">
    <span style="font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:600">${balances.length} wallet${balances.length !== 1 ? 's' : ''}</span>
    <span style="font-size:12px;font-weight:700;color:var(--green);font-family:'JetBrains Mono','Fira Code',monospace">${totalEth.toFixed(6)} ETH total</span>
  </div>`;

  html += balances.map(b => {
    const isError  = b.balance_display === 'error';
    const balFloat = isError ? 0 : parseFloat(b.balance_display);
    const valColor = isError ? 'var(--red)' : balFloat > 0 ? 'var(--green)' : 'var(--muted)';

    return `<div class="balance-card">
      <div class="balance-icon">\uD83D\uDC8E</div>
      <div class="balance-info">
        <div class="balance-label">${b.label || shortAddr(b.address)}</div>
        <div class="balance-addr">${shortAddr(b.address)} \u00B7 ${esc(b.chain)}</div>
      </div>
      <div class="balance-amount">
        <div class="balance-value" style="color:${valColor}">${isError ? 'Error' : b.balance_display}</div>
        <div class="balance-symbol">${isError ? '' : b.symbol}</div>
      </div>
    </div>`;
  }).join('');

  el.innerHTML = html;
}

// Expose to inline onclick handlers
window.fetchWallets             = fetchWallets;
window.fetchManagedWallets      = fetchManagedWallets;
window.fetchWalletBalances      = fetchWalletBalances;
window.deleteWallet             = deleteWallet;
window.setDefaultWallet         = setDefaultWallet;
window.togglePrivKeyVisibility  = togglePrivKeyVisibility;
