"""Public blockchain anchor for the audit ledger (GridGuardAnchor contract, Ethereum Sepolia).

Only the ledger's genesis hash (ledgerId), its latest record hash (head) and record count go
on-chain. Records stay off-chain. Writing needs a funded account; READING needs nothing, so any
judge can verify a ledger snapshot against the chain.

Security: private keys are never read from files or arguments here. Callers pass an
eth_account LocalAccount created in memory (run_chain_anchor.py asks via a hidden prompt).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web3 import Web3

from .ledger import Ledger, VerifyResult

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "contracts" / "GridGuardAnchor.json"
DEPLOYMENT = ROOT / "contracts" / "deployment.json"
SEPOLIA_CHAIN_ID = 11155111
DEFAULT_RPCS = ("https://ethereum-sepolia-rpc.publicnode.com", "https://sepolia.drpc.org",
                "https://rpc.sepolia.org")
EXPLORER = "https://sepolia.etherscan.io"


def load_artifact() -> dict:
    return json.loads(ARTIFACT.read_text())


def hex32(h: str) -> bytes:
    b = bytes.fromhex(h.removeprefix("0x"))
    if len(b) != 32:
        raise ValueError("expected a 32-byte hex hash")
    return b


def connect(rpc_urls=DEFAULT_RPCS, timeout: float = 15.0) -> Web3:
    errors = []
    for url in rpc_urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": timeout}))
            if w3.is_connected():
                return w3
            errors.append(f"{url}: not connected")
        except Exception as e:  # noqa: BLE001 - try the next public endpoint
            errors.append(f"{url}: {e}")
    raise ConnectionError("could not reach any Sepolia RPC endpoint:\n  " + "\n  ".join(errors))


def _send(w3: Web3, account, tx: dict) -> Any:
    tx.setdefault("from", account.address)
    tx.setdefault("chainId", w3.eth.chain_id)
    tx.setdefault("nonce", w3.eth.get_transaction_count(account.address))
    if "gas" not in tx:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    if "maxFeePerGas" not in tx and "gasPrice" not in tx:
        tx["gasPrice"] = w3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if receipt.status != 1:
        raise RuntimeError(f"transaction {tx_hash.hex()} reverted")
    return receipt


def deploy(w3: Web3, account) -> dict:
    art = load_artifact()
    factory = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    receipt = _send(w3, account, factory.constructor().build_transaction({"from": account.address}))
    return {"network": "sepolia" if w3.eth.chain_id == SEPOLIA_CHAIN_ID else f"chain-{w3.eth.chain_id}",
            "chain_id": w3.eth.chain_id, "address": receipt.contractAddress,
            "deploy_tx": "0x" + receipt.transactionHash.hex().removeprefix("0x"),
            "block": receipt.blockNumber, "deployer": account.address,
            "compiler": art["compiler"], "source_sha256": art["sourceSha256"],
            "deployed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


class ChainAnchor:
    """Anchor backend backed by the GridGuardAnchor contract."""

    def __init__(self, w3: Web3, address: str, publisher: str, ledger_id: str, account=None):
        self.w3 = w3
        self.contract = w3.eth.contract(address=Web3.to_checksum_address(address),
                                        abi=load_artifact()["abi"])
        self.publisher = Web3.to_checksum_address(publisher)
        self.ledger_id = ledger_id
        self.account = account

    def publish(self, head_hash: str, n_records: int, run_id: str = "") -> dict:
        if self.account is None:
            raise PermissionError("publishing needs an account; reading does not")
        fn = self.contract.functions.anchor(hex32(self.ledger_id), hex32(head_hash), n_records, run_id)
        receipt = _send(self.w3, self.account, fn.build_transaction({"from": self.account.address}))
        tx = "0x" + receipt.transactionHash.hex().removeprefix("0x")
        return {"backend": "ethereum", "chain_id": self.w3.eth.chain_id,
                "contract": self.contract.address, "publisher": self.publisher,
                "ledger_id": self.ledger_id, "head_hash": head_hash, "n_records": n_records,
                "run_id": run_id, "tx": tx, "block": receipt.blockNumber,
                "explorer_tx": f"{EXPLORER}/tx/{tx}",
                "published_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def latest(self) -> dict | None:
        n = self.contract.functions.count(self.publisher, hex32(self.ledger_id)).call()
        if n == 0:
            return None
        head, n_rec, ts, block = self.contract.functions.latest(self.publisher, hex32(self.ledger_id)).call()
        return {"head_hash": head.hex().removeprefix("0x"), "n_records": n_rec, "timestamp": ts,
                "block": block, "n_anchors": n}


def verify_against_chain(ledger: Ledger, anchor: ChainAnchor) -> tuple[VerifyResult, dict | None]:
    """Verify the ledger's own hash chain AND that it still contains the on-chain anchored head."""
    onchain = anchor.latest()
    if onchain is None:
        return VerifyResult(False, len(ledger.records()), ledger.head_hash(), None,
                            "no anchor found on-chain for this publisher and ledger"), None
    return ledger.verify(trusted_head=onchain["head_hash"], trusted_n=onchain["n_records"]), onchain
