import ganache from 'ganache';
import solc from 'solc';
import {ethers} from 'ethers';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const raw = ganache.provider({logging:{quiet:true},wallet:{deterministic:true}});
try {
  const provider = new ethers.BrowserProvider(raw);
  const [owner,issuer,stranger] = await Promise.all([0,1,2].map(i=>provider.getSigner(i)));
  const compiled=JSON.parse(solc.compile(JSON.stringify({language:'Solidity',sources:{'R.sol':{content:fs.readFileSync('contracts/AuthenTraRegistry.sol','utf8')}},settings:{evmVersion:'shanghai',outputSelection:{'*':{'*':['abi','evm.bytecode']}}}}))).contracts['R.sol'].AuthenTraRegistry;
  const contract=await new ethers.ContractFactory(compiled.abi,compiled.evm.bytecode.object,owner).deploy();await contract.waitForDeployment();
  const reference=ethers.sha256(ethers.toUtf8Bytes('AT-TEST-001')), hash=ethers.sha256(ethers.toUtf8Bytes('original'));
  let passed=0;
  async function rejected(promise,label){await assert.rejects(async()=>{const tx=await promise;await tx.wait()});console.log('PASS '+label);passed++}
  await rejected(contract.connect(stranger).setIssuer(await stranger.getAddress(),true),'Owner-only institution approval');
  await rejected(contract.connect(issuer).register(reference,hash),'Unapproved issuer cannot register');
  await (await contract.setIssuer(await issuer.getAddress(),true)).wait();
  await (await contract.connect(issuer).register(reference,hash,{gasLimit:300000})).wait();
  assert.equal((await contract.certificates(reference)).fileHash,hash);passed++;console.log('PASS Original SHA-256 stored');
  await rejected(contract.connect(issuer).register(reference,hash),'Duplicate reference cannot overwrite record');
  await (await contract.setIssuer(await stranger.getAddress(),true)).wait();
  await rejected(contract.connect(stranger).revoke(reference),'Different approved issuer cannot revoke');
  await (await contract.setIssuer(await issuer.getAddress(),false)).wait();
  await rejected(contract.connect(issuer).revoke(reference),'Disabled issuer cannot revoke');
  await (await contract.revoke(reference)).wait();
  assert.equal((await contract.certificates(reference)).revoked,true);passed++;console.log('PASS Owner can revoke disabled-issuer certificate');
  await rejected(contract.revoke(reference),'Revocation is permanent and idempotence protected');
  const reference2=ethers.sha256(ethers.toUtf8Bytes('AT-TEST-002'));
  await (await contract.connect(stranger).register(reference2,hash)).wait();
  await (await contract.connect(stranger).revoke(reference2)).wait();
  assert.equal((await contract.certificates(reference2)).revoked,true);passed++;console.log('PASS Issuer can revoke its own certificate');
  console.log(`${passed} smart-contract checks passed.`);
} finally {await raw.disconnect();}
