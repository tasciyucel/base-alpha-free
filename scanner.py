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


def get_transfer_logs(block_number):

    return rpc(
        "eth_getLogs",
        [
            {
                "fromBlock": hex(block_number),
                "toBlock": hex(block_number),
                "topics": [
                    TRANSFER_TOPIC
                ]
            }
        ]
    )


def topic_to_address(topic):

    return "0x" + topic[-40:]


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

    print("Base Alpha Scanner başlıyor...")

    init_db()

    latest = get_latest_block()

    print(
        "Base latest block:",
        latest
    )

    logs = get_transfer_logs(latest)

    print(
        "Transfer event sayısı:",
        len(logs)
    )

    checked = set()
    eoa_count = 0

    print()

    for log in logs:

        topics = log.get("topics", [])

        if len(topics) < 3:
            continue

        token = log.get("address")

        sender = topic_to_address(
            topics[1]
        )

        receiver = topic_to_address(
            topics[2]
        )

        for address in [sender, receiver]:

            address = address.lower()

            if address in checked:
                continue

            checked.add(address)

            try:

                if is_eoa(address):

                    eoa_count += 1

                    print(
                        "EOA:",
                        address
                    )

                    print(
                        "Token:",
                        token
                    )

                    print()

            except Exception as error:

                print(
                    "EOA kontrol hatası:",
                    error
                )

    print(
        "Kontrol edilen adres:",
        len(checked)
    )

    print(
        "Bulunan EOA:",
        eoa_count
    )

    print()
    print(
        "EOA kontrolü başarılı."
    )


if __name__ == "__main__":
    main()
