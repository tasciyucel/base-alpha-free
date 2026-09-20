import requests

from config import BASE_RPC_URL
from database import (
    init_db,
    get_last_scanned_block,
    save_last_scanned_block
)


USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a9df523b3ef"
)

CHUNK_SIZE = 10

BACKFILL_START = 51569194
BACKFILL_END = 51569821


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


def get_latest_block():

    result = rpc(
        "eth_blockNumber",
        []
    )

    return int(result, 16)


def get_usdc_logs(start_block, end_block):

    print(
        f"USDC logları aranıyor: "
        f"{start_block} -> {end_block}"
    )

    return rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
            "address": USDC_ADDRESS
        }]
    )


def parse_transfer_log(log):

    topics = log.get(
        "topics",
        []
    )

    if len(topics) < 3:
        return None

    topic0 = topics[0].lower()

    if topic0 != TRANSFER_TOPIC:
        return None

    return {
        "tx_hash": log.get("transactionHash"),
        "block_number": int(
            log["blockNumber"],
            16
        ),
        "log_index": int(
            log["logIndex"],
            16
        )
    }


def process_block_range(start_block, end_block):

    logs = get_usdc_logs(
        start_block,
        end_block
    )

    # SADECE İLK LOGU GÖSTER
    if logs:

        print()
        print("========== İLK USDC LOG ==========")
        print(logs[0])
        print("==================================")

        print()
        print("İLK LOG TOPICS:")

        for index, topic in enumerate(
            logs[0].get("topics", [])
        ):

            print(
                f"topics[{index}]:",
                topic
            )

        print()

        print(
            "Beklenen Transfer topic:",
            TRANSFER_TOPIC
        )

        print()

        if logs[0].get("topics"):

            print(
                "İlk topic eşleşiyor mu?:",
                logs[0]["topics"][0].lower()
                == TRANSFER_TOPIC
            )

    print()
    print(
        "Toplam USDC log:",
        len(logs)
    )

    transfer_count = 0

    for log in logs:

        transfer = parse_transfer_log(
            log
        )

        if transfer:

            transfer_count += 1

    print(
        "USDC Transfer log:",
        transfer_count
    )

    return 0


def main():

    init_db()

    latest = get_latest_block()

    print()
    print("====================================")
    print("BASE ALPHA SCANNER")
    print("Latest block:", latest)
    print("====================================")

    last_scanned = get_last_scanned_block()

    if last_scanned is not None:

        if (
            last_scanned >= BACKFILL_START
            and
            last_scanned <= BACKFILL_END
        ):

            start_block = BACKFILL_START

            print(
                "BACKFILL aktif:",
                BACKFILL_START,
                "->",
                BACKFILL_END
            )

        elif last_scanned < BACKFILL_START:

            start_block = BACKFILL_START

        else:

            start_block = last_scanned + 1

    else:

        start_block = BACKFILL_START

    if start_block <= BACKFILL_END:

        scan_end = min(
            BACKFILL_END,
            latest
        )

    else:

        scan_end = latest

    print(
        "Tarama başlangıcı:",
        start_block
    )

    print(
        "Tarama bitişi:",
        scan_end
    )

    current = start_block

    total_analyzed = 0

    while current <= scan_end:

        chunk_end = min(
            current + CHUNK_SIZE - 1,
            scan_end
        )

        print()
        print("------------------------------------")
        print(
            "Chunk:",
            current,
            "->",
            chunk_end
        )

        try:

            analyzed = process_block_range(
                current,
                chunk_end
            )

            total_analyzed += analyzed

            save_last_scanned_block(
                chunk_end
            )

            print(
                "Chunk tamamlandı."
            )

            current = chunk_end + 1

        except Exception as error:

            print(
                "CHUNK HATASI:",
                error
            )

            break

    print()
    print("====================================")
    print(
        "Toplam analiz edilen swap:",
        total_analyzed
    )
    print("====================================")


if __name__ == "__main__":
    main()
