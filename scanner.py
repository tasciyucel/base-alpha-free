import requests

from config import BASE_RPC_URL
from database import init_db


USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


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


def main():

    init_db()

    latest = int(
        rpc("eth_blockNumber", []),
        16
    )

    start = latest - 9

    print()
    print("====================================")
    print("USDC LOG TESTİ")
    print("Blok:", start, "->", latest)
    print("====================================")

    logs = rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(start),
            "toBlock": hex(latest),
            "address": USDC_ADDRESS
        }]
    )

    print()
    print("Toplam log:", len(logs))

    if not logs:
        print("Hiç log bulunamadı.")
        return

    print()
    print("========== İLK LOG ==========")
    print(logs[0])
    print("==============================")

    print()
    print("TOPICS:")

    for i, topic in enumerate(
        logs[0].get("topics", [])
    ):
        print(
            f"topics[{i}]: {topic}"
        )


if __name__ == "__main__":
    main()
