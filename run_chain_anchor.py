"""Anchor the GridGuard audit ledger on the public Ethereum Sepolia TESTNET.

    .venv/bin/python run_chain_anchor.py deploy    # once: deploy GridGuardAnchor (needs test ETH)
    .venv/bin/python run_chain_anchor.py anchor    # snapshot results/ledger.jsonl and anchor its head
    .venv/bin/python run_chain_anchor.py verify    # read-only: check the snapshot against the chain

Your private key is asked for with a hidden prompt, used in memory only, and never written
anywhere. Use a FRESH wallet that holds only free testnet ETH, never one with real funds.
"""
from __future__ import annotations

import getpass
import json
import shutil
import sys
from pathlib import Path

from eth_account import Account

from src.chain import DEPLOYMENT, EXPLORER, SEPOLIA_CHAIN_ID, ChainAnchor, connect, deploy, verify_against_chain
from src.ledger import Ledger

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "results" / "ledger.jsonl"
SNAPSHOT = ROOT / "results" / "anchored_ledger.jsonl"
RECEIPT = ROOT / "results" / "chain_anchor_receipt.json"
MIN_BALANCE_ETH = 0.002


def ask_account():
    key = getpass.getpass("Paste the TESTNET wallet private key (input is hidden), then Enter: ").strip()
    try:
        acct = Account.from_key(key if key.startswith("0x") else "0x" + key)
    except Exception:
        sys.exit("That does not look like a valid private key (64 hex characters).")
    finally:
        key = None  # noqa: F841 - drop the reference as soon as possible
    return acct


def require_sepolia(w3) -> None:
    if w3.eth.chain_id != SEPOLIA_CHAIN_ID:
        sys.exit(f"Connected to chain {w3.eth.chain_id}, expected Sepolia ({SEPOLIA_CHAIN_ID}).")


def check_funds(w3, acct) -> None:
    bal = w3.from_wei(w3.eth.get_balance(acct.address), "ether")
    print(f"Wallet {acct.address}: {bal:.5f} Sepolia ETH")
    if bal < MIN_BALANCE_ETH:
        sys.exit("Not enough test ETH. Get free Sepolia ETH from the Google Cloud faucet "
                 "(https://cloud.google.com/application/web3/faucet/ethereum/sepolia) and try again.")


def cmd_deploy() -> None:
    if DEPLOYMENT.exists():
        sys.exit(f"Already deployed: {json.loads(DEPLOYMENT.read_text())['address']} "
                 f"(delete {DEPLOYMENT.name} to deploy a new one).")
    w3 = connect(); require_sepolia(w3)
    acct = ask_account(); check_funds(w3, acct)
    print("Deploying GridGuardAnchor ... (about 15-60 s)")
    info = deploy(w3, acct)
    DEPLOYMENT.write_text(json.dumps(info, indent=2))
    print(f"Deployed at {info['address']}\n  {EXPLORER}/address/{info['address']}\nSaved {DEPLOYMENT}")


def cmd_anchor() -> None:
    if not DEPLOYMENT.exists():
        sys.exit("Deploy first: run_chain_anchor.py deploy")
    if not LEDGER.exists():
        sys.exit("No ledger yet: run run_demo.py first")
    local = Ledger(LEDGER).verify()
    if not local.ok:
        sys.exit(f"Refusing to anchor: local ledger fails verification ({local.reason})")
    shutil.copy(LEDGER, SNAPSHOT)
    snap = Ledger(SNAPSHOT)
    recs = snap.records()
    dep = json.loads(DEPLOYMENT.read_text())
    w3 = connect(); require_sepolia(w3)
    acct = ask_account(); check_funds(w3, acct)
    anchor = ChainAnchor(w3, dep["address"], acct.address, snap.ledger_id(), account=acct)
    print(f"Anchoring head {snap.head_hash()[:16]}... of {len(recs)} records ...")
    receipt = anchor.publish(snap.head_hash(), len(recs), recs[-1].get("run_id", ""))
    RECEIPT.write_text(json.dumps(receipt, indent=2))
    print(f"Anchored in block {receipt['block']}\n  {receipt['explorer_tx']}\n"
          f"Saved {SNAPSHOT.name} and {RECEIPT.name} (commit both so judges can verify)")


def cmd_verify() -> None:
    if not (DEPLOYMENT.exists() and RECEIPT.exists() and SNAPSHOT.exists()):
        sys.exit("Nothing anchored yet (need contracts/deployment.json, results/anchored_ledger.jsonl "
                 "and results/chain_anchor_receipt.json).")
    dep, rec = json.loads(DEPLOYMENT.read_text()), json.loads(RECEIPT.read_text())
    w3 = connect(); require_sepolia(w3)
    snap = Ledger(SNAPSHOT)
    res, onchain = verify_against_chain(snap, ChainAnchor(w3, dep["address"], rec["publisher"],
                                                          snap.ledger_id()))
    print(f"On-chain head: {onchain['head_hash'][:16]}... covering {onchain['n_records']} records "
          f"(block {onchain['block']})" if onchain else "No on-chain anchor found")
    print("VALID: snapshot matches the Sepolia anchor" if res.ok else f"FAILED: {res.reason}")
    sys.exit(0 if res.ok else 1)


if __name__ == "__main__":
    cmds = {"deploy": cmd_deploy, "anchor": cmd_anchor, "verify": cmd_verify}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
