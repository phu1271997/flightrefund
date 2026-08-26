# Deploy FlightRefund to GenLayer studionet

## Prerequisites

- MetaMask installed and unlocked
- A funded wallet on GenLayer studionet (see README §1)

## A. Deploy the contract via GenLayer Studio (recommended)

1. Open <https://studio.genlayer.com/contracts>.
2. Click **New Contract** → **Blank Python**.
3. Delete the default template.
4. Copy the entire content of `contracts/flight_refund.py` and paste it. The first line **must** be the `# { "Depends": ... }` pragma. Do not add any blank line above it.
5. Click **Deploy**. Wait for `Status: FINALIZED`, then click the transaction and confirm the sidebar shows `Result: SUCCESS`.
6. Copy the deployed contract address.

## B. Deploy via GenLayer CLI (optional)

```bash
npm install -g @genlayer/cli
genlayer deploy contracts/flight_refund.py \
  --network studionet \
  --from <your funded address>
```

## C. Fund the insurer pool

From the deployer address (the pool owner), call `fund_pool()` with the amount of GEN you want the pool to back coverage with. Buyers cannot underwrite policies larger than the pool's available (unlocked) capacity.

In Studio: **Run & Debug → fund_pool → value: <GEN amount> → Send**.

## D. Record the address

Paste it into:

- `frontend/.env.local` as `VITE_CONTRACT_ADDRESS`
- Vercel project → Settings → Environment Variables as `VITE_CONTRACT_ADDRESS`, then redeploy
- `README.md` under the "Contract address" section
- The GenLayer Portal submission

## E. Post-deploy smoke test

1. `cd frontend && npm run dev`.
2. Connect MetaMask (funded on studionet).
3. Confirm the "Coverage pool" card shows the funded balance.
4. Buy a small policy against a real upcoming flight (≥ 1 day away, e.g. tomorrow's `VN123`).
5. After the flight has landed, file a claim by policy ID.
6. Wait for validator consensus (~30–120s). Both flight-tracking sites are fetched; both must agree on the bucket AND both must confirm the exact dated flight for the pool to release coverage.
7. Confirm the payout on <https://genlayer-explorer.vercel.app>.

## Common deploy failures

| Symptom | Fix |
|---|---|
| `Could not load contract schema` | Version pragma on line 1 is missing or wrong; see rule R14 / R18 in `~GEN_RULES/02-common-errors.md` |
| `AssertionError: TreeMap <- TreeMap` | You reassigned a `TreeMap` in `__init__` (rule #2). Remove it — GenVM auto-initializes. |
| `AttributeError: module 'genlayer.gl' has no attribute 'eth'` | Rule R15 — use `gl.get_contract_at(addr).emit_transfer(value=...)`, not `gl.eth.send_value` |
| Sidebar shows `Result: ERROR` on `file_claim` in a test run | LLM/web mocks were not installed — see rule R17. Also make sure the time mock is installed (`.*worldtimeapi\.org.*`). |
| `buy_policy` rejects with "Coverage exceeds available pool capacity" | Call `fund_pool()` from the owner first, or lower coverage. |
| `buy_policy` rejects with "Purchase window closed" | Pick a `flight_date` ≥ 1 day from today (UTC). |
| `file_claim` rejects with "Claim window not open" | Flight has not happened yet. Wait until the day after `flight_date` (UTC). |
| `file_claim` rejects with "Time source unreachable" | Retry — `worldtimeapi.org` was momentarily down. |
| Claim finalizes but nothing paid | Sources disagreed, one page didn't describe the exact dated flight, or both returned `UNKNOWN` → status is `UNRESOLVED`. Owner can call `resolve_unresolved` to refund the premium and unlock coverage. |
