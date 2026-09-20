import sqlite3
from pathlib import Path

DB_PATH = Path("alpha.db")


def connect():
    return sqlite3.connect(DB_PATH)


def init_db():

    db = connect()

    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tx_hash TEXT UNIQUE,

            block_number INTEGER,

            timestamp INTEGER,

            trader TEXT,

            token TEXT,

            symbol TEXT,

            side TEXT,

            amount_usd REAL

        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallets (

            address TEXT PRIMARY KEY,

            trades INTEGER DEFAULT 0,

            buys INTEGER DEFAULT 0,

            sells INTEGER DEFAULT 0,

            buy_usd REAL DEFAULT 0,

            sell_usd REAL DEFAULT 0,

            first_seen INTEGER,

            last_seen INTEGER

        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            token TEXT,

            symbol TEXT,

            score INTEGER,

            timestamp INTEGER,

            UNIQUE(token, timestamp)

        )
    """)

    db.commit()
    db.close()


def save_trade(trade):

    db = connect()

    cur = db.cursor()

    try:

        cur.execute("""
            INSERT INTO trades (

                tx_hash,
                block_number,
                timestamp,
                trader,
                token,
                symbol,
                side,
                amount_usd

            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        """, (

            trade["tx_hash"],
            trade["block_number"],
            trade["timestamp"],
            trade["trader"],
            trade["token"],
            trade["symbol"],
            trade["side"],
            trade["amount_usd"]

        ))

        db.commit()

    except sqlite3.IntegrityError:
        pass

    db.close()


def update_wallet(trade):

    db = connect()

    cur = db.cursor()

    address = trade["trader"]

    cur.execute("""
        INSERT INTO wallets (

            address,
            trades,
            buys,
            sells,
            buy_usd,
            sell_usd,
            first_seen,
            last_seen

        )

        VALUES (?, 1, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(address)

        DO UPDATE SET

            trades =
                trades + 1,

            buys =
                buys + excluded.buys,

            sells =
                sells + excluded.sells,

            buy_usd =
                buy_usd + excluded.buy_usd,

            sell_usd =
                sell_usd + excluded.sell_usd,

            last_seen =
                excluded.last_seen

    """, (

        address,

        1 if trade["side"] == "BUY" else 0,

        1 if trade["side"] == "SELL" else 0,

        trade["amount_usd"]
        if trade["side"] == "BUY"
        else 0,

        trade["amount_usd"]
        if trade["side"] == "SELL"
        else 0,

        trade["timestamp"],

        trade["timestamp"]

    ))

    db.commit()
    db.close()
