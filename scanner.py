import requests

from config import BASE_RPC_URL

from database import (
    init_db,
    save_trade,
    update_wallet,
    get_last_scanned_block,
    save_last_scanned_block
)


USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a9df523b3ef"
)

TOKEN_CACHE = {}


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


def get_transfer_logs(start_block, end_block):

    return rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
            "topics": [
                TRANSFER_TOPIC
            ]
        }]
    )


def get_transaction(tx_hash):

    return rpc(
        "eth_getTransactionByHash",
        [
            tx_hash
        ]
    )


def decode_address(topic):

    return (
        "0x" + topic[-40:]
    ).lower()


def decode_amount(raw_amount, decimals):

    if decimals is None:
        return None

    try:

        return int(
            raw_amount,
            16
        ) / (
            10 ** decimals
        )

    except Exception:

        return None


def decode_abi_string(data):

    try:

        if not data or data == "0x":
            return ""

        raw = bytes.fromhex(
            data[2:]
        )

        # Normal ABI dynamic string
        if len(raw) >= 96:

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
                    )

        # bytes32 style
        if len(raw) == 32:

            return raw.rstrip(
                b"\x00"
            ).decode(
                "utf-8",
                errors="ignore"
            )

        return ""

    except Exception:

        return ""


def get_token_metadata(token_address):

    token_address = token_address.lower()

    if token_address == USDC_ADDRESS:

        metadata = {
            "decimals": 6,
            "symbol": "USDC",
            "name": "USD Coin"
        }

        TOKEN_CACHE[token_address] = metadata

        return metadata

    if token_address in TOKEN_CACHE:

        return TOKEN_CACHE[token_address]

    try:

        decimals_data = rpc(
            "eth_call",
            [
                {
                    "to": token_address,
                    "data": "0x313ce567"
                },
                "latest"
            ]
        )

        decimals = int(
            decimals_data,
            16
        )

        symbol = ""

        try:

            symbol_data = rpc(
                "eth_call",
                [
                    {
                        "to": token_address,
                        "data": "0x95d89b41"
                    },
                    "latest"
                ]
            )

            symbol = decode_abi_string(
                symbol_data
            )

        except Exception:
            pass

        name = ""

        try:

            name_data = rpc(
                "eth_call",
                [
                    {
                        "to": token_address,
                        "data": "0x06fdde03"
                    },
                    "latest"
                ]
            )

            name = decode_abi_string(
                name_data
            )

        except Exception:
            pass

        metadata = {
            "decimals": decimals,
            "symbol": symbol,
            "name": name
        }

        TOKEN_CACHE[token_address] = metadata

        return metadata

    except Exception as e:

        print(
            "Token metadata alınamadı:",
            token_address,
            e
        )

        metadata = {
            "decimals": None,
            "symbol": "",
            "name": ""
        }

        TOKEN_CACHE[token_address] = metadata

        return metadata


def build_transfer_data(log):

    topics = log.get(
        "topics",
        []
    )

    if len(topics) < 3:
        return None

    if topics[0].lower() != TRANSFER_TOPIC:
        return None

    token_address = log.get(
        "address",
        ""
    ).lower()

    from_address = decode_address(
        topics[1]
    )

    to_address = decode_address(
        topics[2]
    )

    raw_amount = log.get(
        "data",
        "0x0"
    )

    return {
        "token": token_address,
        "from": from_address,
        "to": to_address,
        "raw_amount": raw_amount,
        "block_number": int(
            log["blockNumber"],
            16
        ),
        "tx_hash": log["transactionHash"],
        "log_index": int(
            log["logIndex"],
            16
        )
    }


