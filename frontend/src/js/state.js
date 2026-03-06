/*
 * ClawSafe Pay — Dashboard State & Configuration
 * Shared state object and chain configuration used across all modules.
 */

export const API = window.__CLAWSAFE_API || window.location.origin;
export const API_KEY = window.__CLAWSAFE_API_KEY || 'change-me-publisher-key';
export const DEFAULT_AGENT_KEY = window.__CLAWSAFE_DEFAULT_AGENT_KEY || '';

export const CHAINS = {
  sepolia: { name: 'Sepolia', asset: 'ETH', explorer: 'https://sepolia.etherscan.io/tx/', decimals: 18 },
  base:    { name: 'Base',    asset: 'ETH', explorer: 'https://sepolia.basescan.org/tx/',  decimals: 18 },
  solana:  { name: 'Solana',  asset: 'SOL', explorer: 'https://explorer.solana.com/tx/',    decimals: 9  },
  bitcoin: { name: 'Bitcoin', asset: 'BTC', explorer: 'https://mempool.space/tx/',          decimals: 8  },
};

export const state = {
  intents: [],
  agents: [],
  agentIntents: {},
  managedWallets: [],
  filter: 'all',
  prevStatuses: {},
  intentCounter: 0,
  pollTimer: null,
  fastPollCount: 0,
};
