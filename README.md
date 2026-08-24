# FlightRefund

**Parametric flight-delay coverage on GenLayer studionet. No oracle, no insurer.**

Buy a policy against a specific flight. When it lands (or is cancelled), file a
claim. The GenLayer Intelligent Contract fetches
[flightaware.com](https://www.flightaware.com) and
[flightradar24.com](https://www.flightradar24.com) directly on-chain, has
validator LLMs extract the delay bucket from each page, and only releases the
payout when both sources agree.

- **Track:** Agentic Economy + Subjective Consensus
- **Network:** GenLayer studionet only (`https://studio.genlayer.com`)
- **Submit through:** [GenLayer Portal · Builders track](https://portal.genlayer.foundation/#/builders/contributions)

---

## Why it dies without GenLayer

- Traditional parametric flight insurance depends on a paid data provider
  (FlightStats / OAG). That's a trusted middleman between the smart contract
  and reality.
- Off-chain LLM parsing of flight-tracker pages would need a trusted operator
  to run it. Same problem.
- GenLayer lets the contract **read the pages itself** with `gl.nondet.web.render`
  and lets **many validator LLMs** each parse the pages and vote. No oracle in
  the loop.
- The cross-source rule (both sites must agree on the bucket) makes it robust
  to any one site being flaky, misconfigured, or manipulated.

## Consensus design

The contract uses `gl.vm.run_nondet(leader_fn, validator_fn)`. The leader:

1. Fetches the FlightAware and FlightRadar24 pages via `gl.nondet.web.render`.
2. Calls the LLM once per source with a strict prompt that returns
   `{"bucket": "ON_TIME"|"MINOR"|"MODERATE"|"MAJOR"|"SEVERE"|"CANCELLED"|"UNKNOWN", "delay_minutes": int}`.
3. If both sources return the same bucket → that bucket is the verdict, `sources_agreed = true`.
4. If only one source is available (the other 404'd or timed out) → that bucket, `sources_agreed = false`.
5. If they disagree or both are UNKNOWN → verdict is UNKNOWN.

The validator re-runs the same fetch + double LLM and **only compares two
values**: the final `bucket` and the `sources_agreed` boolean. Two validators
producing different `delay_minutes` still pass consensus as long as they bucket
to the same tier — the bucket is the semantic verdict, the minutes are prose.

Payout policy:

| Contract verdict | Payout | Policy status |
|---|---|---|
| `bucket >= threshold` and `sources_agreed = true` | Full payout to buyer | `PAID` |
| `bucket < threshold` and `sources_agreed = true` | Premium to pool | `REJECTED` |
| `sources_agreed = false` **or** `bucket = UNKNOWN` | Nothing | `UNRESOLVED` (manual refund available) |

The `UNRESOLVED` escape hatch is important: parametric insurance that
silently pays or silently rejects on data outage is broken. The contract
freezes the policy for the pool owner to refund manually. No consumer loses
funds because two websites disagreed.

Delay buckets:

| Bucket | Minutes |
|---|---|
| ON_TIME | < 15 |
| MINOR | 15 – 59 |
| MODERATE | 60 – 119 |
| MAJOR | 120 – 299 |
| SEVERE | 300 + |
| CANCELLED | flight did not operate |

Users choose their own threshold at purchase: `MINOR`, `MODERATE`, or `MAJOR`.

## Repository layout

```
FlightRefund/
├── contracts/
│   └── flight_refund.py     # The Intelligent Contract
├── tests/
│   ├── conftest.py
│   └── test_flight_refund.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── client.js
│   │   ├── main.jsx
│   │   └── styles.css
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── .env.example
├── scripts/
│   └── deploy/
│       └── DEPLOY.md
└── README.md
```

---

## Deployment on GenLayer studionet

### 1. Fund a wallet on studionet

Add the GenLayer studionet to MetaMask (the app does it automatically on
Connect if the network is not present):

| Field | Value |
|---|---|
| Chain ID | `61999` (hex `0xF1EF`) |
| RPC | `https://studio.genlayer.com/api` |
| Symbol | `GEN` |
| Explorer | `https://genlayer-explorer.vercel.app` |

Then, in <https://studio.genlayer.com>, open the **Accounts** panel and
transfer GEN from a pre-funded studio account to your MetaMask address. Do
NOT use the testnet faucet — testnet and studionet are separate networks.

### 2. Deploy the contract

Preferred: use GenLayer Studio.

1. Open <https://studio.genlayer.com/contracts>.
2. New contract → paste the contents of `contracts/flight_refund.py`.
3. Deploy. After the tx shows `Status: FINALIZED`, click it and confirm
   `Result: SUCCESS` in the sidebar.
4. Copy the contract address.

Alternative CLI:

```bash
npm install -g @genlayer/cli
genlayer deploy contracts/flight_refund.py --network studionet
```

### 3. Wire the frontend

```bash
cd frontend
cp .env.example .env.local
# paste the deployed address into VITE_CONTRACT_ADDRESS
npm install
npm run dev
```

Open <http://localhost:5174>. Connect MetaMask (funded on studionet):

1. **Buy policy** — pick a real flight (past or upcoming), lock some GEN.
2. **File a claim** — after the flight has landed (or been cancelled), paste
   the policy ID. Wait for validator consensus.
3. Watch the policy card update with each source's extracted delay bucket
   and the final verdict.

### 4. Deploy the frontend

```bash
cd frontend
npm run build
# deploy /dist to Vercel or Netlify
```

Set `VITE_CONTRACT_ADDRESS` on your hosting provider.

---

## Local test loop

```bash
pip install genlayer-test
gltest tests/ --network localnet
```

Tests cover:

| Case | Expectation |
|---|---|
| Both sources agree on MAJOR, threshold MODERATE | `PAID` |
| Sources disagree | `UNRESOLVED` |
| Both sources agree on MINOR, threshold MODERATE | `REJECTED` |
| Both sources agree on CANCELLED | `PAID` regardless of threshold |
| Invalid flight number | rejected on `buy_policy` |
| Zero payout | rejected |
| Invalid threshold | rejected |

Mocks are keyed per source pattern (`.*flightaware.*` vs `.*flightradar24.*`)
so a single test can drive the two sources into agreement or disagreement.

---

## Deployed contract

- **Network:** GenLayer studionet (chainId `61999`)
- **Contract address:** [`0x4630f73C3B07F36a479d27369e3229414e6d11eE`](https://genlayer-explorer.vercel.app/address/0x4630f73C3B07F36a479d27369e3229414e6d11eE)

---

## What is not in scope

- Actuarial pricing: buyers set their own payout amount and threshold. A real
  product would have a premium curve based on route history.
- Cross-currency payouts: everything is denominated in GEN.
- Airline-provided evidence: the contract only consumes public web pages.
