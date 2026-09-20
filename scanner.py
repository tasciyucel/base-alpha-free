import requests

from config import BASE_RPC_URL
from database import (
    init_db,
    save_trade,
    update_wallet,
    get_last_scanned_block,
    save_last_scanned_block
)


USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

CHUNK_SIZE = 10
BATCH_SIZE = 20

BACKFILL_START = 51569194
BACKFILL_END = 51569821

TOKEN_CACHE = {}


# ============================================================
# RPC
# ============================================================

def rpc(method, params):

    response = requests.post(
        BASE_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        },
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise Exception(data["error"])

    return data["result"]


def rpc_batch(calls):

    all_results = []

    for start in range(0, len(calls), BATCH_SIZE):

        batch = calls[start:start + BATCH_SIZE]

        payload = []

        for i, (method, params) in enumerate(batch):

            payload.append({
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": i
            })

        response = requests.post(
            BASE_RPC_URL,
            json=payload,
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        result_map = {}

        for item in data:

            item_id = item.get("id")

            if "error" in item:
                result_map[item_id] = None
            else:
                result_map[item_id] = item.get("result")

        for i in range(len(batch)):

            all_results.append(
                result_map.get(i)
            )

    return all_results


# ============================================================
# BLOCK
# ============================================================

def get_latest_block():

    result = rpc(
        "eth_blockNumber",
        []
    )

    return int(result, 16)


def get_usdc_logs(start_block, end_block):

    return rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
            "address": USDC_ADDRESS
        }]
    )


def get_block_timestamps(block_numbers):

    unique_blocks = sorted(
        set(block_numbers)
    )

    calls = []

    for block_number in unique_blocks:

        calls.append((
            "eth_getBlockByNumber",
            [
                hex(block_number),
                False
            ]
        ))

    results = rpc_batch(calls)

    timestamps = {}

    for block_number, result in zip(
        unique_blocks,
        results
    ):

        if result and "timestamp" in result:

            timestamps[block_number] = int(
                result["timestamp"],
                16
            )

    return timestamps


# ============================================================
# TRANSACTION
# ============================================================

def get_transactions(tx_hashes):

    calls = []

    for tx_hash in tx_hashes:

        calls.append((
            "eth_getTransactionByHash",
            [tx_hash]
        ))

    results = rpc_batch(calls)

    transactions = {}

    for tx_hash, result in zip(
        tx_hashes,
        results
    ):

        if result:

            transactions[tx_hash] = result

    return transactions


def get_receipts(tx_hashes):

    calls = []

    for tx_hash in tx_hashes:

        calls.append((
            "eth_getTransactionReceipt",
            [tx_hash]
        ))

    results = rpc_batch(calls)

    receipts = {}

    for tx_hash, result in zip(
        tx_hashes,
        results
    ):

        if result:

            receipts[tx_hash] = result

    return receipts


# ============================================================
# ABI / TOKEN
# ============================================================

def decode_address(topic):

    return (
        "0x" +
        topic[-40:]
    ).lower()


def decode_amount(raw_amount, decimals):

    if decimals is None:
        return None

    try:

        return int(
            raw_amount,
            16
        ) / (10 ** decimals)

    except Exception:

        return None


def decode_abi_string(data):

    if not data or data == "0x":
        return ""

    try:

        raw = bytes.fromhex(
            data[2:]
        )

        # bytes32
        if len(raw) == 32:

            return raw.rstrip(
                b"\x00"
            ).decode(
                "utf-8",
                errors="ignore"
            )

        # dynamic string
        if len(raw) >= 64:

            offset = int.from_bytes(
                raw[0:32],
                "big"
            )

            if offset + 32 <= len(raw):

                length = int.from_bytes(
                    raw[offset:offset + 32],
                    "big"
                )

                start = offset + 32
                end = start + length

                if end <= len(raw):

                    return raw[start:end].decode(
                        "utf-8",
                        errors="ignore"
                    )

    except Exception:
        pass

    return ""


