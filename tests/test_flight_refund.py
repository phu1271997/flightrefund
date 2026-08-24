"""FlightRefund integration tests.

    gltest tests/test_flight_refund.py --network localnet
    gltest tests/test_flight_refund.py --network studionet

Because the contract calls the LLM twice per claim (once per source) with
different prompts, we key the mock responses by regex on the prompt text
so each source can return a different bucket. See ~GEN_RULES/02-common-errors.md
rule R17 for why mocks are required.
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


def _install_mocks(client, per_source_llm: dict, web_pages: dict):
    llm_mocks = {}
    for pattern, response in per_source_llm.items():
        llm_mocks[pattern] = json.dumps(response)
    web_mocks = {p: {"status": 200, "body": b} for p, b in web_pages.items()}
    client.provider.make_request(
        method="sim_installMocks",
        params={"llm_mocks": llm_mocks, "web_mocks": web_mocks},
    )


def _deploy():
    clear_known_contracts()
    factory = get_contract_factory(str(CONTRACT))
    return factory.deploy()


FLIGHT = "VN123"
DATE = "2026-09-01"
PAYOUT = 500_000_000_000_000_000  # 0.5 GEN


def test_both_sources_agree_major_delay_pays_out(buyer):
    contract = _deploy()
    _install_mocks(
        contract.client,
        per_source_llm={
            ".*flightaware.*": {"bucket": "MAJOR", "delay_minutes": 180},
            ".*flightradar24.*": {"bucket": "MAJOR", "delay_minutes": 185},
        },
        web_pages={
            ".*flightaware.*": "VN123 arrived 3 hours late.",
            ".*flightradar24.*": "VN123 landed 3h05m past schedule.",
        },
    )
    contract.connect(buyer).buy_policy(
        args=[FLIGHT, DATE, "MODERATE"]
    ).transact(value=PAYOUT)
    contract.connect(buyer).file_claim(args=["1"]).transact()

    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "PAID"
    assert record["bucket"] == "MAJOR"
    assert record["sources_agreed"] is True


def test_sources_disagree_marks_unresolved(buyer):
    contract = _deploy()
    _install_mocks(
        contract.client,
        per_source_llm={
            ".*flightaware.*": {"bucket": "MAJOR", "delay_minutes": 180},
            ".*flightradar24.*": {"bucket": "ON_TIME", "delay_minutes": 5},
        },
        web_pages={
            ".*flightaware.*": "delayed",
            ".*flightradar24.*": "on time",
        },
    )
    contract.connect(buyer).buy_policy(
        args=[FLIGHT, DATE, "MODERATE"]
    ).transact(value=PAYOUT)
    contract.connect(buyer).file_claim(args=["1"]).transact()

    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "UNRESOLVED"
    assert record["sources_agreed"] is False


def test_delay_below_threshold_rejects(buyer):
    contract = _deploy()
    _install_mocks(
        contract.client,
        per_source_llm={
            ".*flightaware.*": {"bucket": "MINOR", "delay_minutes": 30},
            ".*flightradar24.*": {"bucket": "MINOR", "delay_minutes": 25},
        },
        web_pages={
            ".*flightaware.*": "30m late",
            ".*flightradar24.*": "25m late",
        },
    )
    contract.connect(buyer).buy_policy(
        args=[FLIGHT, DATE, "MODERATE"]
    ).transact(value=PAYOUT)
    contract.connect(buyer).file_claim(args=["1"]).transact()

    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "REJECTED"
    assert record["bucket"] == "MINOR"


def test_cancelled_flight_pays_out(buyer):
    contract = _deploy()
    _install_mocks(
        contract.client,
        per_source_llm={
            ".*flightaware.*": {"bucket": "CANCELLED", "delay_minutes": 0},
            ".*flightradar24.*": {"bucket": "CANCELLED", "delay_minutes": 0},
        },
        web_pages={
            ".*flightaware.*": "flight cancelled",
            ".*flightradar24.*": "cancelled",
        },
    )
    contract.connect(buyer).buy_policy(
        args=[FLIGHT, DATE, "MINOR"]
    ).transact(value=PAYOUT)
    contract.connect(buyer).file_claim(args=["1"]).transact()

    record = json.loads(contract.get_policy(args=["1"]).call())
    assert record["status"] == "PAID"
    assert record["bucket"] == "CANCELLED"


def test_invalid_flight_number_rejected(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="Invalid flight number"):
        contract.connect(buyer).buy_policy(
            args=["not-a-flight", DATE, "MODERATE"]
        ).transact(value=PAYOUT)


def test_zero_payout_rejected(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="positive"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, DATE, "MODERATE"]
        ).transact(value=0)


def test_bad_threshold_rejected(buyer):
    contract = _deploy()
    with pytest.raises(Exception, match="Threshold"):
        contract.connect(buyer).buy_policy(
            args=[FLIGHT, DATE, "ON_TIME"]
        ).transact(value=PAYOUT)
