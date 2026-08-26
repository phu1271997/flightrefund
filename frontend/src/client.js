import { createClient } from 'genlayer-js';
import { studionet } from 'genlayer-js/chains';

// Default address is the v2 contract on studionet (premium/coverage split,
// on-chain purchase + claim windows, per-flight verdict binding).
// Override at build time with VITE_CONTRACT_ADDRESS for a fresh redeploy.
const DEFAULT_CONTRACT_ADDRESS = '0x85e2A1a66F6d91138DFc76C12fb7c226AFd03C20';
export const CONTRACT_ADDRESS =
  import.meta.env.VITE_CONTRACT_ADDRESS || DEFAULT_CONTRACT_ADDRESS;
export const CHAIN = studionet;
export const CHAIN_ID_HEX = '0x' + CHAIN.id.toString(16);

export async function ensureCorrectChain() {
  if (!window.ethereum) throw new Error('MetaMask not detected. Install it from https://metamask.io.');
  try {
    await window.ethereum.request({
      method: 'wallet_switchEthereumChain',
      params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (err) {
    if (err.code === 4902 || err.code === -32603) {
      await window.ethereum.request({
        method: 'wallet_addEthereumChain',
        params: [{
          chainId: CHAIN_ID_HEX,
          chainName: CHAIN.name || 'GenLayer Studio Network',
          nativeCurrency: { name: 'GEN Token', symbol: 'GEN', decimals: 18 },
          rpcUrls: [CHAIN.rpcUrls?.default?.http?.[0] || 'https://studio.genlayer.com/api'],
          blockExplorerUrls: ['https://genlayer-explorer.vercel.app'],
        }],
      });
    } else {
      throw err;
    }
  }
}

export async function connectWallet() {
  if (!window.ethereum) throw new Error('MetaMask not detected. Install it from https://metamask.io.');
  const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
  if (!accounts.length) throw new Error('No account returned');
  await ensureCorrectChain();
  return accounts[0];
}

export function buildReadClient() {
  return createClient({ chain: CHAIN });
}

export function buildWriteClient(userAddress) {
  return createClient({
    chain: CHAIN,
    account: userAddress,
    provider: window.ethereum,
  });
}
