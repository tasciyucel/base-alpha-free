import time
import requests

from config import BASE_RPC_URL
from database import init_db, save_trade, update_wallet


TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)

UNISWAP_UNIVERSAL_ROUTER = (
    "0x6ff5693b99212da76ad316178a184ab56d299b43"
)

USDC_ADDRESS = (
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
)

TOKEN_CACHE = {}


def rpc(method, params=None, retries=4):

    last_error = None

    for attempt in range(retries):

        try:

            response = requests.post(
                BASE_RPC_URL,
                json={
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or [],
                    "id": 1
                },
                timeout=30
            )

            if response.status_code == 429:

                wait_time = 2 ** attempt

                print(
                    "RPC rate limit (429).",
                    wait_time,
                    "saniye bekleniyor..."
                )

                time.sleep(wait_time)

                continue

            response.raise_for_status()

            data = response.json()

            if "error" in data:

                raise RuntimeError(
                    data["error"]
                )

            return data["result"]

        except Exception as e:

            last_error = e

            if attempt < retries - 1:

                wait_time = 2 ** attempt

                time.sleep(wait_time)

    raise last_error


def get_latest_block():

    block = rpc("eth_blockNumber")

    return int(block, 16)


def get_block(block_number):

    return rpc(
        "eth_getBlockByNumber",
        [
            hex(block_number),
            True
        ]
    )


def get_transaction_receipt(tx_hash):

    return rpc(
        "eth_getTransactionReceipt",
        [tx_hash]
    )


def topic_to_address(topic):

    return "0x" + topic[-40:]


def eth_call(token, selector):

    return rpc(
        "eth_call",
        [
            {
                "to": token,
                "data": selector
            },
            "latest"
        ]
    )


def decode_uint256(data):

    if not data or data == "0x":
        return None

    try:

        clean = data[2:]

        if len(clean) < 64:
            return None

        return int(
            clean[-64:],
            16
        )

    except Exception:

        return None


def decode_string(data):

    if not data or data == "0x":
        return None

    try:

        raw = bytes.fromhex(
            data[2:]
        )

        if len(raw) >= 64:

            offset = int.from_bytes(
                raw[:32],
                "big"
            )

            if (
                offset + 32 <= len(raw)
                and offset < len(raw)
            ):

                length = int.from_bytes(
                    raw[offset:offset + 32],
                    "big"
                )

                start = offset + 32
                end = start + length

                if (
                    length > 0
                    and end <= len(raw)
                ):

                    value = raw[start:end].decode(
                        "utf-8",
                        errors="ignore"
                    ).strip("\x00")

                    if value:
                        return value

        value = raw[:32].rstrip(
            b"\x00"
        ).decode(
            "utf-8",
            errors="ignore"
        ).strip()

        if value:
            return value

    except Exception:

        pass

    return None


def get_token_metadata(token):

    token = token.lower()

    if token in TOKEN_CACHE:
        return TOKEN_CACHE[token]

    # Base USDC: decimals = 6
    # RPC'den okumaya gerek yok.
    if token == USDC_ADDRESS:

        metadata = {
            "address": token,
            "name": "USD Coin",
            "symbol": "USDC",
            "decimals": 6
        }

        TOKEN_CACHE[token] = metadata

        return metadata

    name = None
    symbol = None
    decimals = None

    try:

        name_data = eth_call(
            token,
            "0x06fdde03"
        )

        name = decode_string(
            name_data
        )

    except Exception as e:

        print(
            "name() okunamadı:",
            token,
            "|",
            str(e)
        )

    time.sleep(0.15)

    try:

        symbol_data = eth_call(
            token,
            "0x95d89b41"
        )

        symbol = decode_string(
            symbol_data
        )

    except Exception as e:

        print(
            "symbol() okunamadı:",
            token,
            "|",
            str(e)
        )

    time.sleep(0.15)

    try:

        decimals_data = eth_call(
            token,
            "0x313ce567"
        )

        decimals = decode_uint256(
            decimals_data
        )

        if decimals is not None:

            print(
                "DECIMALS:",
                token,
                "=>",
                decimals
            )

    except Exception as e:

        print(
            "decimals() okunamadı:",
            token,
            "|",
            str(e)
        )

    metadata = {
        "address": token,
        "name": name or "Unknown",
        "symbol": symbol or "UNKNOWN",
        "decimals": decimals
    }

    if decimals is not None:
        TOKEN_CACHE[token] = metadata

    return metadata


def decode_amount(data, decimals):

    if not data or data == "0x":
        return 0

    raw_amount = int(
        data,
        16
    )

    # Ondalık bilgisi bilinmiyorsa
    # ham değeri insan okunabilir miktar gibi kullanma.
    if decimals is None:
        return None

    return raw_amount / (
        10 ** decimals
    )


