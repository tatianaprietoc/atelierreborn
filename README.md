# Atelier Reborn — Control de Inventarios

App web para controlar existencias en varias ubicaciones (puntos de venta y bodegas):
catálogo de productos, importación por CSV, registro de movimientos (entradas, salidas,
traslados), vista consolidada de existencias y alertas de stock mínimo.

Implementa la Fase 1 del roadmap del proyecto, sobre el diseño de `Plataforma Atelier
Reborn` (handoff de Claude Design).

## Stack

Python 3 + Flask + SQLite. Sin dependencias de Node/npm — pensado para correr con lo
que ya trae macOS más un `pip install` a nivel de usuario.

## Cómo correrlo

```bash
cd "atelier-reborn"
pip3 install --user -r requirements.txt   # solo la primera vez
python3 app.py
```

Abre http://localhost:5050 en el navegador.

## Contraseña de acceso

El acceso se controla con dos variables de entorno (ver `.env.example`):

- `APP_PASSWORD` — la contraseña única de acceso. Si no la defines, usa `changeme`
  por defecto — cámbiala antes de usar la app con datos reales.
- `REQUIRE_PASSWORD` — en `true` pide la contraseña en un login; en `false` (valor
  por defecto actual, pensado para pruebas compartidas) deja entrar a cualquiera
  sin pedir nada. Ponla en `true` para producción.

```bash
export APP_PASSWORD="tu-contraseña-nueva"
export REQUIRE_PASSWORD=true
python3 app.py
```

## Datos

Todo se guarda en `data/inventario.db` (SQLite), creado automáticamente la primera
vez que corres `python3 app.py`. Para reiniciar desde cero, borra ese archivo.

## Primer uso

1. Ve a **Ubicaciones** y crea tus puntos de venta y bodegas.
2. Ve a **Catálogo** e importa tu catálogo de productos (CSV con columnas
   `sku`/`codigo`, `nombre`/`descripcion`, opcional `minimo`).
3. Desde **Catálogo**, importa las existencias iniciales (CSV con columnas `sku`,
   `ubicacion`, `cantidad`).
4. Opcionalmente edita productos para agregarles foto.
5. Usa **Movimientos** para registrar entradas, salidas y traslados del día a día.
6. Usa **Existencias** para consultar cuánto hay de cada producto, por ubicación.

## Desplegar en Render

Esta app **no funciona en Vercel** (necesita un proceso persistente, no funciones
serverless). Render sí sirve porque mantiene el proceso corriendo:

1. En [render.com](https://render.com), **New +** → **Blueprint**, y conecta este
   repositorio de GitHub. Render detecta `render.yaml` automáticamente.
2. Te pedirá el valor de `APP_PASSWORD` (no tiene un default seguro en producción).
3. Deploy. La URL pública queda como `https://atelier-reborn.onrender.com` (o el
   nombre que Render asigne).

**Importante sobre el plan gratuito:** el plan `free` de Render **no incluye disco
persistente** — el archivo `data/inventario.db` se reinicia cuando el servicio se
duerme por inactividad (a los 15 min) o cuando vuelves a desplegar. Sirve para que
varias personas prueben la interfaz, pero no para guardar inventario real.

Para que los datos persistan de verdad, sube al plan **Starter** (de pago) y
descomenta el bloque `disk:` en `render.yaml` antes de desplegar.
