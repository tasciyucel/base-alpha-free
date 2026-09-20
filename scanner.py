import time
import requests

from config import BASE_RPC_URL
from database import (
    init_db,
    save_trade,
    update_wallet,
    get_token_metadata,
    save_token_metadata,
    get_last_scanned_block,
    save_last_scanned_block,
)


# ============================================================
# AYARLAR
# ============================================================

USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f"
    "163c4a11628f55a4df523b3ef"
)

# Bir chunk kaç blok?
CHUNK_SIZE = 10

# JSON-RPC batch boyutu
# 429 yaşamamak için 25 kullanıyoruz.
RPC_BATCH_SIZE = 25

# RPC tekrar deneme sayısı
MAX_RETRIES = 7

# Batch'ler arasında küçük bekleme
BATCH_DELAY = 0.25

# Token cache
TOKEN_CACHE = {}

# HTTP connection reuse
SESSION = requests.Session()


# ============================================================
# GENEL RPC
# ============================================================

def rpc(method, params):
    """
    Tek JSON-RPC isteği.
    429 durumunda exponential backoff uygular.
    """

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    for attempt in range(MAX_RETRIES):

        try:

            response = SESSION.post(
                BASE_RPC_URL,
                json=payload,
                timeout=45,
            )

            # ------------------------------------------------
            # Rate limit
            # ------------------------------------------------

            if response.status_code == 429:

                wait = min(
                    2 ** attempt,
                    30,
                )

                print(
                    f"RPC 429 - "
                    f"{wait} saniye bekleniyor..."
                )

                time.sleep(wait)

                continue

            response.raise_for_status()

            data = response.json()

            if "error" in data:

                error = data["error"]

                raise RuntimeError(
                    f"RPC error: {error}"
                )

            return data.get("result")

        except Exception as e:

            if attempt >= MAX_RETRIES - 1:
                raise

            wait = min(
                2 ** attempt,
                30,
            )

            print(
                f"RPC hata: {e}"
            )

            print(
                f"{wait} saniye sonra tekrar..."
            )

            time.sleep(wait)

    return None


# ============================================================
# BATCH RPC
# ============================================================

def rpc_batch(calls):
    """
    Gerçek JSON-RPC batch isteği.

    Önemli:
    - 429 olursa aynı batch tekrar gönderilir.
    - Eksik cevap gelirse batch başarısız kabul edilir.
    - Böylece sessiz veri kaybı olmaz.
    """

    payload = []

    for rpc_id, (method, params) in enumerate(
        calls,
        start=1,
    ):

        payload.append({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params,
        })

    expected_ids = {
        item["id"]
        for item in payload
    }

    for attempt in range(MAX_RETRIES):

        try:

            response = SESSION.post(
                BASE_RPC_URL,
                json=payload,
                timeout=60,
            )

            # ------------------------------------------------
            # 429
            # ------------------------------------------------

            if response.status_code == 429:

                wait = min(
                    2 ** attempt,
                    30,
                )

                print(
                    f"Batch RPC 429 - "
                    f"{wait} saniye bekleniyor..."
                )

                time.sleep(wait)

                continue

            response.raise_for_status()

            data = response.json()

            if not isinstance(data, list):

                raise RuntimeError(
                    "Batch RPC cevabı liste değil."
                )

            # ------------------------------------------------
            # Gelen ID'leri kontrol et
            # ------------------------------------------------

            received_ids = {
                item.get("id")
                for item in data
            }

            missing_ids = (
                expected_ids
                - received_ids
            )

            if missing_ids:

                raise RuntimeError(
                    "Batch RPC eksik cevap verdi. "
                    f"Eksik ID sayısı: "
                    f"{len(missing_ids)}"
                )

            results = {}

            for item in data:

                rpc_id = item.get(
                    "id"
                )

                # ------------------------------------------------
                # RPC error
                # ------------------------------------------------

                if "error" in item:

                    print(
                        f"Batch item RPC error "
                        f"id={rpc_id}: "
                        f"{item['error']}"
                    )

                    results[rpc_id] = None

                else:

                    results[rpc_id] = (
                        item.get("result")
                    )

            return results

        except Exception as e:

            if attempt >= MAX_RETRIES - 1:
                raise

            wait = min(
                2 ** attempt,
                30,
            )

            print(
                f"Batch RPC hata: {e}"
            )

            print(
                f"{wait} saniye sonra "
                f"aynı batch tekrar denenecek..."
            )

            time.sleep(wait)

    raise RuntimeError(
        "Batch RPC başarısız."
    )


