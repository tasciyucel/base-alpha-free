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

        raise RuntimeError(
            data["error"]
        )

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


def is_eoa(address):

    code = rpc(
        "eth_getCode",
        [
            address,
            "latest"
        ]
    )

    return code == "0x"


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
        "Bu bloktaki transaction:",
        len(transactions)
    )

    eoa_count = 0

    checked = set()

    for tx in transactions:

        sender = tx.get("from")

        if not sender:
            continue

        sender = sender.lower()

        if sender in checked:
            continue

        checked.add(sender)

        try:

            if is_eoa(sender):

                eoa_count += 1

                print(
                    "EOA:",
                    sender
                )

        except Exception as error:

            print(
                "EOA kontrol hatası:",
                error
            )

    print()
    print(
        "Kontrol edilen farklı adres:",
        len(checked)
    )

    print(
        "Bulunan EOA:",
        eoa_count
    )

    print()
    print(
        "Test tamamlandı."
    )


if __name__ == "__main__":

    main()
