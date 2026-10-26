import solc from 'solc';
import { ethers } from 'ethers';
import fs from 'node:fs';

const root = process.cwd();
const source = fs.readFileSync('contracts/AuthenTraRegistry.sol', 'utf8');
const compiled = JSON.parse(solc.compile(JSON.stringify({
  language: 'Solidity', sources: { 'AuthenTraRegistry.sol': { content: source } },
  settings: { evmVersion: 'shanghai', optimizer: { enabled: true, runs: 200 }, outputSelection: { '*': { '*': ['abi', 'evm.bytecode'] } } }
})));
const errors = (compiled.errors || []).filter(e => e.severity === 'error');
if (errors.length) throw new Error(errors.map(e => e.formattedMessage).join('\n'));
const contract = compiled.contracts['AuthenTraRegistry.sol'].AuthenTraRegistry;

const provider = new ethers.JsonRpcProvider('http://127.0.0.1:8545');
let currentConfig = JSON.parse(fs.readFileSync('.local/chain.json', 'utf8'));
const owner = new ethers.Wallet(currentConfig.ownerKey, provider);
const ownerAddr = await owner.getAddress();

let currentNonce = parseInt(await provider.send('eth_getTransactionCount', [ownerAddr, 'latest']), 16);
console.log('Deploying updated AuthenTraRegistry from owner', ownerAddr, 'at nonce', currentNonce);
const factory = new ethers.ContractFactory(contract.abi, contract.evm.bytecode.object, owner);
const instance = await factory.deploy({ nonce: currentNonce++ });
await instance.waitForDeployment();
const address = await instance.getAddress();
console.log('Contract deployed at:', address);

for (const issuer of currentConfig.issuers) {
  const tx = await instance.setIssuer(issuer.address, true, { nonce: currentNonce++ });
  await tx.wait();
  console.log('Approved issuer:', issuer.address);
}

currentConfig.contractAddress = address;
currentConfig.abi = contract.abi;
fs.writeFileSync('.local/chain.json', JSON.stringify(currentConfig, null, 2), { mode: 0o600 });
fs.writeFileSync('contracts/abi.json', JSON.stringify(contract.abi, null, 2));
console.log('Updated .local/chain.json and contracts/abi.json successfully.');
