import requests
import time

from config import BASE_RPC_URL


TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

USDC_ADDRESS = (
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
)

CHUNK_SIZE = 2


def rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    for attempt in range(6):

        try:
            response = requests.post(
                BASE_RPC_URL,
                json=payload,
                timeout=30,
            )

            if response.status_code == 429:

                wait = 2 * (attempt + 1)

                print(
                    f"429 - {wait} saniye bekleniyor..."
                )

                time.sleep(wait)
                continue

            response.raise_for_status()

            data = response.json()

            if "error" in data:

                print(
                    "RPC ERROR:",
                    data["error"]
                )

                if data["error"].get("code") == 429:

                    wait = 2 * (attempt + 1)

                    time.sleep(wait)
                    continue

                return None

            return data.get("result")

        except Exception as exc:

            print(
                "RPC exception:",
                exc
            )

            time.sleep(
                2 * (attempt + 1)
            )

    return None


def hex_to_int(value):

    if value is None:
        return 0

    if isinstance(value, int):
        return value

    return int(value, 16)


def get_latest_block():

    result = rpc(
        "eth_blockNumber",
        [],
    )

    return hex_to_int(result)


def get_logs(
    from_block,
    to_block,
    address=None,
):

    params = {
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "topics": [
            TRANSFER_TOPIC
        ],
    }

    if address:
        params["address"] = address

    return rpc(
        "eth_getLogs",
        [params],
    )


def main():

    print("=" * 100)
    print("ERC20 LOG TEST")
    print("=" * 100)

    print(
        "RPC:",
        BASE_RPC_URL
    )

    latest = get_latest_block()

    print(
        "Latest block:",
        latest
    )

    # Sadece son 2 blok test ediliyor.
    start = latest - CHUNK_SIZE + 1

    print(
        f"Test aralığı: {start} -> {latest}"
    )

    print()
    print("1) SADECE USDC TRANSFERLERİ")
    print("-" * 60)

    start_time = time.time()

    usdc_logs = get_logs(
        start,
        latest,
        USDC_ADDRESS,
    )

    elapsed = time.time() - start_time

    if usdc_logs is None:

        print(
            "USDC logları alınamadı."
        )

    else:

        print(
            "USDC log sayısı:",
            len(usdc_logs)
        )

    print(
        f"Süre: {elapsed:.2f} saniye"
    )

    print()
    print("2) TÜM ERC20 TRANSFERLERİ")
    print("-" * 60)

    start_time = time.time()

    all_logs = get_logs(
        start,
        latest,
    )

    elapsed = time.time() - start_time

    if all_logs is None:

        print(
            "ERC20 logları alınamadı."
        )

    else:

        print(
            "Tüm ERC20 Transfer log sayısı:",
            len(all_logs)
        )

    print(
        f"Süre: {elapsed:.2f} saniye"
    )

    print()
    print("=" * 100)
    print("TEST SONUCU")
    print("=" * 100)

    if usdc_logs is not None:
        print(
            "USDC:",
            len(usdc_logs)
        )

    if all_logs is not None:
        print(
            "Tüm ERC20:",
            len(all_logs)
        )

    if (
        usdc_logs is not None
        and all_logs is not None
    ):

        if len(usdc_logs) > 0:

            ratio = (
                len(all_logs)
                / len(usdc_logs)
            )

            print(
                f"ERC20 / USDC oranı: "
                f"{ratio:.2f}x"
            )

    print("=" * 100)


if __name__ == "__main__":
    main()