def get_token_metadata(token_address):

    token_address = token_address.lower()

    if token_address in TOKEN_CACHE:

        return TOKEN_CACHE[token_address]

    if token_address == USDC_ADDRESS:

        metadata = {
            "decimals": 6,
            "symbol": "USDC",
            "name": "USD Coin"
        }

        TOKEN_CACHE[token_address] = metadata

        return metadata

    calls = [

        (
            "eth_call",
            [{
                "to": token_address,
                "data": "0x313ce567"
            }, "latest"]
        ),

        (
            "eth_call",
            [{
                "to": token_address,
                "data": "0x95d89b41"
            }, "latest"]
        ),

        (
            "eth_call",
            [{
                "to": token_address,
                "data": "0x06fdde03"
            }, "latest"]
        )

    ]

    results = rpc_batch(calls)

    decimals = None

    if results[0]:

        try:

            decimals = int(
                results[0],
                16
            )

        except Exception:
            decimals = None

    symbol = decode_abi_string(
        results[1]
    )

    name = decode_abi_string(
        results[2]
    )

    metadata = {
        "decimals": decimals,
        "symbol": symbol,
        "name": name
    }

    TOKEN_CACHE[token_address] = metadata

    return metadata


def get_token_metadata_batch(token_addresses):

    addresses = sorted(
        set(
            address.lower()
            for address in token_addresses
            if address.lower() != USDC_ADDRESS
        )
    )

    new_addresses = [
        address
        for address in addresses
        if address not in TOKEN_CACHE
    ]

    if not new_addresses:
        return

    calls = []

    for address in new_addresses:

        calls.extend([

            (
                "eth_call",
                [{
                    "to": address,
                    "data": "0x313ce567"
                }, "latest"]
            ),

            (
                "eth_call",
                [{
                    "to": address,
                    "data": "0x95d89b41"
                }, "latest"]
            ),

            (
                "eth_call",
                [{
                    "to": address,
                    "data": "0x06fdde03"
                }, "latest"]
            )

        ])

    results = rpc_batch(calls)

    for i, address in enumerate(new_addresses):

        base = i * 3

        decimals = None

        if results[base]:

            try:

                decimals = int(
                    results[base],
                    16
                )

            except Exception:
                decimals = None

        symbol = decode_abi_string(
            results[base + 1]
        )

        name = decode_abi_string(
            results[base + 2]
        )

        TOKEN_CACHE[address] = {
            "decimals": decimals,
            "symbol": symbol,
            "name": name
        }


# ============================================================
# TRANSFER
# ============================================================

def parse_transfer_log(log):

    topics = log.get(
        "topics",
        []
    )

    if len(topics) < 3:
        return None

    if topics[0].lower() != TRANSFER_TOPIC:
        return None

    return {

        "token":
            log["address"].lower(),

        "from":
            decode_address(
                topics[1]
            ),

        "to":
            decode_address(
                topics[2]
            ),

        "raw_amount":
            log.get(
                "data",
                "0x0"
            ),

        "block_number":
            int(
                log["blockNumber"],
                16
            ),

        "tx_hash":
            log["transactionHash"],

        "log_index":
            int(
                log["logIndex"],
                16
            )
    }


# ============================================================
# TRANSACTION ANALYSIS
# ============================================================

