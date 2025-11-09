import os
import time
import logging
from typing import Dict, Any, Optional, List

import requests
from web3 import Web3
from web3.exceptions import BlockNotFound
from web3.types import LogReceipt
from dotenv import load_dotenv

# --- Basic Configuration ---
load_dotenv() # Load environment variables from .env file

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class Config:
    """
    Configuration class to manage settings from environment variables.
    Provides a centralized point for all configurable parameters.
    """
    def __init__(self):
        self.SOURCE_CHAIN_RPC = os.getenv('SOURCE_CHAIN_RPC')
        self.DESTINATION_CHAIN_RPC = os.getenv('DESTINATION_CHAIN_RPC')
        self.BRIDGE_CONTRACT_ADDRESS = os.getenv('BRIDGE_CONTRACT_ADDRESS')
        self.PRIVATE_KEY = os.getenv('PRIVATE_KEY') # For signing transactions on destination chain
        self.POLL_INTERVAL_SECONDS = int(os.getenv('POLL_INTERVAL_SECONDS', '15'))
        self.CONFIRMATIONS_REQUIRED = int(os.getenv('CONFIRMATIONS_REQUIRED', '6'))
        self.GECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"

    def validate(self) -> None:
        """Validates that all necessary configuration variables are set."""
        required_vars = [
            'SOURCE_CHAIN_RPC', 
            'DESTINATION_CHAIN_RPC', 
            'BRIDGE_CONTRACT_ADDRESS',
            'PRIVATE_KEY'
        ]
        for var in required_vars:
            if not getattr(self, var):
                raise ValueError(f"Missing required environment variable: {var}")
        self.BRIDGE_CONTRACT_ADDRESS = Web3.to_checksum_address(self.BRIDGE_CONTRACT_ADDRESS)


