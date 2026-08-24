import { Link } from 'react-router-dom';
import { CONTRACT_ADDRESS, CHAIN } from './client.js';

function short(addr) {
  if (!addr) return '';
  return addr.slice(0, 6) + '…' + addr.slice(-4);
}

const HOW_STEPS = [
  {
    n: '01',
    title: 'Purchase a policy',
    body:
      'Pick a flight number, a date, and how long the delay must be before you get paid. Lock the payout amount into the contract as your premium.',
  },
  {
    n: '02',
    title: 'Fly your flight',
    body:
      'The policy sits on-chain until you file a claim. Nothing happens automatically — you decide when to trigger settlement.',
  },
  {
    n: '03',
    title: 'File your claim',
    body:
      'The Intelligent Contract fetches flightaware.com AND flightradar24.com directly on-chain and asks two independent validator LLMs to extract the delay bucket from each page.',
  },
  {
    n: '04',
    title: 'Settle in seconds',
    body:
      'Both sources agree and the delay meets your threshold → the payout is released to your wallet. They disagree → the policy is marked UNRESOLVED, funds stay safe.',
  },
];

const BUCKETS = [
  { name: 'ON_TIME', range: '< 15 min', color: '#a7f3d0' },
  { name: 'MINOR', range: '15–59 min', color: '#7dd3fc' },
  { name: 'MODERATE', range: '60–119 min', color: '#fcd34d' },
  { name: 'MAJOR', range: '120–299 min', color: '#fb923c' },
  { name: 'SEVERE', range: '300 min +', color: '#f87171' },
  { name: 'CANCELLED', range: 'did not fly', color: '#c084fc' },
];

const FAQS = [
  {
    q: 'Is this actually insurance?',
    a: 'Parametric coverage, technically. There is no claims adjuster and no policy underwriting — the payout formula and trigger are both encoded in the contract. What you buy is a right to a specific payout if a specific, publicly verifiable event happens.',
  },
  {
    q: 'What if the tracking sites are wrong?',
    a: 'If FlightAware and FlightRadar24 return different delay buckets, the contract does NOT pay out. It marks the policy UNRESOLVED and preserves the funds. This is intentional — silent auto-pay on disputed data is what breaks trust in parametric products.',
  },
  {
    q: 'Why not just call the FlightStats API off-chain?',
    a: 'Because that would put a trusted operator between you and the payout. On GenLayer, the contract reads the public web pages itself, and many validator LLMs each parse the pages and vote. No one operator can lie about the data.',
  },
  {
    q: 'What GenLayer feature makes this possible?',
    a: 'gl.nondet.web.render + gl.nondet.exec_prompt inside a gl.vm.run_nondet block. Web reads happen on-chain during consensus; every validator does the same fetch and runs the same LLM, then votes.',
  },
];

