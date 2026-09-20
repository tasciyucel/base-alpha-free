import time
import requests

from database import (
    init_db,
    save_trade,
    update_wallet,
    get_last_scanned_block,
    save_last_scanned_block,
    get_token_metadata,
    save_token_metadata,
)
from config import BASE_RPC_URL


# ============================================================
# AYARLAR
# ============================================================

USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Her chunk'ta kaç blok taranacak
CHUNK_SIZE = 10

# İlk çalışmada geriye doğru kaç blok taransın?
INITIAL_LOOKBACK = 2600

# Receipt batch büyüklüğü.
# Alchemy 429 verdiği için küçük tutuluyor.
RECEIPT_BATCH_SIZE = 5

# Batch'ler arasında bekleme
BATCH_DELAY = 0.75

# RPC retry
MAX_RETRIES = 8

# Her retry arasında başlangıç beklemesi
RETRY_DELAY = 1.5

# Minimum USDC işlem miktarı.
# Çok küçük transferleri elemek için.
MIN_USDC = 1.0


# ============================================================
# RPC
# ============================================================

session = requests.Session()


def rpc_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = session.post(
                BASE_RPC_URL,
                json=payload,
                timeout=30,
            )

            if response.status_code == 429:
                wait = RETRY_DELAY * (attempt + 1)

                print(
                    f"RPC HTTP 429: {method} "
                    f"- {wait:.1f}s bekleniyor..."
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            data = response.json()

            if "error" in data:
                error = data["error"]

                print(
                    f"RPC error: {method}: {error}"
                )

                if error.get("code") == 429:
                    wait = RETRY_DELAY * (attempt + 1)

                    print(
                        f"RPC JSON 429: "
                        f"{wait:.1f}s bekleniyor..."
                    )

                    time.sleep(wait)
                    continue

                return None

            return data.get("result")

        except Exception as exc:
            wait = RETRY_DELAY * (attempt + 1)

            print(
                f"RPC exception: {method}: {exc}"
            )

            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)

    return None


def rpc_batch(calls):
    """
    Batch RPC.
    Başarılı sonuçları korur.
    Tek tek 429 alan çağrıları tekrar dener.
    """

    if not calls:
        return []

    pending = list(calls)
    results = {}

    for attempt in range(MAX_RETRIES):

        if not pending:
            break

        payload = []

        for item in pending:
            payload.append({
                "jsonrpc": "2.0",
                "id": item["id"],
                "method": item["method"],
                "params": item["params"],
            })

        try:
            response = session.post(
                BASE_RPC_URL,
                json=payload,
                timeout=60,
            )

            if response.status_code == 429:
                wait = RETRY_DELAY * (attempt + 1)

                print(
                    f"Batch HTTP 429 "
                    f"({len(pending)} item) "
                    f"- {wait:.1f}s bekleniyor..."
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            data = response.json()

            # RPC batch cevaplarını id -> response şeklinde tut
            response_map = {}

            for item in data:
                response_map[item.get("id")] = item

            next_pending = []

            for item in pending:

                item_id = item["id"]
                result = response_map.get(item_id)

                if result is None:
                    next_pending.append(item)
                    continue

                if "error" in result:
                    error = result["error"]

                    if error.get("code") == 429:

                        next_pending.append(item)

                    else:
                        print(
                            f"Batch RPC error "
                            f"id={item_id}: {error}"
                        )

                        # Kalıcı RPC hatasında None
                        results[item_id] = None

                    continue

                results[item_id] = result.get("result")

            pending = next_pending

            if pending:
                wait = RETRY_DELAY * (attempt + 1)

                print(
                    f"Batch içinde {len(pending)} "
                    f"RPC çağrısı tekrar denenecek "
                    f"- {wait:.1f}s"
                )

                time.sleep(wait)

        except Exception as exc:

            wait = RETRY_DELAY * (attempt + 1)

            print(
                f"Batch exception: {exc} "
                f"- {wait:.1f}s"
            )

            time.sleep(wait)

    # Hâlâ alınamayanları None yap
    for item in pending:
        results[item["id"]] = None

    return [
        results.get(item["id"])
        for item in calls
    ]


# ============================================================
# HEX HELPERS
# ============================================================

def hex_to_int(value):
    if value is None:
        return 0

    if isinstance(value, int):
        return value

    return int(value, 16)


def topic_address(topic):
    if not topic:
        return None

    topic = topic.lower()

    if topic.startswith("0x"):
        topic = topic[2:]

    if len(topic) < 40:
        return None

    return "0x" + topic[-40:]


def normalize_address(address):
    if not address:
        return ""

    return address.lower()


# ============================================================
# BLOCK
# ============================================================

def get_latest_block():

    result = rpc_call(
        "eth_blockNumber",
        [],
    )

    if result is None:
        raise RuntimeError(
            "Latest block alınamadı."
        )

    return hex_to_int(result)


def get_block_timestamp(block_number):

    result = rpc_call(
        "eth_getBlockByNumber",
        [
            hex(block_number),
            False,
        ],
    )

    if not result:
        return None

    return hex_to_int(
        result.get("timestamp")
    )


# ============================================================
# USDC LOGS
# ============================================================

def get_usdc_logs(
    from_block,
    to_block,
):

    print(
        "USDC logları aranıyor..."
    )

    result = rpc_call(
        "eth_getLogs",
        [{
            "address": USDC_ADDRESS,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": [
                TRANSFER_TOPIC
            ],
        }],
    )

    if result is None:
        return None

    print(
        f"Toplam USDC log: {len(result)}"
    )

    return result


