/*
 * ClawSafe Pay — Finance Analytics Module
 * Budget tracker, spend forecast, and cost breakdown.
 */

import { CHAINS, state } from './state.js';
import { esc, weiToEth } from './utils.js';

// ── Main entry point ─────────────────────────────────────────────────
export function renderFinanceWidgets() {
  renderBudgetTracker();
  renderForecast();
  renderCostBreakdown();
}

// ── Budget Tracker ───────────────────────────────────────────────────
function renderBudgetTracker() {
  const barsEl   = document.getElementById('budgetBars');
  const alertsEl = document.getElementById('budgetAlerts');
  const agents   = state.agents.filter(a => a.is_active);

  if (!agents.length) {
    barsEl.innerHTML   = '<div class="empty-state"><div class="icon">\uD83D\uDCB0</div><p>No active agents configured</p></div>';
    alertsEl.innerHTML = '';
    return;
  }

  const today = new Date().toISOString().slice(0, 10);
  let alertHtml = '';
  let barsHtml  = '';

  agents.forEach(agent => {
    const intents        = state.agentIntents[agent.id] || [];
    const todayConfirmed = intents.filter(i =>
      i.status === 'confirmed' && i.created_at && i.created_at.slice(0, 10) === today
    );
    const todaySpend = todayConfirmed.reduce((s, i) => s + weiToEth(i.amount_wei || '0'), 0);
    const totalSpend = intents
      .filter(i => i.status === 'confirmed')
      .reduce((s, i) => s + weiToEth(i.amount_wei || '0'), 0);

    const hasBudget   = agent.daily_limit_wei !== '0';
    const dailyBudget = hasBudget ? weiToEth(agent.daily_limit_wei) : 0;
    const pct         = hasBudget ? (todaySpend / dailyBudget) * 100 : 0;
    const pctDisplay  = hasBudget ? Math.min(pct, 999).toFixed(1) : '\u2014';

    let barClass = 'ok', pctColor = 'var(--green)';
    if (pct > 100)     { barClass = 'over';   pctColor = 'var(--red)'; }
    else if (pct > 80) { barClass = 'danger'; pctColor = 'var(--red)'; }
    else if (pct > 60) { barClass = 'warn';   pctColor = 'var(--amber)'; }

    if (hasBudget && pct > 100) {
      alertHtml += `<div class="alert-row alert-danger">\u26A0\uFE0F ${esc(agent.name)} exceeded daily budget (${pct.toFixed(0)}%)</div>`;
    } else if (hasBudget && pct > 80) {
      alertHtml += `<div class="alert-row alert-warn">\u26A0 ${esc(agent.name)} approaching budget limit (${pct.toFixed(0)}%)</div>`;
    }

    barsHtml += `<div class="budget-bar-wrap">
      <div class="budget-bar-label">
        <span class="budget-bar-name">${esc(agent.name)}</span>
        <span class="budget-bar-pct" style="color:${hasBudget ? pctColor : 'var(--muted)'}">${hasBudget ? pctDisplay + '%' : 'No limit'}</span>
      </div>
      ${hasBudget
        ? `<div class="budget-bar"><div class="budget-bar-fill ${barClass}" style="width:${Math.min(pct, 100)}%"></div></div>`
        : `<div class="budget-bar"><div class="budget-bar-fill ok" style="width:0%"></div></div>`}
      <div class="budget-bar-detail">Today: ${todaySpend.toFixed(4)} ETH${hasBudget ? ' / ' + dailyBudget.toFixed(4) + ' ETH limit' : ''} \u00B7 All-time: ${totalSpend.toFixed(4)} ETH \u00B7 ${intents.length} txns</div>
    </div>`;
  });

  alertsEl.innerHTML = alertHtml;
  barsEl.innerHTML   = barsHtml || '<div class="empty-state"><div class="icon">\uD83D\uDCB0</div><p>No active agents</p></div>';
}

