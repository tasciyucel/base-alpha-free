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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
