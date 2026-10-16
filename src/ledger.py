"""Tamper-evident dispatch ledger: an append-only SHA-256 hash chain stored as JSON Lines.

Each record stores the hash of the previous record, and its own hash over its canonical JSON
(sorted keys, no whitespace, UTF-8). Editing, deleting, inserting or reordering any record
breaks a hash or a link, and verify() reports the first bad record.

LIMITATIONS (stated plainly):
- The chain proves records have not changed since they were written. It does NOT prove the
  inputs or results were truthful when written.
- Whoever controls the file can rewrite the WHOLE chain consistently, or truncate its tail.
  Detecting that needs the latest head hash to be published somewhere the writer cannot alter
  (verify(trusted_head=...)). The AnchorBackend interface is where a public blockchain
  (e.g. a testnet smart contract storing head hashes) plugs in. LocalFileAnchor is a
  stand-in for demos and offers no real protection.
- This is not a blockchain: there is no decentralised consensus or replication.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

GENESIS = "0" * 64
SCHEMA_VERSION = 1


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def record_hash(record: dict) -> str:
    return sha256_hex({k: v for k, v in record.items() if k != "record_hash"})


@dataclass
class VerifyResult:
    ok: bool
    n_records: int
    head_hash: str
    first_bad_index: int | None = None
    reason: str = ""


class AnchorBackend(Protocol):
    def publish(self, head_hash: str, n_records: int) -> dict: ...
    def latest(self) -> dict | None: ...


class LocalFileAnchor:
    """Writes the head hash to a separate file. Demo stand-in only (same trust domain)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def publish(self, head_hash: str, n_records: int) -> dict:
        receipt = {"head_hash": head_hash, "n_records": n_records, "backend": "local_file",
                   "published_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.path.write_text(json.dumps(receipt, indent=2))
        return receipt

    def latest(self) -> dict | None:
        return json.loads(self.path.read_text()) if self.path.exists() else None


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def head_hash(self) -> str:
        recs = self.records()
        return recs[-1]["record_hash"] if recs else GENESIS

    def append(self, payload: dict, scenario_id: str, run_id: str | None = None) -> dict:
        """Append one record. `payload` holds input hash, config, dispatch, metrics, validation."""
        recs = self.records()
        record = {
            "schema_version": SCHEMA_VERSION,
            "index": len(recs),
            "run_id": run_id or uuid.uuid4().hex,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scenario_id": scenario_id,
            **payload,
            "prev_hash": recs[-1]["record_hash"] if recs else GENESIS,
        }
        record["record_hash"] = record_hash(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical_json(record) + "\n")
        return record

    def ledger_id(self) -> str:
        """Identifier of this ledger: the record_hash of its first (genesis) record."""
        recs = self.records()
        return recs[0]["record_hash"] if recs else GENESIS

    def verify(self, trusted_head: str | None = None, trusted_n: int | None = None) -> VerifyResult:
        """Check every hash and link. With trusted_head (from an anchor):
        - trusted_n given: record trusted_n-1 must have that hash (records appended AFTER the
          anchor are allowed); fewer than trusted_n records means truncation.
        - trusted_n omitted: the current head must equal trusted_head exactly."""
        try:
            recs = self.records()
        except json.JSONDecodeError as e:
            return VerifyResult(False, 0, "", 0, f"unparseable ledger line: {e}")
        prev = GENESIS
        for i, r in enumerate(recs):
            if r.get("index") != i:
                return VerifyResult(False, len(recs), "", i, f"index {r.get('index')} at position {i}")
            if r.get("prev_hash") != prev:
                return VerifyResult(False, len(recs), "", i, "prev_hash does not match previous record")
            if record_hash(r) != r.get("record_hash"):
                return VerifyResult(False, len(recs), "", i, "record contents do not match record_hash")
            prev = r["record_hash"]
        if trusted_head is not None:
            if trusted_n is not None:
                if len(recs) < trusted_n:
                    return VerifyResult(False, len(recs), prev, None,
                                        f"ledger has {len(recs)} records but {trusted_n} were anchored: "
                                        "truncated")
                if recs[trusted_n - 1]["record_hash"] != trusted_head:
                    return VerifyResult(False, len(recs), prev, trusted_n - 1,
                                        "record at the anchored position does not match the anchored "
                                        "hash: rewritten")
            elif prev != trusted_head:
                return VerifyResult(False, len(recs), prev, None,
                                    "chain is internally consistent but its head differs from the "
                                    "trusted (anchored) head: rewritten or truncated")
        return VerifyResult(True, len(recs), prev)

    def export_json(self, out_path: str | Path) -> Path:
        out = Path(out_path)
        out.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "head_hash": self.head_hash(),
                                   "records": self.records()}, indent=2, ensure_ascii=False))
        return out


def dispatch_payload(controller: str, inputs_dict: dict, config: dict, dispatch: dict,
                     metrics: dict, validation: dict) -> dict:
    return {"controller": controller, "input_hash": sha256_hex(inputs_dict), "config": config,
            "dispatch": dispatch, "metrics": metrics, "validation": validation}
