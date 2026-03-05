/*
 * ClawSafe Pay — Dashboard Utilities
 * Shared helper functions: escaping, toasts, formatting, badges.
 */

import { CHAINS } from './state.js';

// ── Escaping ─────────────────────────────────────────────────────────
export function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── Toast Notifications ──────────────────────────────────────────────
export function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => {
    el.style.animation = 'none';
    el.style.opacity = '0';
    el.style.transition = 'opacity .3s';
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

// ── Number / Wei Formatting ──────────────────────────────────────────
export function weiToDisplay(wei, chain) {
  const info = CHAINS[chain] || CHAINS.sepolia;
  return (Number(BigInt(wei)) / Math.pow(10, info.decimals)).toFixed(6) + ' ' + info.asset;
}

export function weiToEth(wei) {
  return Number(BigInt(wei)) / 1e18;
}

export function formatWei(wei) {
  try {
    const eth = Number(BigInt(wei)) / 1e18;
    if (eth >= 0.001) return eth.toFixed(4) + ' ETH';
  } catch { /* fallthrough */ }
  return wei + ' wei';
}

// ── Address / Hash Truncation ────────────────────────────────────────
export function shortAddr(a) {
  return a ? a.slice(0, 6) + '\u2026' + a.slice(-4) : '';
}

export function shortHash(h) {
  return h ? h.slice(0, 10) + '\u2026' + h.slice(-6) : '';
}

// ── Time ─────────────────────────────────────────────────────────────
export function timeAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

// ── Badge Renderers ──────────────────────────────────────────────────
export function chainBadge(c) {
  const info = CHAINS[c] || { name: c || 'sepolia' };
  return `<span class="chain-badge ${c || 'sepolia'}">${info.name}</span>`;
}

export function explorerLink(hash, chain) {
  if (!hash) return '\u2014';
  const info = CHAINS[chain] || CHAINS.sepolia;
  return `<a class="hash-link" href="${info.explorer}${hash}" target="_blank" rel="noopener">${shortHash(hash)}</a>`;
}

export function statusBadge(status) {
  const inProg = ['pending', 'building', 'reviewing'].includes(status);
  const pAuth = ['signing', 'pending_auth', 'approved'].includes(status);
  const conf = status === 'confirmed';
  const bcast = status === 'broadcast';
  let inner = '';
  if (inProg || bcast) inner = '<span class="status-spinner"></span>';
  else if (pAuth) inner = '<span class="status-pulse"></span>';
  else if (conf) inner = '<span class="status-check"></span>';
  return `<span class="status-badge status-${status}">${inner}${status.replace(/_/g, ' ')}</span>`;
}

// ── Animated Stat Counter ────────────────────────────────────────────
export function animStat(id, val) {
  const el = document.getElementById(id);
  const old = parseInt(el.textContent) || 0;
  if (old !== val) {
    el.textContent = val;
    el.style.transform = 'scale(1.15)';
    el.style.transition = 'transform .2s';
    setTimeout(() => (el.style.transform = 'scale(1)'), 200);
  }
}

// ── Widget Collapse ──────────────────────────────────────────────────
export function toggleWidget(btn) {
  const w = btn.closest('.widget');
  const body = w.querySelector('.wb');
  if (w.classList.contains('collapsed')) {
    w.classList.remove('collapsed');
    body.style.display = '';
    btn.textContent = '\u2212';
  } else {
    w.classList.add('collapsed');
    body.style.display = 'none';
    btn.textContent = '+';
  }
}

// Expose to inline onclick handlers
window.toggleWidget = toggleWidget;
