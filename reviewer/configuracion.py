"""Configuración del curso y rúbricas guardadas en PostgreSQL (esquema `portal`).

La primera vez se siembran desde `config/course.yaml` y `rubrics/*.yaml`; desde ese momento el
profesor las administra en el portal y cada cambio queda en `portal.config_historial`.
Sin base de datos (uso local), se leen los YAML como antes.
"""
from __future__ import annotations

import copy
import json
import os

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIPOS = ("auto", "asistido", "humano")

DDL = """
CREATE SCHEMA IF NOT EXISTS portal;
CREATE TABLE IF NOT EXISTS portal.usuarios (
    login text PRIMARY KEY, nombre text NOT NULL, clave text NOT NULL, rol text NOT NULL DEFAULT 'colega',
    activo boolean NOT NULL DEFAULT true, creado timestamptz NOT NULL DEFAULT now(), ultimo_ingreso timestamptz,
    version int NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS portal.auditoria (
    id bigserial PRIMARY KEY, fecha timestamptz NOT NULL DEFAULT now(), usuario text, evento text NOT NULL,
    detalle text, origen text
);
CREATE TABLE IF NOT EXISTS portal.config (
    clave text PRIMARY KEY, valor jsonb NOT NULL, actualizado timestamptz NOT NULL DEFAULT now(), por text
);
CREATE TABLE IF NOT EXISTS portal.config_historial (
    id bigserial PRIMARY KEY, clave text NOT NULL, valor jsonb NOT NULL, fecha timestamptz NOT NULL DEFAULT now(), por text
);
CREATE TABLE IF NOT EXISTS portal.solicitudes (
    id bigserial PRIMARY KEY, creada timestamptz NOT NULL DEFAULT now(), usuario text NOT NULL,
    origen text NOT NULL DEFAULT 'manual', alcance text NOT NULL, entrega text NOT NULL, con_ia boolean NOT NULL,
    estado text NOT NULL DEFAULT 'pendiente', inicio timestamptz, fin timestamptz, codigo int,
    cancelar boolean NOT NULL DEFAULT false, log text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS solicitudes_estado ON portal.solicitudes (estado, id);
"""


def asegurar_esquema(con) -> None:
    """Crea las tablas del agente (fis.*) y del portal (portal.*). Seguro con varios procesos a la vez."""
    from .store import DDL as DDL_FIS

    with con.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(424242)")
        cur.execute(DDL_FIS)
        cur.execute(DDL)
    con.commit()


def _yaml(ruta: str) -> dict:
    with open(ruta if os.path.isabs(ruta) else os.path.join(RAIZ, ruta), encoding="utf-8") as f:
        return yaml.safe_load(f)


def desde_yaml(ruta: str = "config/course.yaml") -> dict:
    cfg = _yaml(ruta)
    cfg["_rubricas"] = {k: _yaml(v["rubrica"]) for k, v in cfg.get("entregas", {}).items()}
    for k, v in cfg["entregas"].items():
        v["rubrica"] = k
    return cfg


def cargar(dsn: str | None, ruta: str = "config/course.yaml") -> dict:
    """Configuración vigente con sus rúbricas en cfg['_rubricas'][entrega]."""
    if not dsn:
        return desde_yaml(ruta)
    import psycopg

    with psycopg.connect(dsn) as con:
        asegurar_esquema(con)
        return cargar_con(con, ruta)


def cargar_con(con, ruta: str = "config/course.yaml") -> dict:
    with con.cursor() as cur:
        cur.execute("SELECT clave, valor FROM portal.config")
        filas = dict(cur.fetchall())
    if "curso" not in filas:
        cfg = desde_yaml(ruta)
        guardar(con, "curso", {k: v for k, v in cfg.items() if k != "_rubricas"}, "siembra")
        for k, r in cfg["_rubricas"].items():
            guardar(con, f"rubrica:{k}", r, "siembra")
        return cfg
    cfg = filas["curso"]
    cfg["_rubricas"] = {k[len("rubrica:"):]: v for k, v in filas.items() if k.startswith("rubrica:")}
    return cfg


def guardar(con, clave: str, valor: dict, por: str) -> None:
    datos = json.dumps(valor, ensure_ascii=False)
    with con.cursor() as cur:
        cur.execute("""INSERT INTO portal.config (clave, valor, por) VALUES (%s, %s::jsonb, %s)
                       ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = now(), por = EXCLUDED.por""",
                    (clave, datos, por))
        cur.execute("INSERT INTO portal.config_historial (clave, valor, por) VALUES (%s, %s::jsonb, %s)", (clave, datos, por))
    con.commit()


def validar_rubrica(r: dict, clave: str) -> list[str]:
    from .checks import CHECKS

    errores = []
    if not isinstance(r, dict):
        return ["La rúbrica debe ser un objeto YAML."]
    if r.get("entrega") != clave:
        errores.append(f"El campo `entrega` debe ser `{clave}`.")
    if not r.get("nombre"):
        errores.append("Falta `nombre`.")
    criterios = r.get("criterios")
    if not isinstance(criterios, list) or not criterios:
        return errores + ["`criterios` debe ser una lista con al menos un criterio."]
    ids, total = set(), 0.0
    for i, c in enumerate(criterios, 1):
        if not isinstance(c, dict):
            errores.append(f"Criterio {i}: debe ser un objeto.")
            continue
        for campo in ("id", "nombre", "peso", "tipo", "checks", "niveles"):
            if campo not in c:
                errores.append(f"Criterio {i}: falta `{campo}`.")
        if c.get("id") in ids:
            errores.append(f"Criterio {i}: id repetido `{c.get('id')}`.")
        ids.add(c.get("id"))
        try:
            peso = float(c.get("peso", 0))
            if not 0 <= peso <= 1:
                raise ValueError
            total += peso
        except (TypeError, ValueError):
            errores.append(f"Criterio {i}: `peso` debe ser un número entre 0 y 1.")
        if c.get("tipo") not in TIPOS:
            errores.append(f"Criterio {i}: `tipo` debe ser uno de {', '.join(TIPOS)}.")
        desconocidas = [x for x in c.get("checks") or [] if x not in CHECKS]
        if desconocidas:
            errores.append(f"Criterio {i}: verificaciones desconocidas: {', '.join(desconocidas)}.")
        for n in c.get("niveles") or []:
            rango = n.get("rango") if isinstance(n, dict) else None
            if not (isinstance(rango, list) and len(rango) == 2 and all(isinstance(x, (int, float)) for x in rango)):
                errores.append(f"Criterio {i}: cada nivel necesita `nombre`, `rango: [min, max]` y `descripcion`.")
                break
    if total > 1.0001:
        errores.append(f"Los pesos suman {total:.2f}; no pueden superar 1.")
    return errores


def validar_curso(cfg: dict) -> list[str]:
    errores = []
    for campo in ("org", "curso", "periodo", "repo_prefijo", "entregas"):
        if not cfg.get(campo):
            errores.append(f"Falta `{campo}`.")
    import datetime as dt

    for k, v in (cfg.get("entregas") or {}).items():
        try:
            dt.date.fromisoformat(str(v.get("fecha")))
        except (ValueError, AttributeError):
            errores.append(f"Entrega {k}: `fecha` debe ser AAAA-MM-DD.")
    return errores


def sin_rubricas(cfg: dict) -> dict:
    return {k: copy.deepcopy(v) for k, v in cfg.items() if k != "_rubricas"}