def analyze_transaction(
    tx_hash,
    tx,
    receipt,
    block_timestamp
):

    if not tx:
        return False

    trader = tx.get(
        "from",
        ""
    ).lower()

    if not trader:
        return False

    if not receipt:
        return False

    transfers = []

    for log in receipt.get(
        "logs",
        []
    ):

        transfer = parse_transfer_log(
            log
        )

        if transfer:

            transfers.append(
                transfer
            )

    if not transfers:
        return False

    sent_usdc = []
    received_usdc = []

    sent_tokens = []
    received_tokens = []

    for transfer in transfers:

        if transfer["token"] == USDC_ADDRESS:

            if transfer["from"] == trader:

                sent_usdc.append(
                    transfer
                )

            if transfer["to"] == trader:

                received_usdc.append(
                    transfer
                )

        else:

            if transfer["from"] == trader:

                sent_tokens.append(
                    transfer
                )

            if transfer["to"] == trader:

                received_tokens.append(
                    transfer
                )

    # BUY
    if sent_usdc and received_tokens:

        side = "BUY"

        usdc_transfer = max(
            sent_usdc,
            key=lambda x: int(
                x["raw_amount"],
                16
            )
        )

        token_transfer = max(
            received_tokens,
            key=lambda x: int(
                x["raw_amount"],
                16
            )
        )

    # SELL
    elif received_usdc and sent_tokens:

        side = "SELL"

        usdc_transfer = max(
            received_usdc,
            key=lambda x: int(
                x["raw_amount"],
                16
            )
        )

        token_transfer = max(
            sent_tokens,
            key=lambda x: int(
                x["raw_amount"],
                16
            )
        )

    else:

        return False

    usd_value = decode_amount(
        usdc_transfer["raw_amount"],
        6
    )

    if usd_value is None:
        return False

    metadata = TOKEN_CACHE.get(
        token_transfer["token"]
    )

    if not metadata:

        metadata = get_token_metadata(
            token_transfer["token"]
        )

    token_amount = decode_amount(
        token_transfer["raw_amount"],
        metadata["decimals"]
    )

    if token_amount is None:
        return False

    trade = {

        "tx_hash":
            tx_hash,

        "block_number":
            token_transfer["block_number"],

        "timestamp":
            block_timestamp,

        "trader":
            trader,

        "token":
            token_transfer["token"],

        "symbol":
            metadata["symbol"],

        "side":
            side,

        "amount_usd":
            usd_value,

        "token_amount":
            token_amount
    }

    saved = save_trade(
        trade
    )

    if not saved:
        return False

    update_wallet(
        trade
    )

    print()
    print("====================================")
    print("YENİ SWAP BULUNDU")
    print("Trader:", trader)
    print("Side:", side)
    print("Token:", metadata["symbol"])
    print(
        "Token adresi:",
        token_transfer["token"]
    )
    print(
        "Token miktarı:",
        token_amount
    )
    print(
        "USD:",
        usd_value
    )
    print(
        "TX:",
        tx_hash
    )
    print("====================================")

    return True


# ============================================================
# PROCESS CHUNK
# ============================================================

