import requests
import time

print("SCANNER BAŞLADI", flush=True)

from config import BASE_RPC_URL

from database import (
    init_db,
    save_trade,
    update_wallet,
    get_last_scanned_block,
    save_last_scanned_block,
    get_token_metadata,
    save_token_metadata
)


# ============================================================
# CONFIG
# ============================================================

USDC_ADDRESS = (
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
)

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

# Alchemy Free log range limiti nedeniyle 10 bırakıyoruz.
CHUNK_SIZE = 10

BACKFILL_START = 51569194
BACKFILL_END = 51569821

TOKEN_CACHE = {}


# ============================================================
# RPC
# ============================================================

def rpc(method, params, retries=5):

    for attempt in range(retries):

        try:

            response = requests.post(
                BASE_RPC_URL,
                json={
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": 1
                },
                timeout=60
            )

            if response.status_code == 429:

                wait = min(
                    2 ** attempt,
                    15
                )

                print(
                    "429 rate limit. Bekleniyor:",
                    wait,
                    "sn",
                    flush=True
                )

                time.sleep(wait)

                continue

            response.raise_for_status()

            data = response.json()

            if "error" in data:

                raise Exception(
                    data["error"]
                )

            return data["result"]

        except requests.RequestException as error:

            if attempt == retries - 1:
                raise

            wait = min(
                2 ** attempt,
                15
            )

            print(
                "RPC hatası. Bekleniyor:",
                wait,
                "sn",
                error,
                flush=True
            )

            time.sleep(wait)

    return None


# ============================================================
# BLOCK
# ============================================================

def get_latest_block():

    result = rpc(
        "eth_blockNumber",
        []
    )

    return int(
        result,
        16
    )


# ============================================================
# USDC LOGS
# ============================================================

def get_usdc_logs(
    start_block,
    end_block
):

    return rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
            "address": USDC_ADDRESS,
            "topics": [
                TRANSFER_TOPIC
            ]
        }]
    )


# ============================================================
# BLOCK RECEIPTS
# ============================================================

def get_block_receipts(block_number):

    return rpc(
        "eth_getBlockReceipts",
        [
            hex(block_number)
        ],
        retries=6
    )


def get_receipts_for_blocks(
    block_numbers,
    candidate_tx_hashes
):

    receipts = {}

    candidate_tx_hashes = set(
        candidate_tx_hashes
    )

    print(
        "Receipt blokları:",
        len(block_numbers),
        flush=True
    )

    for block_number in block_numbers:

        print(
            "Block receipt:",
            block_number,
            flush=True
        )

        block_receipts = get_block_receipts(
            block_number
        )

        if not block_receipts:
            continue

        for receipt in block_receipts:

            tx_hash = receipt.get(
                "transactionHash"
            )

            if (
                tx_hash
                and
                tx_hash in candidate_tx_hashes
            ):

                receipts[
                    tx_hash
                ] = receipt

    return receipts


# ============================================================
# TRANSACTIONS
# ============================================================

def get_transactions(tx_hashes):

    tx_hashes = list(tx_hashes)

    if not tx_hashes:
        return {}

    transactions = {}

    batch_size = 50

    for start in range(
        0,
        len(tx_hashes),
        batch_size
    ):

        batch_hashes = tx_hashes[
            start:start + batch_size
        ]

        print(
            "Transaction batch:",
            start + 1,
            "->",
            start + len(batch_hashes),
            flush=True
        )

        payload = []

        for i, tx_hash in enumerate(
            batch_hashes
        ):

            payload.append({
                "jsonrpc": "2.0",
                "method": "eth_getTransactionByHash",
                "params": [tx_hash],
                "id": i
            })

        for attempt in range(6):

            try:

                response = requests.post(
                    BASE_RPC_URL,
                    json=payload,
                    timeout=60
                )

                if response.status_code == 429:

                    wait = min(
                        2 ** attempt,
                        15
                    )

                    print(
                        "Transaction batch 429.",
                        "Bekleme:",
                        wait,
                        "sn",
                        flush=True
                    )

                    time.sleep(wait)

                    continue

                response.raise_for_status()

                results = response.json()

                break

            except requests.RequestException as error:

                if attempt == 5:
                    raise

                wait = min(
                    2 ** attempt,
                    15
                )

                print(
                    "Transaction RPC hatası:",
                    error,
                    "Bekleme:",
                    wait,
                    "sn",
                    flush=True
                )

                time.sleep(wait)

        else:

            raise Exception(
                "Transaction batch alınamadı."
            )

        for item in results:

            tx = item.get("result")

            if tx:

                transactions[
                    tx.get("hash")
                ] = tx

    return transactions


