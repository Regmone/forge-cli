# forge-cli: Cross-Chain Bridge Event Listener

A comprehensive Python simulation of a crucial component in a cross-chain bridge system. This script acts as a relayer or oracle, listening for specific events on a source blockchain and simulating the corresponding action on a destination blockchain.

This project is designed to showcase a robust, modular, and well-documented architecture for building production-grade blockchain applications.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain (e.g., Ethereum) to another (e.g., Polygon). A common mechanism for this is **Lock-and-Mint**:

1.  A user **locks** their tokens (e.g., `USDC`) in a smart contract on the source chain.
2.  The smart contract emits an event, like `TokensLocked`, containing details of the transaction (sender, amount, destination chain).
3.  A network of off-chain listeners (or relayers) detects this event.
4.  After verifying the event, a relayer submits a transaction to a smart contract on the destination chain.
5.  The destination contract **mints** an equivalent amount of a wrapped token (e.g., `pUSDC`) and sends it to the user's address on that chain.

This `forge-cli` script simulates the role of the **off-chain listener (Step 3 & 4)**. It continuously polls a source EVM chain, detects `TokensLocked` events, and simulates the process of validating and submitting the corresponding `mint` transaction on the destination chain.

## Code Architecture

The script is built with a modular, object-oriented design to promote separation of concerns, testability, and maintainability.

-   `Config`:
A centralized class for managing all application settings. It loads configuration from a `.env` file, ensuring that sensitive data like RPC URLs and private keys are not hardcoded in the source code. It also performs validation to ensure all required parameters are present at startup.

-   `BlockchainConnector`:
A reusable utility class responsible for establishing and managing a connection to an EVM-compatible blockchain using the `web3.py` library. It abstracts away the details of the Web3 provider, making it easy to instantiate connections for both source and destination chains.

-   `BridgeEventScanner`:
The core engine of the listener. Its primary responsibility is to scan the source chain for new blocks. It uses filters to efficiently query the blockchain node for logs that match the bridge contract's address and the specific `TokensLocked` event signature. Upon finding logs, it parses the raw data into a structured, human-readable format.

-   `DestinationChainProcessor`:
This component simulates the final action of the relayer. It takes the parsed event data from the `BridgeEventScanner` and performs a series of simulated steps:
    1.  **External Validation**: It makes an API call using the `requests` library (in this case, to CoinGecko) to simulate an external dependency, such as a price oracle or a fraud-detection service.
    2.  **Transaction Simulation**: It logs a detailed breakdown of the transaction that *would* be created, signed, and sent to the destination chain to mint the wrapped tokens. This includes the target function and its parameters.

-   `main()`:
The main orchestrator function. It initializes all the above components, manages the application's state (like the last block number processed), and runs the main infinite loop that drives the scanning and processing cycle. It also includes robust error handling for network failures and other exceptions.

## How it Works

The listener operates in a continuous cycle:

1.  **Initialization**: The script starts by loading all necessary configurations (RPC endpoints, contract address, etc.) from a `.env` file.
2.  **Connection**: It establishes a connection to the source chain's RPC node using `web3.py`.
3.  **State Check**: It determines the starting block for the scan. Initially, this is the current chain head minus a safety margin for block confirmations. In subsequent runs, it starts from the last block it successfully processed.
4.  **Polling Loop**: The script enters an infinite loop, pausing for a configurable interval (e.g., 15 seconds) between each cycle.
5.  **Block Range Scan**: In each cycle, it calculates the range of blocks to scan, from the last processed block up to the latest confirmed block on the chain (`latest_block - confirmations`).
6.  **Event Filtering**: It queries the source node for event logs within that block range that originate from the specified bridge contract address and match the `TokensLocked` event topic.
7.  **Event Parsing**: If any logs are found, they are decoded from their raw hexadecimal format into a structured Python dictionary containing fields like `sender`, `amount`, and `destinationChainId`.
8.  **Processing**: Each parsed event is passed to the `DestinationChainProcessor`.
9.  **Simulation & Validation**: The processor simulates the final step. It logs the details of the minting transaction it would send to the destination chain and performs a dummy API call to demonstrate handling external dependencies.
10. **State Update**: After successfully scanning a range of blocks, the script updates its internal state to save the last block number, ensuring no events are missed or re-processed in the next cycle.