def process_block_range(
    start_block,
    end_block
):

    print(
        "USDC logları aranıyor:",
        start_block,
        "->",
        end_block
    )

    logs = get_usdc_logs(
        start_block,
        end_block
    )

    print(
        "Toplam USDC log:",
        len(logs)
    )

    transfer_logs = []

    for log in logs:

        transfer = parse_transfer_log(
            log
        )

        if transfer:

            transfer_logs.append(
                transfer
            )

    print(
        "USDC Transfer log:",
        len(transfer_logs)
    )

    if not transfer_logs:

        return 0

    tx_hashes = sorted(
        set(
            transfer["tx_hash"]
            for transfer in transfer_logs
        )
    )

    print(
        "Aday transaction:",
        len(tx_hashes)
    )

    # --------------------------------------------------------
    # 1. Transaction'ları BATCH al
    # --------------------------------------------------------

    transactions = get_transactions(
        tx_hashes
    )

    print(
        "Transaction alındı:",
        len(transactions)
    )

    # --------------------------------------------------------
    # 2. Receipt'leri BATCH al
    # --------------------------------------------------------

    receipts = get_receipts(
        list(
            transactions.keys()
        )
    )

    print(
        "Receipt alındı:",
        len(receipts)
    )

    # --------------------------------------------------------
    # 3. Block timestamp'lerini BATCH al
    # --------------------------------------------------------

    block_numbers = []

    for tx in transactions.values():

        if tx and tx.get("blockNumber"):

            block_numbers.append(
                int(
                    tx["blockNumber"],
                    16
                )
            )

    timestamps = get_block_timestamps(
        block_numbers
    )

    # --------------------------------------------------------
    # 4. Önce hangi tokenlar var bul
    # --------------------------------------------------------

    token_addresses = set()

    for receipt in receipts.values():

        if not receipt:
            continue

        for log in receipt.get(
            "logs",
            []
        ):

            transfer = parse_transfer_log(
                log
            )

            if transfer and transfer["token"] != USDC_ADDRESS:

                token_addresses.add(
                    transfer["token"]
                )

    print(
        "Yeni token metadata:",
        len(token_addresses)
    )

    # --------------------------------------------------------
    # 5. Token metadata'larını BATCH al
    # --------------------------------------------------------

    get_token_metadata_batch(
        token_addresses
    )

    # --------------------------------------------------------
    # 6. Swap analizleri
    # --------------------------------------------------------

    analyzed = 0

    for tx_hash in tx_hashes:

        tx = transactions.get(
            tx_hash
        )

        receipt = receipts.get(
            tx_hash
        )

        if not tx or not receipt:
            continue

        block_number = int(
            tx["blockNumber"],
            16
        )

        timestamp = timestamps.get(
            block_number
        )

        if timestamp is None:
            continue

        try:

            if analyze_transaction(
                tx_hash,
                tx,
                receipt,
                timestamp
            ):

                analyzed += 1

        except Exception as error:

            print(
                "Transaction analiz hatası:",
                tx_hash,
                error
            )

    return analyzed


# ============================================================
# MAIN
# ============================================================

def main():

    init_db()

    latest = get_latest_block()

    print()
    print("====================================")
    print("BASE ALPHA SCANNER")
    print("Latest block:", latest)
    print("====================================")

    last_scanned = get_last_scanned_block()

    # --------------------------------------------------------
    # BACKFILL
    # --------------------------------------------------------

    if last_scanned is not None and last_scanned < BACKFILL_END:

        start_block = BACKFILL_START

        print(
            "BACKFILL aktif:",
            BACKFILL_START,
            "->",
            BACKFILL_END
        )

    elif last_scanned is not None:

        start_block = last_scanned + 1

    else:

        start_block = BACKFILL_START

    # --------------------------------------------------------
    # END BLOCK
    # --------------------------------------------------------

    if start_block <= BACKFILL_END:

        scan_end = min(
            BACKFILL_END,
            latest
        )

    else:

        scan_end = latest

    print(
        "Tarama başlangıcı:",
        start_block
    )

    print(
        "Tarama bitişi:",
        scan_end
    )

    if start_block > scan_end:

        print(
            "Taranacak blok yok."
        )

        return

    current = start_block

    total_analyzed = 0

    # --------------------------------------------------------
    # CHUNKS
    # --------------------------------------------------------

    while current <= scan_end:

        chunk_end = min(
            current + CHUNK_SIZE - 1,
            scan_end
        )

        print()
        print("------------------------------------")
        print(
            "Chunk:",
            current,
            "->",
            chunk_end
        )

        try:

            analyzed = process_block_range(
                current,
                chunk_end
            )

            total_analyzed += analyzed

            save_last_scanned_block(
                chunk_end
            )

            print(
                "Chunk tamamlandı."
            )

            print(
                "Bulunan swap:",
                analyzed
            )

            current = chunk_end + 1

        except Exception as error:

            print(
                "CHUNK HATASI:",
                error
            )

            break

    print()
    print("====================================")
    print(
        "Toplam analiz edilen swap:",
        total_analyzed
    )
    print("====================================")


if __name__ == "__main__":
    main()
