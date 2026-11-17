"""Ejecuta cada tarjeta de los tableros FIS en Metabase e informa errores y filas.

    docker compose -f deploy/docker-compose.yml exec revisor python /app/deploy/verificar_tableros.py
"""
import os
import sys

import requests

MB = os.environ.get("MB_URL", "http://metabase:3000").rstrip("/")
s = requests.Session()
r = s.post(f"{MB}/api/session", json={"username": os.environ.get("MB_ADMIN_EMAIL") or "admin@fis.local",
                                       "password": os.environ["MB_ADMIN_PASSWORD"]}, timeout=30)
r.raise_for_status()
s.headers["X-Metabase-Session"] = r.json()["id"]

errores = 0
for d in s.get(f"{MB}/api/dashboard", timeout=30).json():
    if not d["name"].startswith("FIS"):
        continue
    tablero = s.get(f"{MB}/api/dashboard/{d['id']}", timeout=30).json()
    print(f"\n{d['name']} (/dashboard/{d['id']}) — filtros: {[p['slug'] for p in tablero.get('parameters', [])]}")
    for dc in tablero["dashcards"]:
        card = dc["card"]
        res = s.post(f"{MB}/api/dashboard/{d['id']}/dashcard/{dc['id']}/card/{card['id']}/query",
                     json={"parameters": []}, timeout=120).json()
        if res.get("error") or res.get("status") == "failed":
            errores += 1
            print(f"  ERROR {card['name']}: {str(res.get('error'))[:200]}")
        else:
            print(f"  ok    {card['name']}: {res['row_count']} filas")
sys.exit(1 if errores else 0)
