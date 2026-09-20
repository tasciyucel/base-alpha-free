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

USDC_ADDRESS = (
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
)

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

ZERO_ADDRESS = (
    "0x0000000000000000000000000000000000000000"
)

CHUNK_SIZE = 10

INITIAL_LOOKBACK = 2600

MAX_RETRIES = 7

RETRY_DELAY = 1.5

MIN_USDC = 1.0

RPC_TIMEOUT = 60


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()


# ============================================================
# RPC
# ============================================================

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
                timeout=RPC_TIMEOUT,
            )

            if response.status_code == 429:

                wait = RETRY_DELAY * (attempt + 1)

                print(
                    f"RPC 429: {method} "
                    f"- {wait:.1f}s bekleniyor..."
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            data = response.json()

            if "error" in data:

                error = data["error"]

                print(
                    f"RPC error: {method}: "
                    f"{error}"
                )

                if error.get("code") == 429:

                    wait = (
                        RETRY_DELAY
                        * (attempt + 1)
                    )

                    time.sleep(wait)
                    continue

                return None

            return data.get("result")

        except Exception as exc:

            print(
                f"RPC exception: {method}: "
                f"{exc}"
            )

            if attempt < MAX_RETRIES - 1:

                wait = (
                    RETRY_DELAY
                    * (attempt + 1)
                )

                time.sleep(wait)

    return None


# ============================================================
# HELPERS
# ============================================================

def hex_to_int(value):

    if value is None:
        return 0

    if isinstance(value, int):
        return value

    return int(value, 16)


def normalize_address(address):

    if not address:
        return ""

    return address.lower()


def topic_address(topic):

    if not topic:
        return None

    topic = topic.lower()

    if topic.startswith("0x"):
        topic = topic[2:]

    if len(topic) < 40:
        return None

    return "0x" + topic[-40:]


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


def get_block_timestamps(
    block_numbers
):

    if not block_numbers:
        return {}

    timestamps = {}

    for block_number in sorted(
        block_numbers
    ):

        result = rpc_call(
            "eth_getBlockByNumber",
            [
                hex(block_number),
                False,
            ],
        )

        if result:

            timestamps[
                block_number
            ] = hex_to_int(
                result.get("timestamp")
            )

    return timestamps


# ============================================================
# TRANSFER LOG SORGUSU
# ============================================================

def get_transfer_logs(
    from_block,
    to_block,
    address=None,
):

    params = {
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "topics": [
            TRANSFER_TOPIC
        ],
    }

    if address:

        params["address"] = address

    return rpc_call(
        "eth_getLogs",
        [params],
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

    if (
        topics[0].lower()
        != TRANSFER_TOPIC
    ):
        return None

    sender = topic_address(
        topics[1]
    )

    receiver = topic_address(
        topics[2]
    )

    if not sender or not receiver:
        return None

    try:

        amount_raw = hex_to_int(
            log.get(
                "data",
                "0x0",
            )
        )

    except Exception:

        return None

    return {
        "token": normalize_address(
            log.get("address")
        ),
        "from": normalize_address(
            sender
        ),
        "to": normalize_address(
            receiver
        ),
        "amount_raw": amount_raw,
        "tx_hash": log.get(
            "transactionHash"
        ),
        "block_number": hex_to_int(
            log.get("blockNumber")
        ),
        "log_index": hex_to_int(
            log.get("logIndex")
        ),
    }


# ============================================================
# ABI STRING DECODE
# ============================================================

def decode_string_result(
    result
):

    if not result:
        return ""

    try:

        raw = bytes.fromhex(
            result[2:]
        )

        if len(raw) < 64:
            return ""

        offset = int.from_bytes(
            raw[0:32],
            "big",
        )

        if (
            offset + 32
            > len(raw)
        ):
            return ""

        length = int.from_bytes(
            raw[
                offset:
                offset + 32
            ],
            "big",
        )

        start = offset + 32

        end = start + length

        if end > len(raw):
            return ""

        return raw[
            start:end
        ].decode(
            "utf-8",
            errors="ignore",
        )

    except Exception:

        return ""


def decode_bytes32_string(
    result
):

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


# ============================================================
# TOKEN METADATA
# ============================================================

def eth_call(
    token_address,
    data,
):

    return rpc_call(
        "eth_call",
        [
            {
                "to": token_address,
                "data": data,
            },
            "latest",
        ],
    )


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

    print(
        f"Yeni token metadata: "
        f"{token_address}"
    )

    symbol_result = eth_call(
        token_address,
        "0x95d89b41",
    )

    name_result = eth_call(
        token_address,
        "0x06fdde03",
    )

    decimals_result = eth_call(
        token_address,
        "0x313ce567",
    )

    symbol = (
        decode_string_result(
            symbol_result
        )
        or
        decode_bytes32_string(
            symbol_result
        )
    )

    name = (
        decode_string_result(
            name_result
        )
        or
        decode_bytes32_string(
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
# SWAP ANALİZİ
# ============================================================

def analyze_transaction(
    tx_hash,
    transfers,
    usdc_transfers,
    timestamp,
):

    if not transfers:
        return None

    if not usdc_transfers:
        return None

    # --------------------------------------------------------
    # USDC transferlerini değerlendir.
    # --------------------------------------------------------

    for usdc in usdc_transfers:

        amount_usd = (
            usdc["amount_raw"]
            / 1_000_000
        )

        if amount_usd < MIN_USDC:
            continue

        usdc_from = normalize_address(
            usdc["from"]
        )

        usdc_to = normalize_address(
            usdc["to"]
        )

        token_transfers = []

        for transfer in transfers:

            token = normalize_address(
                transfer["token"]
            )

            if (
                token
                == USDC_ADDRESS.lower()
            ):
                continue

            if (
                token
                == ZERO_ADDRESS
            ):
                continue

            token_transfers.append(
                transfer
            )

        if not token_transfers:
            continue

        trader = None
        side = None
        token_transfer = None

        # ----------------------------------------------------
        # BUY
        #
        # USDC trader'dan çıkıyor.
        # Token trader'a geliyor.
        # ----------------------------------------------------

        for transfer in token_transfers:

            if normalize_address(
                transfer["to"]
            ) == usdc_from:

                trader = usdc_from
                side = "BUY"
                token_transfer = transfer

                break

        # ----------------------------------------------------
        # SELL
        #
        # Token trader'dan çıkıyor.
        # USDC trader'a geliyor.
        # ----------------------------------------------------

        if trader is None:

            for transfer in token_transfers:

                if normalize_address(
                    transfer["from"]
                ) == usdc_to:

                    trader = usdc_to
                    side = "SELL"
                    token_transfer = transfer

                    break

        if trader is None:
            continue

        token_address = normalize_address(
            token_transfer["token"]
        )

        metadata = (
            get_token_metadata_cached(
                token_address
            )
        )

        if metadata is None:
            continue

        decimals = metadata.get(
            "decimals",
            18,
        )

        token_amount = (
            token_transfer[
                "amount_raw"
            ]
            / (10 ** decimals)
        )

        symbol = metadata.get(
            "symbol",
            "",
        )

        if not symbol:

            symbol = (
                token_address[:10]
            )

        return {
            "tx_hash": tx_hash,
            "block_number":
                usdc["block_number"],
            "timestamp": timestamp,
            "trader": trader,
            "token": token_address,
            "symbol": symbol,
            "side": side,
            "amount_usd":
                amount_usd,
            "token_amount":
                token_amount,
        }

    return None


# ============================================================
# CHUNK
# ============================================================

def process_chunk(
    from_block,
    to_block,
):

    print()
    print("=" * 100)

    print(
        f"Chunk: "
        f"{from_block} -> {to_block}"
    )

    # --------------------------------------------------------
    # 1. USDC LOGS
    # --------------------------------------------------------

    print(
        "USDC Transfer logları aranıyor..."
    )

    usdc_logs = get_transfer_logs(
        from_block,
        to_block,
        USDC_ADDRESS,
    )

    if usdc_logs is None:

        print(
            "USDC logları alınamadı."
        )

        return False

    print(
        f"USDC logları: "
        f"{len(usdc_logs)}"
    )

    if not usdc_logs:

        print(
            "Bu chunk'ta USDC transferi yok."
        )

        return True

    # --------------------------------------------------------
    # 2. TÜM ERC20 TRANSFER LOGS
    # --------------------------------------------------------

    print(
        "Tüm ERC20 Transfer logları aranıyor..."
    )

    all_logs = get_transfer_logs(
        from_block,
        to_block,
    )

    if all_logs is None:

        print(
            "ERC20 logları alınamadı."
        )

        return False

    print(
        f"Tüm ERC20 logları: "
        f"{len(all_logs)}"
    )

    # --------------------------------------------------------
    # 3. LOG PARSE
    # --------------------------------------------------------

    parsed_by_tx = {}

    for log in all_logs:

        parsed = parse_transfer_log(
            log
        )

        if parsed is None:
            continue

        tx_hash = parsed[
            "tx_hash"
        ]

        if not tx_hash:
            continue

        parsed_by_tx.setdefault(
            tx_hash.lower(),
            []
        ).append(
            parsed
        )

    # --------------------------------------------------------
    # 4. USDC LOGS -> TX MAP
    # --------------------------------------------------------

    usdc_by_tx = {}

    for log in usdc_logs:

        parsed = parse_transfer_log(
            log
        )

        if parsed is None:
            continue

        tx_hash = parsed[
            "tx_hash"
        ]

        if not tx_hash:
            continue

        usdc_by_tx.setdefault(
            tx_hash.lower(),
            []
        ).append(
            parsed
        )

    candidate_txs = list(
        usdc_by_tx.keys()
    )

    print(
        f"Aday transaction: "
        f"{len(candidate_txs)}"
    )

    # --------------------------------------------------------
    # 5. TIMESTAMP CACHE
    #
    # Aynı block için yalnızca bir kez
    # eth_getBlockByNumber çağrısı.
    # --------------------------------------------------------

    block_numbers = set()

    for tx_hash in candidate_txs:

        for usdc in usdc_by_tx[
            tx_hash
        ]:

            block_numbers.add(
                usdc["block_number"]
            )

    timestamps = (
        get_block_timestamps(
            block_numbers
        )
    )

    # --------------------------------------------------------
    # 6. SWAP ANALİZİ
    # --------------------------------------------------------

    found = 0
    saved = 0

    for tx_hash in candidate_txs:

        transfers = parsed_by_tx.get(
            tx_hash,
            []
        )

        usdc_transfers = (
            usdc_by_tx.get(
                tx_hash,
                []
            )
        )

        if not transfers:
            continue

        block_number = (
            usdc_transfers[0][
                "block_number"
            ]
        )

        timestamp = timestamps.get(
            block_number
        )

        if timestamp is None:

            timestamp = int(
                time.time()
            )

        trade = analyze_transaction(
            tx_hash,
            transfers,
            usdc_transfers,
            timestamp,
        )

        if trade is None:
            continue

        found += 1

        if save_trade(trade):

            update_wallet(
                trade
            )

            saved += 1

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
                trade["symbol"]
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
        f"{found}"
    )

    print(
        f"Yeni kaydedilen swap: "
        f"{saved}"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 100)

    print(
        "BASE ALPHA SCANNER"
    )

    print("=" * 100)

    print(
        "RPC:",
        BASE_RPC_URL
    )

    init_db()

    latest_block = (
        get_latest_block()
    )

    print(
        f"Latest block: "
        f"{latest_block}"
    )

    last_scanned = (
        get_last_scanned_block()
    )

    if last_scanned is None:

        start_block = max(
            0,
            latest_block
            - INITIAL_LOOKBACK,
        )

        print(
            f"İlk tarama. "
            f"Geriye doğru "
            f"{INITIAL_LOOKBACK} "
            f"blok."
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
            "Yeni block yok."
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
            current
            + CHUNK_SIZE
            - 1,
            latest_block,
        )

        success = process_chunk(
            current,
            end_block,
        )

        if not success:

            print()
            print("!" * 100)

            print(
                "CHUNK BAŞARISIZ."
            )

            print(
                "last_scanned_block "
                "güncellenmedi."
            )

            print(
                "Sonraki çalışmada "
                "aynı chunk tekrar "
                "denenecek."
            )

            print("!" * 100)

            return

        # ----------------------------------------------------
        # Chunk tamamen başarılıysa state ilerler.
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

    print()
    print("=" * 100)

    print(
        "TARAMA TAMAMLANDI"
    )

    print(
        f"Son block: "
        f"{latest_block}"
    )

    print("=" * 100)


if __name__ == "__main__":
    main()
