// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title GridGuardAnchor
/// @notice Public, append-only anchor for GridGuard audit-ledger head hashes.
/// @dev The dispatch records themselves stay off-chain (SHA-256 hash chain, JSON Lines). Only the
///      32-byte hash of the latest record (the "head") and the record count are written here,
///      so anyone can later check that an off-chain ledger has not been rewritten or truncated.
///      Anchors are attributed to msg.sender; a verifier trusts the publisher address it expects.
///      A ledger is identified by the hash of its first record (ledgerId), so one publisher can
///      keep several independent ledgers. For a given (publisher, ledgerId) the anchored record
///      count can never decrease, which makes on-chain truncation impossible to hide.
contract GridGuardAnchor {
    struct Anchor {
        bytes32 headHash;    // record_hash of record nRecords-1
        uint64 nRecords;     // number of records covered by headHash
        uint64 timestamp;    // block timestamp when anchored
        uint64 blockNumber;  // block in which it was anchored
    }

    mapping(address => mapping(bytes32 => Anchor[])) private _anchors;

    event Anchored(
        address indexed publisher,
        bytes32 indexed ledgerId,
        uint256 index,
        bytes32 headHash,
        uint64 nRecords,
        string runId
    );

    function anchor(bytes32 ledgerId, bytes32 headHash, uint64 nRecords, string calldata runId)
        external
        returns (uint256 index)
    {
        require(ledgerId != bytes32(0) && headHash != bytes32(0), "empty hash");
        require(nRecords > 0, "empty ledger");
        Anchor[] storage list = _anchors[msg.sender][ledgerId];
        if (list.length > 0) {
            require(nRecords >= list[list.length - 1].nRecords, "ledger cannot shrink");
        }
        list.push(Anchor(headHash, nRecords, uint64(block.timestamp), uint64(block.number)));
        index = list.length - 1;
        emit Anchored(msg.sender, ledgerId, index, headHash, nRecords, runId);
    }

    function count(address publisher, bytes32 ledgerId) external view returns (uint256) {
        return _anchors[publisher][ledgerId].length;
    }

    function get(address publisher, bytes32 ledgerId, uint256 index) external view returns (Anchor memory) {
        return _anchors[publisher][ledgerId][index];
    }

    function latest(address publisher, bytes32 ledgerId) external view returns (Anchor memory) {
        Anchor[] storage list = _anchors[publisher][ledgerId];
        require(list.length > 0, "no anchors");
        return list[list.length - 1];
    }
}
