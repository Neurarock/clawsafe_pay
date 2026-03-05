/*
 * ClawSafe Pay — Dashboard Entry Point
 * Imports all modules, initialises the UI, and starts polling loops.
 */

import { state }                                       from './state.js';
import './utils.js';                                    // exposes toggleWidget on window
import { initTheme, setupThemeClickOutside }           from './theme.js';
import { fetchIntents, setupTxForm }                   from './transactions.js';
import {
  fetchAgents, setupSelectorInputs, setupAgentForm,
  setupEditForm,
}                                                      from './agents.js';
import {
  fetchWallets, fetchManagedWallets,
  fetchWalletBalances, setupWalletForm,
}                                                      from './wallets.js';
import './monitor.js';                                  // exposes fetchAllAgentIntents, renderMonitor
import { renderFinanceWidgets }                        from './finance.js';
import {
  fetchMoltbook, fetchCryptoPrices, fetchCryptoNews,
}                                                      from './feeds.js';
import { initParticles }                               from './particles.js';

// ── Clock ────────────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('liveClock');
  if (el) el.textContent = new Date().toISOString().slice(11, 19) + ' UTC';
}

// ── Bootstrap ────────────────────────────────────────────────────────
initTheme();
setupThemeClickOutside();
initParticles();
setInterval(updateClock, 1000);
updateClock();

document.addEventListener('DOMContentLoaded', () => {
  // Wire up forms
  setupTxForm();
  setupAgentForm();
  setupEditForm();
  setupWalletForm();
  setupSelectorInputs();

  // Initial data fetches
  fetchWallets();
  fetchManagedWallets();
  fetchWalletBalances();
  fetchIntents();
  fetchAgents();
  fetchMoltbook();
  fetchCryptoPrices();
  fetchCryptoNews();

  // Polling intervals
  state.pollTimer = setInterval(() => { fetchIntents(); }, 10000);
  setInterval(fetchMoltbook, 60000);
  setInterval(fetchCryptoPrices, 60000);
  setInterval(fetchCryptoNews, 120000);
  setInterval(renderFinanceWidgets, 30000);
  setInterval(fetchWalletBalances, 60000);
});
