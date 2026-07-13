import os
import sys

# app.py lives one directory up (repo root), alongside templates/ and static/.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app  # noqa: E402  (Vercel's Python runtime looks for `app` here)
