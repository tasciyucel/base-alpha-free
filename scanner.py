import requests
import time

from config import BASE_RPC_URL

from database import (
    init_db,
    save_trade,
    update_wallet,
    get_token_metadata,
    save_token_metadata,
    get_last_scanned_block,
    save_last_scanned_block
)


USDC_ADDRESS = (
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
)

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f"
    "163c4a11628f55a4df523b3ef"
)

CHUNK_SIZE = 10

# İlk kez tarama yapılacak başlangıç bloğu.
BACKFILL_START = 51569194

TOKEN_CACHE = {}


def rpc(method, params, retries=6):

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
                    f"429 rate limit... "
                    f"{method} "
                    f"bekleme: {wait}",
                    flush=True
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            payload = response.json()

            if "error" in payload:
                raise RuntimeError(
                    payload["error"]
                )

            return payload.get("result")

        except requests.RequestException as error:

            if attempt == retries - 1:
                raise

            wait = min(
                2 ** attempt,
                15
            )

            print(
                f"RPC hata: {method} "
                f"bekleme: {wait} "
                f"hata: {error}",
                flush=True
            )

            time.sleep(wait)

    return None


def get_latest_block():

    result = rpc(
        "eth_blockNumber",
        []
    )

    return int(
        result,
        16
    )


