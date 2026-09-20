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

CHUNK_SIZE = 10

# Aynı anda gönderilecek JSON-RPC isteği sayısı.
# 50 genellikle iyi bir denge.
RPC_BATCH_SIZE = 50

# İlk kez tarama yapılacaksa buradan başlar.
BACKFILL_START = 51569194

# RPC rate-limit durumunda tekrar deneme
MAX_RETRIES = 5

# Token metadata cache
TOKEN_CACHE = {}

# HTTP bağlantısını tekrar kullan
SESSION = requests.Session()


# ============================================================
# RPC
# ============================================================

def rpc(method, params):
    """
    Tek JSON-RPC isteği.
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
                timeout=30,
            )

            if response.status_code == 429:
                wait = 2 ** attempt
                print(
                    f"RPC 429 - {wait} saniye bekleniyor..."
                )
                time.sleep(wait)
                continue

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise RuntimeError(
                    f"RPC error: {data['error']}"
                )

            return data.get("result")

        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise

            wait = 2 ** attempt

            print(
                f"RPC hata: {e}"
            )
            print(
                f"{wait} saniye sonra tekrar deneniyor..."
            )

            time.sleep(wait)

    return None


def rpc_batch(calls):
    """
    Gerçek JSON-RPC batch isteği.

    calls:
        [
            ("eth_getTransactionByHash", [tx_hash]),
            ("eth_getTransactionByHash", [tx_hash]),
            ...
        ]

    Dönen:
        {
            rpc_id: result
        }
    """

    payload = []

    for rpc_id, (method, params) in enumerate(calls, start=1):
        payload.append({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params,
        })

    for attempt in range(MAX_RETRIES):

        try:
            response = SESSION.post(
                BASE_RPC_URL,
                json=payload,
                timeout=60,
            )

            if response.status_code == 429:
                wait = 2 ** attempt

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

            results = {}

            for item in data:
                rpc_id = item.get("id")

                if "error" in item:
                    results[rpc_id] = None
                else:
                    results[rpc_id] = item.get("result")

            return results

        except Exception as e:

            if attempt == MAX_RETRIES - 1:
                raise

            wait = 2 ** attempt

            print(
                f"Batch RPC hata: {e}"
            )

            print(
                f"{wait} saniye sonra tekrar deneniyor..."
            )

            time.sleep(wait)

    return {}


# ============================================================
# BLOCK
# ============================================================

def get_latest_block():
    result = rpc(
        "eth_blockNumber",
        [],
    )

    return int(result, 16)


def get_block_timestamp(block_number):
    """
    Gerekirse block timestamp'i alır.
    """

    result = rpc(
        "eth_getBlockByNumber",
        [
            hex(block_number),
            False,
        ],
    )

    if not result:
        return int(time.time())

    return int(
        result["timestamp"],
        16,
    )


# ============================================================
# USDC LOG
# ============================================================

def get_usdc_logs(
    from_block,
    to_block,
):
    """
    Belirtilen blok aralığındaki USDC Transfer loglarını alır.
    """

    params = {
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "address": USDC_ADDRESS,
        "topics": [
            TRANSFER_TOPIC
        ],
    }

    return rpc(
        "eth_getLogs",
        [params],
    ) or []


# ============================================================
# ADDRESS / AMOUNT
# ============================================================

def topic_to_address(topic):
    """
    32 byte topic -> Ethereum address
    """

    if not topic:
        return ""

    return "0x" + topic[-40:].lower()


def hex_to_int(value):
    if value is None:
        return 0

    return int(value, 16)


def parse_transfer_log(log):
    """
    ERC20 Transfer eventini parse eder.
    """

    topics = log.get("topics", [])

    if len(topics) < 3:
        return None

    from_address = topic_to_address(
        topics[1]
    )

    to_address = topic_to_address(
        topics[2]
    )

    raw_amount = hex_to_int(
        log.get("data", "0x0")
    )

    block_number = hex_to_int(
        log.get("blockNumber", "0x0")
    )

    timestamp = log.get("blockTimestamp")

    if timestamp:
        if isinstance(timestamp, str):
            try:
                timestamp = int(
                    timestamp,
                    16
                )
            except ValueError:
                timestamp = int(timestamp)
    else:
        timestamp = 0

    return {
        "from": from_address,
        "to": to_address,
        "amount": raw_amount,
        "block_number": block_number,
        "timestamp": timestamp,
        "tx_hash": log.get("transactionHash"),
    }


# ============================================================
# TRANSACTION BATCH
# ============================================================

def get_transactions(tx_hashes):
    """
    Transaction'ları gerçek JSON-RPC batch ile çeker.
    """

    transactions = {}

    total = len(tx_hashes)

    if total == 0:
        return transactions

    batch_number = 0

    for start in range(
        0,
        total,
        RPC_BATCH_SIZE,
    ):

        batch_number += 1

        batch_hashes = tx_hashes[
            start:start + RPC_BATCH_SIZE
        ]

        end = start + len(batch_hashes)

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

        results = rpc_batch(calls)

        for index, tx_hash in enumerate(
            batch_hashes,
            start=1,
        ):

            rpc_id = index

            tx = results.get(rpc_id)

            if tx is not None:
                transactions[tx_hash] = tx

        # Rate limit'e gereksiz yük bindirmemek için
        time.sleep(0.1)

    return transactions


# ============================================================
# RECEIPT BATCH
# ============================================================

def get_transaction_receipts(tx_hashes):
    """
    Sadece aday transaction'ların receipt'lerini çeker.

    Eski sistem:
        eth_getBlockReceipts
        -> bloktaki bütün receipt'ler

    Yeni sistem:
        eth_getTransactionReceipt
        -> sadece aday transaction'lar
    """

    receipts = {}

    total = len(tx_hashes)

    if total == 0:
        return receipts

    for start in range(
        0,
        total,
        RPC_BATCH_SIZE,
    ):

        batch_hashes = tx_hashes[
            start:start + RPC_BATCH_SIZE
        ]

        end = start + len(batch_hashes)

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

        results = rpc_batch(calls)

        for index, tx_hash in enumerate(
            batch_hashes,
            start=1,
        ):

            rpc_id = index

            receipt = results.get(rpc_id)

            if receipt is not None:
                receipts[tx_hash] = receipt

        time.sleep(0.1)

    return receipts


# ============================================================
# TOKEN METADATA
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


def get_token_decimals(address):
    """
    ERC20 decimals()
    selector: 0x313ce567
    """

    address = address.lower()

    if address in TOKEN_CACHE:
        return TOKEN_CACHE[address]

    metadata = get_token_metadata(address)

    if metadata is not None:
        decimals = metadata.get("decimals")

        if decimals is not None:
            TOKEN_CACHE[address] = decimals
            return decimals

    try:
        result = eth_call(
            address,
            "0x313ce567",
        )

        if result:
            decimals = int(
                result,
                16,
            )

            save_token_metadata(
                address,
                "",
                "",
                decimals,
            )

            TOKEN_CACHE[address] = decimals

            return decimals

    except Exception as e:
        print(
            f"Decimals alınamadı "
            f"{address}: {e}"
        )

    return None


# ============================================================
# SWAP ANALYSIS
# ============================================================

def analyze_transaction(
    tx,
    receipt,
    usdc_log_info,
):
    """
    Transaction içindeki USDC hareketi ile
    token hareketini karşılaştırarak BUY / SELL bulur.
    """

    if not tx or not receipt:
        return None

    tx_hash = tx.get("hash")

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

    timestamp = usdc_log_info.get(
        "timestamp",
        0,
    )

    block_number = usdc_log_info.get(
        "block_number",
        0,
    )

    # --------------------------------------------------------
    # Receipt içindeki bütün Transfer loglarını tara
    # --------------------------------------------------------

    for log in receipt_logs:

        topics = log.get(
            "topics",
            [],
        )

        if len(topics) < 3:
            continue

        if topics[0].lower() != TRANSFER_TOPIC:
            continue

        token_address = (
            log.get("address")
            or ""
        ).lower()

        parsed = parse_transfer_log(
            log
        )

        if parsed is None:
            continue

        from_address = parsed["from"]
        to_address = parsed["to"]

        amount = parsed["amount"]

        # Receipt loglarında timestamp olmayabilir.
        if parsed["timestamp"]:
            timestamp = parsed["timestamp"]

        if parsed["block_number"]:
            block_number = parsed["block_number"]

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
        # Diğer tokenlar
        # ----------------------------------------------------

        if from_address == trader:

            if token_address not in token_movements:
                token_movements[token_address] = {
                    "sent": 0,
                    "received": 0,
                }

            token_movements[token_address][
                "sent"
            ] += amount

        if to_address == trader:

            if token_address not in token_movements:
                token_movements[token_address] = {
                    "sent": 0,
                    "received": 0,
                }

            token_movements[token_address][
                "received"
            ] += amount

    # --------------------------------------------------------
    # USDC hareketi yoksa swap değil
    # --------------------------------------------------------

    if usdc_in == 0 and usdc_out == 0:
        return None

    # --------------------------------------------------------
    # Token hareketi yoksa swap değil
    # --------------------------------------------------------

    if not token_movements:
        return None

    # --------------------------------------------------------
    # BUY / SELL
    # --------------------------------------------------------

    side = None
    amount_usd_raw = 0
    token_address = None
    token_amount_raw = 0

    # BUY:
    # trader USDC gönderiyor
    # trader token alıyor
    if usdc_out > 0:

        for address, movement in token_movements.items():

            if movement["received"] > 0:

                side = "BUY"
                token_address = address
                token_amount_raw = movement[
                    "received"
                ]
                amount_usd_raw = usdc_out

                break

    # SELL:
    # trader token gönderiyor
    # trader USDC alıyor
    if side is None and usdc_in > 0:

        for address, movement in token_movements.items():

            if movement["sent"] > 0:

                side = "SELL"
                token_address = address
                token_amount_raw = movement[
                    "sent"
                ]
                amount_usd_raw = usdc_in

                break

    if side is None:
        return None

    # --------------------------------------------------------
    # USDC 6 decimal
    # --------------------------------------------------------

    amount_usd = (
        amount_usd_raw / 1_000_000
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
        / (10 ** decimals)
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
    # 1. USDC logları
    # --------------------------------------------------------

    print(
        "USDC logları aranıyor..."
    )

    logs = get_usdc_logs(
        from_block,
        to_block,
    )

    print(
        f"Toplam USDC log: {len(logs)}"
    )

    if not logs:
        print(
            "Bu chunk'ta USDC hareketi yok."
        )
        return True

    # --------------------------------------------------------
    # 2. Logları parse et
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
    # 3. Unique transaction hash
    # --------------------------------------------------------

    tx_info = {}

    for item in parsed_logs:

        tx_hash = item.get(
            "tx_hash"
        )

        if not tx_hash:
            continue

        # Aynı transaction için
        # ilk bilgiyi koru.
        if tx_hash not in tx_info:
            tx_info[tx_hash] = item

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
    # 4. Transaction'ları batch çek
    # --------------------------------------------------------

    transactions = get_transactions(
        tx_hashes
    )

    print(
        f"Transaction alındı: "
        f"{len(transactions)}"
    )

    if not transactions:
        print(
            "Transaction alınamadı."
        )
        return False

    # --------------------------------------------------------
    # 5. Receipt'leri sadece aday tx'ler
    #    için batch çek
    # --------------------------------------------------------

    receipt_hashes = [
        tx_hash
        for tx_hash in tx_hashes
        if tx_hash in transactions
    ]

    receipts = get_transaction_receipts(
        receipt_hashes
    )

    print(
        f"Receipt alındı: "
        f"{len(receipts)}"
    )

    # --------------------------------------------------------
    # 6. Gerçek swap'ları bul
    # --------------------------------------------------------

    real_swaps = []

    for tx_hash in receipt_hashes:

        tx = transactions.get(
            tx_hash
        )

        receipt = receipts.get(
            tx_hash
        )

        if tx is None or receipt is None:
            continue

        result = analyze_transaction(
            tx,
            receipt,
            tx_info[tx_hash],
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
    # 7. DB'ye kaydet
    # --------------------------------------------------------

    saved_count = 0

    for trade in real_swaps:

        saved = save_trade(
            trade
        )

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

    init_db()

    latest_block = get_latest_block()

    print(
        f"Latest block: "
        f"{latest_block}"
    )

    last_scanned = get_last_scanned_block()

    if last_scanned is None:
        start_block = BACKFILL_START
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

    if start_block > latest_block:

        print(
            "Yeni blok yok."
        )

        return

    current = start_block

    while current <= latest_block:

        chunk_end = min(
            current + CHUNK_SIZE - 1,
            latest_block,
        )

        try:

            success = process_chunk(
                current,
                chunk_end,
            )

            if not success:

                print(
                    "Chunk başarısız. "
                    "Scanner bu noktada duruyor."
                )

                break

            # ------------------------------------------------
            # Chunk başarıyla tamamlandıysa
            # state'i ilerlet.
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
                e
            )
            print(
                "=" * 70
            )

            print(
                "Bu chunk tekrar denenmek üzere "
                "burada duruluyor."
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
