import json
import os
import threading
from pathlib import Path
from web3 import Web3
from eth_account import Account
from .core import reference_hash

ROOT = Path(__file__).resolve().parents[1]
TRANSACTION_LOCK = threading.Lock()

class UncertainTransactionError(Exception):
    def __init__(self, tx_hash: str | None, message: str):
        super().__init__(message)
        self.tx_hash = tx_hash
        self.message = message

class Registry:
    def __init__(self):
        demo = os.getenv("AUTHENTRA_DEMO", "0") == "1"
        if demo:
            chain_file = ROOT / ".local/chain.json"
            if not chain_file.exists():
                raise RuntimeError("Local demo blockchain configuration (.local/chain.json) is missing. Run scripts/setup_demo_chain.mjs first.")
            config = json.loads(chain_file.read_text())
            self.keys = {Web3.to_checksum_address(i["address"]): i["key"] for i in config["issuers"]}
            self.keys[Web3.to_checksum_address(config["ownerAddress"])] = config["ownerKey"]
            self.owner = Web3.to_checksum_address(config["ownerAddress"])
        else:
            missing = []
            if not os.getenv("RPC_URL"):
                missing.append("RPC_URL")
            if not os.getenv("CONTRACT_ADDRESS"):
                missing.append("CONTRACT_ADDRESS")
            if missing:
                raise RuntimeError(f"Missing blockchain configuration: {', '.join(missing)}. Configure these environment variables before registering certificates.")
            abi_file = ROOT / "contracts/abi.json"
            if not abi_file.exists():
                raise RuntimeError("Smart contract ABI (contracts/abi.json) is missing.")
            config = {"rpcUrl": os.environ["RPC_URL"], "contractAddress": os.environ["CONTRACT_ADDRESS"], "abi": json.loads(abi_file.read_text())}
            self.keys = {Web3.to_checksum_address(k): v for k, v in json.loads(os.getenv("ISSUER_PRIVATE_KEYS", "{}")).items()}
            owner_key = os.getenv("OWNER_PRIVATE_KEY")
            self.owner = Account.from_key(owner_key).address if owner_key else None
            if owner_key:
                self.keys[self.owner] = owner_key
        self.w3 = Web3(Web3.HTTPProvider(config["rpcUrl"], request_kwargs={"timeout": 10}))
        self.contract = self.w3.eth.contract(address=Web3.to_checksum_address(config["contractAddress"]), abi=config["abi"])

    def health(self):
        try:
            return self.w3.is_connected() and len(self.w3.eth.get_code(self.contract.address)) > 0
        except Exception:
            return False

    def lookup(self, reference):
        if not reference:
            return None
        value = self.contract.functions.certificates(reference_hash(reference)).call()
        if value[1] == "0x0000000000000000000000000000000000000000":
            return None
        return {"file_hash": bytes(value[0]).hex().lower(), "issuer": value[1], "registered_at": value[2], "revoked": value[3]}

    def lookup_by_hash(self, file_hash: str):
        if not file_hash:
            return None
        canonical = file_hash.lower().removeprefix("0x")
        if len(canonical) != 64:
            return None
        raw_hash = bytes.fromhex(canonical)
        if hasattr(self.contract.functions, "lookupByHash"):
            val = self.contract.functions.lookupByHash(raw_hash).call()
            if val[1] == "0x0000000000000000000000000000000000000000":
                return None
            ref_hash_hex = bytes(val[4]).hex().lower() if val[4] != b"\x00" * 32 else None
            return {
                "file_hash": bytes(val[0]).hex().lower(),
                "issuer": val[1],
                "registered_at": val[2],
                "revoked": val[3],
                "reference_hash": ref_hash_hex,
            }
        elif hasattr(self.contract.functions, "certificatesByHash"):
            val = self.contract.functions.certificatesByHash(raw_hash).call()
            if val[1] == "0x0000000000000000000000000000000000000000":
                return None
            ref_hash_hex = None
            if hasattr(self.contract.functions, "referenceByFileHash"):
                try:
                    raw_ref = self.contract.functions.referenceByFileHash(raw_hash).call()
                    if raw_ref != b"\x00" * 32:
                        ref_hash_hex = bytes(raw_ref).hex().lower()
                except Exception:
                    pass
            return {
                "file_hash": bytes(val[0]).hex().lower(),
                "issuer": val[1],
                "registered_at": val[2],
                "revoked": val[3],
                "reference_hash": ref_hash_hex,
            }
        return None

    def approved(self, address):
        return self.contract.functions.approvedIssuers(Web3.to_checksum_address(address)).call()

    def get_network_info(self):
        try:
            chain_id = self.w3.eth.chain_id
        except Exception:
            chain_id = 1337
        networks = {
            1: ("Ethereum Mainnet", "https://etherscan.io/tx/{tx_hash}"),
            11155111: ("Sepolia Testnet", "https://sepolia.etherscan.io/tx/{tx_hash}"),
            17000: ("Holesky Testnet", "https://holesky.etherscan.io/tx/{tx_hash}"),
            1337: ("Local development · chain 1337", None),
            31337: ("Local Hardhat/Ganache", None),
        }
        custom_explorer = os.getenv("EXPLORER_TX_URL")
        name, default_explorer = networks.get(chain_id, (f"Chain {chain_id}", None))
        explorer_template = custom_explorer or default_explorer
        return {
            "chain_id": chain_id,
            "network_name": name,
            "contract_address": self.contract.address,
            "explorer_template": explorer_template,
        }

    def get_explorer_url(self, tx_hash):
        if not tx_hash:
            return None
        info = self.get_network_info()
        template = info.get("explorer_template")
        if template and "{tx_hash}" in template:
            return template.format(tx_hash=tx_hash)
        return None

    def send(self, function, address):
        address = Web3.to_checksum_address(address)
        if address not in self.keys:
            raise ValueError(f"No server-side signer is configured for this institution ({address}).")
        with TRANSACTION_LOCK:
            transaction = function.build_transaction({"from": address, "nonce": self.w3.eth.get_transaction_count(address, "pending"), "chainId": self.w3.eth.chain_id})
            signed = self.w3.eth.account.sign_transaction(transaction, self.keys[address])
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            try:
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=45)
            except Exception as exc:
                if "timeout" in str(exc).lower() or "timeexhausted" in exc.__class__.__name__.lower():
                    raise UncertainTransactionError(tx_hash.hex(), f"Transaction {tx_hash.hex()} was broadcast but receipt confirmation timed out. Outcome is uncertain.") from exc
                raise
            if receipt.status != 1:
                raise ValueError("Blockchain transaction reverted.")
        return {"transaction_hash": tx_hash.hex(), "gas_used": receipt.gasUsed, "fee_wei": str(receipt.gasUsed * receipt.effectiveGasPrice), "block_number": receipt.blockNumber}

    def register(self, reference, file_hash, issuer):
        return self.send(self.contract.functions.register(reference_hash(reference), bytes.fromhex(file_hash)), issuer)

    def register_and_verify(self, reference, file_hash, issuer):
        """Execute on-chain registration and independently verify read-back before returning success."""
        issuer = Web3.to_checksum_address(issuer)
        canonical_hash = file_hash.lower().removeprefix("0x")

        # Idempotence: check if already registered on-chain
        existing = self.lookup(reference)
        if existing:
            if existing["file_hash"].lower() == canonical_hash and existing["issuer"].lower() == issuer.lower() and not existing["revoked"]:
                return {
                    "transaction_hash": None,
                    "gas_used": 0,
                    "fee_wei": "0",
                    "block_number": None,
                    "registered_at": existing["registered_at"],
                    "contract_address": self.contract.address,
                    "network": str(self.w3.eth.chain_id),
                    "on_chain_verified": True,
                    "idempotent": True,
                }
            raise ValueError("This certificate ID already exists on the blockchain with different parameters.")

        # Real transaction submission
        tx_result = self.register(reference, canonical_hash, issuer)

        # Independent on-chain read verification
        try:
            verified_record = self.lookup(reference)
            verified_hash_record = self.lookup_by_hash(canonical_hash)
        except Exception as exc:
            raise UncertainTransactionError(tx_result["transaction_hash"], f"Transaction {tx_result['transaction_hash']} confirmed, but read-back verification failed due to RPC error: {exc}") from exc

        if not verified_record or not verified_hash_record:
            raise RuntimeError("On-chain verification failed: record not found after transaction confirmation.")
        if verified_record["file_hash"].lower() != canonical_hash:
            raise RuntimeError(f"On-chain verification failed: on-chain hash {verified_record['file_hash']} does not match expected {canonical_hash}.")
        if verified_record["issuer"].lower() != issuer.lower():
            raise RuntimeError(f"On-chain verification failed: on-chain issuer {verified_record['issuer']} does not match expected {issuer}.")
        if verified_record["revoked"]:
            raise RuntimeError("On-chain verification failed: certificate record is marked as revoked.")

        return {
            "transaction_hash": tx_result["transaction_hash"],
            "gas_used": tx_result["gas_used"],
            "fee_wei": tx_result["fee_wei"],
            "block_number": tx_result["block_number"],
            "registered_at": verified_record["registered_at"],
            "contract_address": self.contract.address,
            "network": str(self.w3.eth.chain_id),
            "on_chain_verified": True,
            "idempotent": False,
        }

    def revoke(self, reference, actor):
        return self.send(self.contract.functions.revoke(reference_hash(reference)), actor)

    def set_issuer(self, address, approved):
        return self.send(self.contract.functions.setIssuer(Web3.to_checksum_address(address), approved), self.owner)
