# GridGuard — Security and data-integrity assessment

## 1. What we protect

| Asset | Why it matters |
|---|---|
| Dispatch records (decisions, metrics, validation) | Operators, funders and carbon-credit buyers need to trust that reported performance was not edited afterwards |
| Model inputs and configuration | A result is only meaningful together with the exact inputs and parameters that produced it |
| The publisher's signing key | Whoever holds it can publish anchors under that identity |

## 2. Controls

| Control | Implementation | Test |
|---|---|---|
| Record integrity | SHA-256 over canonical JSON (sorted keys, no whitespace, UTF-8, NaN rejected) | `test_canonical_json_is_key_order_independent`, `test_nan_rejected` |
| Ordering and completeness | Each record stores the previous record's hash and its index | `test_deleted_and_reordered_records_detected` |
| Input binding | Each record stores a SHA-256 hash of the full input time series, plus the full configuration | `dispatch_payload()` |
| Tamper detection | `verify()` reports the first bad record and the reason | `test_modified_value_detected`, `test_modified_value_with_recomputed_hash_breaks_next_link` |
| Rewrite and truncation resistance | Head hash anchored in the `GridGuardAnchor` contract on public Ethereum Sepolia; the record count can only increase | `test_rewritten_chain_detected_against_chain`, `test_truncation_detected_against_chain`, `test_contract_rejects_shrinking_ledger_and_empty_hash` |
| Publisher isolation | Anchors are keyed by `msg.sender`; a third party cannot overwrite or confuse another publisher's anchors | `test_anchors_are_per_publisher` |
| Data minimization | Only 32-byte hashes and a record count go on-chain; records stay off-chain | Contract design |
| Key handling | Private key entered only through a hidden prompt, held in memory, never written to disk, arguments, logs or the repository; `.env` is git-ignored | `run_chain_anchor.py` |
| Physics integrity | An independent validator re-checks every controller's dispatch, so a buggy optimizer cannot report impossible results | 14 checks, 81 tests, 300-case random stress test |
| Reproducibility | Deterministic scenarios, unique optimal plans, and a results fingerprint that matches across machines | `test_plan_unique_across_solver_paths`, `run_validation.py` |
| Supply chain | Solidity compiler pinned (0.8.28); source SHA-256 recorded in the build artifact | `contracts/compile.js` |

## 3. Threat model

| Threat | Outcome |
|---|---|
| Someone edits a value in a stored record | **Detected** at that record (hash mismatch) |
| Someone edits a value and recomputes that record's hash | **Detected** at the next record (broken link) |
| Someone edits a record and re-hashes every later record | **Missed** by a local check alone; **detected** against the on-chain anchor |
| Someone deletes the newest records | **Missed** by a local check alone; **detected** against the on-chain anchor |
| Someone deletes, inserts or reorders middle records | **Detected** (index or link mismatch) |
| A third party publishes fake anchors | **No effect**: verification uses the expected publisher's address |
| The publisher's key is stolen | **Not prevented**: the attacker can publish new anchors, but existing anchors cannot be changed, and the record count cannot shrink. Mitigation: hardware wallet or multisig in production |
| Inputs are false when first recorded | **Not detected**: a hash chain proves "unchanged since", not "true". Mitigation: signed meter or sensor data at the source (future work) |
| Dashboard visitors | The hosted demo has no accounts and no personal data; its local ledger file is temporary and resets on restart |

## 4. Residual risks and next steps

- **Testnet only.** Sepolia has no economic security. Production would anchor on a mainnet or an
  L2, or batch several sites into one Merkle root to cut cost.
- **Single publisher.** Multi-party trust (operator, auditor and funder co-signing) would need a
  multisig or one anchor per party.
- **Off-chain storage.** Records live in a file. Production would replicate them (for example
  object storage plus IPFS) so the data stays available, not just tamper-evident.
- **No source authentication.** Signed meter data would close the gap between "unchanged" and
  "true".