# ============================================================
# HEX GÜVENLİ DÖNÜŞÜM
# ============================================================

def safe_hex_to_int(value, default=0):
    """
    '0x' veya None gibi değerlerde hata vermez.
    """

    if value is None:
        return default

    if isinstance(value, int):
        return value

    if not isinstance(value, str):
        return default

    value = value.strip()

    if value == "":
        return default

    if value.lower() == "0x":
        return default

    try:

        return int(
            value,
            16,
        )

    except (
        ValueError,
        TypeError,
    ):

        return default


# ============================================================
# BLOCK
# ============================================================

def get_latest_block():

    result = rpc(
        "eth_blockNumber",
        [],
    )

    return safe_hex_to_int(
        result
    )


def get_block_timestamp(
    block_number,
):

    result = rpc(
        "eth_getBlockByNumber",
        [
            hex(block_number),
            False,
        ],
    )

    if not result:
        return int(
            time.time()
        )

    return safe_hex_to_int(
        result.get(
            "timestamp"
        ),
        int(time.time()),
    )


# ============================================================
# USDC LOG
# ============================================================

def get_usdc_logs(
    from_block,
    to_block,
):

    params = {
        "fromBlock": hex(
            from_block
        ),
        "toBlock": hex(
            to_block
        ),
        "address": USDC_ADDRESS,
        "topics": [
            TRANSFER_TOPIC
        ],
    }

    result = rpc(
        "eth_getLogs",
        [params],
    )

    return result or []


# ============================================================
# ADDRESS
# ============================================================

def topic_to_address(topic):

    if not topic:
        return ""

    if not isinstance(
        topic,
        str,
    ):
        return ""

    if len(topic) < 40:
        return ""

    return (
        "0x"
        + topic[-40:].lower()
    )


# ============================================================
# TRANSFER LOG PARSE
# ============================================================

def parse_transfer_log(log):

    topics = log.get(
        "topics",
        [],
    )

    if len(topics) < 3:
        return None

    from_address = topic_to_address(
        topics[1]
    )

    to_address = topic_to_address(
        topics[2]
    )

    raw_amount = safe_hex_to_int(
        log.get(
            "data",
            "0x0",
        )
    )

    block_number = safe_hex_to_int(
        log.get(
            "blockNumber",
            "0x0",
        )
    )

    timestamp = log.get(
        "blockTimestamp"
    )

    if isinstance(
        timestamp,
        str,
    ):

        timestamp = safe_hex_to_int(
            timestamp,
            0,
        )

    elif not isinstance(
        timestamp,
        int,
    ):

        timestamp = 0

    return {
        "from": from_address,
        "to": to_address,
        "amount": raw_amount,
        "block_number": block_number,
        "timestamp": timestamp,
        "tx_hash": log.get(
            "transactionHash"
        ),
    }


# ============================================================
# TRANSACTION BATCH
# ============================================================

def get_transactions(
    tx_hashes,
):

    transactions = {}

    total = len(
        tx_hashes
    )

    if total == 0:
        return transactions

    for start in range(
        0,
        total,
        RPC_BATCH_SIZE,
    ):

        batch_hashes = tx_hashes[
            start:
            start + RPC_BATCH_SIZE
        ]

        end = start + len(
            batch_hashes
        )

        print(
            f"Transaction batch: "
            f"{start + 1} -> {end} / {total}"
        )

        calls = []

        for tx_hash in batch_hashes:

            calls.append(
                (
                    "eth_getTransactionByHash",
                    [tx_hash],
                )
            )

        results = rpc_batch(
            calls
        )

        for index, tx_hash in enumerate(
            batch_hashes,
            start=1,
        ):

            tx = results.get(
                index
            )

            if tx is not None:

                transactions[
                    tx_hash
                ] = tx

        time.sleep(
            BATCH_DELAY
        )

    return transactions


# ============================================================
# RECEIPT BATCH
# ============================================================

