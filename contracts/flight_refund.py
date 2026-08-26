# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *

import json
import re

STATUS_ACTIVE = "ACTIVE"
STATUS_PAID = "PAID"
STATUS_REJECTED = "REJECTED"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_CANCELLED = "CANCELLED"

BUCKET_UNKNOWN = "UNKNOWN"
BUCKET_ON_TIME = "ON_TIME"
BUCKET_MINOR = "MINOR"
BUCKET_MODERATE = "MODERATE"
BUCKET_MAJOR = "MAJOR"
BUCKET_SEVERE = "SEVERE"
BUCKET_CANCELLED = "CANCELLED"

BUCKET_ORDER = {
    BUCKET_ON_TIME: 0,
    BUCKET_MINOR: 1,
    BUCKET_MODERATE: 2,
    BUCKET_MAJOR: 3,
    BUCKET_SEVERE: 4,
    BUCKET_CANCELLED: 5,
}

VALID_THRESHOLDS = [BUCKET_MINOR, BUCKET_MODERATE, BUCKET_MAJOR]
VALID_BUCKETS = list(BUCKET_ORDER.keys()) + [BUCKET_UNKNOWN]

FLIGHT_NUMBER_RE = r"^[A-Z0-9]{2,3}[0-9]{1,5}$"
FLIGHT_DATE_RE = r"^20[2-9][0-9]-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$"

MAX_REASON = 500

# Premium the buyer must pay expressed as basis points of coverage.
# 1000 = 10%. Buyer covers this out of msg.value; the pool provides the coverage.
PREMIUM_RATE_BPS = 1000

# Claim must be filed within this many days after the scheduled flight_date.
CLAIM_WINDOW_DAYS = 30

# Purchase must happen at least this many days before the scheduled flight_date.
MIN_PURCHASE_LEAD_DAYS = 1

# Public UTC time source used to gate purchase and claim windows on-chain.
TIME_URL = "https://worldtimeapi.org/api/timezone/Etc/UTC"


def _addr_str(addr: Address) -> str:
    try:
        return addr.as_hex
    except Exception:
        return str(addr)


def _clean(text, limit: int) -> str:
    text = str(text or "").strip()
    return re.sub(r"[\x00-\x1f\x7f]", "", text)[:limit]


def _parse_iso(s: str):
    m = re.match(r"^(20\d{2})-(\d{2})-(\d{2})$", s or "")
    if not m:
        return None
    y = int(m.group(1))
    mo = int(m.group(2))
    d = int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return (y, mo, d)


def _days_between(later_iso: str, earlier_iso: str) -> int:
    from datetime import date
    a = _parse_iso(later_iso)
    b = _parse_iso(earlier_iso)
    if a is None or b is None:
        raise gl.vm.UserError("Invalid ISO date encountered")
    return (date(*a) - date(*b)).days


