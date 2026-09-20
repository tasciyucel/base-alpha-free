import sqlite3
from pathlib import Path


DB_PATH = Path("alpha.db")


def connect():
    return sqlite3.connect(DB_PATH)


def init_db():

    db = connect()
    cur = db.cursor()

    # ========================================================
    # TRADES
    # ========================================================

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
            amount_usd REAL,
            token_amount REAL DEFAULT 0
        )
    """)

    cur.execute("""
        PRAGMA table_info(trades)
    """)

    columns = [
        row[1]
        for row in cur.fetchall()
    ]

    if "token_amount" not in columns:

        cur.execute("""
            ALTER TABLE trades
            ADD COLUMN token_amount REAL DEFAULT 0
        """)

    # ========================================================
    # WALLETS
    # ========================================================

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

    # ========================================================
    # ALERTS
    # ========================================================

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

    # ========================================================
    # SCANNER STATE
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scanner_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # ========================================================
    # TOKEN METADATA
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS token_metadata (
            address TEXT PRIMARY KEY,
            symbol TEXT,
            name TEXT,
            decimals INTEGER
        )
    """)

    db.commit()
    db.close()


# ============================================================
# TRADE
# ============================================================

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
                amount_usd,
                token_amount
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
            trade["amount_usd"],
            trade["token_amount"]
        ))

        db.commit()

        return True

    except sqlite3.IntegrityError:

        return False

    finally:

        db.close()


# ============================================================
# WALLET
# ============================================================

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

            first_seen =
                MIN(first_seen, excluded.first_seen),

            last_seen =
                MAX(last_seen, excluded.last_seen)
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


# ============================================================
# TOKEN METADATA
# ============================================================

def get_token_metadata(address):

    db = connect()
    cur = db.cursor()

    cur.execute("""
        SELECT
            symbol,
            name,
            decimals
        FROM token_metadata
        WHERE address = ?
    """, (
        address.lower(),
    ))

    row = cur.fetchone()

    db.close()

    if row is None:
        return None

    return {
        "symbol": row[0] or "",
        "name": row[1] or "",
        "decimals": row[2]
    }


def save_token_metadata(
    address,
    symbol,
    name,
    decimals
):

    db = connect()
    cur = db.cursor()

    cur.execute("""
        INSERT INTO token_metadata (
            address,
            symbol,
            name,
            decimals
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(address)
        DO UPDATE SET

            symbol =
                excluded.symbol,

            name =
                excluded.name,

            decimals =
                excluded.decimals
    """, (
        address.lower(),
        symbol or "",
        name or "",
        decimals
    ))

    db.commit()
    db.close()


# ============================================================
# SCANNER STATE
# ============================================================

def get_last_scanned_block():

    db = connect()
    cur = db.cursor()

    cur.execute("""
        SELECT value
        FROM scanner_state
        WHERE key = 'last_scanned_block'
    """)

    row = cur.fetchone()

    db.close()

    if row is None:
        return None

    return int(row[0])


def save_last_scanned_block(block_number):

    db = connect()
    cur = db.cursor()

    cur.execute("""
        INSERT INTO scanner_state (
            key,
            value
        )
        VALUES (
            'last_scanned_block',
            ?
        )

        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value
    """, (
        str(block_number),
    ))

    db.commit()
    db.close()