# ============================================================
# LOG PARSING
# ============================================================

def parse_transfer_log(log):

    topics = log.get("topics", [])

    if len(topics) < 3:
        return None

    if topics[0].lower() != TRANSFER_TOPIC:
        return None

    sender = topic_address(topics[1])
    receiver = topic_address(topics[2])

    data = log.get("data", "0x0")

    try:
        amount_raw = hex_to_int(data)
    except Exception:
        return None

    amount = amount_raw / 1_000_000

    return {
        "token": normalize_address(
            log.get("address")
        ),
        "from": normalize_address(sender),
        "to": normalize_address(receiver),
        "amount_raw": amount_raw,
        "amount": amount,
        "tx_hash": log.get("transactionHash"),
        "block_number": hex_to_int(
            log.get("blockNumber")
        ),
        "log_index": hex_to_int(
            log.get("logIndex")
        ),
    }


def parse_all_transfer_logs(receipt):

    transfers = []

    for log in receipt.get("logs", []):

        topics = log.get("topics", [])

        if not topics:
            continue

        if topics[0].lower() != TRANSFER_TOPIC:
            continue

        parsed = parse_transfer_log(log)

        if parsed:
            transfers.append(parsed)

    return transfers


# ============================================================
# RECEIPTS
# ============================================================

def get_receipts(tx_hashes):

    if not tx_hashes:
        return []

    receipts = []

    total = len(tx_hashes)

    for start in range(
        0,
        total,
        RECEIPT_BATCH_SIZE,
    ):

        batch_hashes = tx_hashes[
            start:start + RECEIPT_BATCH_SIZE
        ]

        calls = []

        for index, tx_hash in enumerate(
            batch_hashes
        ):

            calls.append({
                "id": start + index + 1,
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash],
            })

        print(
            f"Receipt batch: "
            f"{start + 1} -> "
            f"{min(start + RECEIPT_BATCH_SIZE, total)} "
            f"/ {total}"
        )

        batch_results = rpc_batch(
            calls
        )

        for tx_hash, receipt in zip(
            batch_hashes,
            batch_results,
        ):

            if receipt is not None:
                receipts.append(
                    receipt
                )

        if start + RECEIPT_BATCH_SIZE < total:
            time.sleep(BATCH_DELAY)

    print(
        f"Receipt alındı: "
        f"{len(receipts)} / {total}"
    )

    return receipts


# ============================================================
# TOKEN METADATA
# ============================================================