def analyze_transaction(
    tx_hash,
    transfers,
    block_timestamp
):

    tx = get_transaction(
        tx_hash
    )

    if not tx:
        return False

    trader = tx.get(
        "from",
        ""
    ).lower()

    if not trader:
        return False

    sent_tokens = []
    received_tokens = []

    for transfer in transfers:

        token_address = transfer["token"]

        metadata = get_token_metadata(
            token_address
        )

        amount = decode_amount(
            transfer["raw_amount"],
            metadata["decimals"]
        )

        if amount is None:
            continue

        token_data = {
            "address": token_address,
            "symbol": metadata["symbol"],
            "name": metadata["name"],
            "amount": amount,
            "decimals": metadata["decimals"]
        }

        if transfer["from"] == trader:

            sent_tokens.append(
                token_data
            )

        if transfer["to"] == trader:

            received_tokens.append(
                token_data
            )

    if not sent_tokens and not received_tokens:

        return False

    usd_value = None

    for token in (
        sent_tokens +
        received_tokens
    ):

        if token["address"] == USDC_ADDRESS:

            usd_value = token["amount"]

            break

    # Şimdilik sadece USDC karşılığı olan swapları kaydet.
    if usd_value is None:

        return False

    side = None
    token_symbol = None
    token_address = None
    token_amount = None

    # Önce gönderilen tarafta USDC dışındaki token
    # varsa SELL olarak değerlendir.
    for token in sent_tokens:

        if token["address"] != USDC_ADDRESS:

            side = "SELL"
            token_symbol = token["symbol"]
            token_address = token["address"]
            token_amount = token["amount"]

            break

    # Gönderilen tarafta token yoksa alınan tarafta
    # USDC dışındaki token BUY olarak değerlendirilir.
    if side is None:

        for token in received_tokens:

            if token["address"] != USDC_ADDRESS:

                side = "BUY"
                token_symbol = token["symbol"]
                token_address = token["address"]
                token_amount = token["amount"]

                break

    if side is None:

        return False

    trade = {
        "tx_hash": tx_hash,
        "block_number": int(
            tx.get(
                "blockNumber",
                "0x0"
            ),
            16
        ),
        "timestamp": block_timestamp,
        "trader": trader,
        "token": token_address,
        "symbol": token_symbol,
        "side": side,
        "amount_usd": usd_value,
        "token_amount": token_amount
    }

    saved = save_trade(
        trade
    )

    if saved:

        update_wallet(
            trade
        )

        print(
            f"{side:4} | "
            f"{token_symbol or 'UNKNOWN':12} | "
            f"{usd_value:10.2f} USD | "
            f"{trader}"
        )

    return True


def process_block_range(
    start_block,
    end_block
):

    print()
    print(
        f"Transfer logları taranıyor: "
        f"{start_block} -> {end_block}"
    )

    logs = get_transfer_logs(
        start_block,
        end_block
    )

    print(
        "Bulunan ERC20 Transfer log:",
        len(logs)
    )

    transfers_by_tx = {}

    timestamps = {}

    # Logları transaction bazında grupla.
    for log in logs:

        transfer = build_transfer_data(
            log
        )

        if transfer is None:
            continue

        tx_hash = transfer["tx_hash"]

        if tx_hash not in transfers_by_tx:

            transfers_by_tx[tx_hash] = []

        transfers_by_tx[tx_hash].append(
            transfer
        )

    # Aynı aralıktaki blok zamanlarını almak için
    # blokları ayrıca çekiyoruz.
    block_timestamps = {}

    for block_number in range(
        start_block,
        end_block + 1
    ):

        try:

            result = rpc(
                "eth_getBlockByNumber",
                [
                    hex(block_number),
                    False
                ]
            )

            if result:

                block_timestamps[block_number] = int(
                    result["timestamp"],
                    16
                )

        except Exception as e:

            print(
                "Blok zamanı alınamadı:",
                block_number,
                e
            )

            raise

    analyzed = 0

    for tx_hash, transfers in transfers_by_tx.items():

        if not transfers:
            continue

        block_number = transfers[0][
            "block_number"
        ]

        block_timestamp = block_timestamps.get(
            block_number
        )

        if block_timestamp is None:
            continue

        try:

            if analyze_transaction(
                tx_hash,
                transfers,
                block_timestamp
            ):

                analyzed += 1

        except Exception as e:

            print(
                "Transaction analiz hatası:",
                tx_hash
            )

            print(e)

    return analyzed


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

    last_scanned_block = get_last_scanned_block()

    if last_scanned_block is None:

        start_block = max(
            0,
            latest - 4
        )

        print(
            "İlk çalışma. Son 5 blok taranıyor."
        )

    else:

        start_block = (
            last_scanned_block + 1
        )

        print(
            "Son taranan blok:",
            last_scanned_block
        )

        print(
            "Buradan devam ediliyor:",
            start_block
        )

    if start_block > latest:

        print(
            "Yeni blok yok."
        )

        return

    total_analyzed = 0

    # Büyük aralıkları küçük parçalara böl.
    # Böylece RPC limitlerine takılma ihtimali azalır.
    CHUNK_SIZE = 10

    current_block = start_block

    while current_block <= latest:

        chunk_end = min(
            current_block + CHUNK_SIZE - 1,
            latest
        )

        try:

            analyzed = process_block_range(
                current_block,
                chunk_end
            )

            total_analyzed += analyzed

            # Chunk tamamen başarılıysa state kaydet.
            save_last_scanned_block(
                chunk_end
            )

            print(
                f"Chunk tamamlandı: "
                f"{current_block} -> {chunk_end}"
            )

            print(
                "Son taranan blok kaydedildi:",
                chunk_end
            )

            current_block = (
                chunk_end + 1
            )

        except Exception as e:

            print()
            print(
                "CHUNK HATASI:"
            )

            print(
                f"{current_block} -> {chunk_end}"
            )

            print(e)

            print()
            print(
                "Scanner bu noktada duruyor."
            )

            break

    print()
    print(
        "Toplam analiz edilen swap:",
        total_analyzed
    )

    print()
    print(
        "Scanner tamamlandı."
    )


if __name__ == "__main__":

    main()