// ── Spend Forecast ───────────────────────────────────────────────────
function renderForecast() {
  const el        = document.getElementById('forecastContent');
  const confirmed = state.intents.filter(i => i.status === 'confirmed');

  if (!confirmed.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">\uD83D\uDCC8</div><p>No confirmed transactions for forecast</p></div>';
    return;
  }

  const dailySpend = {};
  confirmed.forEach(i => {
    const day = i.created_at ? i.created_at.slice(0, 10) : 'unknown';
    dailySpend[day] = (dailySpend[day] || 0) + weiToEth(i.amount_wei);
  });

  const days       = Object.keys(dailySpend).sort();
  const totalSpend = confirmed.reduce((s, i) => s + weiToEth(i.amount_wei), 0);
  const firstDate  = new Date(days[0]);
  const lastDate   = new Date(days[days.length - 1]);
  const activeDays = Math.max(1, Math.ceil((lastDate - firstDate) / 86400000) + 1);

  const dailyBurnRate      = totalSpend / activeDays;
  const weeklyProjected    = dailyBurnRate * 7;
  const monthlyProjected   = dailyBurnRate * 30;
  const quarterlyProjected = dailyBurnRate * 90;

  const recentDays = days.slice(-3);
  const prevDays   = days.slice(-6, -3);
  const recentAvg  = recentDays.reduce((s, d) => s + (dailySpend[d] || 0), 0) / Math.max(recentDays.length, 1);
  const prevAvg    = prevDays.length ? prevDays.reduce((s, d) => s + (dailySpend[d] || 0), 0) / prevDays.length : recentAvg;

  let trendClass = 'trend-flat', trendIcon = '\u2192', trendLabel = 'Stable';
  if (prevAvg > 0) {
    const change = ((recentAvg - prevAvg) / prevAvg) * 100;
    if (change > 10)  { trendClass = 'trend-up';   trendIcon = '\u2191'; trendLabel = '+' + change.toFixed(0) + '%'; }
    else if (change < -10) { trendClass = 'trend-down'; trendIcon = '\u2193'; trendLabel = change.toFixed(0) + '%'; }
  }

  const totalDailyBudget = state.agents
    .filter(a => a.is_active && a.daily_limit_wei !== '0')
    .reduce((s, a) => s + weiToEth(a.daily_limit_wei), 0);
  const budgetUtil = totalDailyBudget > 0 ? ((dailyBurnRate / totalDailyBudget) * 100).toFixed(1) : null;
  const avgTxSize  = totalSpend / confirmed.length;
  const maxTx      = Math.max(...confirmed.map(i => weiToEth(i.amount_wei)));

  el.innerHTML = `
    <div class="kpi-row">
      <div class="kpi-mini"><div class="kpi-mini-val" style="color:var(--accent2)">${dailyBurnRate.toFixed(4)}</div><div class="kpi-mini-label">ETH/Day</div></div>
      <div class="kpi-mini"><div class="kpi-mini-val" style="color:var(--purple)">${avgTxSize.toFixed(4)}</div><div class="kpi-mini-label">Avg Tx Size</div></div>
      <div class="kpi-mini"><div class="kpi-mini-val" style="color:var(--amber)">${maxTx.toFixed(4)}</div><div class="kpi-mini-label">Largest Tx</div></div>
    </div>
    <div class="forecast-metric">
      <div><div class="fm-label">Daily Burn Rate</div><div class="fm-sub">${activeDays} day${activeDays > 1 ? 's' : ''} active</div></div>
      <div style="text-align:right"><div class="fm-value">${dailyBurnRate.toFixed(4)} <span style="font-size:10px;color:var(--muted)">ETH</span></div>
        <span class="trend-indicator ${trendClass}">${trendIcon} ${trendLabel}</span></div>
    </div>
    <div class="forecast-metric">
      <div><div class="fm-label">7-Day Projected</div></div>
      <div class="fm-value" style="color:var(--amber)">${weeklyProjected.toFixed(4)} <span style="font-size:10px;color:var(--muted)">ETH</span></div>
    </div>
    <div class="forecast-metric">
      <div><div class="fm-label">30-Day Projected</div></div>
      <div class="fm-value" style="color:var(--purple)">${monthlyProjected.toFixed(4)} <span style="font-size:10px;color:var(--muted)">ETH</span></div>
    </div>
    <div class="forecast-metric">
      <div><div class="fm-label">90-Day Projected (Quarter)</div></div>
      <div class="fm-value" style="color:var(--cyan)">${quarterlyProjected.toFixed(4)} <span style="font-size:10px;color:var(--muted)">ETH</span></div>
    </div>
    <div class="forecast-metric">
      <div><div class="fm-label">Total Confirmed Spend</div><div class="fm-sub">${confirmed.length} transactions</div></div>
      <div class="fm-value" style="color:var(--green)">${totalSpend.toFixed(4)} <span style="font-size:10px;color:var(--muted)">ETH</span></div>
    </div>
    ${budgetUtil !== null ? `<div class="forecast-metric">
      <div><div class="fm-label">Budget Utilization Rate</div><div class="fm-sub">Burn vs. ${totalDailyBudget.toFixed(4)} ETH daily limit</div></div>
      <div class="fm-value" style="color:${parseFloat(budgetUtil) > 90 ? 'var(--red)' : parseFloat(budgetUtil) > 70 ? 'var(--amber)' : 'var(--green)'}">${budgetUtil}%</div>
    </div>` : `<div class="forecast-metric">
      <div><div class="fm-label">Budget Utilization</div></div>
      <div class="fm-value" style="color:var(--muted)">\u2014 no budgets set</div>
    </div>`}`;
}

