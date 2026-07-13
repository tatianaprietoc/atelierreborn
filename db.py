import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "inventario.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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
