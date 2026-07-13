# Atelier Reborn — Control de Inventarios

App web para controlar existencias en varias ubicaciones (puntos de venta y bodegas):
catálogo de productos, importación por CSV, registro de movimientos (entradas, salidas,
traslados), vista consolidada de existencias y alertas de stock mínimo.

Implementa la Fase 1 del roadmap del proyecto, sobre el diseño de `Plataforma Atelier
Reborn` (handoff de Claude Design).

## Stack

Python 3 + Flask + Postgres (Supabase). La base de datos es Postgres (no SQLite)
para poder correr en Vercel: las funciones serverless no tienen disco persistente,
así que el inventario necesita vivir en una base de datos externa.

## Variables de entorno

Copia `.env.example` a `.env` (o expórtalas en tu shell) y ajusta:

- `DATABASE_URL` — connection string de Postgres. En Supabase: **Project Settings
  → Database → Connection string → URI** (usa el modo "Transaction pooler" para
  entornos serverless como Vercel).
- `APP_PASSWORD` — la contraseña única de acceso. Sin default seguro: defínela.
- `SECRET_KEY` — clave para firmar la sesión de Flask. Usa un valor aleatorio propio.
- `REQUIRE_PASSWORD` — `true` pide la contraseña en un login; `false` deja entrar a
  cualquiera sin pedir nada (útil para pruebas compartidas, no para datos reales).
- `PORT` — solo relevante corriendo local con `python3 app.py` (default 5050).

## Cómo correrlo en local

```bash
cd "atelier-reborn"
pip3 install --user -r requirements.txt   # solo la primera vez
export DATABASE_URL="postgresql://postgres:tu-contraseña@db.tu-proyecto.supabase.co:5432/postgres"
export APP_PASSWORD="tu-contraseña"
python3 app.py
```

Abre http://localhost:5050 en el navegador. El esquema de tablas se crea solo la
primera vez que arranca (`CREATE TABLE IF NOT EXISTS`).

## Primer uso

1. Ve a **Ubicaciones** y crea tus puntos de venta y bodegas.
2. Ve a **Catálogo** e importa tu catálogo de productos (CSV con columnas
   `sku`/`codigo`, `nombre`/`descripcion`, opcional `minimo`).
3. Desde **Catálogo**, importa las existencias iniciales (CSV con columnas `sku`,
   `ubicacion`, `cantidad`).
4. Opcionalmente edita productos para agregarles foto.
5. Usa **Movimientos** para registrar entradas, salidas y traslados del día a día.
6. Usa **Existencias** para consultar cuánto hay de cada producto, por ubicación.

## Desplegar en Vercel

1. En Supabase, entra al **SQL Editor** de tu proyecto, pega el contenido de
   `schema.sql` y ejecútalo una vez (crea las tablas).
2. En [vercel.com](https://vercel.com), **Add New** → **Project**, importa este
   repositorio de GitHub (`atelierreborn`). Vercel detecta `vercel.json` y
   `api/index.py` automáticamente como función Python.
3. En **Environment Variables**, agrega `DATABASE_URL`, `APP_PASSWORD`,
   `SECRET_KEY` y `REQUIRE_PASSWORD` (los mismos valores de `.env.example`, con tus
   datos reales de Supabase).
4. Deploy.

Como el inventario vive en Supabase (no en el disco de la función), no hay
problema de persistencia: los datos sobreviven a cada nueva invocación o deploy.

## Alternativa: Render

`render.yaml` también queda configurado por si prefieres Render en vez de Vercel
(mismo código, mismo `DATABASE_URL` de Supabase — solo cambia dónde corre el
proceso). En Render: **New +** → **Blueprint** → conectar el repo → agregar las
mismas variables de entorno.