def get_transaction_receipts(
    tx_hashes,
):

    receipts = {}

    total = len(
        tx_hashes
    )

    if total == 0:
        return receipts

    for start in range(
        0,
        total,
        RPC_BATCH_SIZE,
    ):

        batch_hashes = tx_hashes[
            start:
            start + RPC_BATCH_SIZE
        ]

        end = start + len(
            batch_hashes
        )

        print(
            f"Receipt batch: "
            f"{start + 1} -> {end} / {total}"
        )

        calls = []

        for tx_hash in batch_hashes:

            calls.append(
                (
                    "eth_getTransactionReceipt",
                    [tx_hash],
                )
            )

        results = rpc_batch(
            calls
        )

        for index, tx_hash in enumerate(
            batch_hashes,
            start=1,
        ):

            receipt = results.get(
                index
            )

            if receipt is not None:

                receipts[
                    tx_hash
                ] = receipt

        time.sleep(
            BATCH_DELAY
        )

    return receipts


# ============================================================
# TOKEN DECIMALS
# ============================================================

def eth_call(
    to,
    data,
):

    return rpc(
        "eth_call",
        [
            {
                "to": to,
                "data": data,
            },
            "latest",
        ],
    )


def get_token_decimals(
    address,
):

    address = address.lower()

    # --------------------------------------------------------
    # RAM CACHE
    # --------------------------------------------------------

    if address in TOKEN_CACHE:

        return TOKEN_CACHE[
            address
        ]

    # --------------------------------------------------------
    # DATABASE CACHE
    # --------------------------------------------------------

    metadata = get_token_metadata(
        address
    )

    if metadata is not None:

        decimals = metadata.get(
            "decimals"
        )

        if decimals is not None:

            TOKEN_CACHE[
                address
            ] = decimals

            return decimals

    # --------------------------------------------------------
    # RPC
    # --------------------------------------------------------

    try:

        result = eth_call(
            address,
            "0x313ce567",
        )

        if not result:
            return None

        decimals = safe_hex_to_int(
            result,
            None,
        )

        if decimals is None:
            return None

        save_token_metadata(
            address,
            "",
            "",
            decimals,
        )

        TOKEN_CACHE[
            address
        ] = decimals

        return decimals

    except Exception as e:

        print(
            f"Decimals alınamadı "
            f"{address}: {e}"
        )

        return None


# ============================================================
# TRANSACTION ANALYSIS
# ============================================================

