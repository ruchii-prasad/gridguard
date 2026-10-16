"""Demonstrate tamper detection on a COPY of the audit ledger (the real ledger is untouched).

Run run_demo.py first so results/ledger.jsonl exists.
Usage:  .venv/bin/python run_tamper_demo.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.ledger import Ledger, LocalFileAnchor, canonical_json, record_hash

RESULTS = Path(__file__).parent / "results"


def show(label: str, res) -> None:
    where = f" at record {res.first_bad_index}" if res.first_bad_index is not None else ""
    status = "VALID" if res.ok else f"TAMPER DETECTED{where}: {res.reason}"
    print(f"{label:52s} {status}")


def main() -> None:
    src = RESULTS / "ledger.jsonl"
    if not src.exists():
        raise SystemExit("results/ledger.jsonl not found: run run_demo.py first")
    copy = RESULTS / "tamper_demo_copy.jsonl"
    trusted = LocalFileAnchor(RESULTS / "ledger_anchor.json").latest()
    ledger = Ledger(copy)

    def reset() -> list[dict]:
        shutil.copy(src, copy)
        return ledger.records()

    def write(recs: list[dict]) -> None:
        copy.write_text("".join(canonical_json(r) + "\n" for r in recs))

    recs = reset()
    show("1. Untouched copy", ledger.verify(trusted["head_hash"] if trusted else None))

    i = next(k for k, r in enumerate(recs) if r["controller"] == "reoptimized")
    before = recs[i]["metrics"]["emissions_storage_adjusted_kg"]
    recs[i]["metrics"]["emissions_storage_adjusted_kg"] = before * 0.8
    write(recs)
    print(f"\n   Editing record {i} ({recs[i]['scenario_id']}/reoptimized): "
          f"emissions {before:.1f} -> {before * 0.8:.1f} kg")
    show("2. Edited emissions value", ledger.verify())

    recs[i]["record_hash"] = record_hash(recs[i])
    write(recs)
    show("3. Same edit + record hash recomputed", ledger.verify())

    recs = reset()
    write(recs[:-3])
    show("4. Last 3 records deleted (no anchor)", ledger.verify())
    if trusted:
        show("5. Last 3 records deleted (checked vs anchored head)",
             ledger.verify(trusted["head_hash"]))
    copy.unlink()
    print("\nNote: case 4 shows the limitation: truncation is only caught against an external anchor.")


if __name__ == "__main__":
    main()
