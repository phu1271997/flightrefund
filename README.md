# FlightRefund

**Parametric flight-delay coverage on GenLayer studionet. Pooled insurer capital, on-chain time windows, verdicts bound to the exact dated flight.**

- **Live app:** <https://flightrefund-genlayer.vercel.app>
- **Contract:** deploy fresh from `contracts/flight_refund.py` to GenLayer studionet, then set `VITE_CONTRACT_ADDRESS`.
- **Repo:** <https://github.com/phu1271997/flightrefund>

Buy coverage against a specific dated flight. You pay a small premium; the insurer's pool provides the coverage. After the flight lands (or is cancelled), file a claim. The Intelligent Contract fetches [flightaware.com](https://www.flightaware.com) and [flightradar24.com](https://www.flightradar24.com) directly on-chain, has validator LLMs classify the delay bucket for **that exact dated flight** on each page, and only releases the coverage when both sources agree.

- **Track:** Agentic Economy + Subjective Consensus
- **Network:** GenLayer studionet only (`https://studio.genlayer.com`)
- **Submit through:** [GenLayer Portal · Builders track](https://portal.genlayer.foundation/#/builders/contributions)

---

## Why it dies without GenLayer

- Traditional parametric flight insurance depends on a paid data provider (FlightStats / OAG). That's a trusted middleman between the smart contract and reality.
- Off-chain LLM parsing of flight-tracker pages would need a trusted operator to run it. Same problem.
- GenLayer lets the contract **read the pages itself** with `gl.nondet.web.render` and lets **many validator LLMs** each parse the pages and vote. No oracle in the loop.
- The cross-source rule (both sites must agree on the bucket for the same dated flight) makes it robust to any one site being flaky, misconfigured, or manipulated.
- The purchase and claim windows are enforced by a second on-chain nondet block that reads a public UTC time source — no external oracle needed for time either.

---

## What changed in v2 (grader feedback)

The reviewer flagged three areas. Each is now enforced on-chain:

| Concern | Where it's enforced |
|---|---|
| **Separate premium from insurer-funded coverage** | `fund_pool` / `pool_balance` / `locked_coverage` on the contract. Buyer's `msg.value` is the *premium* (≥ 10% of coverage); the coverage itself is provided by the pool. Payout comes from the pool, not from the buyer. |
| **Enforce purchase and claim windows** | Both `buy_policy` and `file_claim` fetch UTC today via `gl.eq_principle.strict_eq(...)` on a public time API. Purchase requires flight_date to be ≥ 1 day in the future. Claim requires flight_date ≤ today ≤ flight_date + 30 days. |
| **Bind each verdict to the exact dated flight** | Prompt forces the LLM to emit `flight_match` / `date_match` / `completed`. If any is false, `_normalize_source` collapses the bucket to `UNKNOWN`. Two validators seeing "different dated instance of VN123" both return UNKNOWN → policy is `UNRESOLVED`, not silently paid. |

---

## Consensus design

The contract uses `gl.vm.run_nondet(leader_fn, validator_fn)`. The leader:

1. Fetches the FlightAware and FlightRadar24 pages via `gl.nondet.web.render`.
2. Calls the LLM once per source with a strict prompt that returns `{"flight_match": bool, "date_match": bool, "completed": bool, "bucket": ..., "delay_minutes": int}`.
3. `_normalize_source` forces bucket to `UNKNOWN` unless all three flags are true. This is what binds the verdict to the exact dated flight.
4. If both sources return the same bucket → that bucket is the verdict, `sources_agreed = true`.
5. If only one source is available (the other 404'd or timed out) → that bucket, `sources_agreed = false`.
6. If they disagree or both are UNKNOWN → verdict is UNKNOWN.

The validator re-runs the same fetch + double LLM and only compares two values: the final `bucket` and the `sources_agreed` boolean. Two validators producing different `delay_minutes` still pass consensus as long as they bucket to the same tier — the bucket is the semantic verdict, the minutes are prose.

### Coverage / premium mechanics

| Buyer verdict | Money flow |
|---|---|
| `bucket >= threshold` and `sources_agreed = true` | Pool sends `coverage` to buyer. `pool_balance -= coverage`. Premium stays in pool as insurer income. Status `PAID`. |
| `bucket < threshold` and `sources_agreed = true` | Coverage returned to pool availability (`locked_coverage -= coverage`). Premium stays in pool as insurer income. Status `REJECTED`. |
| `sources_agreed = false` or `bucket = UNKNOWN` | Nothing sent. Coverage stays locked. Owner may call `resolve_unresolved` to refund the premium and unlock coverage. Status `UNRESOLVED` → `CANCELLED`. |

### Delay buckets

| Bucket | Minutes |
|---|---|
| ON_TIME | < 15 |
| MINOR | 15 – 59 |
| MODERATE | 60 – 119 |
| MAJOR | 120 – 299 |
| SEVERE | 300 + |
| CANCELLED | flight did not operate |

Users choose their own threshold at purchase: `MINOR`, `MODERATE`, or `MAJOR`.

### On-chain time windows

- **Purchase window:** today (UTC, from `worldtimeapi.org` via `strict_eq`) + 1 day ≤ `flight_date`.
- **Claim window:** `flight_date` ≤ today ≤ `flight_date` + 30 days.

Both use `gl.eq_principle.strict_eq(...)` — every validator fetches the same URL and must return the same `YYYY-MM-DD`. If the time source is unreachable, the transaction reverts with a clear error and can be retried; nothing goes through with unknown time.

---

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
│   │   ├── AppView.jsx
│   │   ├── LandingPage.jsx
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

Add the GenLayer studionet to MetaMask (the app does it automatically on Connect if the network is not present):

| Field | Value |
|---|---|
| Chain ID | `61999` (hex `0xF1EF`) |
| RPC | `https://studio.genlayer.com/api` |
| Symbol | `GEN` |
| Explorer | `https://genlayer-explorer.vercel.app` |

Then, in <https://studio.genlayer.com>, open the **Accounts** panel and transfer GEN from a pre-funded studio account to your MetaMask address. Do NOT use the testnet faucet — testnet and studionet are separate networks.

### 2. Deploy the contract (Studio)

1. Open <https://studio.genlayer.com/contracts>.
2. New contract → paste the contents of `contracts/flight_refund.py`.
3. Deploy. After the tx shows `Status: FINALIZED`, click it and confirm `Result: SUCCESS`.
4. Copy the contract address.

### 3. Fund the insurer pool

From the same account that deployed (the pool owner), call `fund_pool()` with the amount of GEN you want the pool to underwrite. This is the capital that will pay coverage. Buyers can't purchase policies larger than the available pool.

### 4. Wire the frontend

```bash
cd frontend
cp .env.example .env.local
# paste the new deployed address into VITE_CONTRACT_ADDRESS
npm install
npm run dev
```

Open <http://localhost:5174>. Connect MetaMask (funded on studionet):

1. **Buy coverage** — pick a flight ≥ 1 day in the future, choose a threshold, choose how much coverage you want. The app shows the premium (10% of coverage) and sends it as `msg.value`.
2. **File a claim** — after the flight has landed (or been cancelled), paste the policy ID. Wait for validator consensus.
3. Watch the policy card update with each source's extracted delay bucket and the final verdict.

### 5. Deploy the frontend

Vercel auto-builds on push (see `vercel.json`). Set `VITE_CONTRACT_ADDRESS` in the Vercel project settings and redeploy after any contract redeploy.

---

## Local test loop

```bash
pip install genlayer-test
gltest tests/ --network localnet
```

Tests cover:

| Case | Expectation |
|---|---|
| Pool funding and locking | pool_balance / locked_coverage update correctly |
| Coverage exceeds pool | `buy_policy` rejects |
| Premium below 10% | `buy_policy` rejects |
| Purchase within window | ACTIVE policy, coverage locked, premium in pool |
| Purchase after cutoff | `buy_policy` rejects (window closed) |
| Both sources agree MAJOR, threshold MODERATE, in window | `PAID` from pool |
| Both sources agree MINOR, threshold MODERATE, in window | `REJECTED`, pool keeps premium |
| Sources disagree | `UNRESOLVED` |
| One source says flight/date does not match | `UNRESOLVED` (verdict binding) |
| Both agree CANCELLED | `PAID` regardless of threshold |
| Claim before flight | rejected — window not open |
| Claim after 30 days | rejected — window expired |
| Invalid flight number / zero premium / bad threshold / zero coverage | rejected |
| `resolve_unresolved` | refunds premium and unlocks coverage |

Mocks are keyed per URL pattern (`.*flightaware.*`, `.*flightradar24.*`, `.*worldtimeapi\.org.*`) so a single test can drive the two sources into agreement or disagreement AND control the "today" that the on-chain window checks use.

---

## What is not in scope

- Actuarial pricing: buyers set their own coverage amount; the premium rate is a fixed 10%. A real product would price the premium per route history.
- Cross-currency payouts: everything is denominated in GEN.
- Airline-provided evidence: the contract only consumes public web pages.
