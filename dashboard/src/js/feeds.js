/*
 * ClawSafe Pay — Feeds Module
 * Crypto price ticker (with sparklines), crypto news, and Moltbook feed.
 */

import { esc } from './utils.js';

// ── Crypto Symbol Metadata ───────────────────────────────────────────
const CRYPTO_SYMBOLS = {
  bitcoin:        { icon: '\u20BF', name: 'Bitcoin',     sym: 'BTC',   color: '#f7931a' },
  ethereum:       { icon: '\u25C6', name: 'Ethereum',    sym: 'ETH',   color: '#627eea' },
  tether:         { icon: '\u20AE', name: 'Tether',      sym: 'USDT',  color: '#26a17b' },
  binancecoin:    { icon: '\u25C7', name: 'BNB',         sym: 'BNB',   color: '#f3ba2f' },
  solana:         { icon: '\u25CE', name: 'Solana',      sym: 'SOL',   color: '#9945ff' },
  'usd-coin':     { icon: '\u25CB', name: 'USD Coin',    sym: 'USDC',  color: '#2775ca' },
  ripple:         { icon: '\u2715', name: 'XRP',         sym: 'XRP',   color: '#00aae4' },
  cardano:        { icon: '\u2666', name: 'Cardano',     sym: 'ADA',   color: '#0033ad' },
  dogecoin:       { icon: '\u0110', name: 'Dogecoin',    sym: 'DOGE',  color: '#c2a633' },
  'staked-ether': { icon: '\u25C6', name: 'Lido stETH',  sym: 'stETH', color: '#00a3ff' },
};

// ── Sparkline Renderer ───────────────────────────────────────────────
function drawSparkline(canvas, data, isUp) {
  if (!canvas || !data || data.length < 2) return;
  const ctx = canvas.getContext('2d');
  const w = (canvas.width = 50), h = (canvas.height = 20);
  ctx.clearRect(0, 0, w, h);
  const min   = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const color = isUp ? 'rgba(16,185,129,0.8)' : 'rgba(239,68,68,0.8)';
  const grad  = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, isUp ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)');
  grad.addColorStop(1, 'transparent');
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 2) - 1;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.stroke();
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();
}

// ── Crypto Prices ────────────────────────────────────────────────────
export async function fetchCryptoPrices() {
  const el = document.getElementById('cryptoTicker');
  try {
    const r = await fetch('/crypto-prices');
    if (!r.ok) throw new Error(r.status);
    const coins = await r.json();
    if (!coins.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">\u20BF</div><p>No price data available</p></div>';
      return;
    }
    el.innerHTML = coins.slice(0, 10).map((c, idx) => {
      const meta   = CRYPTO_SYMBOLS[c.id] || { icon: '\u25CF', name: c.name, sym: c.symbol?.toUpperCase() || '?', color: 'var(--accent)' };
      const change = c.price_change_percentage_24h || 0;
      const isUp   = change >= 0;
      const usd    = c.current_price;
      const btcPrice = c.btc_price;
      const usdFmt = usd >= 1
        ? '$' + usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '$' + usd.toFixed(6);
      const btcFmt = btcPrice !== undefined
        ? (btcPrice < 0.0001 ? btcPrice.toExponential(2) : btcPrice.toFixed(6)) + ' BTC'
        : '';
      return `<div class="crypto-card">
        <span class="crypto-rank">#${c.market_cap_rank || idx + 1}</span>
        <div class="crypto-icon" style="background:${meta.color}15;color:${meta.color};font-weight:700;font-size:14px">
          ${c.image ? `<img src="${c.image}" alt="${esc(c.name)}" onerror="this.outerHTML='${meta.icon}'">` : meta.icon}
        </div>
        <div class="crypto-info">
          <div class="crypto-name">${esc(c.name)} <span class="sym">${meta.sym}</span></div>
          <div class="crypto-prices">
            <span class="crypto-usd">${usdFmt}</span>
            ${btcFmt ? `<span class="crypto-btc">${btcFmt}</span>` : ''}
          </div>
        </div>
        <div class="crypto-right">
          <span class="crypto-change ${isUp ? 'up' : 'down'}">${isUp ? '\u25B2' : '\u25BC'} ${Math.abs(change).toFixed(1)}%</span>
          <canvas class="crypto-sparkline" id="spark-${c.id}"></canvas>
        </div>
      </div>`;
    }).join('');
    // Draw sparklines
    coins.slice(0, 10).forEach(c => {
      const canvas = document.getElementById('spark-' + c.id);
      const data   = c.sparkline_in_7d?.price;
      if (canvas && data) drawSparkline(canvas, data.slice(-24), (c.price_change_percentage_24h || 0) >= 0);
    });
  } catch (e) {
    el.innerHTML = '<div class="empty-state"><div class="icon">\u26A0\uFE0F</div><p>Could not load crypto prices</p></div>';
    console.error('Crypto prices error:', e);
  }
}

