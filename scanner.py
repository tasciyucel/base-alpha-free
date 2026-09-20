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
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a9df523b3ef"
)

CHUNK_SIZE = 10

# Son testte taranmış fakat analiz edilememiş aralık.
# Backfill tamamlandıktan sonra None yapılacak.
BACKFILL_START = 51569194
BACKFILL_END = 51569821

TOKEN_CACHE = {}


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


def get_latest_block():

    result = rpc(
        "eth_blockNumber",
        []
    )

    return int(result, 16)


def get_usdc_logs(start_block, end_block):

    print(
        f"USDC logları aranıyor: "
        f"{start_block} -> {end_block}"
    )

    return rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
            "address": USDC_ADDRESS
        }]
    )


def get_transaction(tx_hash):

    return rpc(
        "eth_getTransactionByHash",
        [tx_hash]
    )


def get_transaction_receipt(tx_hash):

    return rpc(
        "eth_getTransactionReceipt",
        [tx_hash]
    )


def get_block_timestamp(block_number):

    result = rpc(
        "eth_getBlockByNumber",
        [
            hex(block_number),
            False
        ]
    )

    return int(
        result["timestamp"],
        16
    )


def decode_address(topic):

    return (
        "0x" +
        topic[-40:]
    ).lower()


def decode_amount(raw_amount, decimals):

    if decimals is None:
        return None

    try:

        return (
            int(raw_amount, 16)
            /
            (10 ** decimals)
        )

    except Exception:

        return None


def decode_abi_string(data):

    if not data or data == "0x":
        return ""

    try:

        raw = bytes.fromhex(data[2:])

        if len(raw) == 32:

            return raw.rstrip(b"\x00").decode(
                "utf-8",
                errors="ignore"
            )

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

    # USDC sabit metadata
    if token_address == USDC_ADDRESS:

        metadata = {
            "decimals": 6,
            "symbol": "USDC",
            "name": "USD Coin"
        }

        TOKEN_CACHE[token_address] = metadata

        return metadata

    try:

        decimals_result = rpc(
            "eth_call",
            [{
                "to": token_address,
                "data": "0x313ce567"
            }, "latest"]
        )

        decimals = int(
            decimals_result,
            16
        )

    except Exception:

        decimals = None

    symbol = ""

    try:

        result = rpc(
            "eth_call",
            [{
                "to": token_address,
                "data": "0x95d89b41"
            }, "latest"]
        )

        symbol = decode_abi_string(result)

    except Exception:

        pass

    name = ""

    try:

        result = rpc(
            "eth_call",
            [{
                "to": token_address,
                "data": "0x06fdde03"
            }, "latest"]
        )

        name = decode_abi_string(result)

    except Exception:

        pass

    metadata = {
        "decimals": decimals,
        "symbol": symbol,
        "name": name
    }

    TOKEN_CACHE[token_address] = metadata

    return metadata


def parse_transfer_log(log):

    topics = log.get(
        "topics",
        []
    )

    if len(topics) < 3:
        return None

    topic0 = topics[0].lower()

    if topic0 != TRANSFER_TOPIC:
        return None

    token = log.get(
        "address",
        ""
    ).lower()

    from_address = decode_address(
        topics[1]
    )

    to_address = decode_address(
        topics[2]
    )

    raw_amount = log.get(
        "data",
        "0x0"
    )

    return {
        "token": token,
        "from": from_address,
        "to": to_address,
        "raw_amount": raw_amount,
        "block_number": int(
            log["blockNumber"],
            16
        ),
        "tx_hash": log["transactionHash"],
        "log_index": int(
            log["logIndex"],
            16
        )
    }


def analyze_transaction(
    tx_hash,
    block_timestamp
):

    tx = get_transaction(
        tx_hash
    )

    if not tx:
        return False

    trader = tx.get(
        "from",
        ""
    ).lower()

    if not trader:
        return False

    receipt = get_transaction_receipt(
        tx_hash
    )

    if not receipt:
        return False

    logs = receipt.get(
        "logs",
        []
    )

    transfers = []

    for log in logs:

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

        token = transfer["token"]

        if token == USDC_ADDRESS:

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

    # BUY:
    # Trader USDC gönderiyor
    # Trader token alıyor

    if sent_usdc and received_tokens:

        side = "BUY"

        usdc_transfer = max(
            sent_usdc,
            key=lambda x: int(
                x["raw_amount"],
                16
            )
        )

        token_transfer = received_tokens[0]

    # SELL:
    # Trader token gönderiyor
    # Trader USDC alıyor

    elif received_usdc and sent_tokens:

        side = "SELL"

        usdc_transfer = max(
            received_usdc,
            key=lambda x: int(
                x["raw_amount"],
                16
            )
        )

        token_transfer = sent_tokens[0]

    else:

        return False

    usd_value = decode_amount(
        usdc_transfer["raw_amount"],
        6
    )

    if usd_value is None:
        return False

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

        "tx_hash": tx_hash,

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

    if saved:

        update_wallet(
            trade
        )

        print()
        print("====================================")
        print("YENİ SWAP BULUNDU")
        print("Trader:", trader)
        print("Side:", side)
        print("Token:", metadata["symbol"])
        print("Token adresi:", token_transfer["token"])
        print("Token miktarı:", token_amount)
        print("USD:", usd_value)
        print("TX:", tx_hash)
        print("====================================")

        return True

    return False


def process_block_range(
    start_block,
    end_block
):

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

    # Aynı transaction birden fazla USDC
    # transferi içerebilir.
    tx_hashes = set()

    for transfer in transfer_logs:

        tx_hashes.add(
            transfer["tx_hash"]
        )

    print(
        "Aday transaction:",
        len(tx_hashes)
    )

    # Timestamp cache
    timestamp_cache = {}

    analyzed = 0

    for tx_hash in tx_hashes:

        try:

            tx = get_transaction(
                tx_hash
            )

            if not tx:
                continue

            block_number = int(
                tx["blockNumber"],
                16
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

            if analyze_transaction(
                tx_hash,
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


def main():

    init_db()

    latest = get_latest_block()

    print()
    print("====================================")
    print("BASE ALPHA SCANNER")
    print("Latest block:", latest)
    print("====================================")

    last_scanned = get_last_scanned_block()

    # Önce kaçırılan eski aralığı tamamla.
    if last_scanned is not None:

        if (
            last_scanned >= BACKFILL_START
            and
            last_scanned <= BACKFILL_END
        ):

            start_block = BACKFILL_START

            print(
                "BACKFILL aktif:",
                BACKFILL_START,
                "->",
                BACKFILL_END
            )

        elif last_scanned < BACKFILL_START:

            start_block = BACKFILL_START

        else:

            start_block = last_scanned + 1

    else:

        start_block = BACKFILL_START

    # Backfill bittiyse normal çalışmaya geç.
    scan_end = latest

    if start_block <= BACKFILL_END:

        scan_end = min(
            BACKFILL_END,
            latest
        )

    print(
        "Tarama başlangıcı:",
        start_block
    )

    print(
        "Tarama bitişi:",
        scan_end
    )

    total_analyzed = 0

    current = start_block

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
