import requests

from config import BASE_RPC_URL
from database import init_db


TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)

UNISWAP_UNIVERSAL_ROUTER = (
    "0x6ff5693b99212da76ad316178a184ab56d299b43"
)

WETH = (
    "0x4200000000000000000000000000000000000006"
)


def rpc(method, params=None):

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

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return data["result"]


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


def decode_string(data):

    if not data or data == "0x":
        return None

    raw = bytes.fromhex(data[2:])

    try:

        # Dynamic ABI string
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
                    ).strip("\x00")

        # bytes32 fallback
        return raw.rstrip(b"\x00").decode(
            "utf-8",
            errors="ignore"
        )

    except Exception:

        return None


def get_token_metadata(token):

    token = token.lower()

    try:

        name_data = eth_call(
            token,
            "0x06fdde03"
        )

        name = decode_string(
            name_data
        )

    except Exception:

        name = None

    try:

        symbol_data = eth_call(
            token,
            "0x95d89b41"
        )

        symbol = decode_string(
            symbol_data
        )

    except Exception:

        symbol = None

    try:

        decimals_data = eth_call(
            token,
            "0x313ce567"
        )

        decimals = int(
            decimals_data,
            16
        )

    except Exception:

        decimals = None

    return {
        "address": token,
        "name": name or "Unknown",
        "symbol": symbol or "UNKNOWN",
        "decimals": decimals
    }


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

    block = get_block(
        latest
    )

    transactions = block.get(
        "transactions",
        []
    )

    print(
        "Transaction sayısı:",
        len(transactions)
    )

    found = 0

    checked_tokens = set()

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

            topics = log.get(
                "topics",
                []
            )

            if len(topics) < 3:
                continue

            if topics[0].lower() != TRANSFER_TOPIC:
                continue

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

            if receiver == wallet.lower():
                received.append(token)

            if sender == wallet.lower():
                sent.append(token)

        tokens = set(
            received + sent
        )

        if not tokens:
            continue

        found += 1

        print("=" * 70)

        print(
            "SWAP:",
            tx_hash
        )

        print(
            "WALLET:",
            wallet
        )

        print()
        print("GÖNDERİLEN TOKENLAR:")

        for token in set(sent):

            if token == WETH:

                print(
                    "WETH",
                    WETH
                )

                continue

            if token not in checked_tokens:

                metadata = get_token_metadata(
                    token
                )

                checked_tokens.add(
                    token
                )

            else:

                metadata = get_token_metadata(
                    token
                )

            print(
                metadata["symbol"],
                "|",
                metadata["name"],
                "|",
                token,
                "| decimals:",
                metadata["decimals"]
            )

        print()
        print("ALINAN TOKENLAR:")

        for token in set(received):

            if token == WETH:

                print(
                    "WETH",
                    WETH
                )

                continue

            if token not in checked_tokens:

                metadata = get_token_metadata(
                    token
                )

                checked_tokens.add(
                    token
                )

            else:

                metadata = get_token_metadata(
                    token
                )

            print(
                metadata["symbol"],
                "|",
                metadata["name"],
                "|",
                token,
                "| decimals:",
                metadata["decimals"]
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
        "Token metadata testi tamamlandı."
    )


if __name__ == "__main__":
    main()