export default function LandingPage() {
  return (
    <div className="lp">
      <div className="lp__sky" aria-hidden="true">
        <div className="cloud cloud--1" />
        <div className="cloud cloud--2" />
        <div className="cloud cloud--3" />
        <div className="plane">✈</div>
      </div>

      <header className="lp__nav">
        <div className="lp-brand">
          <span className="lp-brand__mark">✈</span>
          <span className="lp-brand__name">FlightRefund</span>
        </div>
        <nav className="lp-nav-links">
          <a href="#how" className="lp-nav-link">How it works</a>
          <a href="#buckets" className="lp-nav-link">Coverage</a>
          <a href="#faq" className="lp-nav-link">FAQ</a>
          <a
            href="https://github.com/phu1271997/flightrefund"
            target="_blank"
            rel="noreferrer"
            className="lp-nav-link"
          >
            GitHub
          </a>
          <Link to="/app" className="lp-btn lp-btn--primary lp-btn--sm">
            Launch app →
          </Link>
        </nav>
      </header>

      <section className="lp-hero">
        <div className="lp-hero__copy">
          <span className="lp-chip">Powered by GenLayer · studionet</span>
          <h1>
            Flight delayed? <br />
            <em>The chain pays you.</em>
          </h1>
          <p>
            FlightRefund is parametric coverage that settles itself. No insurance company, no
            paid oracle, no claim form. When your flight is late, the Intelligent Contract
            checks two independent flight-tracking sites on-chain — and pays if they agree.
          </p>
          <div className="lp-hero__cta">
            <Link to="/app" className="lp-btn lp-btn--primary">
              Launch app →
            </Link>
            <a
              href="https://github.com/phu1271997/flightrefund"
              target="_blank"
              rel="noreferrer"
              className="lp-btn lp-btn--ghost"
            >
              Read the source
            </a>
          </div>
          <p className="lp-hero__meta">
            Contract <code>{short(CONTRACT_ADDRESS)}</code> · chain{' '}
            <code>{CHAIN.name}</code>
          </p>
        </div>

        <div className="lp-hero__pass">
          <div className="pass">
            <div className="pass__header">
              <span className="pass__label">Boarding Pass</span>
              <span className="pass__brand">✈ FR</span>
            </div>
            <div className="pass__grid">
              <div className="pass__field">
                <span>Passenger</span>
                <strong>YOU</strong>
              </div>
              <div className="pass__field">
                <span>Flight</span>
                <strong>VN 123</strong>
              </div>
              <div className="pass__field">
                <span>Date</span>
                <strong>2026‑09‑01</strong>
              </div>
              <div className="pass__field">
                <span>Threshold</span>
                <strong>MODERATE</strong>
              </div>
            </div>
            <div className="pass__route">
              <div className="pass__airport">
                <strong>HAN</strong>
                <span>Hanoi</span>
              </div>
              <div className="pass__line">
                <div className="pass__line-bar" />
                <span className="pass__plane">✈</span>
              </div>
              <div className="pass__airport">
                <strong>SIN</strong>
                <span>Singapore</span>
              </div>
            </div>
            <div className="pass__stub">
              <div className="pass__stub-field">
                <span>Payout on delay ≥ 60 min</span>
                <strong>0.50 GEN</strong>
              </div>
              <div className="pass__barcode">||| |||| ||| ||||| ||| |||| ||</div>
            </div>
          </div>
        </div>
      </section>

      <section className="lp-section" id="how">
        <div className="lp-section__lead">
          <span className="lp-eyebrow">Flow</span>
          <h2>Four steps, one flight</h2>
          <p>
            You interact with two on-chain actions: buying a policy, and filing a claim.
            Everything else — data collection, delay classification, cross-source
            agreement, payout — happens inside the Intelligent Contract.
          </p>
        </div>
        <ol className="lp-steps">
          {HOW_STEPS.map((s) => (
            <li key={s.n} className="lp-step">
              <span className="lp-step__n">{s.n}</span>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="lp-section lp-section--buckets" id="buckets">
        <div className="lp-section__lead">
          <span className="lp-eyebrow">Coverage tiers</span>
          <h2>What counts as “delayed”</h2>
          <p>
            The contract classifies actual arrival delay into buckets. You pick your
            threshold at purchase — if the actual bucket meets or exceeds it, you get paid.
          </p>
        </div>
        <div className="bucket-strip">
          {BUCKETS.map((b) => (
            <div key={b.name} className="bucket" style={{ borderColor: b.color }}>
              <span className="bucket__name" style={{ color: b.color }}>{b.name}</span>
              <span className="bucket__range">{b.range}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-section lp-section--dual">
        <div className="dual-card">
          <span className="lp-eyebrow">Two independent sources</span>
          <h2>Cross-source consensus, on-chain</h2>
          <p>
            Every claim triggers two web fetches — flightaware.com and flightradar24.com —
            inside the contract. A validator LLM classifies each page independently. The
            payout only runs when the two sites agree on the same bucket. If they disagree,
            no one loses: the policy is frozen as <code>UNRESOLVED</code> and can be refunded.
          </p>
          <div className="dual-visual">
            <div className="dual-tile">
              <span className="dual-tile__badge">SOURCE A</span>
              <strong>flightaware.com</strong>
              <span className="dual-tile__value">MAJOR · 180 min</span>
            </div>
            <div className="dual-vs">≡</div>
            <div className="dual-tile">
              <span className="dual-tile__badge">SOURCE B</span>
              <strong>flightradar24.com</strong>
              <span className="dual-tile__value">MAJOR · 185 min</span>
            </div>
          </div>
          <div className="dual-agree">
            <span>Sources agree — verdict <code>MAJOR</code></span>
            <span>Payout released ✓</span>
          </div>
        </div>
      </section>

      <section className="lp-section lp-section--faq" id="faq">
        <div className="lp-section__lead">
          <span className="lp-eyebrow">FAQ</span>
          <h2>Straightforward questions, straightforward answers</h2>
        </div>
        <div className="faq-grid">
          {FAQS.map((f) => (
            <article key={f.q} className="faq">
              <h3>{f.q}</h3>
              <p>{f.a}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="lp-cta">
        <div className="lp-cta__inner">
          <h2>Try it on studionet</h2>
          <p>
            Bring a MetaMask wallet funded on GenLayer studionet. Pick a real recent
            flight. Buy a small policy. File a claim. Watch validator LLMs settle it in
            about a minute.
          </p>
          <Link to="/app" className="lp-btn lp-btn--primary lp-btn--lg">
            Launch app →
          </Link>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-footer__cols">
          <div>
            <div className="lp-brand">
              <span className="lp-brand__mark">✈</span>
              <span className="lp-brand__name">FlightRefund</span>
            </div>
            <p>
              Submitted to the GenLayer Foundation Builders program. Live on studionet
              — chain id {CHAIN.id}.
            </p>
          </div>
          <div>
            <h4>Contract</h4>
            <p>
              <a
                href={`https://genlayer-explorer.vercel.app/address/${CONTRACT_ADDRESS}`}
                target="_blank"
                rel="noreferrer"
              >
                <code>{CONTRACT_ADDRESS}</code>
              </a>
            </p>
          </div>
          <div>
            <h4>Links</h4>
            <ul>
              <li>
                <a href="https://github.com/phu1271997/flightrefund" target="_blank" rel="noreferrer">
                  GitHub
                </a>
              </li>
              <li>
                <a href="https://genlayer.com" target="_blank" rel="noreferrer">
                  GenLayer
                </a>
              </li>
              <li>
                <a href="https://docs.genlayer.com" target="_blank" rel="noreferrer">
                  Docs
                </a>
              </li>
            </ul>
          </div>
        </div>
        <p className="lp-footer__copy">© 2026 · Built on GenLayer studionet</p>
      </footer>
    </div>
  );
}