def eth_call(
    to,
    data,
):

    return rpc_call(
        "eth_call",
        [
            {
                "to": to,
                "data": data,
            },
            "latest",
        ],
    )


def decode_string_result(result):

    if not result:
        return ""

    try:

        raw = bytes.fromhex(
            result[2:]
        )

        if len(raw) < 64:
            return ""

        # ABI dynamic string
        offset = int.from_bytes(
            raw[0:32],
            "big",
        )

        if offset + 32 > len(raw):
            return ""

        length = int.from_bytes(
            raw[offset:offset + 32],
            "big",
        )

        start = offset + 32
        end = start + length

        return raw[start:end].decode(
            "utf-8",
            errors="ignore",
        )

    except Exception:
        return ""


def decode_bytes32_string(result):

    if not result:
        return ""

    try:

        raw = bytes.fromhex(
            result[2:]
        )

        raw = raw[:32]

        return raw.rstrip(
            b"\x00"
        ).decode(
            "utf-8",
            errors="ignore",
        )

    except Exception:
        return ""


def get_token_metadata_cached(
    token_address
):

    token_address = normalize_address(
        token_address
    )

    if not token_address:
        return None

    cached = get_token_metadata(
        token_address
    )

    if cached:
        return cached

    # symbol()
    symbol_result = eth_call(
        token_address,
        "0x95d89b41",
    )

    # name()
    name_result = eth_call(
        token_address,
        "0x06fdde03",
    )

    # decimals()
    decimals_result = eth_call(
        token_address,
        "0x313ce567",
    )

    symbol = (
        decode_string_result(
            symbol_result
        )
        or decode_bytes32_string(
            symbol_result
        )
    )

    name = (
        decode_string_result(
            name_result
        )
        or decode_bytes32_string(
            name_result
        )
    )

    decimals = 18

    if decimals_result:

        try:
            decimals = hex_to_int(
                decimals_result
            )
        except Exception:
            decimals = 18

    save_token_metadata(
        token_address,
        symbol,
        name,
        decimals,
    )

    return {
        "symbol": symbol,
        "name": name,
        "decimals": decimals,
    }


# ============================================================
# SWAP ANALYSIS
# ============================================================

def analyze_transaction(
    receipt,
    usdc_log,
    timestamp,
):

    tx_hash = receipt.get(
        "transactionHash"
    )

    if not tx_hash:
        return None

    transfers = parse_all_transfer_logs(
        receipt
    )

    if not transfers:
        return None

    usdc_transfers = []

    for transfer in transfers:

        if (
            transfer["token"]
            == USDC_ADDRESS.lower()
        ):
            usdc_transfers.append(
                transfer
            )

    if not usdc_transfers:
        return None

    # --------------------------------------------------------
    # Aynı transaction'daki USDC hareketlerini değerlendir.
    # Bir transaction'da birden fazla USDC transferi olabilir.
    # --------------------------------------------------------

    target_usdc = None

    usdc_from = normalize_address(
        usdc_log["from"]
    )

    usdc_to = normalize_address(
        usdc_log["to"]
    )

    for transfer in usdc_transfers:

        if (
            normalize_address(
                transfer["from"]
            ) == usdc_from
            and
            normalize_address(
                transfer["to"]
            ) == usdc_to
        ):

            target_usdc = transfer
            break

    if target_usdc is None:
        target_usdc = usdc_transfers[0]

    amount_usd = target_usdc["amount"]

    if amount_usd < MIN_USDC:
        return None

    # --------------------------------------------------------
    # USDC hareketinin karşılığındaki token transferini bul.
    #
    # BUY:
    #   trader -> USDC
    #   pool/router -> trader : token
    #
    # SELL:
    #   trader -> token
    #   pool/router -> trader : USDC
    #
    # Böylece transaction'ın "from" bilgisini almak için
    # eth_getTransactionByHash kullanmak zorunda kalmıyoruz.
    # --------------------------------------------------------

    candidate_token_transfers = []

    for transfer in transfers:

        token = normalize_address(
            transfer["token"]
        )

        if token == USDC_ADDRESS.lower():
            continue

        if token == ZERO_ADDRESS:
            continue

        candidate_token_transfers.append(
            transfer
        )

    if not candidate_token_transfers:
        return None

    trader = None
    side = None
    token_transfer = None

    # --------------------------------------------------------
    # BUY
    #
    # USDC gönderen adres aynı zamanda
    # token alan adres ise:
    #
    # trader = USDC from
    # --------------------------------------------------------

    for transfer in candidate_token_transfers:

        if (
            normalize_address(
                transfer["to"]
            ) == usdc_from
        ):

            trader = usdc_from
            side = "BUY"
            token_transfer = transfer
            break

    # --------------------------------------------------------
    # SELL
    #
    # USDC alan adres token gönderen adres ise:
    #
    # trader = USDC to
    # --------------------------------------------------------

    if trader is None:

        for transfer in candidate_token_transfers:

            if (
                normalize_address(
                    transfer["from"]
                ) == usdc_to
            ):

                trader = usdc_to
                side = "SELL"
                token_transfer = transfer
                break

    if trader is None:
        return None

    token_address = normalize_address(
        token_transfer["token"]
    )

    # --------------------------------------------------------
    # Token metadata
    # --------------------------------------------------------

    metadata = get_token_metadata_cached(
        token_address
    )

    if metadata is None:
        return None

    decimals = metadata.get(
        "decimals",
        18,
    )

    token_amount = (
        token_transfer["amount_raw"]
        / (10 ** decimals)
    )

    symbol = metadata.get(
        "symbol",
        "",
    )

    # Bazı kontratlarda sembol boş olabilir.
    if not symbol:
        symbol = token_address[:10]

    return {
        "tx_hash": tx_hash,
        "block_number": hex_to_int(
            receipt.get("blockNumber")
        ),
        "timestamp": timestamp,
        "trader": trader,
        "token": token_address,
        "symbol": symbol,
        "side": side,
        "amount_usd": amount_usd,
        "token_amount": token_amount,
    }


