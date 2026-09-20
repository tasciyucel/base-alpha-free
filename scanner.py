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


def main():

    print("Base Alpha Scanner başlıyor...")

    init_db()

    latest = get_latest_block()

    print("Base latest block:", latest)

    block = get_block(latest)

    transactions = block.get(
        "transactions",
        []
    )

    print(
        "Transaction sayısı:",
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

            topics = log.get("topics", [])

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

        if not received or not sent:
            continue

        found += 1

        print("=" * 70)

        print("MUHTEMEL SWAP")
        print("Transaction:", tx_hash)
        print("Wallet:", wallet)

        print()
        print("GÖNDERİLEN:")

        for token in set(sent):

            if token == WETH:
                print("WETH")
            else:
                print(token)

        print()
        print("ALINAN:")

        for token in set(received):

            if token == WETH:
                print("WETH")
            else:
                print(token)

        non_weth_received = [
            token
            for token in set(received)
            if token != WETH
        ]

        non_weth_sent = [
            token
            for token in set(sent)
            if token != WETH
        ]

        if non_weth_received and WETH in sent:

            print()
            print("SONUÇ: MUHTEMEL BUY")

        elif non_weth_sent and WETH in received:

            print()
            print("SONUÇ: MUHTEMEL SELL")

        else:

            print()
            print("SONUÇ: TOKEN-TOKEN veya KARMA SWAP")

        if found >= 5:
            break

    print("=" * 70)

    print(
        "Analiz edilen swap:",
        found
    )

    print()
    print(
        "BUY/SELL yön analizi tamamlandı."
    )


if __name__ == "__main__":
    main()