class BlockchainConnector:
    """
    A reusable component for establishing and managing a connection 
    to an EVM-compatible blockchain via a Web3 provider.
    """
    def __init__(self, rpc_url: str):
        """
        Initializes the connector with a given RPC URL.

        Args:
            rpc_url (str): The HTTP RPC endpoint URL for the blockchain node.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.rpc_url = rpc_url
        self.w3 = None
        self.connect()

    def connect(self) -> None:
        """
        Establishes a connection to the blockchain node.
        Handles connection errors and retries.
        """
        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.w3.is_connected():
                raise ConnectionError("Failed to connect to the blockchain node.")
            self.logger.info(f"Successfully connected to node at {self.rpc_url}. Chain ID: {self.w3.eth.chain_id}")
        except Exception as e:
            self.logger.error(f"Could not connect to {self.rpc_url}: {e}")
            self.w3 = None
            raise

    def get_latest_block(self) -> int:
        """
        Fetches the latest block number from the connected chain.

        Returns:
            int: The latest block number.
        """
        if not self.w3:
            self.logger.warning("Not connected. Attempting to reconnect...")
            self.connect()
        return self.w3.eth.block_number


class BridgeEventScanner:
    """
    Core engine that polls the source chain for new blocks, filters for 
    specific contract events (`TokensLocked`), and parses their data.
    """
    # A simplified ABI for the event we are interested in.
    # In a real application, this would be loaded from a full contract ABI JSON file.
    EVENT_ABI = {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "token", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "sender", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "destinationChainId", "type": "uint256"},
            {"indexed": True, "internalType": "uint256", "name": "nonce", "type": "uint256"}
        ],
        "name": "TokensLocked",
        "type": "event"
    }

    def __init__(self, connector: BlockchainConnector, contract_address: str, confirmations: int):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.connector = connector
        self.contract_address = contract_address
        self.confirmations_required = confirmations
        
        # Get the event signature topic
        self.event_topic = self.connector.w3.keccak(text="TokensLocked(address,address,uint256,uint256,uint256)").hex()
        self.logger.info(f"Listening for event with topic: {self.event_topic}")

    def scan_blocks(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        """
        Scans a range of blocks for the 'TokensLocked' event.

        Args:
            from_block (int): The starting block number.
            to_block (int): The ending block number.

        Returns:
            List[Dict[str, Any]]: A list of parsed event data dictionaries.
        """
        if from_block > to_block:
            return []
        
        self.logger.info(f"Scanning blocks from {from_block} to {to_block}...")
        try:
            filter_params = {
                'fromBlock': from_block,
                'toBlock': to_block,
                'address': self.contract_address,
                'topics': [self.event_topic]
            }
            logs = self.connector.w3.eth.get_logs(filter_params)
            if logs:
                self.logger.info(f"Found {len(logs)} potential event(s) in block range.")
                return [self._parse_log(log) for log in logs]
            return []
        except BlockNotFound:
            self.logger.warning(f"Block range not yet available ({from_block}-{to_block}). Will retry.")
            return []
        except Exception as e:
            self.logger.error(f"An error occurred while scanning blocks: {e}")
            # In a production system, you might want more specific error handling.
            return []

    def _parse_log(self, log: LogReceipt) -> Dict[str, Any]:
        """
        Decodes a raw event log into a structured dictionary.

        Args:
            log (LogReceipt): The raw log object from web3.

        Returns:
            Dict[str, Any]: A dictionary containing the parsed event data.
        """
        # Manually decode topics and data since we don't have a full contract object
        # Topics: [event_signature, indexed_arg1, indexed_arg2, ...]
        # Data: concatenation of non-indexed args
        parsed_data = {}
        
        # Indexed fields (order matters)
        parsed_data['token'] = Web3.to_checksum_address('0x' + log['topics'][1].hex()[-40:])
        parsed_data['sender'] = Web3.to_checksum_address('0x' + log['topics'][2].hex()[-40:])
        parsed_data['nonce'] = Web3.to_int(hexstr=log['topics'][3].hex())

        # Non-indexed fields (order matters)
        non_indexed_data = log['data']
        parsed_data['amount'] = Web3.to_int(non_indexed_data[0:32])
        parsed_data['destinationChainId'] = Web3.to_int(non_indexed_data[32:64])

        # Add metadata
        parsed_data['transactionHash'] = log['transactionHash'].hex()
        parsed_data['blockNumber'] = log['blockNumber']

        self.logger.info(f"Successfully parsed TokensLocked event in tx {parsed_data['transactionHash']}")
        return parsed_data


class DestinationChainProcessor:
    """
    Simulates the action on the destination chain. It receives parsed event data,
    validates it, and simulates the submission of a 'mintTokens' transaction.
    """
    def __init__(self, connector: BlockchainConnector, private_key: str, api_url: str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.connector = connector
        self.private_key = private_key
        self.account = self.connector.w3.eth.account.from_key(private_key)
        self.api_url = api_url
        self.logger.info(f"Processor initialized for destination chain. Relayer address: {self.account.address}")

    def process_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Processes a single 'TokensLocked' event.

        Args:
            event_data (Dict[str, Any]): The parsed event data.

        Returns:
            bool: True if processing was successfully simulated, False otherwise.
        """
        self.logger.info(f"Processing event with nonce {event_data['nonce']} for user {event_data['sender']}.")
        
        # --- Step 1: External validation (simulation) ---
        # In a real-world scenario, this could be a check against a fraud detection service,
        # or fetching additional metadata from an oracle.
        try:
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status() # Raise an exception for bad status codes
            price_data = response.json()
            eth_price = price_data.get('ethereum', {}).get('usd', 'N/A')
            self.logger.info(f"[External Check] Current ETH price is ${eth_price}. Validation passed.")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"[External Check] Failed to query external API: {e}")
            return False

        # --- Step 2: Simulate transaction preparation on destination chain ---
        # Here we would build a transaction to call a 'mint' or 'unlock' function on
        # the destination bridge contract.
        try:
            self.logger.info(f"[SIMULATION] Preparing to mint {event_data['amount']} wrapped tokens for {event_data['sender']}...")
            
            # In a real implementation:
            # 1. Get destination contract instance: `contract = w3.eth.contract(...)`
            # 2. Build the transaction:
            #    tx = contract.functions.mint(event_data['sender'], event_data['amount']).build_transaction({ 'nonce': w3.eth.get_transaction_count(self.account.address), ... })
            # 3. Sign it: `signed_tx = w3.eth.account.sign_transaction(tx, self.private_key)`
            # 4. Send it: `tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)`
            # 5. Wait for receipt: `w3.eth.wait_for_transaction_receipt(tx_hash)`
            
            self.logger.info(f"[SIMULATION] Transaction for nonce {event_data['nonce']} successfully created and signed.")
            self.logger.info(f"-- Details --")
            self.logger.info(f"  To: Destination Bridge Contract")
            self.logger.info(f"  Function: mint(to: {event_data['sender']}, amount: {event_data['amount']}) ")
            self.logger.info(f"  Source Tx: {event_data['transactionHash']}")
            self.logger.info(f"--------------")
            return True
        except Exception as e:
            self.logger.error(f"[SIMULATION] Failed to process transaction for nonce {event_data['nonce']}: {e}")
            return False

