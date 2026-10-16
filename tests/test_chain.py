"""GridGuardAnchor contract + Python client, tested on an in-process EVM (no network, no real keys)."""
import pytest

pytest.importorskip("eth_tester")
from eth_account import Account  # noqa: E402
from web3 import EthereumTesterProvider, Web3  # noqa: E402

from src.chain import ChainAnchor, deploy, hex32, verify_against_chain  # noqa: E402
from src.ledger import Ledger, canonical_json  # noqa: E402


@pytest.fixture
def chain():
    w3 = Web3(EthereumTesterProvider())
    # eth-tester ships pre-funded TEST accounts; use one as a LocalAccount signer.
    funded = w3.eth.accounts[0]
    acct = Account.create()                         # throwaway key, exists only in this test
    w3.eth.send_transaction({"from": funded, "to": acct.address, "value": w3.to_wei(1, "ether")})
    info = deploy(w3, acct)
    return w3, acct, info


@pytest.fixture
def ledger(tmp_path):
    lg = Ledger(tmp_path / "ledger.jsonl")
    for i in range(5):
        lg.append({"metrics": {"cost": 100.0 + i}}, scenario_id=f"s{i}")
    return lg


def test_deploy_and_anchor_round_trip(chain, ledger):
    w3, acct, info = chain
    a = ChainAnchor(w3, info["address"], acct.address, ledger.ledger_id(), account=acct)
    assert a.latest() is None
    receipt = a.publish(ledger.head_hash(), 5, "run-1")
    assert receipt["tx"].startswith("0x") and receipt["n_records"] == 5
    onchain = a.latest()
    assert onchain["head_hash"] == ledger.head_hash() and onchain["n_records"] == 5
    res, _ = verify_against_chain(ledger, ChainAnchor(w3, info["address"], acct.address,
                                                      ledger.ledger_id()))   # read-only client
    assert res.ok


def test_appending_after_anchor_still_verifies(chain, ledger):
    w3, acct, info = chain
    a = ChainAnchor(w3, info["address"], acct.address, ledger.ledger_id(), account=acct)
    a.publish(ledger.head_hash(), 5)
    ledger.append({"metrics": {"cost": 1.0}}, scenario_id="later")
    assert verify_against_chain(ledger, a)[0].ok


def test_rewritten_chain_detected_against_chain(chain, ledger):
    """Attacker edits record 2 AND re-hashes every later record: the file is internally
    consistent, but no longer matches the on-chain head."""
    from src.ledger import record_hash
    w3, acct, info = chain
    a = ChainAnchor(w3, info["address"], acct.address, ledger.ledger_id(), account=acct)
    a.publish(ledger.head_hash(), 5)
    recs = ledger.records()
    recs[2]["metrics"]["cost"] = 0.0
    for i in range(2, len(recs)):
        if i > 2:
            recs[i]["prev_hash"] = recs[i - 1]["record_hash"]
        recs[i]["record_hash"] = record_hash(recs[i])
    ledger.path.write_text("".join(canonical_json(r) + "\n" for r in recs))
    assert ledger.verify().ok                       # fools a local-only check
    res, _ = verify_against_chain(ledger, a)
    assert not res.ok and "rewritten" in res.reason


def test_truncation_detected_against_chain(chain, ledger):
    w3, acct, info = chain
    a = ChainAnchor(w3, info["address"], acct.address, ledger.ledger_id(), account=acct)
    a.publish(ledger.head_hash(), 5)
    ledger.path.write_text("".join(canonical_json(r) + "\n" for r in ledger.records()[:3]))
    res, _ = verify_against_chain(ledger, a)
    assert not res.ok and "truncated" in res.reason


def test_contract_rejects_shrinking_ledger_and_empty_hash(chain, ledger):
    w3, acct, info = chain
    a = ChainAnchor(w3, info["address"], acct.address, ledger.ledger_id(), account=acct)
    a.publish(ledger.head_hash(), 5)
    with pytest.raises(Exception, match="ledger cannot shrink"):
        a.publish(ledger.head_hash(), 4)
    with pytest.raises(ValueError):
        hex32("00" * 31)


def test_anchors_are_per_publisher(chain, ledger):
    """Someone else anchoring a fake head under THEIR address does not affect verification
    against the expected publisher."""
    w3, acct, info = chain
    a = ChainAnchor(w3, info["address"], acct.address, ledger.ledger_id(), account=acct)
    a.publish(ledger.head_hash(), 5)
    mallory = Account.create()
    w3.eth.send_transaction({"from": w3.eth.accounts[0], "to": mallory.address,
                             "value": w3.to_wei(1, "ether")})
    ChainAnchor(w3, info["address"], mallory.address, ledger.ledger_id(),
                account=mallory).publish("ab" * 32, 99)
    assert verify_against_chain(ledger, a)[0].ok