# ============================================================
# CHUNK PROCESSING
# ============================================================

def process_chunk(
    from_block,
    to_block,
):

    print()
    print(
        "=" * 100
    )

    print(
        f"Chunk: "
        f"{from_block} -> {to_block}"
    )

    print(
        "USDC Transfer logları taranıyor..."
    )

    logs = get_usdc_logs(
        from_block,
        to_block,
    )

    if logs is None:

        print(
            "USDC logları alınamadı."
        )

        return False

    if not logs:

        print(
            "Bu chunk'ta USDC transferi yok."
        )

        # Timestamp/state için latest block
        # daha sonra güvenle ilerlenebilir.
        return True

    parsed_logs = []

    tx_map = {}

    for log in logs:

        parsed = parse_transfer_log(
            log
        )

        if parsed is None:
            continue

        parsed_logs.append(
            parsed
        )

        tx_hash = parsed["tx_hash"]

        if tx_hash:
            tx_map.setdefault(
                tx_hash,
                []
            ).append(parsed)

    print(
        f"USDC Transfer log: "
        f"{len(parsed_logs)}"
    )

    tx_hashes = list(
        tx_map.keys()
    )

    print(
        f"Aday transaction: "
        f"{len(tx_hashes)}"
    )

    if not tx_hashes:
        return True

    # --------------------------------------------------------
    # TransactionByHash YOK.
    # Sadece receipt alıyoruz.
    # --------------------------------------------------------

    receipts = get_receipts(
        tx_hashes
    )

    if len(receipts) != len(tx_hashes):

        print()
        print(
            f"UYARI: "
            f"{len(tx_hashes) - len(receipts)} "
            f"receipt alınamadı."
        )

        print(
            "Chunk başarısız kabul ediliyor."
        )

        print(
            "last_scanned_block ilerletilmeyecek."
        )

        return False

    # Receipt'leri hash ile eşleştir
    receipt_map = {}

    for receipt in receipts:

        tx_hash = receipt.get(
            "transactionHash"
        )

        if tx_hash:
            receipt_map[
                tx_hash.lower()
            ] = receipt

    # Block timestamp cache
    timestamp_cache = {}

    found_trades = 0
    saved_trades = 0

    for tx_hash, tx_logs in tx_map.items():

        receipt = receipt_map.get(
            tx_hash.lower()
        )

        if receipt is None:
            continue

        block_number = hex_to_int(
            receipt.get("blockNumber")
        )

        if block_number not in timestamp_cache:

            timestamp_cache[
                block_number
            ] = get_block_timestamp(
                block_number
            )

        timestamp = timestamp_cache[
            block_number
        ]

        if timestamp is None:
            timestamp = int(
                time.time()
            )

        # Aynı transaction'daki her USDC logunu
        # ayrı ayrı deniyoruz.
        for usdc_log in tx_logs:

            trade = analyze_transaction(
                receipt,
                usdc_log,
                timestamp,
            )

            if trade is None:
                continue

            found_trades += 1

            saved = save_trade(
                trade
            )

            if saved:
                update_wallet(
                    trade
                )

                saved_trades += 1

                print()
                print(
                    "SWAP BULUNDU"
                )
                print(
                    "TX:",
                    trade["tx_hash"]
                )
                print(
                    "Wallet:",
                    trade["trader"]
                )
                print(
                    "Token:",
                    trade["symbol"],
                    trade["token"]
                )
                print(
                    "Side:",
                    trade["side"]
                )
                print(
                    "USDC:",
                    trade["amount_usd"]
                )
                print(
                    "Token miktarı:",
                    trade["token_amount"]
                )

    print()
    print(
        f"Analiz edilen swap: "
        f"{found_trades}"
    )

    print(
        f"Yeni kaydedilen swap: "
        f"{saved_trades}"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=" * 100
    )
    print(
        "BASE ALPHA SCANNER"
    )
    print(
        "=" * 100
    )

    print(
        "RPC:",
        BASE_RPC_URL
    )

    init_db()

    latest_block = get_latest_block()

    print(
        f"Latest block: "
        f"{latest_block}"
    )

    last_scanned = get_last_scanned_block()

    if last_scanned is None:

        start_block = max(
            0,
            latest_block - INITIAL_LOOKBACK,
        )

        print(
            f"İlk tarama. "
            f"Geriye doğru {INITIAL_LOOKBACK} "
            f"blok taranacak."
        )

    else:

        start_block = (
            last_scanned + 1
        )

        print(
            f"Son taranan block: "
            f"{last_scanned}"
        )

    if start_block > latest_block:

        print(
            "Yeni taranacak block yok."
        )

        return

    print(
        f"Tarama başlangıcı: "
        f"{start_block}"
    )

    print(
        f"Tarama bitişi: "
        f"{latest_block}"
    )

    current = start_block

    while current <= latest_block:

        end_block = min(
            current + CHUNK_SIZE - 1,
            latest_block,
        )

        success = process_chunk(
            current,
            end_block,
        )

        if not success:

            print()
            print(
                "!" * 100
            )
            print(
                "CHUNK BAŞARISIZ."
            )
            print(
                "Bu noktada scanner duruyor."
            )
            print(
                "last_scanned_block "
                "güncellenmeyecek."
            )
            print(
                "Sonraki çalışmada aynı "
                "chunk tekrar denenecek."
            )
            print(
                "!" * 100
            )

            return

        # ----------------------------------------------------
        # SADECE CHUNK TAMAMLANDIKTAN SONRA STATE GÜNCELLENİR
        # ----------------------------------------------------

        save_last_scanned_block(
            end_block
        )

        print()
        print(
            f"Chunk tamamlandı: "
            f"{current} -> {end_block}"
        )

        print(
            f"last_scanned_block = "
            f"{end_block}"
        )

        current = end_block + 1

        # Chunk'lar arasında biraz nefes
        time.sleep(0.5)

    print()
    print(
        "=" * 100
    )

    print(
        "TARAMA TAMAMLANDI"
    )

    print(
        f"Son block: "
        f"{latest_block}"
    )

    print(
        "=" * 100
    )


if __name__ == "__main__":
    main()
