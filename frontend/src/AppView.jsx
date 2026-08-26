import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  buildReadClient,
  buildWriteClient,
  connectWallet,
  ensureCorrectChain,
  CONTRACT_ADDRESS,
  CHAIN,
} from './client.js';

const WEI = 10n ** 18n;
const PREMIUM_RATE_BPS = 1000n; // 10% — mirrors contract constant

function formatGen(wei) {
  if (wei === undefined || wei === null) return '0';
  let big;
  try {
    big = BigInt(wei);
  } catch {
    return '0';
  }
  const whole = big / WEI;
  const frac = big % WEI;
  if (frac === 0n) return whole.toString();
  return `${whole}.${frac.toString().padStart(18, '0').slice(0, 4)}`;
}

function toWei(gen) {
  const val = parseFloat(gen);
  if (!(val > 0)) return 0n;
  return BigInt(Math.floor(val * 1e18));
}

function short(addr) {
  if (!addr) return '';
  return addr.slice(0, 6) + '…' + addr.slice(-4);
}

const THRESHOLDS = [
  { value: 'MINOR', label: 'MINOR — pay out if delay ≥ 15 minutes' },
  { value: 'MODERATE', label: 'MODERATE — pay out if delay ≥ 60 minutes' },
  { value: 'MAJOR', label: 'MAJOR — pay out if delay ≥ 120 minutes' },
];

const EXPLORER_TX = 'https://genlayer-explorer.vercel.app/tx/';

