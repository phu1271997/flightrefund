import { createClient } from 'genlayer-js';
import { studionet } from 'genlayer-js/chains';

export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS;
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
