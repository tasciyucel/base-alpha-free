import time
import requests

from config import BASE_RPC_URL
from database import init_db


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

    block = rpc(
        "eth_blockNumber"
    )

    return int(
        block,
        16
    )


def get_block(block_number):

    return rpc(
        "eth_getBlockByNumber",
        [
            hex(block_number),
            True
        ]
    )


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
        "Blok:",
        latest
    )

    print(
        "Transaction sayısı:",
        len(transactions)
    )

    print()
    print(
        "İlk transactionlar:"
    )

    for tx in transactions[:10]:

        print(
            tx.get("hash"),
            "|",
            tx.get("from"),
            "→",
            tx.get("to")
        )

    print()
    print(
        "Blockchain bağlantı testi başarılı."
    )


if __name__ == "__main__":
    main()