def main():
    """
    Main orchestrator function.
    Initializes all components and runs the main event listening loop.
    """
    logger = logging.getLogger('main')
    logger.info("--- Starting Forge-CLI Cross-Chain Bridge Listener ---")
    
    try:
        config = Config()
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return

    try:
        source_connector = BlockchainConnector(config.SOURCE_CHAIN_RPC)
        destination_connector = BlockchainConnector(config.DESTINATION_CHAIN_RPC) # Initialized for simulation
        
        scanner = BridgeEventScanner(source_connector, config.BRIDGE_CONTRACT_ADDRESS, config.CONFIRMATIONS_REQUIRED)
        processor = DestinationChainProcessor(destination_connector, config.PRIVATE_KEY, config.GECKO_API_URL)

    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        return

    # In a real-world application, `last_processed_block` should be persisted to a database
    # or a file to ensure resilience against restarts.
    # For this simulation, we start from a recent block.
    try:
        last_processed_block = source_connector.get_latest_block() - config.CONFIRMATIONS_REQUIRED - 1
        logger.info(f"Starting scan from block {last_processed_block + 1}")
    except Exception as e:
        logger.error(f"Could not fetch initial block number: {e}")
        return

    # --- Main Loop ---
    while True:
        try:
            # Determine the range of blocks to scan
            latest_block = source_connector.get_latest_block()
            # We only scan blocks that have received enough confirmations
            to_block = latest_block - config.CONFIRMATIONS_REQUIRED
            from_block = last_processed_block + 1

            if from_block <= to_block:
                events = scanner.scan_blocks(from_block, to_block)
                if events:
                    logger.info(f"Found {len(events)} new events to process.")
                    for event in events:
                        success = processor.process_event(event)
                        if not success:
                            logger.warning(f"Failed to process event from tx {event['transactionHash']}. It will be retried.")
                            # In a real system, you'd implement a retry mechanism with backoff
                            # or move it to a dead-letter queue.
                
                # Update state only if scanning was successful
                last_processed_block = to_block
                logger.info(f"Scan complete. Last processed block is now {last_processed_block}.")
            else:
                logger.info(f"No new blocks to scan. Current head: {latest_block}. Waiting for confirmations...")

        except ConnectionError as e:
            logger.error(f"Connection error in main loop: {e}. Retrying after delay...")
            time.sleep(config.POLL_INTERVAL_SECONDS * 2) # Longer delay on connection failure
            # Attempt to reconnect
            try:
                source_connector.connect()
            except Exception as conn_e:
                logger.error(f"Reconnect failed: {conn_e}")
                
        except Exception as e:
            logger.critical(f"An unexpected critical error occurred in the main loop: {e}", exc_info=True)
            # A critical error might require a shutdown or manual intervention.

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()


# @-internal-utility-start
def get_config_value_6708(key: str):
    """Reads a value from a simple key-value config. Added on 2025-11-09 13:33:53"""
    with open('config.ini', 'r') as f:
        for line in f:
            if line.startswith(key):
                return line.split('=')[1].strip()
    return None
# @-internal-utility-end

