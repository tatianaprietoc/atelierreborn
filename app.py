import base64
import csv
import io
import os
import uuid
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, abort,
)

import db

APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
# Toggle for sharing the app during testing without asking anyone for a password.
# Set REQUIRE_PASSWORD=true to re-enable the login screen.
REQUIRE_PASSWORD = os.environ.get("REQUIRE_PASSWORD", "false").lower() == "true"

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB uploads

# In-memory cache for parsed CSV import previews, keyed by uuid.
# Single-process dev server, single owner-user — no need for persistence here.
IMPORT_CACHE = {}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if REQUIRE_PASSWORD and not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if not REQUIRE_PASSWORD:
        return redirect(url_for("existencias"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("existencias"))
        flash("Contraseña incorrecta.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("existencias"))


# ---------------------------------------------------------------------------
# Existencias
# ---------------------------------------------------------------------------

@app.route("/existencias")
@login_required
def existencias():
    conn = db.get_connection()
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    locations = conn.execute("SELECT * FROM locations ORDER BY type, name").fetchall()

    product_rows = []
    alert_count = 0
    for p in products:
        total = db.total_stock(conn, p["sku"])
        status = db.stock_status(total, p["min_stock"])
        if status["tone"] != "success":
            alert_count += 1
        breakdown = db.stock_by_location(conn, p["sku"])
        product_rows.append({
            "sku": p["sku"], "name": p["name"], "min_stock": p["min_stock"],
            "photo": p["photo"], "total": total, "status": status,
            "breakdown": breakdown,
        })
    conn.close()

    query = request.args.get("q", "").strip()
    return render_template(
        "existencias.html",
        products=product_rows,
        locations=locations,
        alert_count=alert_count,
        query=query,
    )


# ---------------------------------------------------------------------------
# Movimientos
# ---------------------------------------------------------------------------

TYPE_CONFIG = {
    "entrada": {"label": "Entrada", "needs_origin": False, "needs_dest": True},
    "salida": {"label": "Salida", "needs_origin": True, "needs_dest": False},
    "traslado": {"label": "Traslado", "needs_origin": True, "needs_dest": True},
}


@app.route("/movimientos")
@login_required
def movimientos():
    conn = db.get_connection()
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    locations = conn.execute("SELECT * FROM locations ORDER BY type, name").fetchall()
    history = conn.execute(
        """
        SELECT m.*, p.name AS product_name,
               lo.name AS origin_name, ld.name AS dest_name
        FROM movements m
        JOIN products p ON p.sku = m.product_sku
        LEFT JOIN locations lo ON lo.id = m.origin_location_id
        LEFT JOIN locations ld ON ld.id = m.dest_location_id
        ORDER BY m.id DESC
        LIMIT 50
        """
    ).fetchall()
    conn.close()
    active_type = request.args.get("tipo", "traslado")
    if active_type not in TYPE_CONFIG:
        active_type = "traslado"
    return render_template(
        "movimientos.html",
        products=products,
        locations=locations,
        history=history,
        active_type=active_type,
        type_config=TYPE_CONFIG,
    )


@app.route("/movimientos/registrar", methods=["POST"])
@login_required
def registrar_movimiento():
    tipo = request.form.get("tipo")
    if tipo not in TYPE_CONFIG:
        abort(400)
    cfg = TYPE_CONFIG[tipo]
    sku = request.form.get("sku", "").strip()
    note = request.form.get("nota", "").strip() or None
    origin_id = request.form.get("origen") or None
    dest_id = request.form.get("destino") or None

    conn = db.get_connection()
    product = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    if not product:
        flash("Selecciona un producto válido.", "danger")
        conn.close()
        return redirect(url_for("movimientos", tipo=tipo))

    try:
        qty = int(request.form.get("cantidad", ""))
        if qty <= 0:
            raise ValueError
    except ValueError:
        flash("La cantidad debe ser un número mayor a 0.", "danger")
        conn.close()
        return redirect(url_for("movimientos", tipo=tipo))

    if cfg["needs_origin"] and not origin_id:
        flash("Selecciona la ubicación de origen.", "danger")
        conn.close()
        return redirect(url_for("movimientos", tipo=tipo))
    if cfg["needs_dest"] and not dest_id:
        flash("Selecciona la ubicación de destino.", "danger")
        conn.close()
        return redirect(url_for("movimientos", tipo=tipo))

    if cfg["needs_origin"]:
        available = db.get_stock_qty(conn, sku, origin_id)
        if qty > available:
            origin = conn.execute("SELECT name FROM locations WHERE id = ?", (origin_id,)).fetchone()
            flash(
                f"Solo hay {available} unidades disponibles en {origin['name']}. "
                "Ajusta el inventario antes de continuar.",
                "danger",
            )
            conn.close()
            return redirect(url_for("movimientos", tipo=tipo))

    if cfg["needs_origin"]:
        db.adjust_stock_qty(conn, sku, origin_id, -qty)
    if cfg["needs_dest"]:
        db.adjust_stock_qty(conn, sku, dest_id, qty)

    conn.execute(
        """
        INSERT INTO movements (type, product_sku, origin_location_id, dest_location_id, qty, note)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tipo, sku, origin_id, dest_id, qty, note),
    )
    conn.commit()
    conn.close()
    flash(f"{cfg['label']} registrada correctamente.", "success")
    return redirect(url_for("movimientos", tipo=tipo))


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

def _encode_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    data = file_storage.read()
    if not data:
        return None
    mime = file_storage.mimetype or "image/jpeg"
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@app.route("/catalogo")
@login_required
def catalogo():
    conn = db.get_connection()
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    locations = conn.execute("SELECT * FROM locations ORDER BY type, name").fetchall()
    rows = []
    for p in products:
        total = db.total_stock(conn, p["sku"])
        status = db.stock_status(total, p["min_stock"])
        rows.append({
            "sku": p["sku"], "name": p["name"], "min_stock": p["min_stock"],
            "photo": p["photo"], "total": total, "status": status,
        })
    conn.close()

    query = request.args.get("q", "").strip()

    preview = None
    import_id = request.args.get("import_id")
    import_kind = request.args.get("import_kind")
    if import_id and import_id in IMPORT_CACHE:
        preview = IMPORT_CACHE[import_id]

    return render_template(
        "catalogo.html",
        products=rows,
        locations=locations,
        query=query,
        preview=preview,
        import_id=import_id,
        import_kind=import_kind,
    )


@app.route("/catalogo/nuevo", methods=["POST"])
@login_required
def catalogo_nuevo():
    sku = request.form.get("sku", "").strip()
    name = request.form.get("name", "").strip()
    min_raw = request.form.get("min_stock", "").strip()
    photo = _encode_photo(request.files.get("photo"))

    conn = db.get_connection()
    if not sku or not name:
        flash("Código y descripción son obligatorios.", "danger")
        conn.close()
        return redirect(url_for("catalogo"))

    min_stock = None
    if min_raw:
        try:
            min_stock = int(min_raw)
            if min_stock < 0:
                raise ValueError
        except ValueError:
            flash("El mínimo debe ser un número mayor o igual a 0.", "danger")
            conn.close()
            return redirect(url_for("catalogo"))

    existing = conn.execute(
        "SELECT * FROM products WHERE LOWER(sku) = LOWER(?)", (sku,)
    ).fetchone()
    if existing:
        flash(
            f'El código {existing["sku"]} ya existe: "{existing["name"]}". '
            "Edítalo en vez de crear un duplicado.",
            "danger",
        )
        conn.close()
        return redirect(url_for("catalogo"))

    conn.execute(
        "INSERT INTO products (sku, name, min_stock, photo) VALUES (?, ?, ?, ?)",
        (sku, name, min_stock, photo),
    )
    locations = conn.execute("SELECT id FROM locations").fetchall()
    for loc in locations:
        db.set_stock_qty(conn, sku, loc["id"], 0)
    conn.commit()
    conn.close()
    flash(f"Producto {sku} creado.", "success")
    return redirect(url_for("catalogo"))


@app.route("/catalogo/editar/<sku>", methods=["POST"])
@login_required
def catalogo_editar(sku):
    conn = db.get_connection()
    product = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    if not product:
        abort(404)

    new_sku = request.form.get("sku", "").strip()
    name = request.form.get("name", "").strip()
    min_raw = request.form.get("min_stock", "").strip()
    remove_photo = request.form.get("remove_photo") == "1"
    uploaded = _encode_photo(request.files.get("photo"))

    if not new_sku or not name:
        flash("Código y descripción son obligatorios.", "danger")
        conn.close()
        return redirect(url_for("catalogo"))

    min_stock = None
    if min_raw:
        try:
            min_stock = int(min_raw)
            if min_stock < 0:
                raise ValueError
        except ValueError:
            flash("El mínimo debe ser un número mayor o igual a 0.", "danger")
            conn.close()
            return redirect(url_for("catalogo"))

    duplicate = conn.execute(
        "SELECT * FROM products WHERE LOWER(sku) = LOWER(?) AND sku != ?",
        (new_sku, sku),
    ).fetchone()
    if duplicate:
        flash(
            f'El código {duplicate["sku"]} ya existe: "{duplicate["name"]}". '
            "Edítalo en vez de crear un duplicado.",
            "danger",
        )
        conn.close()
        return redirect(url_for("catalogo"))

    photo = product["photo"]
    if remove_photo:
        photo = None
    if uploaded:
        photo = uploaded

    if new_sku != sku:
        conn.execute("UPDATE products SET sku = ? WHERE sku = ?", (new_sku, sku))
        conn.execute("UPDATE stock SET product_sku = ? WHERE product_sku = ?", (new_sku, sku))
        conn.execute("UPDATE movements SET product_sku = ? WHERE product_sku = ?", (new_sku, sku))

    conn.execute(
        "UPDATE products SET name = ?, min_stock = ?, photo = ? WHERE sku = ?",
        (name, min_stock, photo, new_sku),
    )
    conn.commit()
    conn.close()
    flash("Cambios guardados.", "success")
    return redirect(url_for("catalogo"))


@app.route("/catalogo/eliminar/<sku>", methods=["POST"])
@login_required
def catalogo_eliminar(sku):
    conn = db.get_connection()
    product = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    if product:
        conn.execute("DELETE FROM products WHERE sku = ?", (sku,))
        conn.commit()
        flash(f"Producto {sku} eliminado.", "success")
    conn.close()
    return redirect(url_for("catalogo"))


# ---------------------------------------------------------------------------
# Importación CSV (catálogo y existencias)
# ---------------------------------------------------------------------------

CATALOG_HEADER_ALIASES = {
    "sku": {"sku", "codigo", "código"},
    "name": {"nombre", "descripcion", "descripción"},
    "min": {"minimo", "mínimo", "stock_minimo", "stock_mínimo"},
}
STOCK_HEADER_ALIASES = {
    "sku": {"sku", "codigo", "código"},
    "location": {"ubicacion", "ubicación", "location"},
    "qty": {"cantidad", "existencia", "existencias", "qty"},
}


def _match_headers(fieldnames, aliases):
    normalized = {(f or "").strip().lower(): f for f in fieldnames or []}
    resolved = {}
    for key, options in aliases.items():
        for opt in options:
            if opt in normalized:
                resolved[key] = normalized[opt]
                break
    return resolved


def _read_csv(file_storage):
    raw = file_storage.read()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


@app.route("/catalogo/importar/preview", methods=["POST"])
@login_required
def catalogo_importar_preview():
    file = request.files.get("archivo")
    if not file or not file.filename:
        flash("Selecciona un archivo CSV para importar.", "danger")
        return redirect(url_for("catalogo"))

    try:
        rows = _read_csv(file)
    except Exception:
        flash("No se pudo leer el archivo. Verifica que sea un CSV válido.", "danger")
        return redirect(url_for("catalogo"))

    if not rows:
        flash("El archivo no tiene filas para importar.", "danger")
        return redirect(url_for("catalogo"))

    resolved = _match_headers(rows[0].keys(), CATALOG_HEADER_ALIASES)
    if "sku" not in resolved or "name" not in resolved:
        flash(
            'El archivo no tiene el formato esperado. Se esperan columnas como '
            '"sku"/"codigo" y "nombre"/"descripcion" (opcional: "minimo").',
            "danger",
        )
        return redirect(url_for("catalogo"))

    conn = db.get_connection()
    existing_skus = {r["sku"].lower() for r in conn.execute("SELECT sku FROM products").fetchall()}
    conn.close()

    seen = set()
    parsed = []
    for row in rows:
        sku = (row.get(resolved["sku"]) or "").strip()
        name = (row.get(resolved["name"]) or "").strip()
        min_raw = (row.get(resolved.get("min", ""), "") or "").strip() if "min" in resolved else ""

        issue = None
        min_stock = None
        if not sku or not name:
            issue = "Columna vacía"
        elif sku.lower() in seen:
            issue = "Código duplicado"
        elif min_raw:
            try:
                min_stock = int(float(min_raw))
                if min_stock < 0:
                    issue = "Mínimo inválido"
            except ValueError:
                issue = "Mínimo no numérico"

        if not issue:
            seen.add(sku.lower())

        parsed.append({
            "sku": sku, "name": name, "min_stock": min_stock,
            "issue": issue, "is_update": sku.lower() in existing_skus,
        })

    import_id = uuid.uuid4().hex
    IMPORT_CACHE[import_id] = {
        "kind": "catalogo",
        "filename": file.filename,
        "rows": parsed,
        "valid_count": sum(1 for r in parsed if not r["issue"]),
        "issue_count": sum(1 for r in parsed if r["issue"]),
    }
    return redirect(url_for("catalogo", import_id=import_id, import_kind="catalogo"))


@app.route("/catalogo/importar/existencias/preview", methods=["POST"])
@login_required
def existencias_importar_preview():
    file = request.files.get("archivo")
    if not file or not file.filename:
        flash("Selecciona un archivo CSV para importar.", "danger")
        return redirect(url_for("catalogo"))

    try:
        rows = _read_csv(file)
    except Exception:
        flash("No se pudo leer el archivo. Verifica que sea un CSV válido.", "danger")
        return redirect(url_for("catalogo"))

    if not rows:
        flash("El archivo no tiene filas para importar.", "danger")
        return redirect(url_for("catalogo"))

    resolved = _match_headers(rows[0].keys(), STOCK_HEADER_ALIASES)
    if not all(k in resolved for k in ("sku", "location", "qty")):
        flash(
            'El archivo no tiene el formato esperado. Se esperan columnas '
            '"sku"/"codigo", "ubicacion" y "cantidad".',
            "danger",
        )
        return redirect(url_for("catalogo"))

    conn = db.get_connection()
    products = {r["sku"].lower(): r["sku"] for r in conn.execute("SELECT sku FROM products").fetchall()}
    locations = {r["name"].lower(): r["id"] for r in conn.execute("SELECT id, name FROM locations").fetchall()}
    conn.close()

    parsed = []
    for row in rows:
        sku = (row.get(resolved["sku"]) or "").strip()
        location_name = (row.get(resolved["location"]) or "").strip()
        qty_raw = (row.get(resolved["qty"]) or "").strip()

        issue = None
        qty = None
        if not sku or not location_name or qty_raw == "":
            issue = "Columna vacía"
        elif sku.lower() not in products:
            issue = "Producto no existe en catálogo"
        elif location_name.lower() not in locations:
            issue = "Ubicación no existe"
        else:
            try:
                qty = int(float(qty_raw))
                if qty < 0:
                    issue = "Cantidad no numérica"
            except ValueError:
                issue = "Cantidad no numérica"

        parsed.append({
            "sku": sku, "location": location_name, "qty": qty, "issue": issue,
            "location_id": locations.get(location_name.lower()),
        })

    import_id = uuid.uuid4().hex
    IMPORT_CACHE[import_id] = {
        "kind": "existencias",
        "filename": file.filename,
        "rows": parsed,
        "valid_count": sum(1 for r in parsed if not r["issue"]),
        "issue_count": sum(1 for r in parsed if r["issue"]),
    }
    return redirect(url_for("catalogo", import_id=import_id, import_kind="existencias"))


@app.route("/catalogo/importar/confirmar", methods=["POST"])
@login_required
def importar_confirmar():
    import_id = request.form.get("import_id")
    cached = IMPORT_CACHE.pop(import_id, None)
    if not cached:
        flash("La vista previa expiró. Vuelve a subir el archivo.", "danger")
        return redirect(url_for("catalogo"))

    conn = db.get_connection()
    if cached["kind"] == "catalogo":
        location_ids = [r["id"] for r in conn.execute("SELECT id FROM locations").fetchall()]
        count = 0
        for row in cached["rows"]:
            if row["issue"]:
                continue
            conn.execute(
                """
                INSERT INTO products (sku, name, min_stock) VALUES (?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET name = excluded.name, min_stock = excluded.min_stock
                """,
                (row["sku"], row["name"], row["min_stock"]),
            )
            for loc_id in location_ids:
                cur = conn.execute(
                    "SELECT 1 FROM stock WHERE product_sku = ? AND location_id = ?",
                    (row["sku"], loc_id),
                ).fetchone()
                if not cur:
                    db.set_stock_qty(conn, row["sku"], loc_id, 0)
            count += 1
        conn.commit()
        flash(f"{count} productos importados desde {cached['filename']}.", "success")
    else:
        count = 0
        for row in cached["rows"]:
            if row["issue"]:
                continue
            db.set_stock_qty(conn, row["sku"], row["location_id"], row["qty"])
            count += 1
        conn.commit()
        flash(f"Existencias actualizadas para {count} filas desde {cached['filename']}.", "success")
    conn.close()
    return redirect(url_for("catalogo"))


# ---------------------------------------------------------------------------
# Ubicaciones
# ---------------------------------------------------------------------------

@app.route("/ubicaciones")
@login_required
def ubicaciones():
    conn = db.get_connection()
    locations = conn.execute("SELECT * FROM locations ORDER BY type, name").fetchall()
    rows = []
    for loc in locations:
        total = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS total FROM stock WHERE location_id = ?", (loc["id"],)
        ).fetchone()["total"]
        rows.append({"id": loc["id"], "name": loc["name"], "type": loc["type"], "total": total})
    conn.close()
    return render_template("ubicaciones.html", locations=rows)


@app.route("/ubicaciones/nueva", methods=["POST"])
@login_required
def ubicaciones_nueva():
    name = request.form.get("name", "").strip()
    loc_type = request.form.get("type", "").strip()
    if not name or loc_type not in ("bodega", "punto"):
        flash("Nombre y tipo de ubicación son obligatorios.", "danger")
        return redirect(url_for("ubicaciones"))

    conn = db.get_connection()
    existing = conn.execute("SELECT 1 FROM locations WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
    if existing:
        flash(f'Ya existe una ubicación llamada "{name}".', "danger")
        conn.close()
        return redirect(url_for("ubicaciones"))

    cur = conn.execute("INSERT INTO locations (name, type) VALUES (?, ?) RETURNING id", (name, loc_type))
    new_id = cur.fetchone()["id"]
    products = conn.execute("SELECT sku FROM products").fetchall()
    for p in products:
        db.set_stock_qty(conn, p["sku"], new_id, 0)
    conn.commit()
    conn.close()
    flash(f"Ubicación {name} creada.", "success")
    return redirect(url_for("ubicaciones"))


try:
    db.init_db()
except Exception as e:  # noqa: BLE001
    # Don't let a bad DATABASE_URL take down the whole app at import time —
    # individual routes already fail gracefully via db.get_connection() instead.
    app.logger.error("db.init_db() failed at startup: %s", e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=True, port=port)
