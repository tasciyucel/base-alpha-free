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

    print()

    for log in logs[:10]:

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

        print(
            "Token:",
            token
        )

        print(
            "From:",
            sender
        )

        print(
            "To:",
            receiver
        )

        print(
            "Tx:",
            log.get("transactionHash")
        )

        print("-" * 60)

    print()
    print(
        "Token transfer taraması başarılı."
    )


if __name__ == "__main__":
    main()
