// Reproducible build: node contracts/compile.js  ->  contracts/GridGuardAnchor.json
// Requires the pinned compiler: (cd contracts && npm install solc@0.8.28)
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const solc = require("solc");

const src = fs.readFileSync(path.join(__dirname, "GridGuardAnchor.sol"), "utf8");
const settings = { optimizer: { enabled: true, runs: 200 }, evmVersion: "paris",
  outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } } };
const out = JSON.parse(solc.compile(JSON.stringify({
  language: "Solidity", sources: { "GridGuardAnchor.sol": { content: src } }, settings })));
const errors = (out.errors || []).filter((e) => e.severity === "error");
if (errors.length) { console.error(errors.map((e) => e.formattedMessage).join("\n")); process.exit(1); }
const c = out.contracts["GridGuardAnchor.sol"].GridGuardAnchor;
const artifact = {
  contractName: "GridGuardAnchor", compiler: solc.version(), settings,
  sourceSha256: crypto.createHash("sha256").update(src).digest("hex"),
  abi: c.abi, bytecode: "0x" + c.evm.bytecode.object,
};
fs.writeFileSync(path.join(__dirname, "GridGuardAnchor.json"), JSON.stringify(artifact, null, 2));
console.log(`compiled with ${solc.version()}: ${artifact.bytecode.length / 2 - 1} bytes, source sha256 ${artifact.sourceSha256.slice(0, 16)}...`);
