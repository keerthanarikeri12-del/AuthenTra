import json
import os
import threading
from pathlib import Path
from web3 import Web3
from eth_account import Account
from .core import reference_hash

ROOT = Path(__file__).resolve().parents[1]
TRANSACTION_LOCK = threading.Lock()

class Registry:
    def __init__(self):
        demo = os.getenv("AUTHENTRA_DEMO", "0") == "1"
        if demo:
            config = json.loads((ROOT / ".local/chain.json").read_text())
            self.keys = {Web3.to_checksum_address(i["address"]): i["key"] for i in config["issuers"]}
            self.keys[Web3.to_checksum_address(config["ownerAddress"])] = config["ownerKey"]
            self.owner = Web3.to_checksum_address(config["ownerAddress"])
        else:
            config = {"rpcUrl": os.environ["RPC_URL"], "contractAddress": os.environ["CONTRACT_ADDRESS"], "abi": json.loads((ROOT / "contracts/abi.json").read_text())}
            self.keys = {Web3.to_checksum_address(k): v for k, v in json.loads(os.getenv("ISSUER_PRIVATE_KEYS", "{}")).items()}
            owner_key = os.getenv("OWNER_PRIVATE_KEY")
            self.owner = Account.from_key(owner_key).address if owner_key else None
            if owner_key:
                self.keys[self.owner] = owner_key
        self.w3 = Web3(Web3.HTTPProvider(config["rpcUrl"], request_kwargs={"timeout": 10}))
        self.contract = self.w3.eth.contract(address=Web3.to_checksum_address(config["contractAddress"]), abi=config["abi"])

    def health(self):
        return self.w3.is_connected() and len(self.w3.eth.get_code(self.contract.address)) > 0

    def lookup(self, reference):
        value = self.contract.functions.certificates(reference_hash(reference)).call()
        if value[1] == "0x0000000000000000000000000000000000000000":
            return None
        return {"file_hash": bytes(value[0]).hex(), "issuer": value[1], "registered_at": value[2], "revoked": value[3]}

    def approved(self, address):
        return self.contract.functions.approvedIssuers(Web3.to_checksum_address(address)).call()

    def send(self, function, address):
        address = Web3.to_checksum_address(address)
        if address not in self.keys:
            raise ValueError("No server-side signer is configured for this institution.")
        with TRANSACTION_LOCK:
            transaction = function.build_transaction({"from": address, "nonce": self.w3.eth.get_transaction_count(address, "pending"), "chainId": self.w3.eth.chain_id})
            signed = self.w3.eth.account.sign_transaction(transaction, self.keys[address])
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=45)
            if receipt.status != 1:
                raise ValueError("Blockchain transaction did not succeed.")
        return {"transaction_hash": tx_hash.hex(), "gas_used": receipt.gasUsed, "fee_wei": str(receipt.gasUsed * receipt.effectiveGasPrice), "block_number": receipt.blockNumber}

    def register(self, reference, file_hash, issuer):
        return self.send(self.contract.functions.register(reference_hash(reference), bytes.fromhex(file_hash)), issuer)

    def revoke(self, reference, actor):
        return self.send(self.contract.functions.revoke(reference_hash(reference)), actor)

    def set_issuer(self, address, approved):
        return self.send(self.contract.functions.setIssuer(Web3.to_checksum_address(address), approved), self.owner)