def analyze_transaction(
    tx,
    receipt,
    usdc_log_info,
):

    if not tx:
        return None

    if not receipt:
        return None

    tx_hash = tx.get(
        "hash"
    )

    trader = (
        tx.get("from")
        or ""
    ).lower()

    if not trader:
        return None

    receipt_logs = receipt.get(
        "logs",
        [],
    )

    if not receipt_logs:
        return None

    usdc_in = 0
    usdc_out = 0

    token_movements = {}

    timestamp = (
        usdc_log_info.get(
            "timestamp",
            0,
        )
        or 0
    )

    block_number = (
        usdc_log_info.get(
            "block_number",
            0,
        )
        or 0
    )

    # --------------------------------------------------------
    # Receipt loglarını tara
    # --------------------------------------------------------

    for log in receipt_logs:

        topics = log.get(
            "topics",
            [],
        )

        if len(topics) < 3:
            continue

        topic0 = topics[0]

        if not isinstance(
            topic0,
            str,
        ):
            continue

        if topic0.lower() != TRANSFER_TOPIC:
            continue

        token_address = (
            log.get(
                "address"
            )
            or ""
        ).lower()

        parsed = parse_transfer_log(
            log
        )

        if parsed is None:
            continue

        from_address = parsed[
            "from"
        ]

        to_address = parsed[
            "to"
        ]

        amount = parsed[
            "amount"
        ]

        if parsed[
            "timestamp"
        ]:

            timestamp = parsed[
                "timestamp"
            ]

        if parsed[
            "block_number"
        ]:

            block_number = parsed[
                "block_number"
            ]

        # ----------------------------------------------------
        # USDC
        # ----------------------------------------------------

        if token_address == USDC_ADDRESS:

            if from_address == trader:

                usdc_out += amount

            if to_address == trader:

                usdc_in += amount

            continue

        # ----------------------------------------------------
        # Diğer token
        # ----------------------------------------------------

        if from_address == trader:

            if token_address not in token_movements:

                token_movements[
                    token_address
                ] = {
                    "sent": 0,
                    "received": 0,
                }

            token_movements[
                token_address
            ][
                "sent"
            ] += amount

        if to_address == trader:

            if token_address not in token_movements:

                token_movements[
                    token_address
                ] = {
                    "sent": 0,
                    "received": 0,
                }

            token_movements[
                token_address
            ][
                "received"
            ] += amount

    # --------------------------------------------------------
    # USDC hareketi yok
    # --------------------------------------------------------

    if (
        usdc_in == 0
        and usdc_out == 0
    ):

        return None

    # --------------------------------------------------------
    # Token hareketi yok
    # --------------------------------------------------------

    if not token_movements:
        return None

    side = None

    amount_usd_raw = 0

    token_address = None

    token_amount_raw = 0

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if usdc_out > 0:

        for (
            address,
            movement,
        ) in token_movements.items():

            if movement[
                "received"
            ] > 0:

                side = "BUY"

                token_address = address

                token_amount_raw = (
                    movement[
                        "received"
                    ]
                )

                amount_usd_raw = (
                    usdc_out
                )

                break

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

    if (
        side is None
        and usdc_in > 0
    ):

        for (
            address,
            movement,
        ) in token_movements.items():

            if movement[
                "sent"
            ] > 0:

                side = "SELL"

                token_address = address

                token_amount_raw = (
                    movement[
                        "sent"
                    ]
                )

                amount_usd_raw = (
                    usdc_in
                )

                break

    if side is None:
        return None

    # --------------------------------------------------------
    # USDC 6 decimals
    # --------------------------------------------------------

    amount_usd = (
        amount_usd_raw
        / 1_000_000
    )

    # --------------------------------------------------------
    # Token decimals
    # --------------------------------------------------------

    decimals = get_token_decimals(
        token_address
    )

    if decimals is None:

        print(
            f"Token decimals bulunamadı: "
            f"{token_address}"
        )

        return None

    token_amount = (
        token_amount_raw
        / (
            10 ** decimals
        )
    )

    return {
        "tx_hash": tx_hash,
        "block_number": block_number,
        "timestamp": timestamp,
        "trader": trader,
        "token": token_address,
        "symbol": "",
        "side": side,
        "amount_usd": amount_usd,
        "token_amount": token_amount,
    }


# ============================================================
# CHUNK
# ============================================================

