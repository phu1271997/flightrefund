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


def _addr_str(addr: Address) -> str:
    try:
        return addr.as_hex
    except Exception:
        return str(addr)


def _clean(text, limit: int) -> str:
    text = str(text or "").strip()
    return re.sub(r"[\x00-\x1f\x7f]", "", text)[:limit]


def _normalize_source(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {"bucket": BUCKET_UNKNOWN, "delay_minutes": 0}
    if not isinstance(raw, dict):
        return {"bucket": BUCKET_UNKNOWN, "delay_minutes": 0}
    bucket = str(raw.get("bucket", BUCKET_UNKNOWN)).upper()
    if bucket not in VALID_BUCKETS:
        bucket = BUCKET_UNKNOWN
    try:
        delay = max(0, min(2000, int(raw.get("delay_minutes", 0))))
    except (TypeError, ValueError):
        delay = 0
    return {"bucket": bucket, "delay_minutes": delay}


class Contract(gl.Contract):
    owner: Address
    policies: TreeMap[str, str]
    policy_count: u256
    total_locked: u256

    def __init__(self):
        self.owner = gl.message.sender_address
        self.policy_count = u256(0)
        self.total_locked = u256(0)

    @gl.public.view
    def get_policy(self, policy_id: str) -> str:
        return self.policies.get(policy_id, "")

    @gl.public.view
    def get_policy_count(self) -> u256:
        return self.policy_count

    @gl.public.view
    def get_total_locked(self) -> u256:
        return self.total_locked

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

    @gl.public.write.payable
    def buy_policy(
        self,
        flight_number: str,
        flight_date: str,
        threshold: str,
    ) -> None:
        amount = int(gl.message.value)
        if amount <= 0:
            raise gl.vm.UserError("Policy payout must be positive")
        flight_number = str(flight_number or "").upper().replace(" ", "")
        if not re.match(FLIGHT_NUMBER_RE, flight_number):
            raise gl.vm.UserError("Invalid flight number (e.g. VN123, DL42)")
        if not re.match(FLIGHT_DATE_RE, flight_date):
            raise gl.vm.UserError("Invalid flight date (YYYY-MM-DD)")
        threshold = str(threshold or "").upper()
        if threshold not in VALID_THRESHOLDS:
            raise gl.vm.UserError("Threshold must be MINOR, MODERATE, or MAJOR")

        new_id = int(self.policy_count) + 1
        policy_id = str(new_id)
        record = {
            "id": policy_id,
            "buyer": _addr_str(gl.message.sender_address),
            "flight_number": flight_number,
            "flight_date": flight_date,
            "threshold": threshold,
            "payout": str(amount),
            "status": STATUS_ACTIVE,
            "bucket": "",
            "sources_agreed": None,
            "sources": {},
            "reason": "",
        }
        self.policies[policy_id] = json.dumps(record, sort_keys=True)
        self.policy_count = u256(new_id)
        self.total_locked = u256(int(self.total_locked) + amount)

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
        payout = int(record["payout"])
        buyer_str = record["buyer"]
        owner_str = _addr_str(self.owner)

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
                    "Flight number: " + flight_number + "\n"
                    "Date (UTC): " + flight_date + "\n"
                    "Source: " + source + "\n\n"
                    "PAGE TEXT (truncated):\n"
                    + page[:6000]
                    + "\n\nReturn JSON ONLY with keys:\n"
                    + '  "bucket": "ON_TIME"|"MINOR"|"MODERATE"|"MAJOR"|"SEVERE"|"CANCELLED"|"UNKNOWN",\n'
                    + '  "delay_minutes": integer (0 if unknown).\n\n'
                    + "Bucket rubric:\n"
                    + "  ON_TIME:   arrival delay < 15 minutes\n"
                    + "  MINOR:     15 to 59 minutes\n"
                    + "  MODERATE:  60 to 119 minutes\n"
                    + "  MAJOR:     120 to 299 minutes\n"
                    + "  SEVERE:    300 minutes or more\n"
                    + "  CANCELLED: the flight is cancelled or did not operate\n"
                    + "  UNKNOWN:   the page does not describe THIS flight on THIS date.\n"
                    + "Never guess. If uncertain, return UNKNOWN."
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

            buckets = [s["bucket"] for s in sources.values() if s["bucket"] != BUCKET_UNKNOWN]

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
            record["reason"] = _clean(
                "Sources unavailable or disagreed. Policy remains active until "
                "resolved. Owner may refund manually.",
                MAX_REASON,
            )
            self.policies[policy_id] = json.dumps(record, sort_keys=True)
            return

        actual_rank = BUCKET_ORDER.get(bucket, -1)
        threshold_rank = BUCKET_ORDER.get(threshold, 999)

        if actual_rank >= threshold_rank:
            gl.get_contract_at(Address(buyer_str)).emit_transfer(value=u256(payout))
            record["status"] = STATUS_PAID
            record["reason"] = _clean(
                "Delay bucket "
                + bucket
                + " met the "
                + threshold
                + " threshold. Payout released.",
                MAX_REASON,
            )
            self.total_locked = u256(int(self.total_locked) - payout)
        else:
            gl.get_contract_at(Address(owner_str)).emit_transfer(value=u256(payout))
            record["status"] = STATUS_REJECTED
            record["reason"] = _clean(
                "Delay bucket "
                + bucket
                + " did not meet the "
                + threshold
                + " threshold. Premium retained.",
                MAX_REASON,
            )
            self.total_locked = u256(int(self.total_locked) - payout)

        record["bucket"] = bucket
        record["sources_agreed"] = agreed
        record["sources"] = sources
        self.policies[policy_id] = json.dumps(record, sort_keys=True)

    @gl.public.write
    def resolve_unresolved(self, policy_id: str) -> None:
        """Owner-only escape hatch: refund an unresolved policy."""
        if gl.message.sender_address != self.owner:
            raise gl.vm.UserError("Only the pool owner can resolve manually")
        raw = self.policies.get(policy_id, "")
        if not raw:
            raise gl.vm.UserError("Policy not found")
        record = json.loads(raw)
        if record["status"] != STATUS_UNRESOLVED:
            raise gl.vm.UserError("Policy is not unresolved")
        payout = int(record["payout"])
        buyer_str = record["buyer"]
        gl.get_contract_at(Address(buyer_str)).emit_transfer(value=u256(payout))
        record["status"] = STATUS_CANCELLED
        record["reason"] = _clean(
            "Refunded manually because flight status remained unresolved.",
            MAX_REASON,
        )
        self.policies[policy_id] = json.dumps(record, sort_keys=True)
        self.total_locked = u256(int(self.total_locked) - payout)