// ── Cost Breakdown ───────────────────────────────────────────────────
function renderCostBreakdown() {
  const el = document.getElementById('costBreakdown');
  if (!el) return;
  const confirmed = state.intents.filter(i => i.status === 'confirmed');

  if (!confirmed.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">\uD83D\uDCCA</div><p>No confirmed spend data</p></div>';
    return;
  }

  const byChain = {};
  confirmed.forEach(i => {
    const chain = i.chain || 'sepolia';
    byChain[chain] = (byChain[chain] || 0) + weiToEth(i.amount_wei);
  });

  const byAgent = {};
  for (const agent of state.agents) {
    const aIntents = (state.agentIntents[agent.id] || []).filter(i => i.status === 'confirmed');
    if (aIntents.length) {
      byAgent[agent.name] = aIntents.reduce((s, i) => s + weiToEth(i.amount_wei || '0'), 0);
    }
  }

  const totalSpend   = confirmed.reduce((s, i) => s + weiToEth(i.amount_wei), 0);
  const chainColors  = { sepolia: 'var(--accent)', base: 'var(--blue)', solana: 'var(--purple)', bitcoin: 'var(--amber)', cardano: 'var(--cyan)' };
  const agentColors  = ['var(--accent)', 'var(--cyan)', 'var(--purple)', 'var(--amber)', 'var(--pink)', 'var(--green)'];

  let html = '<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:6px">By Chain</div>';

  Object.entries(byChain).sort((a, b) => b[1] - a[1]).forEach(([chain, spend]) => {
    const pct   = totalSpend > 0 ? (spend / totalSpend) * 100 : 0;
    const color = chainColors[chain] || 'var(--muted)';
    html += `<div class="cost-row">
      <span class="cost-label" style="color:${color}">${(CHAINS[chain] || { name: chain }).name}</span>
      <div class="cost-bar-wrap"><div class="cost-bar-fill" style="width:${pct}%;background:${color}"></div></div>
      <span class="cost-value">${spend.toFixed(4)} ETH</span>
    </div>`;
  });

  if (Object.keys(byAgent).length) {
    html += '<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin:12px 0 6px">By Agent</div>';
    Object.entries(byAgent).sort((a, b) => b[1] - a[1]).forEach(([name, spend], idx) => {
      const pct   = totalSpend > 0 ? (spend / totalSpend) * 100 : 0;
      const color = agentColors[idx % agentColors.length];
      html += `<div class="cost-row">
        <span class="cost-label">${esc(name)}</span>
        <div class="cost-bar-wrap"><div class="cost-bar-fill" style="width:${pct}%;background:${color}"></div></div>
        <span class="cost-value">${spend.toFixed(4)} ETH</span>
      </div>`;
    });
  }

  const agentIntentIds = new Set();
  Object.values(state.agentIntents).flat().forEach(i => { if (i.intent_id) agentIntentIds.add(i.intent_id); });
  const adminSpend = confirmed.filter(i => !agentIntentIds.has(i.intent_id)).reduce((s, i) => s + weiToEth(i.amount_wei), 0);
  if (adminSpend > 0) {
    const pct = totalSpend > 0 ? (adminSpend / totalSpend) * 100 : 0;
    html += `<div class="cost-row">
      <span class="cost-label" style="color:var(--amber)">Admin (Direct)</span>
      <div class="cost-bar-wrap"><div class="cost-bar-fill" style="width:${pct}%;background:var(--amber)"></div></div>
      <span class="cost-value">${adminSpend.toFixed(4)} ETH</span>
    </div>`;
  }

  const byAsset = {};
  confirmed.forEach(i => {
    const asset = i.asset || 'ETH';
    byAsset[asset] = (byAsset[asset] || 0) + weiToEth(i.amount_wei);
  });
  if (Object.keys(byAsset).length > 1) {
    html += '<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin:12px 0 6px">By Asset</div>';
    const assetColors = { ETH: 'var(--accent)', USDC: 'var(--green)', USDT: 'var(--cyan)', SOL: 'var(--purple)', BTC: 'var(--amber)' };
    Object.entries(byAsset).sort((a, b) => b[1] - a[1]).forEach(([asset, spend]) => {
      const pct   = totalSpend > 0 ? (spend / totalSpend) * 100 : 0;
      const color = assetColors[asset] || 'var(--muted)';
      html += `<div class="cost-row">
        <span class="cost-label" style="color:${color}">${esc(asset)}</span>
        <div class="cost-bar-wrap"><div class="cost-bar-fill" style="width:${pct}%;background:${color}"></div></div>
        <span class="cost-value">${spend.toFixed(4)} ETH</span>
      </div>`;
    });
  }

  el.innerHTML = html;
}