## Usage Example

Follow these steps to run the event listener simulation.

### 1. Prerequisites

-   Python 3.8+
-   An RPC endpoint URL for an EVM-compatible source chain (e.g., from Infura, Alchemy, or your own node).
-   An RPC endpoint for a destination chain.
-   A dummy private key (for simulation purposes).

### 2. Setup

```bash
# Clone the repository
_git clone <your-repo-url>/forge-cli.git_
cd forge-cli

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

# Install the required dependencies
pip install -r requirements.txt
```

### 3. Configuration

Create a file named `.env` in the root of the project and populate it with your configuration. You can copy the example below.

**.env.example**
```
# RPC endpoint for the source chain (e.g., Ethereum Sepolia)
SOURCE_CHAIN_RPC="https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"

# RPC endpoint for the destination chain (e.g., Polygon Amoy)
DESTINATION_CHAIN_RPC="https://polygon-amoy.infura.io/v3/YOUR_INFURA_PROJECT_ID"

# Address of the bridge contract on the source chain to monitor
BRIDGE_CONTRACT_ADDRESS="0x1234567890123456789012345678901234567890"

# Private key of the relayer account on the destination chain (for simulation)
# IMPORTANT: Use a key from a test/throwaway account. DO NOT USE A REAL KEY WITH FUNDS.
PRIVATE_KEY="0xabcdef123456..."

# Time in seconds between each poll for new blocks
POLL_INTERVAL_SECONDS=15

# Number of block confirmations to wait before processing an event
CONFIRMATIONS_REQUIRED=6
```

### 4. Run the Script

Execute the script from your terminal:

```bash
python script.py
```

### 5. Expected Output

The script will start logging its activities to the console. When it finds and processes an event, the output will look similar to this:

```
2023-10-27 14:30:00 - INFO - [main] - --- Starting Forge-CLI Cross-Chain Bridge Listener ---
2023-10-27 14:30:01 - INFO - [BlockchainConnector] - Successfully connected to node at https://sepolia.infura.io/v3/.... Chain ID: 11155111
2023-10-27 14:30:02 - INFO - [BlockchainConnector] - Successfully connected to node at https://polygon-amoy.infura.io/v3/.... Chain ID: 80002
2023-10-27 14:30:02 - INFO - [BridgeEventScanner] - Listening for event with topic: 0xabcdef...
2023-10-27 14:30:02 - INFO - [main] - Starting scan from block 4950100
...
2023-10-27 14:30:17 - INFO - [BridgeEventScanner] - Scanning blocks from 4950101 to 4950110...
2023-10-27 14:30:18 - INFO - [BridgeEventScanner] - Found 1 potential event(s) in block range.
2023-10-27 14:30:18 - INFO - [BridgeEventScanner] - Successfully parsed TokensLocked event in tx 0x1a2b3c...
2023-10-27 14:30:18 - INFO - [main] - Found 1 new events to process.
2023-10-27 14:30:18 - INFO - [DestinationChainProcessor] - Processing event with nonce 1234 for user 0xSenderAddress...
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] - [External Check] Current ETH price is $1580.45. Validation passed.
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] - [SIMULATION] Preparing to mint 1000000000000000000 wrapped tokens for 0xSenderAddress...
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] - [SIMULATION] Transaction for nonce 1234 successfully created and signed.
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] - -- Details --
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] -   To: Destination Bridge Contract
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] -   Function: mint(to: 0xSenderAddress, amount: 1000000000000000000) 
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] -   Source Tx: 0x1a2b3c...
2023-10-27 14:30:19 - INFO - [DestinationChainProcessor] - --------------
2023-10-27 14:30:19 - INFO - [main] - Scan complete. Last processed block is now 4950110.
```