def _normalize_source(raw) -> dict:
    """Coerce an LLM classification into a strict shape.

    A verdict is only accepted when the LLM confirms all of:
      - flight_match: the page describes the exact target flight number
      - date_match:   the page shows this flight on the target UTC date
      - completed:    the flight has already landed / been cancelled / diverted

    If any of these are missing or false, the bucket is forced to UNKNOWN.
    This is the mechanism that binds the verdict to the exact dated flight.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {
                "bucket": BUCKET_UNKNOWN,
                "delay_minutes": 0,
                "flight_match": False,
                "date_match": False,
                "completed": False,
            }
    if not isinstance(raw, dict):
        return {
            "bucket": BUCKET_UNKNOWN,
            "delay_minutes": 0,
            "flight_match": False,
            "date_match": False,
            "completed": False,
        }
    bucket = str(raw.get("bucket", BUCKET_UNKNOWN)).upper()
    if bucket not in VALID_BUCKETS:
        bucket = BUCKET_UNKNOWN
    try:
        delay = max(0, min(2000, int(raw.get("delay_minutes", 0))))
    except (TypeError, ValueError):
        delay = 0
    flight_match = bool(raw.get("flight_match", False))
    date_match = bool(raw.get("date_match", False))
    completed = bool(raw.get("completed", False))
    if not (flight_match and date_match and completed):
        bucket = BUCKET_UNKNOWN
        delay = 0
    return {
        "bucket": bucket,
        "delay_minutes": delay,
        "flight_match": flight_match,
        "date_match": date_match,
        "completed": completed,
    }


def _fetch_today_utc_iso() -> str:
    """Fetch today's UTC date (YYYY-MM-DD) via consensus.

    Uses strict_eq so validators must return the exact same date string.
    Returns "" if the time source is unreachable or unparseable.
    """

    def fn():
        try:
            text = gl.nondet.web.render(TIME_URL, mode="text") or ""
        except Exception:
            return ""
        try:
            data = json.loads(text)
            iso = str(data.get("utc_datetime", "") or data.get("datetime", ""))
            m = re.search(r"(20\d{2}-\d{2}-\d{2})", iso)
            if m:
                return m.group(1)
        except Exception:
            pass
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
        return m.group(1) if m else ""

    return gl.eq_principle.strict_eq(fn)


class Contract(gl.Contract):
    owner: Address
    policies: TreeMap[str, str]
    policy_count: u256
    pool_balance: u256
    locked_coverage: u256

    def __init__(self):
        self.owner = gl.message.sender_address
        self.policy_count = u256(0)
        self.pool_balance = u256(0)
        self.locked_coverage = u256(0)

    # ---- Views ----------------------------------------------------------

    @gl.public.view
    def get_policy(self, policy_id: str) -> str:
        return self.policies.get(policy_id, "")

    @gl.public.view
    def get_policy_count(self) -> u256:
        return self.policy_count

    @gl.public.view
    def get_pool_balance(self) -> u256:
        return self.pool_balance

    @gl.public.view
    def get_locked_coverage(self) -> u256:
        return self.locked_coverage

    @gl.public.view
    def get_available_pool(self) -> u256:
        p = int(self.pool_balance)
        l = int(self.locked_coverage)
        return u256(max(0, p - l))

    @gl.public.view
    def get_config(self) -> str:
        return json.dumps({
            "owner": _addr_str(self.owner),
            "premium_rate_bps": PREMIUM_RATE_BPS,
            "claim_window_days": CLAIM_WINDOW_DAYS,
            "min_purchase_lead_days": MIN_PURCHASE_LEAD_DAYS,
        })

    @gl.public.view
    def list_policies(self, start: u256, limit: u256) -> str:
        start_i = int(start)
        limit_i = min(int(limit), 50)
        total = int(self.policy_count)
        out = []
        for i in range(start_i, min(start_i + limit_i, total)):
            key = str(i + 1)
            raw = self.policies.get(key, "")
            if raw:
                try:
                    out.append(json.loads(raw))
                except Exception:
                    continue
        return json.dumps({"items": out, "total": total})

    # ---- Pool management -----------------------------------------------

    @gl.public.write.payable
    def fund_pool(self) -> None:
        """Insurer capital: anyone can add to the coverage pool."""
        amount = int(gl.message.value)
        if amount <= 0:
            raise gl.vm.UserError("Funding amount must be positive")
        self.pool_balance = u256(int(self.pool_balance) + amount)

    @gl.public.write
    def withdraw_pool(self, amount_wei_str: str) -> None:
        """Owner-only: withdraw unlocked pool capital."""
        if gl.message.sender_address != self.owner:
            raise gl.vm.UserError("Only the pool owner can withdraw")
        try:
            amount = int(amount_wei_str)
        except Exception:
            raise gl.vm.UserError("Invalid withdraw amount")
        if amount <= 0:
            raise gl.vm.UserError("Withdraw amount must be positive")
        available = int(self.pool_balance) - int(self.locked_coverage)
        if amount > available:
            raise gl.vm.UserError("Withdraw exceeds unlocked pool balance")
        gl.get_contract_at(self.owner).emit_transfer(value=u256(amount))
        self.pool_balance = u256(int(self.pool_balance) - amount)

    # ---- Policy lifecycle ----------------------------------------------

    @gl.public.write.payable
    def buy_policy(
        self,
        flight_number: str,
        flight_date: str,
        threshold: str,
        coverage_wei_str: str,
    ) -> None:
        """Buy coverage against a specific dated flight.

        msg.value is the *premium* the buyer pays. The pool provides the
        *coverage* — the amount the buyer receives if the delay meets the
        threshold. Buyer is not funding their own payout.
        """
        premium = int(gl.message.value)
        if premium <= 0:
            raise gl.vm.UserError("Premium (msg.value) must be positive")

        flight_number = str(flight_number or "").upper().replace(" ", "")
        if not re.match(FLIGHT_NUMBER_RE, flight_number):
            raise gl.vm.UserError("Invalid flight number (e.g. VN123, DL42)")
        if not re.match(FLIGHT_DATE_RE, flight_date):
            raise gl.vm.UserError("Invalid flight date (YYYY-MM-DD)")
        threshold = str(threshold or "").upper()
        if threshold not in VALID_THRESHOLDS:
            raise gl.vm.UserError("Threshold must be MINOR, MODERATE, or MAJOR")

        try:
            coverage = int(coverage_wei_str)
        except Exception:
            raise gl.vm.UserError("Invalid coverage amount")
        if coverage <= 0:
            raise gl.vm.UserError("Coverage must be positive")

        # Insurer solvency: only underwrite coverage the pool can back.
        available = int(self.pool_balance) - int(self.locked_coverage)
        if coverage > available:
            raise gl.vm.UserError("Coverage exceeds available pool capacity")

        # Buyer must pay at least the required premium rate.
        min_premium = (coverage * PREMIUM_RATE_BPS + 9999) // 10000
        if premium < min_premium:
            raise gl.vm.UserError(
                "Premium below required rate ("
                + str(PREMIUM_RATE_BPS // 100)
                + "% of coverage)"
            )

        # Purchase window: today must be at least MIN_PURCHASE_LEAD_DAYS
        # before the scheduled flight date. Enforced on-chain via a
        # consensus-fetched UTC date.
        today_iso = _fetch_today_utc_iso()
        if not today_iso or _parse_iso(today_iso) is None:
            raise gl.vm.UserError("Time source unreachable; retry later")
        lead = _days_between(flight_date, today_iso)
        if lead < MIN_PURCHASE_LEAD_DAYS:
            raise gl.vm.UserError(
                "Purchase window closed: flight must be at least "
                + str(MIN_PURCHASE_LEAD_DAYS)
                + " day(s) in the future"
            )

        new_id = int(self.policy_count) + 1
        policy_id = str(new_id)
        record = {
            "id": policy_id,
            "buyer": _addr_str(gl.message.sender_address),
            "flight_number": flight_number,
            "flight_date": flight_date,
            "threshold": threshold,
            "premium": str(premium),
            "coverage": str(coverage),
            "status": STATUS_ACTIVE,
            "bucket": "",
            "sources_agreed": None,
            "sources": {},
            "reason": "",
            "purchased_on": today_iso,
            "claimed_on": "",
        }
        self.policies[policy_id] = json.dumps(record, sort_keys=True)
        self.policy_count = u256(new_id)
        # Pool accepts the premium and reserves the coverage.
        self.pool_balance = u256(int(self.pool_balance) + premium)
        self.locked_coverage = u256(int(self.locked_coverage) + coverage)

    @gl.public.write
    def file_claim(self, policy_id: str) -> None:
        raw = self.policies.get(policy_id, "")
        if not raw:
            raise gl.vm.UserError("Policy not found")
        record = json.loads(raw)
        if record["status"] != STATUS_ACTIVE:
            raise gl.vm.UserError("Policy is not active")

        flight_number = record["flight_number"]
        flight_date = record["flight_date"]
        threshold = record["threshold"]
        coverage = int(record["coverage"])
        buyer_str = record["buyer"]

        # Claim window: flight must have already occurred and the window
        # must still be open. Enforced on-chain via UTC date consensus.
        today_iso = _fetch_today_utc_iso()
        if not today_iso or _parse_iso(today_iso) is None:
            raise gl.vm.UserError("Time source unreachable; retry later")
        elapsed = _days_between(today_iso, flight_date)
        if elapsed < 0:
            raise gl.vm.UserError(
                "Claim window not open: flight has not occurred yet"
            )
        if elapsed > CLAIM_WINDOW_DAYS:
            raise gl.vm.UserError(
                "Claim window expired (>"
                + str(CLAIM_WINDOW_DAYS)
                + " days after flight)"
            )

        fa_url = "https://www.flightaware.com/live/flight/" + flight_number
        fr_url = (
            "https://www.flightradar24.com/data/flights/"
            + flight_number.lower()
        )

        def leader_fn():
            def fetch(url):
                try:
                    return gl.nondet.web.render(url, mode="text") or ""
                except Exception:
                    return ""

            fa_page = fetch(fa_url)
            fr_page = fetch(fr_url)
            if not fa_page and not fr_page:
                raise gl.vm.UserError("Both flight data sources unreachable")

            def classify(page: str, source: str):
                if not page:
                    return None
                prompt = (
                    "You are extracting the on-time status of a specific "
                    "commercial flight from a public flight-tracking page.\n\n"
                    "Target flight number: " + flight_number + "\n"
                    "Target date (UTC):    " + flight_date + "\n"
                    "Source:               " + source + "\n\n"
                    "PAGE TEXT (truncated):\n"
                    + page[:6000]
                    + "\n\nReturn JSON ONLY with EXACT keys:\n"
                    + '  "flight_match": true if the page describes flight '
                    + flight_number
                    + ' (else false),\n'
                    + '  "date_match":   true if the page shows THIS flight operated on '
                    + flight_date
                    + ' UTC (else false),\n'
                    + '  "completed":    true if the flight has ALREADY landed, been cancelled, or diverted (else false),\n'
                    + '  "bucket":       "ON_TIME"|"MINOR"|"MODERATE"|"MAJOR"|"SEVERE"|"CANCELLED"|"UNKNOWN",\n'
                    + '  "delay_minutes": integer (0 if unknown).\n\n'
                    + "Hard rules:\n"
                    + "  - If flight_match is false, OR date_match is false, OR completed is false, then bucket MUST be UNKNOWN.\n"
                    + "  - Do NOT extrapolate from a different dated instance of the same flight number.\n"
                    + "  - Do NOT guess. If uncertain, return UNKNOWN.\n\n"
                    + "Bucket rubric (only applies when flight_match, date_match, completed are all true):\n"
                    + "  ON_TIME:   arrival delay < 15 minutes\n"
                    + "  MINOR:     15 to 59 minutes\n"
                    + "  MODERATE:  60 to 119 minutes\n"
                    + "  MAJOR:     120 to 299 minutes\n"
                    + "  SEVERE:    300 minutes or more\n"
                    + "  CANCELLED: the flight is cancelled or did not operate\n"
                    + "  UNKNOWN:   the page does not describe THIS flight on THIS date, or flight has not completed."
                )
                return _normalize_source(
                    gl.nondet.exec_prompt(prompt, response_format="json")
                )

            fa_result = classify(fa_page, "flightaware.com")
            fr_result = classify(fr_page, "flightradar24.com")

            sources = {}
            if fa_result:
                sources["flightaware"] = fa_result
            if fr_result:
                sources["flightradar24"] = fr_result

            buckets = [
                s["bucket"]
                for s in sources.values()
                if s["bucket"] != BUCKET_UNKNOWN
            ]

            if len(buckets) >= 2 and buckets[0] == buckets[1]:
                final_bucket = buckets[0]
                agreed = True
            elif len(buckets) == 1:
                final_bucket = buckets[0]
                agreed = False
            else:
                final_bucket = BUCKET_UNKNOWN
                agreed = False

            return {
                "bucket": final_bucket,
                "sources_agreed": agreed,
                "sources": sources,
            }

        def validator_fn(leader_res):
            if not isinstance(leader_res, gl.vm.Return):
                return False
            proposed = leader_res.calldata
            if not isinstance(proposed, dict):
                return False
            try:
                mine = leader_fn()
            except Exception:
                return False
            # Validators compare the *meaning*: the final bucket and whether
            # the two sources agreed. The verbatim `delay_minutes` on each
            # source is treated as prose, not consensus.
            return (
                mine["bucket"] == proposed.get("bucket")
                and bool(mine["sources_agreed"]) == bool(proposed.get("sources_agreed"))
            )

        run_nondet = getattr(gl.vm, "run_nondet", gl.vm.run_nondet_unsafe)
        verdict = run_nondet(leader_fn, validator_fn)
        bucket = verdict["bucket"]
        agreed = bool(verdict["sources_agreed"])
        sources = verdict.get("sources", {})

        if bucket == BUCKET_UNKNOWN or not agreed:
            record["status"] = STATUS_UNRESOLVED
            record["bucket"] = bucket
            record["sources_agreed"] = agreed
            record["sources"] = sources
            record["claimed_on"] = today_iso
            record["reason"] = _clean(
                "Sources unavailable, disagreed, or could not confirm this exact "
                "dated flight. Coverage stays locked until the pool owner "
                "resolves manually.",
                MAX_REASON,
            )
            self.policies[policy_id] = json.dumps(record, sort_keys=True)
            return

        actual_rank = BUCKET_ORDER.get(bucket, -1)
        threshold_rank = BUCKET_ORDER.get(threshold, 999)

        if actual_rank >= threshold_rank:
            # Pool pays the coverage to the buyer. Premium stays in the pool
            # as insurer income.
            gl.get_contract_at(Address(buyer_str)).emit_transfer(value=u256(coverage))
            self.pool_balance = u256(int(self.pool_balance) - coverage)
            self.locked_coverage = u256(int(self.locked_coverage) - coverage)
            record["status"] = STATUS_PAID
            record["reason"] = _clean(
                "Delay bucket "
                + bucket
                + " met the "
                + threshold
                + " threshold on "
                + flight_date
                + ". Coverage released to buyer.",
                MAX_REASON,
            )
        else:
            # Coverage returns to the pool as available capacity. The premium
            # already sits in the pool as net insurer income.
            self.locked_coverage = u256(int(self.locked_coverage) - coverage)
            record["status"] = STATUS_REJECTED
            record["reason"] = _clean(
                "Delay bucket "
                + bucket
                + " did not meet the "
                + threshold
                + " threshold on "
                + flight_date
                + ". Premium retained.",
                MAX_REASON,
            )

        record["bucket"] = bucket
        record["sources_agreed"] = agreed
        record["sources"] = sources
        record["claimed_on"] = today_iso
        self.policies[policy_id] = json.dumps(record, sort_keys=True)

    @gl.public.write
    def resolve_unresolved(self, policy_id: str) -> None:
        """Owner-only escape hatch: refund premium and unlock coverage."""
        if gl.message.sender_address != self.owner:
            raise gl.vm.UserError("Only the pool owner can resolve manually")
        raw = self.policies.get(policy_id, "")
        if not raw:
            raise gl.vm.UserError("Policy not found")
        record = json.loads(raw)
        if record["status"] != STATUS_UNRESOLVED:
            raise gl.vm.UserError("Policy is not unresolved")
        premium = int(record.get("premium", "0"))
        coverage = int(record.get("coverage", "0"))
        buyer_str = record["buyer"]
        if premium > 0:
            gl.get_contract_at(Address(buyer_str)).emit_transfer(value=u256(premium))
            self.pool_balance = u256(int(self.pool_balance) - premium)
        if coverage > 0:
            self.locked_coverage = u256(int(self.locked_coverage) - coverage)
        record["status"] = STATUS_CANCELLED
        record["reason"] = _clean(
            "Refunded manually: flight status remained unresolved. Premium "
            "returned to buyer, coverage unlocked.",
            MAX_REASON,
        )
        self.policies[policy_id] = json.dumps(record, sort_keys=True)
