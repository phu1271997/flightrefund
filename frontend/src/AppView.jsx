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

function formatGen(wei) {
  if (!wei) return '0';
  const big = BigInt(wei);
  const whole = big / 10n ** 18n;
  const frac = big % 10n ** 18n;
  if (frac === 0n) return whole.toString();
  return `${whole}.${frac.toString().padStart(18, '0').slice(0, 4)}`;
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
  const [payoutGen, setPayoutGen] = useState('0.1');
  const [claimId, setClaimId] = useState('');
  const [policies, setPolicies] = useState([]);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [lastTxHash, setLastTxHash] = useState('');

  const readClient = useMemo(() => buildReadClient(), []);
  const writeClient = useMemo(
    () => (account ? buildWriteClient(account) : null),
    [account],
  );
  const configured = CONTRACT_ADDRESS && CONTRACT_ADDRESS !== '0x0000000000000000000000000000000000000000';

  const refresh = useCallback(async () => {
    if (!configured) return;
    try {
      const raw = await readClient.readContract({
        address: CONTRACT_ADDRESS,
        functionName: 'list_policies',
        args: [0n, 50n],
      });
      const parsed = JSON.parse(raw || '{"items": []}');
      setPolicies((parsed.items || []).slice().reverse());
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
          await writeClient.waitForTransactionReceipt({ hash, retries: 150, interval: 3000 });
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

  const doBuy = () => withTx('Buying policy…', async () => {
    const value = BigInt(Math.floor(parseFloat(payoutGen) * 1e18));
    if (value <= 0n) throw new Error('Payout must be > 0');
    const hash = await writeClient.writeContract({
      address: CONTRACT_ADDRESS,
      functionName: 'buy_policy',
      args: [flight.trim().toUpperCase(), flightDate, threshold],
      value,
    });
    setFlight('');
    setFlightDate('');
    return hash;
  });

  const doClaim = () => withTx(
    'Running validator consensus (fetching FlightAware + FlightRadar24, LLM voting)…',
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
        Buy a policy against a specific flight. When it lands, file a claim. Both flight
        tracking sites must agree on the delay bucket for the payout to release.
      </p>

      <div className="card">
        <div className="row">
          {account ? (
            <span>
              Connected: <code>{short(account)}</code> · chain <code>{CHAIN.name}</code>
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
        <h3>1 · Buy policy</h3>
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
        <label>Payout amount (GEN)</label>
        <input
          type="number"
          min="0"
          step="0.01"
          value={payoutGen}
          onChange={(e) => setPayoutGen(e.target.value)}
        />
        <button disabled={!account || !flight || !flightDate || !!busy} onClick={doBuy}>
          Lock premium &amp; buy
        </button>
      </div>

      <div className="card">
        <h3>2 · File a claim</h3>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 0 }}>
          Once the flight has landed (or been cancelled), file a claim by policy ID. The
          contract fetches both flight-tracking sites, extracts the delay bucket via LLM on
          each source, and only pays if the two sites agree. This takes 30–120 seconds
          because validators do real inference before consensus finalizes.
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
                {formatGen(p.payout)} GEN payout
              </span>
            </div>
            <div className="meta">
              flight <strong>{p.flight_number}</strong> on <strong>{p.flight_date}</strong> ·
              threshold {p.threshold}
            </div>
            <div className="meta">buyer: {short(p.buyer)}</div>
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