def analyze_transfer(log, wallet):

    topics = log.get(
        "topics",
        []
    )

    if len(topics) < 3:
        return None

    if topics[0].lower() != TRANSFER_TOPIC:
        return None

    token = log.get(
        "address",
        ""
    ).lower()

    sender = topic_to_address(
        topics[1]
    ).lower()

    receiver = topic_to_address(
        topics[2]
    ).lower()

    metadata = get_token_metadata(
        token
    )

    amount = decode_amount(
        log.get("data"),
        metadata["decimals"]
    )

    result = {
        "token": token,
        "symbol": metadata["symbol"],
        "name": metadata["name"],
        "decimals": metadata["decimals"],
        "amount": amount,
        "from": sender,
        "to": receiver
    }

    if receiver == wallet.lower():

        result["direction"] = "RECEIVED"

    elif sender == wallet.lower():

        result["direction"] = "SENT"

    else:

        result["direction"] = "OTHER"

    return result


def calculate_usd_value(sent, received):

    all_tokens = sent + received

    for item in all_tokens:

        if item["token"].lower() == USDC_ADDRESS:

            return item["amount"]

    return None


def main():

    print(
        "Base Alpha Scanner başlıyor..."
    )

    init_db()

    latest = get_latest_block()

    print(
        "Base latest block:",
        latest
    )

    blocks_to_scan = 5

    all_transactions = []
    tx_context = {}

    for block_number in range(
        latest - blocks_to_scan + 1,
        latest + 1
    ):

        print(
            "Blok taranıyor:",
            block_number
        )

        block = get_block(
            block_number
        )

        block_timestamp = int(
            block["timestamp"],
            16
        )

        block_transactions = block.get(
            "transactions",
            []
        )

        for tx in block_transactions:

            all_transactions.append(
                tx
            )

            tx_context[tx["hash"]] = {
                "block_number": block_number,
                "timestamp": block_timestamp
            }

    transactions = all_transactions

    print(
        "Toplam transaction sayısı:",
        len(transactions)
    )

    found = 0

    for tx in transactions:

        tx_hash = tx.get("hash")
        tx_to = tx.get("to")
        wallet = tx.get("from")

        if not tx_hash or not tx_to or not wallet:
            continue

        if tx_to.lower() != UNISWAP_UNIVERSAL_ROUTER:
            continue

        receipt = get_transaction_receipt(
            tx_hash
        )

        logs = receipt.get(
            "logs",
            []
        )

        received = []
        sent = []

        for log in logs:

            transfer = analyze_transfer(
                log,
                wallet
            )

            if not transfer:
                continue

            if transfer["direction"] == "RECEIVED":

                received.append(
                    transfer
                )

            elif transfer["direction"] == "SENT":

                sent.append(
                    transfer
                )

        if not received or not sent:
            continue

        found += 1

        usd_value = calculate_usd_value(
            sent,
            received
        )

        # BUY / SELL belirle ve veritabanına kaydet
        if usd_value is not None:

            usdc_sent = next(
                (
                    item for item in sent
                    if item["token"].lower() == USDC_ADDRESS
                ),
                None
            )

            usdc_received = next(
                (
                    item for item in received
                    if item["token"].lower() == USDC_ADDRESS
                ),
                None
            )

            if usdc_sent and not usdc_received:

                side = "BUY"

                token_items = [
                    item for item in received
                    if item["token"].lower() != USDC_ADDRESS
                ]

            elif usdc_received and not usdc_sent:

                side = "SELL"

                token_items = [
                    item for item in sent
                    if item["token"].lower() != USDC_ADDRESS
                ]

            else:

                side = None
                token_items = []

            if side:

                context = tx_context[tx_hash]

                for item in token_items:

                    trade = {
                        "tx_hash": tx_hash,
                        "block_number": context["block_number"],
                        "timestamp": context["timestamp"],
                        "trader": wallet.lower(),
                        "token": item["token"],
                        "symbol": item["symbol"],
                        "side": side,
                        "amount_usd": usd_value,
                        "token_amount": item["amount"]
                    }

                    if save_trade(trade):

                        update_wallet(trade)

                        print(
                            "DB KAYDI:",
                            side,
                            item["symbol"],
                            "|",
                            usd_value,
                            "USD"
                        )

                    else:

                        print(
                            "DB'de zaten var:",
                            tx_hash
                        )

        print("=" * 70)

        print(
            "SWAP:",
            tx_hash
        )

        print(
            "WALLET:",
            wallet
        )

        if usd_value is not None:

            print(
                "USD DEĞERİ:",
                usd_value
            )

        else:

            print(
                "USD DEĞERİ: Hesaplanamadı"
            )

        print()
        print(
            "GÖNDERİLEN TOKENLAR:"
        )

        for item in sent:

            print(
                item["symbol"],
                "|",
                item["name"],
                "| miktar:",
                item["amount"],
                "| decimals:",
                item["decimals"],
                "|",
                item["token"]
            )

        print()
        print(
            "ALINAN TOKENLAR:"
        )

        for item in received:

            print(
                item["symbol"],
                "|",
                item["name"],
                "| miktar:",
                item["amount"],
                "| decimals:",
                item["decimals"],
                "|",
                item["token"]
            )

        if found >= 5:
            break

    print("=" * 70)

    print(
        "Analiz edilen swap:",
        found
    )

    print()
    print(
        "USD değer testi tamamlandı."
    )


if __name__ == "__main__":

    main()
