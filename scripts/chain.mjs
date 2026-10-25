import ganache from 'ganache';
import solc from 'solc';
import { ethers } from 'ethers';
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
fs.mkdirSync('.local', { recursive: true });
const source = fs.readFileSync('contracts/AuthenTraRegistry.sol', 'utf8');
const compiled = JSON.parse(solc.compile(JSON.stringify({
  language: 'Solidity', sources: { 'AuthenTraRegistry.sol': { content: source } },
  settings: { evmVersion: 'shanghai', optimizer: { enabled: true, runs: 200 }, outputSelection: { '*': { '*': ['abi', 'evm.bytecode'] } } }
})));
const errors = (compiled.errors || []).filter(e => e.severity === 'error');
if (errors.length) throw new Error(errors.map(e => e.formattedMessage).join('\n'));
const contract = compiled.contracts['AuthenTraRegistry.sol'].AuthenTraRegistry;
const server = ganache.server({
  chain: { chainId: 1337 }, database: { dbPath: path.join(root, '.local', 'chain-db') },
  wallet: { deterministic: true, totalAccounts: 5 }, logging: { quiet: true }
});
await server.listen(8545, '127.0.0.1');
const accounts = Object.entries(server.provider.getInitialAccounts());
const provider = new ethers.JsonRpcProvider('http://127.0.0.1:8545');
const owner = new ethers.Wallet(accounts[0][1].secretKey, provider);
let previous = null;
try { previous = JSON.parse(fs.readFileSync('.local/chain.json', 'utf8')); } catch {}
let address = previous?.contractAddress;
if (!address || await provider.getCode(address) === '0x') {
  const instance = await new ethers.ContractFactory(contract.abi, contract.evm.bytecode.object, owner).deploy();
  await instance.waitForDeployment(); address = await instance.getAddress();
  await (await instance.setIssuer(accounts[1][0], true)).wait();
}
fs.writeFileSync('.local/chain.json', JSON.stringify({
  rpcUrl: 'http://127.0.0.1:8545', chainId: 1337, contractAddress: address, abi: contract.abi,
  ownerAddress: accounts[0][0], ownerKey: accounts[0][1].secretKey,
  issuers: accounts.slice(1, 4).map(([address, account]) => ({ address, key: account.secretKey }))
}, null, 2), { mode: 0o600 });
fs.writeFileSync('contracts/abi.json', JSON.stringify(contract.abi, null, 2));
console.log(`Local development blockchain ready on http://127.0.0.1:8545. Contract: ${address}`);
console.log('Development accounts only. Never fund these deterministic accounts on a public network.');
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, async () => { await server.close(); process.exit(0); });
