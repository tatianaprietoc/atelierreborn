import os

import psycopg2
import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

DATABASE_URL = os.environ.get("DATABASE_URL")


class Connection:
    """Thin wrapper so the rest of the app can keep calling conn.execute(...)
    with '?' placeholders, like it did against sqlite3, while actually
    talking to Postgres (needed for Vercel: serverless functions have no
    persistent local disk, so SQLite can't be used there)."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        cur.close()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_connection():
    pg_conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return Connection(pg_conn)


def init_db():
    conn = get_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def total_stock(conn, sku):
    row = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) AS total FROM stock WHERE product_sku = ?", (sku,)
    ).fetchone()
    return row["total"] if row else 0


def stock_status(total, min_stock):
    if total <= 0:
        return {"tone": "danger", "label": "Sin stock"}
    if min_stock is not None and total <= min_stock:
        return {"tone": "warning", "label": "Bajo mínimo"}
    return {"tone": "success", "label": "Disponible"}


def stock_by_location(conn, sku):
    rows = conn.execute(
        """
        SELECT l.id, l.name, l.type, COALESCE(s.qty, 0) AS qty
        FROM locations l
        LEFT JOIN stock s ON s.location_id = l.id AND s.product_sku = ?
        ORDER BY l.type, l.name
        """,
        (sku,),
    ).fetchall()
    return rows


def get_stock_qty(conn, sku, location_id):
    row = conn.execute(
        "SELECT qty FROM stock WHERE product_sku = ? AND location_id = ?",
        (sku, location_id),
    ).fetchone()
    return row["qty"] if row else 0


def set_stock_qty(conn, sku, location_id, qty):
    conn.execute(
        """
        INSERT INTO stock (product_sku, location_id, qty) VALUES (?, ?, ?)
        ON CONFLICT(product_sku, location_id) DO UPDATE SET qty = excluded.qty
        """,
        (sku, location_id, qty),
    )


def adjust_stock_qty(conn, sku, location_id, delta):
    current = get_stock_qty(conn, sku, location_id)
    set_stock_qty(conn, sku, location_id, current + delta)
