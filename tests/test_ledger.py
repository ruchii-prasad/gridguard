import json

import pytest

from src.ledger import GENESIS, Ledger, LocalFileAnchor, canonical_json, record_hash, sha256_hex


def payload(i: int) -> dict:
    return {"controller": "oracle", "input_hash": sha256_hex({"x": i}),
            "metrics": {"cost": 100.0 + i, "emissions_kg": 50.0 + i}}


@pytest.fixture
def ledger(tmp_path):
    lg = Ledger(tmp_path / "ledger.jsonl")
    for i in range(4):
        lg.append(payload(i), scenario_id=f"s{i}")
    return lg


def rewrite(lg: Ledger, recs: list[dict]) -> None:
    lg.path.write_text("".join(canonical_json(r) + "\n" for r in recs))


def test_canonical_json_is_key_order_independent():
    assert sha256_hex({"a": 1, "b": [1.5, 2]}) == sha256_hex({"b": [1.5, 2], "a": 1})


def test_chain_links_and_verifies(ledger):
    recs = ledger.records()
    assert recs[0]["prev_hash"] == GENESIS
    assert all(recs[i]["prev_hash"] == recs[i - 1]["record_hash"] for i in range(1, 4))
    res = ledger.verify()
    assert res.ok and res.n_records == 4 and res.head_hash == recs[-1]["record_hash"]


def test_empty_ledger_verifies(tmp_path):
    res = Ledger(tmp_path / "none.jsonl").verify()
    assert res.ok and res.n_records == 0 and res.head_hash == GENESIS


def test_modified_value_detected(ledger):
    recs = ledger.records()
    recs[2]["metrics"]["emissions_kg"] -= 10.0          # quietly improve a result
    rewrite(ledger, recs)
    res = ledger.verify()
    assert not res.ok and res.first_bad_index == 2 and "record_hash" in res.reason


def test_modified_value_with_recomputed_hash_breaks_next_link(ledger):
    recs = ledger.records()
    recs[1]["metrics"]["cost"] = 1.0
    recs[1]["record_hash"] = record_hash(recs[1])       # attacker recomputes this record's hash
    rewrite(ledger, recs)
    res = ledger.verify()
    assert not res.ok and res.first_bad_index == 2 and "prev_hash" in res.reason


def test_deleted_and_reordered_records_detected(ledger):
    recs = ledger.records()
    rewrite(ledger, recs[:1] + recs[2:])
    assert ledger.verify().first_bad_index == 1
    rewrite(ledger, [recs[0], recs[2], recs[1], recs[3]])
    assert not ledger.verify().ok


def test_truncation_only_detected_against_trusted_head(ledger, tmp_path):
    anchor = LocalFileAnchor(tmp_path / "anchor.json")
    anchor.publish(ledger.head_hash(), len(ledger.records()))
    rewrite(ledger, ledger.records()[:2])               # drop the last two records
    assert ledger.verify().ok                           # internally consistent: limitation
    res = ledger.verify(trusted_head=anchor.latest()["head_hash"])
    assert not res.ok and "trusted" in res.reason


def test_garbage_line_detected(ledger):
    with ledger.path.open("a") as f:
        f.write("{not json\n")
    assert not ledger.verify().ok


def test_export_round_trip(ledger, tmp_path):
    out = json.loads(ledger.export_json(tmp_path / "export.json").read_text())
    assert out["head_hash"] == ledger.head_hash()
    assert out["records"] == ledger.records()


def test_nan_rejected(tmp_path):
    with pytest.raises(ValueError):
        Ledger(tmp_path / "l.jsonl").append({"metrics": {"cost": float("nan")}}, "s")