# ============================================================
# ABI HELPERS
# ============================================================

def decode_address(topic):

    if not topic:
        return ""

    return (
        "0x" +
        topic[-40:]
    ).lower()


def raw_amount_int(raw_amount):

    if (
        not raw_amount
        or
        raw_amount in ("0x", "0X")
    ):
        return 0

    try:

        return int(
            raw_amount,
            16
        )

    except (
        ValueError,
        TypeError
    ):

        return 0


def decode_amount(
    raw_amount,
    decimals
):

    if decimals is None:
        return None

    raw = raw_amount_int(
        raw_amount
    )

    return raw / (
        10 ** decimals
    )


def decode_abi_string(data):

    if (
        not data
        or
        data in ("0x", "0X")
    ):
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

            if (
                offset + 32
                <= len(raw)
            ):

                length = int.from_bytes(
                    raw[
                        offset:
                        offset + 32
                    ],
                    "big"
                )

                start = (
                    offset + 32
                )

                end = (
                    start + length
                )

                if end <= len(raw):

                    return raw[
                        start:end
                    ].decode(
                        "utf-8",
                        errors="ignore"
                    )

    except Exception:

        pass

    return ""


# ============================================================
# TRANSFER PARSER
# ============================================================

def parse_transfer_log(log):

    topics = log.get(
        "topics",
        []
    )

    if len(topics) < 3:
        return None

    if (
        topics[0].lower()
        != TRANSFER_TOPIC
    ):
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
                "0x"
            ),

        "block_number":
            int(
                log["blockNumber"],
                16
            ),

        "timestamp":
            int(
                log.get(
                    "blockTimestamp",
                    "0x0"
                ),
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
# FIND SWAP
# ============================================================

def find_swap(
    tx,
    receipt
):

    if not tx or not receipt:
        return None

    trader = tx.get(
        "from",
        ""
    ).lower()

    if not trader:
        return None

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
        return None

    sent_usdc = []
    received_usdc = []

    sent_tokens = []
    received_tokens = []

    for transfer in transfers:

        if (
            transfer["token"]
            == USDC_ADDRESS
        ):

            if (
                transfer["from"]
                == trader
            ):
                sent_usdc.append(
                    transfer
                )

            if (
                transfer["to"]
                == trader
            ):
                received_usdc.append(
                    transfer
                )

        else:

            if (
                transfer["from"]
                == trader
            ):
                sent_tokens.append(
                    transfer
                )

            if (
                transfer["to"]
                == trader
            ):
                received_tokens.append(
                    transfer
                )

    # BUY
    if (
        sent_usdc
        and
        received_tokens
    ):

        usdc_transfer = max(
            sent_usdc,
            key=lambda x:
                raw_amount_int(
                    x["raw_amount"]
                )
        )

        token_transfer = max(
            received_tokens,
            key=lambda x:
                raw_amount_int(
                    x["raw_amount"]
                )
        )

        return {
            "side": "BUY",
            "usdc_transfer": usdc_transfer,
            "token_transfer": token_transfer,
            "trader": trader
        }

    # SELL
    if (
        received_usdc
        and
        sent_tokens
    ):

        usdc_transfer = max(
            received_usdc,
            key=lambda x:
                raw_amount_int(
                    x["raw_amount"]
                )
        )

        token_transfer = max(
            sent_tokens,
            key=lambda x:
                raw_amount_int(
                    x["raw_amount"]
                )
        )

        return {
            "side": "SELL",
            "usdc_transfer": usdc_transfer,
            "token_transfer": token_transfer,
            "trader": trader
        }

    return None


# ============================================================
# TOKEN METADATA
# ============================================================

def get_token_metadata_rpc(
    address
):

    address = address.lower()

    # Önce RAM cache
    if address in TOKEN_CACHE:

        return TOKEN_CACHE[address]

    # Sonra SQLite
    cached = get_token_metadata(
        address
    )

    if cached is not None:

        TOKEN_CACHE[address] = cached

        return cached

    calls = [
        (
            "decimals",
            "0x313ce567"
        ),
        (
            "symbol",
            "0x95d89b41"
        ),
        (
            "name",
            "0x06fdde03"
        )
    ]

    values = {}

    for key, data in calls:

        result = None

        for attempt in range(5):

            try:

                response = requests.post(
                    BASE_RPC_URL,
                    json={
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [
                            {
                                "to": address,
                                "data": data
                            },
                            "latest"
                        ],
                        "id": 1
                    },
                    timeout=30
                )

                if response.status_code == 429:

                    wait = min(
                        2 ** attempt,
                        10
                    )

                    print(
                        "Metadata 429:",
                        address,
                        key,
                        "bekleme:",
                        wait,
                        flush=True
                    )

                    time.sleep(wait)

                    continue

                response.raise_for_status()

                payload = response.json()

                result = payload.get(
                    "result"
                )

                break

            except requests.RequestException:

                if attempt == 4:
                    break

                time.sleep(
                    min(
                        2 ** attempt,
                        10
                    )
                )

        values[key] = result

    decimals = None

    if (
        values.get("decimals")
        and
        values["decimals"]
        not in ("0x", "0X")
    ):

        try:

            decimals = int(
                values["decimals"],
                16
            )

        except (
            ValueError,
            TypeError
        ):

            decimals = None

    symbol = decode_abi_string(
        values.get("symbol")
    )

    name = decode_abi_string(
        values.get("name")
    )

    metadata = {
        "decimals": decimals,
        "symbol": symbol,
        "name": name
    }

    # Sadece decimals gerçekten
    # alınabildiyse kalıcı cache'e koy.
    if decimals is not None:

        save_token_metadata(
            address,
            symbol,
            name,
            decimals
        )

        TOKEN_CACHE[address] = metadata

    return metadata


# ============================================================
# ANALYZE
# ============================================================

def analyze_transaction(
    tx_hash,
    tx,
    receipt
):

    swap = find_swap(
        tx,
        receipt
    )

    if not swap:
        return False

    token_transfer = swap[
        "token_transfer"
    ]

    usdc_transfer = swap[
        "usdc_transfer"
    ]

    token_address = token_transfer[
        "token"
    ]

    metadata = get_token_metadata_rpc(
        token_address
    )

    if not metadata:
        return False

    if metadata["decimals"] is None:
        return False

    usd_value = decode_amount(
        usdc_transfer["raw_amount"],
        6
    )

    token_amount = decode_amount(
        token_transfer["raw_amount"],
        metadata["decimals"]
    )

    if usd_value is None:
        return False

    if token_amount is None:
        return False

    timestamp = (
        token_transfer.get(
            "timestamp"
        )
        or
        usdc_transfer.get(
            "timestamp"
        )
    )

    if not timestamp:
        return False

    symbol = (
        metadata["symbol"]
        or
        token_address[:10]
        + "..."
    )

    trade = {

        "tx_hash":
            tx_hash,

        "block_number":
            token_transfer[
                "block_number"
            ],

        "timestamp":
            timestamp,

        "trader":
            swap["trader"],

        "token":
            token_address,

        "symbol":
            symbol,

        "side":
            swap["side"],

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
    print(
        "====================================",
        flush=True
    )

    print(
        "YENİ SWAP BULUNDU",
        flush=True
    )

    print(
        "Trader:",
        swap["trader"],
        flush=True
    )

    print(
        "Side:",
        swap["side"],
        flush=True
    )

    print(
        "Token:",
        symbol,
        flush=True
    )

    print(
        "Token adresi:",
        token_address,
        flush=True
    )

    print(
        "Token miktarı:",
        token_amount,
        flush=True
    )

    print(
        "USD:",
        usd_value,
        flush=True
    )

    print(
        "TX:",
        tx_hash,
        flush=True
    )

    print(
        "====================================",
        flush=True
    )

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
        end_block,
        flush=True
    )

    logs = get_usdc_logs(
        start_block,
        end_block
    )

    print(
        "Toplam USDC log:",
        len(logs),
        flush=True
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
        len(transfer_logs),
        flush=True
    )

    if not transfer_logs:
        return 0

    tx_hashes = sorted(
        set(
            transfer["tx_hash"]
            for transfer
            in transfer_logs
        )
    )

    print(
        "Aday transaction:",
        len(tx_hashes),
        flush=True
    )

    transactions = get_transactions(
        tx_hashes
    )

    print(
        "Transaction alındı:",
        len(transactions),
        flush=True
    )

    if not transactions:
        return 0

    block_numbers = []

    for tx in transactions.values():

        if tx and tx.get(
            "blockNumber"
        ):

            block_numbers.append(
                int(
                    tx["blockNumber"],
                    16
                )
            )

    unique_blocks = sorted(
        set(block_numbers)
    )

    receipts = get_receipts_for_blocks(
        unique_blocks,
        transactions.keys()
    )

    print(
        "Receipt alındı:",
        len(receipts),
        flush=True
    )

    # --------------------------------------------------------
    # ÖNEMLİ:
    # Artık bütün receipt'lerdeki tokenlar için
    # metadata istemiyoruz.
    #
    # Önce gerçek swap adaylarını buluyoruz.
    # --------------------------------------------------------

    swap_candidates = []

    candidate_tokens = set()

    for tx_hash in tx_hashes:

        tx = transactions.get(
            tx_hash
        )

        receipt = receipts.get(
            tx_hash
        )

        if not tx or not receipt:
            continue

        swap = find_swap(
            tx,
            receipt
        )

        if not swap:
            continue

        swap_candidates.append(
            (
                tx_hash,
                tx,
                receipt
            )
        )

        candidate_tokens.add(
            swap["token_transfer"][
                "token"
            ]
        )

    print(
        "Gerçek swap adayı:",
        len(swap_candidates),
        flush=True
    )

    print(
        "Gerekli token metadata:",
        len(candidate_tokens),
        flush=True
    )

    analyzed = 0

    # --------------------------------------------------------
    # Sadece gerçek swap adaylarını analiz et.
    # Metadata sadece burada istenir.
    # --------------------------------------------------------

    for (
        tx_hash,
        tx,
        receipt
    ) in swap_candidates:

        try:

            if analyze_transaction(
                tx_hash,
                tx,
                receipt
            ):

                analyzed += 1

        except Exception as error:

            print(
                "Transaction analiz hatası:",
                tx_hash,
                error,
                flush=True
            )

    return analyzed


# ============================================================
# MAIN
# ============================================================

def main():

    init_db()

    latest = get_latest_block()

    print()
    print(
        "===================================="
    )

    print(
        "BASE ALPHA SCANNER"
    )

    print(
        "Latest block:",
        latest
    )

    print(
        "===================================="
    )

    last_scanned = get_last_scanned_block()

    # --------------------------------------------------------
    # BACKFILL
    # --------------------------------------------------------

    if (
        last_scanned is not None
        and
        last_scanned < BACKFILL_END
    ):

        start_block = BACKFILL_START

        print(
            "BACKFILL aktif:",
            BACKFILL_START,
            "->",
            BACKFILL_END
        )

    elif last_scanned is not None:

        start_block = (
            last_scanned + 1
        )

    else:

        start_block = BACKFILL_START

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

    while current <= scan_end:

        chunk_end = min(
            current + CHUNK_SIZE - 1,
            scan_end
        )

        print()
        print(
            "------------------------------------"
        )

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

            # ------------------------------------------------
            # Chunk gerçekten tamamlandıktan sonra state
            # kaydediliyor.
            # ------------------------------------------------

            save_last_scanned_block(
                chunk_end
            )

            print(
                "Chunk tamamlandı.",
                flush=True
            )

            print(
                "Bulunan swap:",
                analyzed,
                flush=True
            )

            current = (
                chunk_end + 1
            )

        except Exception as error:

            print(
                "CHUNK HATASI:",
                error,
                flush=True
            )

            break

    print()
    print(
        "===================================="
    )

    print(
        "Toplam analiz edilen swap:",
        total_analyzed
    )

    print(
        "===================================="
    )


if __name__ == "__main__":
    main()
