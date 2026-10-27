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

const rpcUrl = 'http://127.0.0.1:8545';
const configPath = '.local/chain.json';
let server;
let provider;

function readConfig() {
  if (!fs.existsSync(configPath)) return null;
  try { return JSON.parse(fs.readFileSync(configPath, 'utf8')); }
  catch { throw new Error('Cannot read .local/chain.json. Restore its matching backup; existing chain data has not been changed.'); }
}

async function validate(config) {
  if (!config?.contractAddress || !config.abi?.some(f => f.name === 'lookupByHash'))
    throw new Error('Missing or incompatible .local/chain.json. Restore the configuration matching this chain; no automatic redeployment was attempted.');
  if ((await provider.getNetwork()).chainId !== 1337n)
    throw new Error('Port 8545 is serving a different chain. AuthenTra requires local chain 1337.');
  if (await provider.getCode(config.contractAddress) === '0x')
    throw new Error('Configured registry has no deployed bytecode. Restore the matching chain/configuration; no automatic redeployment was attempted.');
  const instance = new ethers.Contract(config.contractAddress, contract.abi, provider);
  if ((await instance.owner()).toLowerCase() !== config.ownerAddress.toLowerCase())
    throw new Error('Registry owner does not match local configuration.');
  await instance.lookupByHash(ethers.ZeroHash);
}

try {
  // A bounded probe avoids ethers retry loops when no RPC is listening.
  let listening = false;
  try {
    await fetch(rpcUrl, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'eth_chainId', params: []}),
      signal: AbortSignal.timeout(2000)});
    listening = true;
  } catch {}
  let config = readConfig();
  provider = new ethers.JsonRpcProvider(rpcUrl, undefined, {cacheTimeout: -1});
  if (listening) {
    await validate(config);
    if (config.bootstrapComplete === false) throw new Error('Registry initialization is incomplete. Stop the local chain process and rerun scripts/chain.mjs to resume approvals.');
    console.log(`Local development blockchain ready (already running). Contract: ${config.contractAddress}`);
    provider.destroy();
  } else {
    if (process.argv.includes('--check')) throw new Error('Local blockchain RPC is unavailable on port 8545.');
    const dbPath = path.join(root, '.local', 'chain-db');
    if (!config && fs.existsSync(path.join(dbPath, 'CURRENT')))
      throw new Error('Existing chain database has no configuration. Restore .local/chain.json; refusing to redeploy over saved data.');
    server = ganache.server({
      chain: {chainId: 1337}, database: {dbPath},
      wallet: {deterministic: true, totalAccounts: 5}, logging: {quiet: true}
    });
    await server.listen(8545, '127.0.0.1');
    const accounts = Object.entries(server.provider.getInitialAccounts());
    const owner = new ethers.NonceManager(new ethers.Wallet(accounts[0][1].secretKey, provider));
    const save = () => fs.writeFileSync(configPath, JSON.stringify(config, null, 2), {mode: 0o600});
    if (!config) {
      const instance = await new ethers.ContractFactory(contract.abi, contract.evm.bytecode.object, owner).deploy();
      await instance.waitForDeployment();
      config = {rpcUrl, chainId: 1337, contractAddress: await instance.getAddress(), abi: contract.abi,
        ownerAddress: accounts[0][0], ownerKey: accounts[0][1].secretKey,
        issuers: accounts.slice(1, 4).map(([address, account]) => ({address, key: account.secretKey})), bootstrapComplete: false};
      // Persist deployment before approvals so a retry can resume without redeployment.
      save();
    }
    await validate(config);
    if (config.bootstrapComplete === false) {
      const instance = new ethers.Contract(config.contractAddress, contract.abi, owner);
      for (const issuer of config.issuers.slice(0, 2)) {
        if (!await instance.approvedIssuers(issuer.address)) {
          const receipt = await (await instance.setIssuer(issuer.address, true)).wait();
          if (receipt.status !== 1) throw new Error('Initial issuer approval reverted. Restart to retry initialization.');
        }
      }
      config.bootstrapComplete = true;
      save();
    }
    fs.writeFileSync('contracts/abi.json', JSON.stringify(contract.abi, null, 2));
    console.log(`Local development blockchain ready on ${rpcUrl}. Contract: ${config.contractAddress}`);
    console.log('Development accounts only. Never fund these deterministic accounts on a public network.');
    for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, async () => { provider.destroy(); await server.close(); process.exit(0); });
  }
} catch (err) {
  // Do not print transaction objects or signer configuration.
  console.error(`Local blockchain startup failed: ${err.shortMessage || err.message}`);
  console.error('Check port 8545, database access/locks, and the matching .local/chain.json. Existing data was preserved.');
  provider?.destroy();
  // Exit immediately: Ganache may still emit a LevelDB error after a failed open.
  process.exit(1);
}