def process_chunk(
    from_block,
    to_block,
):

    print()
    print(
        f"Chunk: "
        f"{from_block} -> {to_block}"
    )

    # --------------------------------------------------------
    # 1. USDC logs
    # --------------------------------------------------------

    print(
        "USDC logları aranıyor..."
    )

    logs = get_usdc_logs(
        from_block,
        to_block,
    )

    print(
        f"Toplam USDC log: "
        f"{len(logs)}"
    )

    if not logs:

        print(
            "Bu chunk'ta USDC hareketi yok."
        )

        return True

    # --------------------------------------------------------
    # 2. Parse
    # --------------------------------------------------------

    parsed_logs = []

    for log in logs:

        parsed = parse_transfer_log(
            log
        )

        if parsed is None:
            continue

        parsed_logs.append(
            parsed
        )

    print(
        f"USDC Transfer log: "
        f"{len(parsed_logs)}"
    )

    # --------------------------------------------------------
    # 3. Unique tx
    # --------------------------------------------------------

    tx_info = {}

    for item in parsed_logs:

        tx_hash = item.get(
            "tx_hash"
        )

        if not tx_hash:
            continue

        if tx_hash not in tx_info:

            tx_info[
                tx_hash
            ] = item

    tx_hashes = list(
        tx_info.keys()
    )

    print(
        f"Aday transaction: "
        f"{len(tx_hashes)}"
    )

    if not tx_hashes:
        return True

    # --------------------------------------------------------
    # 4. Transactions
    # --------------------------------------------------------

    transactions = get_transactions(
        tx_hashes
    )

    print(
        f"Transaction alındı: "
        f"{len(transactions)} / "
        f"{len(tx_hashes)}"
    )

    # Transaction eksikliği varsa
    # chunk'ı tamamlanmış saymıyoruz.
    if len(transactions) != len(
        tx_hashes
    ):

        print(
            "Bazı transaction'lar "
            "alınamadı."
        )

        return False

    # --------------------------------------------------------
    # 5. Receipts
    # --------------------------------------------------------

    receipts = get_transaction_receipts(
        tx_hashes
    )

    print(
        f"Receipt alındı: "
        f"{len(receipts)} / "
        f"{len(tx_hashes)}"
    )

    # Receipt eksikliği varsa
    # chunk'ı tamamlamıyoruz.
    if len(receipts) != len(
        tx_hashes
    ):

        print(
            "Bazı receipt'ler "
            "alınamadı."
        )

        return False

    # --------------------------------------------------------
    # 6. Swap analysis
    # --------------------------------------------------------

    real_swaps = []

    for tx_hash in tx_hashes:

        tx = transactions.get(
            tx_hash
        )

        receipt = receipts.get(
            tx_hash
        )

        if tx is None:
            continue

        if receipt is None:
            continue

        result = analyze_transaction(
            tx,
            receipt,
            tx_info[
                tx_hash
            ],
        )

        if result is not None:

            real_swaps.append(
                result
            )

    print(
        f"Gerçek swap adayı: "
        f"{len(real_swaps)}"
    )

    # --------------------------------------------------------
    # 7. DB
    # --------------------------------------------------------

    saved_count = 0

    for trade in real_swaps:

        saved = save_trade(
            trade
        )

        # UNIQUE tx_hash sayesinde
        # tekrar taramalarda duplicate olmaz.
        if not saved:
            continue

        update_wallet(
            trade
        )

        saved_count += 1

        print(
            f"{trade['side']} "
            f"{trade['token']} "
            f"${trade['amount_usd']:.6f} "
            f"wallet={trade['trader']}"
        )

    print(
        f"Yeni kaydedilen swap: "
        f"{saved_count}"
    )

    print(
        f"Chunk tamamlandı: "
        f"{to_block}"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=" * 70
    )
    print(
        "BASE ALPHA SCANNER"
    )
    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # DB
    # --------------------------------------------------------

    init_db()

    # --------------------------------------------------------
    # Latest block
    # --------------------------------------------------------

    latest_block = get_latest_block()

    print(
        f"Latest block: "
        f"{latest_block}"
    )

    # --------------------------------------------------------
    # Nereden devam ediyoruz?
    # --------------------------------------------------------

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

    print(
        f"Tarama başlangıcı: "
        f"{start_block}"
    )

    print(
        f"Tarama bitişi: "
        f"{latest_block}"
    )

    # --------------------------------------------------------
    # Yeni blok yok
    # --------------------------------------------------------

    if start_block > latest_block:

        print(
            "Yeni blok yok."
        )

        return

    current = start_block

    # --------------------------------------------------------
    # Chunk loop
    # --------------------------------------------------------

    while current <= latest_block:

        chunk_end = min(
            current
            + CHUNK_SIZE
            - 1,
            latest_block,
        )

        try:

            success = process_chunk(
                current,
                chunk_end,
            )

            if not success:

                print()
                print(
                    "Chunk başarısız."
                )

                print(
                    "Bu chunk tekrar "
                    "denenmek üzere "
                    "burada duruyor."
                )

                break

            # ------------------------------------------------
            # SADECE BAŞARILI CHUNK'TAN
            # SONRA STATE İLERLET
            # ------------------------------------------------

            save_last_scanned_block(
                chunk_end
            )

            current = (
                chunk_end + 1
            )

        except Exception as e:

            print()
            print(
                "=" * 70
            )
            print(
                "CHUNK HATASI"
            )
            print(
                str(e)
            )
            print(
                "=" * 70
            )

            print(
                "Bu chunk tekrar "
                "denenmek üzere "
                "burada duruyor."
            )

            break

    print()
    print(
        "=" * 70
    )
    print(
        "SCAN TAMAMLANDI"
    )
    print(
        "=" * 70
    )


if __name__ == "__main__":
    main()
