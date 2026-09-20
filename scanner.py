import requests

from config import BASE_RPC_URL
from database import init_db


TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
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


def topic_to_address(topic):

    return "0x" + topic[-40:]


def get_transaction_receipt(tx_hash):

    return rpc(
        "eth_getTransactionReceipt",
        [tx_hash]
    )


def main():

    print("Base Alpha Scanner başlıyor...")

    init_db()

    latest = get_latest_block()

    print(
        "Base latest block:",
        latest
    )

    block = get_block(latest)

    transactions = block.get(
        "transactions",
        []
    )

    print(
        "Transaction sayısı:",
        len(transactions)
    )

    print()

    found = 0

    for tx in transactions:

        tx_hash = tx.get("hash")

        if not tx_hash:
            continue

        receipt = get_transaction_receipt(
            tx_hash
        )

        logs = receipt.get(
            "logs",
            []
        )

        transfers = []

        for log in logs:

            topics = log.get(
                "topics",
                []
            )

            if len(topics) < 3:
                continue

            if topics[0].lower() != TRANSFER_TOPIC:
                continue

            transfers.append({

                "token": log.get("address"),

                "from": topic_to_address(
                    topics[1]
                ),

                "to": topic_to_address(
                    topics[2]
                ),

                "tx_hash": tx_hash

            })

        if not transfers:
            continue

        found += 1

        print("=" * 70)

        print(
            "Transaction:",
            tx_hash
        )

        print(
            "Cüzdan:",
            tx.get("from")
        )

        print(
            "Token hareketleri:",
            len(transfers)
        )

        for transfer in transfers[:5]:

            print(
                "Token:",
                transfer["token"]
            )

            print(
                "From:",
                transfer["from"]
            )

            print(
                "To:",
                transfer["to"]
            )

            print()

        if found >= 10:
            break

    print("=" * 70)

    print(
        "İncelenen token işlem örneği:",
        found
    )

    print()
    print(
        "Transaction → Token ilişkisi başarıyla okundu."
    )


if __name__ == "__main__":
    main()
