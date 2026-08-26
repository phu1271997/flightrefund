"""FlightRefund integration tests.

    gltest tests/test_flight_refund.py --network localnet
    gltest tests/test_flight_refund.py --network studionet

The contract now has three axes of enforcement:

  1. Coverage is funded by the pool (insurer), premium is paid by the buyer.
     Buyer never funds their own payout.
  2. Purchase must be at least 1 day before flight_date; claims must be
     filed within 30 days after flight_date. Both windows are checked
     on-chain against a UTC time source.
  3. The verdict must bind to the exact dated flight. The LLM is prompted
     to return `flight_match`, `date_match`, `completed` — if any is false
     the bucket collapses to UNKNOWN.

Tests mock the LLM, the two flight-tracking pages, and the UTC time API
so date-sensitive branches can be exercised deterministically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from gltest import get_contract_factory

CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "flight_refund.py"


def clear_known_contracts():
    for name, module in list(sys.modules.items()):
        if "genlayer" in name and hasattr(module, "__known_contract__"):
            setattr(module, "__known_contract__", None)


def _install_mocks(client, llm_mocks: dict, web_pages: dict):
    encoded_llm = {}
    for pattern, response in llm_mocks.items():
        encoded_llm[pattern] = (
            response if isinstance(response, str) else json.dumps(response)
        )
    web_mocks = {p: {"status": 200, "body": b} for p, b in web_pages.items()}
    client.provider.make_request(
        method="sim_installMocks",
        params={"llm_mocks": encoded_llm, "web_mocks": web_mocks},
    )


def _deploy():
    clear_known_contracts()
    factory = get_contract_factory(str(CONTRACT))
    return factory.deploy()


FLIGHT = "VN123"
FLIGHT_DATE = "2026-09-01"
TODAY_BEFORE = "2026-08-30"      # 2 days before flight → purchase valid
TODAY_TOO_LATE = "2026-09-01"     # same day as flight → purchase closed
CLAIM_TODAY = "2026-09-02"        # 1 day after flight → claim window open
LATE_CLAIM_TODAY = "2026-10-05"   # >30 days after flight → expired

COVERAGE = 500_000_000_000_000_000  # 0.5 GEN insurer coverage
PREMIUM = COVERAGE // 10            # 10% = 0.05 GEN buyer premium
FUND = COVERAGE * 10                # 5 GEN pool

TIME_URL_RE = r".*worldtimeapi\.org.*"
FA_URL_RE = r".*flightaware\.com.*"
FR_URL_RE = r".*flightradar24\.com.*"


def _time_page(today_iso: str) -> str:
    return json.dumps({"utc_datetime": today_iso + "T12:00:00.000000+00:00"})


def _classification(bucket: str, delay: int, *, match: bool = True, completed: bool = True):
    return {
        "flight_match": match,
        "date_match": match,
        "completed": completed,
        "bucket": bucket,
        "delay_minutes": delay,
    }


def _fund_and_buy(contract, buyer, today_iso, threshold="MODERATE"):
    contract.fund_pool(args=[]).transact(value=FUND)
    _install_mocks(contract.client, llm_mocks={}, web_pages={TIME_URL_RE: _time_page(today_iso)})
    contract.connect(buyer).buy_policy(
        args=[FLIGHT, FLIGHT_DATE, threshold, str(COVERAGE)]
    ).transact(value=PREMIUM)


def _run_claim(
    contract,
    buyer,
    today_iso,
    fa_class,
    fr_class,
    fa_body="FlightAware body",
    fr_body="FlightRadar24 body",
):
    _install_mocks(
        contract.client,
        llm_mocks={
            FA_URL_RE: fa_class,
            FR_URL_RE: fr_class,
        },
        web_pages={
            TIME_URL_RE: _time_page(today_iso),
            FA_URL_RE: fa_body,
            FR_URL_RE: fr_body,
        },
    )
    contract.connect(buyer).file_claim(args=["1"]).transact()


# ---------------------------------------------------------------------- pool


def test_fund_pool_increases_available(buyer):
    contract = _deploy()
    contract.fund_pool(args=[]).transact(value=FUND)
    assert int(contract.get_pool_balance(args=[]).call()) == FUND
    assert int(contract.get_available_pool(args=[]).call()) == FUND
    assert int(contract.get_locked_coverage(args=[]).call()) == 0


def test_fund_pool_rejects_zero(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="positive"):
        contract.fund_pool(args=[]).transact(value=0)


def test_withdraw_pool_owner_only(buyer):
    contract = _deploy()
    contract.fund_pool(args=[]).transact(value=FUND)
    with pytest.raises(Exception, match="owner"):
        contract.connect(buyer).withdraw_pool(args=[str(FUND // 2)]).transact()


# ------------------------------------------------------------- buy_policy


def test_buy_policy_locks_coverage_and_absorbs_premium(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    assert int(contract.get_locked_coverage(args=[]).call()) == COVERAGE
    # Pool balance = original fund + premium
    assert int(contract.get_pool_balance(args=[]).call()) == FUND + PREMIUM
    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "ACTIVE"
    assert record["coverage"] == str(COVERAGE)
    assert record["premium"] == str(PREMIUM)
    assert record["purchased_on"] == TODAY_BEFORE


def test_buy_policy_rejects_when_pool_insufficient(buyer):
    contract = _deploy()
    _install_mocks(
        contract.client,
        llm_mocks={},
        web_pages={TIME_URL_RE: _time_page(TODAY_BEFORE)},
    )
    with pytest.raises(Exception, match="pool capacity"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, FLIGHT_DATE, "MODERATE", str(COVERAGE)]
        ).transact(value=PREMIUM)


def test_buy_policy_rejects_low_premium(buyer):
    contract = _deploy()
    contract.fund_pool(args=[]).transact(value=FUND)
    _install_mocks(
        contract.client,
        llm_mocks={},
        web_pages={TIME_URL_RE: _time_page(TODAY_BEFORE)},
    )
    too_low = (PREMIUM // 2) + 1
    with pytest.raises(Exception, match="Premium below required"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, FLIGHT_DATE, "MODERATE", str(COVERAGE)]
        ).transact(value=too_low)


def test_buy_policy_rejects_when_purchase_window_closed(buyer):
    contract = _deploy()
    contract.fund_pool(args=[]).transact(value=FUND)
    _install_mocks(
        contract.client,
        llm_mocks={},
        web_pages={TIME_URL_RE: _time_page(TODAY_TOO_LATE)},
    )
    with pytest.raises(Exception, match="Purchase window closed"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, FLIGHT_DATE, "MODERATE", str(COVERAGE)]
        ).transact(value=PREMIUM)


def test_invalid_flight_number_rejected(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="Invalid flight number"):
        contract.connect(buyer).buy_policy(
            args=["not-a-flight", FLIGHT_DATE, "MODERATE", str(COVERAGE)]
        ).transact(value=PREMIUM)


def test_zero_premium_rejected(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="positive"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, FLIGHT_DATE, "MODERATE", str(COVERAGE)]
        ).transact(value=0)


def test_bad_threshold_rejected(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="Threshold"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, FLIGHT_DATE, "ON_TIME", str(COVERAGE)]
        ).transact(value=PREMIUM)


def test_zero_coverage_rejected(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="Coverage"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, FLIGHT_DATE, "MODERATE", "0"]
        ).transact(value=PREMIUM)


# ------------------------------------------------------------- file_claim


def test_claim_paid_when_sources_agree_major(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    _run_claim(
        contract, buyer, CLAIM_TODAY,
        _classification("MAJOR", 180),
        _classification("MAJOR", 185),
    )
    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "PAID"
    assert record["bucket"] == "MAJOR"
    assert record["sources_agreed"] is True
    # Locked coverage returns to zero.
    assert int(contract.get_locked_coverage(args=[]).call()) == 0
    # Pool paid out coverage; premium remained.
    assert int(contract.get_pool_balance(args=[]).call()) == FUND + PREMIUM - COVERAGE


def test_claim_rejected_when_delay_below_threshold(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    _run_claim(
        contract, buyer, CLAIM_TODAY,
        _classification("MINOR", 30),
        _classification("MINOR", 25),
    )
    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "REJECTED"
    assert record["bucket"] == "MINOR"
    assert int(contract.get_locked_coverage(args=[]).call()) == 0
    # Pool keeps the premium as insurer income.
    assert int(contract.get_pool_balance(args=[]).call()) == FUND + PREMIUM


def test_claim_unresolved_when_sources_disagree(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    _run_claim(
        contract, buyer, CLAIM_TODAY,
        _classification("MAJOR", 180),
        _classification("ON_TIME", 5),
    )
    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "UNRESOLVED"
    assert record["sources_agreed"] is False


def test_claim_unresolved_when_flight_does_not_match(buyer):
    """Verdict is bound to the exact dated flight — if the LLM says
    flight_match/date_match/completed = false, the bucket collapses to
    UNKNOWN and consensus produces UNRESOLVED, no matter what bucket the
    LLM proposed."""
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    _run_claim(
        contract, buyer, CLAIM_TODAY,
        _classification("MAJOR", 180, match=False),
        _classification("MAJOR", 180, match=False),
    )
    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "UNRESOLVED"
    assert record["bucket"] == "UNKNOWN"


def test_claim_paid_for_cancelled_flight(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE, threshold="MINOR")
    _run_claim(
        contract, buyer, CLAIM_TODAY,
        _classification("CANCELLED", 0),
        _classification("CANCELLED", 0),
    )
    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "PAID"
    assert record["bucket"] == "CANCELLED"


def test_claim_rejected_before_flight(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    _install_mocks(
        contract.client,
        llm_mocks={},
        web_pages={TIME_URL_RE: _time_page("2026-08-31")},
    )
    with pytest.raises(Exception, match="not occurred"):
        contract.connect(buyer).file_claim(args=["1"]).transact()


def test_claim_rejected_after_window(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    _install_mocks(
        contract.client,
        llm_mocks={},
        web_pages={TIME_URL_RE: _time_page(LATE_CLAIM_TODAY)},
    )
    with pytest.raises(Exception, match="Claim window expired"):
        contract.connect(buyer).file_claim(args=["1"]).transact()


# ---------------------------------------------------------- resolve_unresolved


def test_resolve_unresolved_refunds_premium(buyer):
    contract = _deploy()
    _fund_and_buy(contract, buyer, TODAY_BEFORE)
    _run_claim(
        contract, buyer, CLAIM_TODAY,
        _classification("MAJOR", 180),
        _classification("ON_TIME", 5),
    )
    # Owner (deployer) resolves manually.
    contract.resolve_unresolved(args=["1"]).transact()
    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "CANCELLED"
    # Locked coverage returned; premium refunded so pool balance = FUND.
    assert int(contract.get_locked_coverage(args=[]).call()) == 0
    assert int(contract.get_pool_balance(args=[]).call()) == FUND
