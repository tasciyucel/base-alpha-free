import requests
import time

from config import BASE_RPC_URL

from database import (
    init_db,
    save_trade,
    update_wallet,
    get_last_scanned_block,
    save_last_scanned_block
)


USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

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
        [
            tx_hash
        ]
    )


def get_token_metadata(token_address):

    token_address = token_address.lower()

    if token_address == USDC_ADDRESS:
        TOKEN_CACHE[token_address] = {
            "decimals": 6,
            "symbol": "USDC",
            "name": "USD Coin"
        }

        return TOKEN_CACHE[token_address]

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

        symbol_hex = symbol_data[2:]

        symbol_bytes = bytes.fromhex(symbol_hex)

        symbol = symbol_bytes.rstrip(
            b"\x00"
        ).decode(
            "utf-8",
            errors="ignore"
        )

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

        name = ""

        try:

            name_hex = name_data[2:]

            name_bytes = bytes.fromhex(
                name_hex
            )

            name = name_bytes.rstrip(
                b"\x00"
            ).decode(
                "utf-8",
                errors="ignore"
            )

        except Exception:
            name = ""

        TOKEN_CACHE[token_address] = {
            "decimals": decimals,
            "symbol": symbol,
            "name": name
        }

        print(
            f"DECIMALS: {token_address} => {decimals}"
        )

        return TOKEN_CACHE[token_address]

    except Exception as e:

        print(
            f"Token metadata alınamadı: {token_address}"
        )

        print(e)

        return {
            "decimals": None,
            "symbol": "",
            "name": ""
        }


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


def calculate_usd_value(sent_tokens, received_tokens):

    for token in sent_tokens + received_tokens:

        if token["address"].lower() == USDC_ADDRESS:

            return token["amount"]

    return None


def print_token_list(title, tokens):

    print(title)

    for token in tokens:

        amount_text = token["amount"]

        print(
            f'{token["symbol"]} | '
            f'{token["name"]} | '
            f'miktar: {amount_text} | '
            f'decimals: {token["decimals"]} | '
            f'{token["address"]}'
        )


def analyze_transaction(tx, block_timestamp):

    tx_hash = tx["hash"]

    receipt = get_transaction_receipt(
        tx_hash
    )

    logs = receipt.get(
        "logs",
        []
    )

    sent_tokens = []
    received_tokens = []

    trader = tx.get(
        "from",
        ""
    ).lower()

    for log in logs:

        topics = log.get(
            "topics",
            []
        )

        if len(topics) < 3:
            continue

        if topics[0].lower() != (
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a9df523b3ef"
        ):
            continue

        token_address = log.get(
            "address",
            ""
        ).lower()

        from_address = (
            "0x" + topics[1][-40:]
        ).lower()

        to_address = (
            "0x" + topics[2][-40:]
        ).lower()

        raw_amount = log.get(
            "data",
            "0x0"
        )

        metadata = get_token_metadata(
            token_address
        )

        decimals = metadata["decimals"]

        amount = decode_amount(
            raw_amount,
            decimals
        )

        if amount is None:
            continue

        token_data = {
            "address": token_address,
            "symbol": metadata["symbol"],
            "name": metadata["name"],
            "amount": amount,
            "decimals": decimals
        }

        if from_address == trader:

            sent_tokens.append(
                token_data
            )

        if to_address == trader:

            received_tokens.append(
                token_data
            )

    if not sent_tokens and not received_tokens:
        return False

    usd_value = calculate_usd_value(
        sent_tokens,
        received_tokens
    )

    print()
    print("=" * 70)

    print(
        "SWAP:",
        tx_hash
    )

    print(
        "WALLET:",
        trader
    )

    if usd_value is None:

        print(
            "USD DEĞERİ: Hesaplanamadı"
        )

    else:

        print(
            "USD DEĞERİ:",
            usd_value
        )

    print_token_list(
        "GÖNDERİLEN TOKENLAR:",
        sent_tokens
    )

    print_token_list(
        "ALINAN TOKENLAR:",
        received_tokens
    )

    if usd_value is None:

        return True

    side = None
    token_symbol = None
    token_address = None
    token_amount = None

    if sent_tokens:

        for token in sent_tokens:

            if token["address"].lower() != USDC_ADDRESS:

                side = "SELL"
                token_symbol = token["symbol"]
                token_address = token["address"]
                token_amount = token["amount"]

                break

    if received_tokens and side is None:

        for token in received_tokens:

            if token["address"].lower() != USDC_ADDRESS:

                side = "BUY"
                token_symbol = token["symbol"]
                token_address = token["address"]
                token_amount = token["amount"]

                break

    if side is None:

        return True

    trade = {
        "tx_hash": tx_hash,
        "block_number": int(
            tx["blockNumber"],
            16
        ) if tx.get("blockNumber") else 0,
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
            f"DB KAYDI: {side} {token_symbol} | {usd_value:.6f} USD"
        )

    return True


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

        print()
        print(
            "İlk çalışma. Son 5 blok taranıyor."
        )

    else:

        start_block = (
            last_scanned_block + 1
        )

        print()
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

    total_transactions = 0
    analyzed_swaps = 0

    last_completed_block = (
        last_scanned_block
    )

    for block_number in range(
        start_block,
        latest + 1
    ):

        print()
        print(
            "Blok taranıyor:",
            block_number
        )

        try:

            block = get_block(
                block_number
            )

            transactions = block.get(
                "transactions",
                []
            )

            total_transactions += len(
                transactions
            )

            block_timestamp = int(
                block["timestamp"],
                16
            )

            for tx in transactions:

                try:

                    result = analyze_transaction(
                        tx,
                        block_timestamp
                    )

                    if result:
                        analyzed_swaps += 1

                except Exception as e:

                    print()
                    print(
                        "Transaction analiz hatası:"
                    )

                    print(
                        tx.get(
                            "hash",
                            ""
                        )
                    )

                    print(e)

            # BU BLOĞUN TAMAMI BAŞARIYLA İŞLENDİ
            last_completed_block = (
                block_number
            )

        except Exception as e:

            print()
            print(
                "BLOK HATASI:",
                block_number
            )

            print(e)

            print()
            print(
                "Bu noktada scanner duruyor."
            )

            print(
                "Son tamamlanan blok:",
                last_completed_block
            )

            break

    print()
    print(
        "Toplam transaction sayısı:",
        total_transactions
    )

    print()
    print(
        "Analiz edilen swap:",
        analyzed_swaps
    )

    if last_completed_block is not None:

        save_last_scanned_block(
            last_completed_block
        )

        print()
        print(
            "Son tamamlanan blok kaydedildi:",
            last_completed_block
        )

    print()
    print(
        "USD değer testi tamamlandı."
    )


if __name__ == "__main__":

    main()