// ── Crypto News ──────────────────────────────────────────────────────
export async function fetchCryptoNews() {
  const el = document.getElementById('cryptoNewsPosts');
  try {
    const r = await fetch('/crypto-news');
    if (!r.ok) throw new Error(r.status);
    const articles = await r.json();
    if (!articles.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">\uD83D\uDCF0</div><p>No news available</p></div>';
      return;
    }
    el.innerHTML = articles.map(a => {
      const srcClass = (a.source || '').toLowerCase().replace(/[^a-z]/g, '');
      return `<div class="news-item">
        <div class="news-title"><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a></div>
        <div class="news-meta">
          <span class="news-source ${srcClass}">${esc(a.source)}</span>
          ${a.author ? `<span>\uD83D\uDC64 ${esc(a.author)}</span>` : ''}
          ${a.age ? `<span>\u23F1 ${esc(a.age)}</span>` : ''}
        </div>
        ${a.snippet ? `<div class="news-snippet">${esc(a.snippet)}</div>` : ''}
        ${a.tags && a.tags.length ? `<div class="news-tags">${a.tags.slice(0, 4).map(t => `<span class="news-tag">${esc(t)}</span>`).join('')}</div>` : ''}
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty-state"><div class="icon">\u26A0\uFE0F</div><p>Could not load crypto news</p></div>';
    console.error('Crypto news error:', e);
  }
}

// ── Moltbook Feed ────────────────────────────────────────────────────
export async function fetchMoltbook() {
  const el = document.getElementById('moltbookPosts');
  try {
    const r = await fetch('/moltbook-feed');
    if (!r.ok) throw new Error(r.status);
    const posts = await r.json();
    if (!posts.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">\uD83D\uDC26</div><p>No finance posts found</p></div>';
      return;
    }
    el.innerHTML = posts.map(p => `
      <div class="mb-post">
        <div class="mb-post-title"><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></div>
        <div class="mb-post-meta">
          <span>\uD83D\uDC64 ${esc(p.author)}</span>
          ${p.submolt ? `<span class="mb-tag">${esc(p.submolt)}</span>` : ''}
          ${p.karma ? `<span class="mb-karma">\u25B2 ${p.karma}</span>` : ''}
          ${p.comments !== undefined ? `<span>\uD83D\uDCAC ${p.comments}</span>` : ''}
          ${p.age ? `<span>\u23F1 ${esc(p.age)}</span>` : ''}
        </div>
        ${p.snippet ? `<div class="mb-post-snippet">${esc(p.snippet)}</div>` : ''}
      </div>`).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty-state"><div class="icon">\u26A0\uFE0F</div><p>Could not load Moltbook feed</p></div>';
    console.error('Moltbook fetch error:', e);
  }
}

// Expose to inline onclick handlers
window.fetchCryptoPrices = fetchCryptoPrices;
window.fetchCryptoNews   = fetchCryptoNews;
window.fetchMoltbook     = fetchMoltbook;