export default function AppView() {
  const [account, setAccount] = useState(null);
  const [flight, setFlight] = useState('');
  const [flightDate, setFlightDate] = useState('');
  const [threshold, setThreshold] = useState('MODERATE');
  const [coverageGen, setCoverageGen] = useState('0.5');
  const [claimId, setClaimId] = useState('');
  const [policies, setPolicies] = useState([]);
  const [pool, setPool] = useState({ balance: 0n, locked: 0n, available: 0n });
  const [ownerAddr, setOwnerAddr] = useState('');
  const [fundGen, setFundGen] = useState('1');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [lastTxHash, setLastTxHash] = useState('');

  const readClient = useMemo(() => buildReadClient(), []);
  const writeClient = useMemo(
    () => (account ? buildWriteClient(account) : null),
    [account],
  );
  const configured =
    CONTRACT_ADDRESS && CONTRACT_ADDRESS !== '0x0000000000000000000000000000000000000000';

  const coverageWei = useMemo(() => toWei(coverageGen), [coverageGen]);
  const premiumWei = useMemo(
    () => (coverageWei * PREMIUM_RATE_BPS + 9999n) / 10000n,
    [coverageWei],
  );
  const isOwner =
    account && ownerAddr && account.toLowerCase() === ownerAddr.toLowerCase();

  const refresh = useCallback(async () => {
    if (!configured) return;
    try {
      const [rawList, poolBal, locked, available, cfg] = await Promise.all([
        readClient.readContract({
          address: CONTRACT_ADDRESS,
          functionName: 'list_policies',
          args: [0n, 50n],
        }),
        readClient.readContract({
          address: CONTRACT_ADDRESS,
          functionName: 'get_pool_balance',
          args: [],
        }),
        readClient.readContract({
          address: CONTRACT_ADDRESS,
          functionName: 'get_locked_coverage',
          args: [],
        }),
        readClient.readContract({
          address: CONTRACT_ADDRESS,
          functionName: 'get_available_pool',
          args: [],
        }),
        readClient.readContract({
          address: CONTRACT_ADDRESS,
          functionName: 'get_config',
          args: [],
        }),
      ]);
      const parsed = JSON.parse(rawList || '{"items": []}');
      setPolicies((parsed.items || []).slice().reverse());
      setPool({
        balance: BigInt(poolBal || 0),
        locked: BigInt(locked || 0),
        available: BigInt(available || 0),
      });
      try {
        const conf = JSON.parse(cfg || '{}');
        if (conf.owner) setOwnerAddr(conf.owner);
      } catch {
        /* ignore */
      }
    } catch (err) {
      console.error(err);
    }
  }, [readClient, configured]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!window.ethereum) return;
    const handleAccountsChanged = (accounts) => {
      setAccount(accounts && accounts[0] ? accounts[0] : null);
    };
    const handleChainChanged = () => window.location.reload();
    window.ethereum.on?.('accountsChanged', handleAccountsChanged);
    window.ethereum.on?.('chainChanged', handleChainChanged);
    return () => {
      window.ethereum.removeListener?.('accountsChanged', handleAccountsChanged);
      window.ethereum.removeListener?.('chainChanged', handleChainChanged);
    };
  }, []);

  const doConnect = async () => {
    setError('');
    try {
      const addr = await connectWallet();
      setAccount(addr);
    } catch (err) {
      setError(err.message || String(err));
    }
  };

  const withTx = async (label, fn) => {
    setError('');
    setBusy(label);
    setLastTxHash('');
    try {
      await ensureCorrectChain();
      const hash = await fn();
      if (hash) {
        setLastTxHash(hash);
        try {
          await writeClient.waitForTransactionReceipt({
            hash,
            retries: 150,
            interval: 3000,
          });
        } catch (waitErr) {
          console.warn('waitForTransactionReceipt fell short — polling refresh anyway', waitErr);
        }
      }
      await refresh();
    } catch (err) {
      console.error(err);
      setError(err.shortMessage || err.message || String(err));
    } finally {
      setBusy('');
    }
  };

  const doBuy = () => withTx('Purchasing coverage (checking purchase window on-chain)…', async () => {
    if (coverageWei <= 0n) throw new Error('Coverage must be > 0');
    if (coverageWei > pool.available) {
      throw new Error('Requested coverage exceeds the pool\'s available capacity');
    }
    const hash = await writeClient.writeContract({
      address: CONTRACT_ADDRESS,
      functionName: 'buy_policy',
      args: [flight.trim().toUpperCase(), flightDate, threshold, coverageWei.toString()],
      value: premiumWei,
    });
    setFlight('');
    setFlightDate('');
    return hash;
  });

  const doClaim = () => withTx(
    'Running validator consensus (checking claim window, fetching FlightAware + FlightRadar24, LLM voting)…',
    async () => {
      const hash = await writeClient.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'file_claim',
        args: [claimId.trim()],
        value: 0n,
      });
      setClaimId('');
      return hash;
    },
  );

  const doFundPool = () => withTx('Funding pool…', async () => {
    const wei = toWei(fundGen);
    if (wei <= 0n) throw new Error('Fund amount must be > 0');
    const hash = await writeClient.writeContract({
      address: CONTRACT_ADDRESS,
      functionName: 'fund_pool',
      args: [],
      value: wei,
    });
    return hash;
  });

  return (
    <main>
      {!configured && (
        <div className="status-bar">
          VITE_CONTRACT_ADDRESS is not set — configure it in Vercel or copy .env.example to .env.local.
        </div>
      )}
      <nav className="app-nav">
        <Link to="/" className="back-link">← Boarding info</Link>
        <span className="brand-tag">☁ studionet · chainId {CHAIN.id}</span>
      </nav>
      <h1>Coverage Terminal</h1>
      <p className="tag">
        The insurer funds the pool; the buyer pays a small premium and receives
        coverage from the pool if the delay meets the threshold. Purchase and
        claim windows and per-flight verdict binding are all enforced on-chain.
      </p>

      <div className="card">
        <div className="row">
          {account ? (
            <span>
              Connected: <code>{short(account)}</code>
              {isOwner && (
                <span className="pill" style={{ marginLeft: 8, background: '#dcfce7', color: '#166534' }}>
                  pool owner
                </span>
              )}
              {' · chain '}<code>{CHAIN.name}</code>
            </span>
          ) : (
            <button onClick={doConnect}>Connect MetaMask</button>
          )}
          {configured && (
            <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontSize: 13 }}>
              Contract: <code>{short(CONTRACT_ADDRESS)}</code>
            </span>
          )}
        </div>
        {error && <p style={{ color: 'var(--bad)', marginTop: 10 }}>{error}</p>}
        {busy && (
          <p style={{ color: 'var(--muted)', marginTop: 10 }}>
            {busy}<span className="spinner" />
          </p>
        )}
        {lastTxHash && (
          <p style={{ marginTop: 10, fontSize: 13 }}>
            Latest tx:{' '}
            <a href={EXPLORER_TX + lastTxHash} target="_blank" rel="noreferrer">
              {short(lastTxHash)}
            </a>
          </p>
        )}
      </div>

      <div className="card">
        <h3>Coverage pool</h3>
        <div className="row" style={{ gap: 20, flexWrap: 'wrap' }}>
          <span>Pool balance: <strong>{formatGen(pool.balance)} GEN</strong></span>
          <span>Locked: <strong>{formatGen(pool.locked)} GEN</strong></span>
          <span>Available: <strong>{formatGen(pool.available)} GEN</strong></span>
          {ownerAddr && (
            <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontSize: 13 }}>
              Insurer: <code>{short(ownerAddr)}</code>
            </span>
          )}
        </div>
        {isOwner && (
          <div className="row" style={{ marginTop: 12, gap: 10 }}>
            <input
              type="number"
              min="0"
              step="0.01"
              value={fundGen}
              onChange={(e) => setFundGen(e.target.value)}
              placeholder="GEN to add"
              style={{ maxWidth: 160 }}
            />
            <button disabled={!!busy} onClick={doFundPool}>
              Fund pool
            </button>
          </div>
        )}
        {!isOwner && account && (
          <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 8 }}>
            Only the pool owner can top up capital. Buyers pay only the premium.
          </p>
        )}
      </div>

      <div className="card">
        <h3>1 · Buy coverage</h3>
        <div className="grid-2">
          <div>
            <label>Flight number</label>
            <input placeholder="VN123" value={flight} onChange={(e) => setFlight(e.target.value)} />
          </div>
          <div>
            <label>Flight date (UTC)</label>
            <input type="date" value={flightDate} onChange={(e) => setFlightDate(e.target.value)} />
          </div>
        </div>
        <label>Delay threshold</label>
        <select value={threshold} onChange={(e) => setThreshold(e.target.value)}>
          {THRESHOLDS.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <label>Coverage you want if the flight is delayed (GEN)</label>
        <input
          type="number"
          min="0"
          step="0.01"
          value={coverageGen}
          onChange={(e) => setCoverageGen(e.target.value)}
        />
        <p style={{ color: 'var(--muted)', fontSize: 13, margin: '6px 0 0' }}>
          Premium you pay now (locked in pool): <strong>{formatGen(premiumWei)} GEN</strong> · Coverage
          the pool locks for you: <strong>{formatGen(coverageWei)} GEN</strong>. Must be purchased at
          least 1 day before the flight.
        </p>
        <button
          disabled={!account || !flight || !flightDate || !!busy}
          onClick={doBuy}
        >
          Pay premium &amp; lock coverage
        </button>
      </div>

      <div className="card">
        <h3>2 · File a claim</h3>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 0 }}>
          Claims open the day after the flight date and stay open for 30 days.
          The contract fetches both flight-tracking sites, extracts the delay
          bucket via LLM on each, and only pays out when both sources agree on
          the exact dated flight. Consensus takes 30–120 seconds.
        </p>
        <label>Policy ID</label>
        <input value={claimId} onChange={(e) => setClaimId(e.target.value)} placeholder="1" />
        <button disabled={!account || !claimId || !!busy} onClick={doClaim}>
          Run validator consensus
        </button>
      </div>

      <div className="card">
        <h3>Policies</h3>
        {policies.length === 0 && <p style={{ color: 'var(--muted)' }}>No policies yet.</p>}
        {policies.map((p) => (
          <div key={p.id} className="policy">
            <div className="row">
              <strong>#{p.id}</strong>
              <span className={`pill ${p.status}`}>{p.status}</span>
              {p.bucket && (
                <span
                  className="pill"
                  style={{ background: '#1e2c47', color: '#a5b4fc' }}
                >
                  delay: {p.bucket}
                </span>
              )}
              <span style={{ marginLeft: 'auto', color: 'var(--muted)' }}>
                {formatGen(p.coverage)} GEN coverage · premium {formatGen(p.premium)} GEN
              </span>
            </div>
            <div className="meta">
              flight <strong>{p.flight_number}</strong> on <strong>{p.flight_date}</strong> ·
              threshold {p.threshold}
            </div>
            <div className="meta">buyer: {short(p.buyer)}</div>
            {p.purchased_on && (
              <div className="meta">purchased on: {p.purchased_on}{p.claimed_on ? ` · claimed on: ${p.claimed_on}` : ''}</div>
            )}
            {p.sources && Object.keys(p.sources).length > 0 && (
              <div className="meta">
                sources:{' '}
                {Object.entries(p.sources)
                  .map(([k, v]) => `${k}=${v.bucket}(${v.delay_minutes}m)`)
                  .join(' · ')}{' '}
                · agreed: {p.sources_agreed ? 'yes' : 'no'}
              </div>
            )}
            {p.reason && (
              <div className="reason">
                <strong>Verdict:</strong> {p.reason}
              </div>
            )}
          </div>
        ))}
      </div>

      <footer style={{ marginTop: 40, color: 'var(--muted)', fontSize: 12, textAlign: 'center' }}>
        Powered by{' '}
        <a href="https://genlayer.com" target="_blank" rel="noreferrer">
          GenLayer
        </a>{' '}
        Intelligent Contracts on {CHAIN.name}
      </footer>
    </main>
  );
}