def get_usdc_logs(
    start_block,
    end_block
):

    print(
        "USDC logları aranıyor...",
        flush=True
    )

    result = rpc(
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

    return result or []


def get_block_receipts(block_number):

    print(
        f"Block receipt: {block_number}",
        flush=True
    )

    return rpc(
        "eth_getBlockReceipts",
        [hex(block_number)]
    ) or []


def get_receipts_for_blocks(
    block_numbers
):

    receipts = {}

    for block_number in sorted(
        block_numbers
    ):

        block_receipts = (
            get_block_receipts(
                block_number
            )
        )

        for receipt in block_receipts:

            tx_hash = receipt.get(
                "transactionHash"
            )

            if tx_hash:

                receipts[
                    tx_hash.lower()
                ] = receipt

    return receipts


def get_transactions(tx_hashes):

    transactions = {}

    batch_size = 50

    for i in range(
        0,
        len(tx_hashes),
        batch_size
    ):

        batch = tx_hashes[
            i:i + batch_size
        ]

        print(
            f"Transaction batch: "
            f"{i + 1} -> "
            f"{i + len(batch)}",
            flush=True
        )

        for tx_hash in batch:

            result = rpc(
                "eth_getTransactionByHash",
                [tx_hash]
            )

            if result:

                transactions[
                    tx_hash.lower()
                ] = result

        time.sleep(0.2)

    print(
        f"Transaction alındı: "
        f"{len(transactions)}",
        flush=True
    )

    return transactions


def raw_amount_int(value):

    if not value:
        return 0

    if value in (
        "0x",
        "0X"
    ):
        return 0

    try:

        return int(
            value,
            16
        )

    except (
        ValueError,
        TypeError
    ):

        return 0


def decode_amount(
    value,
    decimals
):

    raw = raw_amount_int(
        value
    )

    if raw == 0:
        return 0

    return raw / (
        10 ** decimals
    )


def get_token_metadata_rpc(address):

    address = address.lower()

    if address in TOKEN_CACHE:

        return TOKEN_CACHE[
            address
        ]

    cached = get_token_metadata(
        address
    )

    if cached is not None:

        TOKEN_CACHE[
            address
        ] = cached

        return cached

    decimals = None

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
                            "data": "0x313ce567"
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
                    "Decimals 429:",
                    address,
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

            if result and result not in (
                "0x",
                "0X"
            ):

                try:

                    decimals = int(
                        result,
                        16
                    )

                except (
                    ValueError,
                    TypeError
                ):

                    decimals = None

            break

        except requests.RequestException as error:

            if attempt == 4:

                print(
                    "Decimals alınamadı:",
                    address,
                    error,
                    flush=True
                )

                break

            wait = min(
                2 ** attempt,
                10
            )

            time.sleep(wait)

    if decimals is None:
        return None

    metadata = {
        "decimals": decimals,
        "symbol": "",
        "name": ""
    }

    save_token_metadata(
        address,
        "",
        "",
        decimals
    )

    TOKEN_CACHE[
        address
    ] = metadata

    return metadata


def parse_transfer_log(log):

    topics = log.get(
        "topics",
        []
    )

    if len(topics) < 3:
        return None

    try:

        from_address = (
            "0x"
            + topics[1][-40:]
        ).lower()

        to_address = (
            "0x"
            + topics[2][-40:]
        ).lower()

        amount = raw_amount_int(
            log.get("data")
        )

        return {
            "token": log.get(
                "address",
                ""
            ).lower(),

            "from": from_address,

            "to": to_address,

            "amount_raw": amount,

            "tx_hash": log.get(
                "transactionHash",
                ""
            ).lower(),

            "block_number": int(
                log.get(
                    "blockNumber",
                    "0x0"
                ),
                16
            ),

            "timestamp": int(
                log.get(
                    "blockTimestamp",
                    "0x0"
                ),
                16
            )
        }

    except Exception:

        return None


def find_swap(
    tx,
    receipt
):

    if not tx or not receipt:
        return None

    tx_hash = tx.get(
        "hash",
        ""
    ).lower()

    trader = tx.get(
        "from",
        ""
    ).lower()

    if not trader:
        return None

    usdc_sent = 0
    usdc_received = 0

    token_sent = {}
    token_received = {}

    block_timestamp = 0

    logs = receipt.get(
        "logs",
        []
    )

    for log in logs:

        parsed = parse_transfer_log(
            log
        )

        if not parsed:
            continue

        if (
            parsed["tx_hash"]
            and parsed["tx_hash"] != tx_hash
        ):
            continue

        token = parsed["token"]

        if parsed["timestamp"]:

            block_timestamp = max(
                block_timestamp,
                parsed["timestamp"]
            )

        if parsed["from"] == trader:

            if token == USDC_ADDRESS:

                usdc_sent += (
                    parsed["amount_raw"]
                )

            else:

                token_sent[token] = (
                    token_sent.get(
                        token,
                        0
                    )
                    + parsed["amount_raw"]
                )

        if parsed["to"] == trader:

            if token == USDC_ADDRESS:

                usdc_received += (
                    parsed["amount_raw"]
                )

            else:

                token_received[token] = (
                    token_received.get(
                        token,
                        0
                    )
                    + parsed["amount_raw"]
                )

    # BUY
    if (
        usdc_sent > 0
        and token_received
    ):

        token = max(
            token_received,
            key=token_received.get
        )

        return {
            "side": "BUY",
            "token": token,
            "usdc_raw": usdc_sent,
            "token_raw": token_received[token],
            "timestamp": block_timestamp
        }

    # SELL
    if (
        usdc_received > 0
        and token_sent
    ):

        token = max(
            token_sent,
            key=token_sent.get
        )

        return {
            "side": "SELL",
            "token": token,
            "usdc_raw": usdc_received,
            "token_raw": token_sent[token],
            "timestamp": block_timestamp
        }

    return None


def analyze_transaction(
    tx,
    receipt
):

    swap = find_swap(
        tx,
        receipt
    )

    if not swap:
        return False

    token_address = swap[
        "token"
    ]

    metadata = get_token_metadata_rpc(
        token_address
    )

    if metadata is None:
        return False

    decimals = metadata.get(
        "decimals",
        18
    )

    usdc_amount = (
        swap["usdc_raw"]
        / 1_000_000
    )

    token_amount = (
        swap["token_raw"]
        / (10 ** decimals)
    )

    symbol = metadata.get(
        "symbol",
        ""
    )

    if not symbol:

        symbol = (
            token_address[:10]
            + "..."
        )

    timestamp = swap[
        "timestamp"
    ]

    if timestamp == 0:

        timestamp = int(
            time.time()
        )

    trade = {

        "tx_hash": tx.get(
            "hash",
            ""
        ).lower(),

        "block_number": int(
            tx.get(
                "blockNumber",
                "0x0"
            ),
            16
        ),

        "timestamp": timestamp,

        "trader": tx.get(
            "from",
            ""
        ).lower(),

        "token": token_address,

        "symbol": symbol,

        "side": swap["side"],

        "amount_usd": usdc_amount,

        "token_amount": token_amount
    }

    saved = save_trade(
        trade
    )

    if saved:

        update_wallet(
            trade
        )

        print(
            f"{trade['side']} "
            f"{trade['symbol']} "
            f"${trade['amount_usd']:.6f} "
            f"wallet={trade['trader']}",
            flush=True
        )

    return saved


def process_block_range(
    start_block,
    end_block
):

    print()
    print(
        f"Chunk: "
        f"{start_block} -> "
        f"{end_block}",
        flush=True
    )

    logs = get_usdc_logs(
        start_block,
        end_block
    )

    print(
        f"Toplam USDC log: "
        f"{len(logs)}",
        flush=True
    )

    transfer_logs = []

    for log in logs:

        if len(
            log.get(
                "topics",
                []
            )
        ) >= 3:

            transfer_logs.append(
                log
            )

    print(
        f"USDC Transfer log: "
        f"{len(transfer_logs)}",
        flush=True
    )

    tx_hashes = sorted(
        set(
            log.get(
                "transactionHash",
                ""
            ).lower()
            for log in transfer_logs
            if log.get(
                "transactionHash"
            )
        )
    )

    print(
        f"Aday transaction: "
        f"{len(tx_hashes)}",
        flush=True
    )

    if not tx_hashes:
        return

    transactions = get_transactions(
        tx_hashes
    )

    block_numbers = sorted(
        set(
            int(
                tx.get(
                    "blockNumber",
                    "0x0"
                ),
                16
            )
            for tx in transactions.values()
            if tx.get("blockNumber")
        )
    )

    print(
        f"Receipt blokları: "
        f"{len(block_numbers)}",
        flush=True
    )

    receipts = get_receipts_for_blocks(
        block_numbers
    )

    print(
        f"Receipt alındı: "
        f"{len(receipts)}",
        flush=True
    )

    real_candidates = []

    for tx_hash, tx in transactions.items():

        receipt = receipts.get(
            tx_hash
        )

        if not receipt:
            continue

        swap = find_swap(
            tx,
            receipt
        )

        if swap:

            real_candidates.append(
                (
                    tx,
                    receipt
                )
            )

    print(
        f"Gerçek swap adayı: "
        f"{len(real_candidates)}",
        flush=True
    )

    token_addresses = set()

    for tx, receipt in real_candidates:

        swap = find_swap(
            tx,
            receipt
        )

        if swap:

            token_addresses.add(
                swap["token"]
            )

    print(
        f"Gerekli token metadata: "
        f"{len(token_addresses)}",
        flush=True
    )

    for tx, receipt in real_candidates:

        try:

            analyze_transaction(
                tx,
                receipt
            )

        except Exception as error:

            print(
                "Transaction analiz hatası:",
                tx.get(
                    "hash",
                    ""
                ),
                error,
                flush=True
            )


def main():

    init_db()

    print()
    print(
        "BASE ALPHA SCANNER",
        flush=True
    )

    latest_block = get_latest_block()

    print(
        f"Latest block: "
        f"{latest_block}",
        flush=True
    )

    last_scanned = (
        get_last_scanned_block()
    )

    if last_scanned is None:

        start_block = (
            BACKFILL_START
        )

    else:

        start_block = (
            last_scanned + 1
        )

    # Artık sabit BACKFILL_END yok.
    # Her çalışmada güncel latest block'a kadar gider.
    end_block = latest_block

    print(
        f"Tarama başlangıcı: "
        f"{start_block}",
        flush=True
    )

    print(
        f"Tarama bitişi: "
        f"{end_block}",
        flush=True
    )

    if start_block > end_block:

        print(
            "Taranacak yeni blok yok.",
            flush=True
        )

        return

    current = start_block

    while current <= end_block:

        chunk_end = min(
            current + CHUNK_SIZE - 1,
            end_block
        )

        try:

            process_block_range(
                current,
                chunk_end
            )

            # Chunk tamamen başarılı olduktan sonra
            # ilerleme kaydediliyor.
            save_last_scanned_block(
                chunk_end
            )

            print(
                f"Chunk tamamlandı: "
                f"{chunk_end}",
                flush=True
            )

        except Exception as error:

            print(
                "Chunk hatası:",
                current,
                chunk_end,
                error,
                flush=True
            )

            print(
                "Bu chunk tekrar denenecek.",
                flush=True
            )

            raise

        current = (
            chunk_end + 1
        )

    print(
        "SCANNER TAMAMLANDI",
        flush=True
    )


if __name__ == "__main__":
    main()
