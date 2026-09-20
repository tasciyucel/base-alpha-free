import sqlite3

DB_PATH = "alpha.db"


def main():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            address,
            trades,
            buys,
            sells,
            buy_usd,
            sell_usd,
            first_seen,
            last_seen
        FROM wallets
        ORDER BY trades DESC
        LIMIT 20
    """)

    wallets = cur.fetchall()

    print()
    print("=" * 100)
    print("WALLET İSTATİSTİKLERİ")
    print("=" * 100)

    if not wallets:

        print("Henüz wallet verisi yok.")

        db.close()
        return

    for wallet in wallets:

        (
            address,
            trades,
            buys,
            sells,
            buy_usd,
            sell_usd,
            first_seen,
            last_seen
        ) = wallet

        print()
        print("WALLET:", address)
        print("İşlem sayısı:", trades)
        print("BUY:", buys)
        print("SELL:", sells)
        print("Toplam BUY USD:", buy_usd)
        print("Toplam SELL USD:", sell_usd)
        print("İlk görülme:", first_seen)
        print("Son görülme:", last_seen)

    print()
    print("=" * 100)

    db.close()


if __name__ == "__main__":
    main()
