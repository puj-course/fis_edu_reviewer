"""Configura Metabase: usuario administrador, conexión a los datos y los dos tableros.

Es idempotente: se puede volver a ejecutar y actualiza lo que ya existe.
Variables: MB_URL, MB_ADMIN_EMAIL, MB_ADMIN_PASSWORD, LECTURA_PASSWORD.
"""
from __future__ import annotations

import os
import sys
import uuid

import requests

MB = os.environ.get("MB_URL", "http://metabase:3000").rstrip("/")
EMAIL = os.environ.get("MB_ADMIN_EMAIL") or "admin@fis.local"
CLAVE = os.environ["MB_ADMIN_PASSWORD"]
S = requests.Session()


def api(metodo: str, ruta: str, **cuerpo):
    r = S.request(metodo, MB + ruta, json=cuerpo or None, timeout=60)
    if r.status_code >= 400:
        sys.exit(f"Metabase {metodo} {ruta} -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.text else None


def iniciar_sesion() -> None:
    props = api("GET", "/api/session/properties")
    if not props.get("has-user-setup"):
        api("POST", "/api/setup", token=props["setup-token"],
            user={"first_name": "Profesor", "last_name": "FIS", "email": EMAIL, "password": CLAVE, "site_name": "FIS"},
            prefs={"site_name": "Fundamentos de Ingeniería de Software", "site_locale": "es", "allow_tracking": False})
        print("Usuario administrador creado")
    sesion = api("POST", "/api/session", username=EMAIL, password=CLAVE)
    S.headers["X-Metabase-Session"] = sesion["id"]


def base_de_datos() -> int:
    existentes = api("GET", "/api/database")
    existentes = existentes["data"] if isinstance(existentes, dict) else existentes
    for d in existentes:
        if d["name"] == "FIS":
            return d["id"]
    d = api("POST", "/api/database", name="FIS", engine="postgres", details={
        "host": "postgres", "port": 5432, "dbname": "fis", "user": "fis_lectura",
        "password": os.environ["LECTURA_PASSWORD"], "ssl": False, "schema-filters-type": "inclusion",
        "schema-filters-patterns": "fis"})
    print("Conexión a PostgreSQL creada")
    return d["id"]


def coleccion() -> int:
    for c in api("GET", "/api/collection"):
        if c.get("name") == "FIS" and not c.get("archived"):
            return c["id"]
    return api("POST", "/api/collection", name="FIS", description="Agente revisor de Fundamentos de Ingeniería de Software")["id"]


FILTROS = {
    "equipo": "[[AND equipo = {{equipo}}]]",
    "entrega": "[[AND entrega_nombre = {{entrega}}]]",
}

# nombre: (visualización, SQL, ajustes de visualización, filtros que acepta)
TARJETAS = {
    "Equipos": ("table", "SELECT DISTINCT equipo FROM fis.v_revision_actual ORDER BY 1", {}, []),
    "Entregas": ("table", "SELECT DISTINCT entrega_nombre FROM fis.v_revision_actual ORDER BY 1", {}, []),
    "Pre-nota sugerida por equipo": (
        "bar",
        "SELECT equipo, entrega_nombre AS entrega, pre_nota FROM fis.v_revision_actual WHERE 1=1 {entrega} ORDER BY 1, 2",
        {"graph.dimensions": ["equipo", "entrega"], "graph.metrics": ["pre_nota"], "graph.show_values": True}, ["entrega"]),
    "Puntaje sugerido por criterio": (
        "table",
        "SELECT criterio, equipo, puntaje FROM fis.v_criterios WHERE 1=1 {entrega} ORDER BY entrega, orden, equipo",
        {"table.pivot": True, "table.pivot_column": "equipo", "table.cell_column": "puntaje"}, ["entrega"]),
    "Commits por semana y equipo": (
        "line",
        "SELECT semana, equipo, sum(commits) AS commits FROM fis.v_commits_semana GROUP BY 1, 2 ORDER BY 1",
        {"graph.dimensions": ["semana", "equipo"], "graph.metrics": ["commits"]}, []),
    "Actividad por equipo": (
        "table",
        """SELECT e.equipo,
       (SELECT count(*) FROM fis.commits c WHERE c.equipo = e.equipo AND NOT c.es_merge) AS commits,
       (SELECT round(100.0 * avg(c.convencional::int)) FROM fis.commits c WHERE c.equipo = e.equipo AND NOT c.es_merge) AS "% conventional",
       (SELECT round(100.0 * avg(c.referencia_issue::int)) FROM fis.commits c WHERE c.equipo = e.equipo AND NOT c.es_merge) AS "% con issue",
       (SELECT count(*) FROM fis.issues i WHERE i.equipo = e.equipo) AS issues,
       (SELECT count(*) FROM fis.issues i WHERE i.equipo = e.equipo AND i.es_historia) AS historias,
       (SELECT count(*) FROM fis.pull_requests p WHERE p.equipo = e.equipo AND p.fusionado IS NOT NULL) AS "PR fusionados",
       (SELECT count(*) FROM fis.pipelines w WHERE w.equipo = e.equipo AND w.ultima = 'success') AS "pipelines en verde"
FROM (SELECT DISTINCT equipo FROM fis.v_revision_actual) e ORDER BY 1""", {}, []),
    "Aporte y factor sugerido por integrante": (
        "table",
        """SELECT equipo, login AS integrante, commits, semanas_activas || '/' || semanas_equipo AS semanas,
       issues_cerradas, prs, revisiones, lineas, indice_aporte, factor_sugerido
FROM fis.v_aporte WHERE 1=1 {equipo} {entrega} ORDER BY equipo, commits DESC""", {}, ["equipo", "entrega"]),
    "Criterios de la rúbrica": (
        "table",
        """SELECT entrega_nombre AS entrega, criterio, round(peso * 100) || '%' AS peso, tipo, nivel, puntaje, fuente,
       justificacion_ia AS "justificación (IA)", verificar_manual AS "verificar manualmente"
FROM fis.v_criterios WHERE 1=1 {equipo} {entrega} ORDER BY entrega, orden""", {}, ["equipo", "entrega"]),
    "Indicadores que no se cumplen": (
        "table",
        """SELECT i.criterio, i.verificacion AS "verificación", i.indicador
FROM fis.v_indicadores i JOIN fis.v_revision_actual r ON r.id = i.revision_id
WHERE i.cumple = false {equipo_i} {entrega_r} ORDER BY 1, 2""", {}, ["equipo", "entrega"]),
    "Commits por semana e integrante": (
        "bar",
        "SELECT semana, login AS integrante, sum(commits) AS commits FROM fis.v_commits_semana WHERE 1=1 {equipo} GROUP BY 1, 2 ORDER BY 1",
        {"graph.dimensions": ["semana", "integrante"], "graph.metrics": ["commits"], "stackable.stack_type": "stacked"}, ["equipo"]),
    "Señales de proceso": (
        "table",
        "SELECT equipo, login AS integrante, tipo, detalle, commits FROM fis.v_senales WHERE 1=1 {equipo} {entrega} ORDER BY 1, 2",
        {}, ["equipo", "entrega"]),
    "Preguntas para la sustentación": (
        "table",
        "SELECT equipo, login AS integrante, orden AS n, pregunta FROM fis.v_preguntas WHERE 1=1 {equipo} {entrega} ORDER BY 1, 2, 3",
        {}, ["equipo", "entrega"]),
    "Pipelines de GitHub Actions": (
        "table",
        "SELECT equipo, archivo, nombre, ejecuciones, exitosas, fallidas, ultima AS \"última\" FROM fis.pipelines WHERE 1=1 {equipo} ORDER BY 1, 2",
        {}, ["equipo"]),
    "Historias de usuario por milestone": (
        "bar",
        """SELECT coalesce(milestone, '(sin milestone)') AS milestone, estado, count(*) AS historias
FROM fis.issues WHERE es_historia {equipo} GROUP BY 1, 2 ORDER BY 1""",
        {"graph.dimensions": ["milestone", "estado"], "graph.metrics": ["historias"], "stackable.stack_type": "stacked"}, ["equipo"]),
}

# tablero: (filtros, [(tarjeta, fila, columna, ancho, alto)])   — la rejilla tiene 24 columnas
TABLEROS = {
    "FIS · Resumen del curso": (["entrega"], [
        ("Pre-nota sugerida por equipo", 0, 0, 10, 7),
        ("Puntaje sugerido por criterio", 0, 10, 14, 7),
        ("Actividad por equipo", 7, 0, 24, 5),
        ("Commits por semana y equipo", 12, 0, 24, 7),
        ("Aporte y factor sugerido por integrante", 19, 0, 24, 10),
    ]),
    "FIS · Detalle por proyecto": (["equipo", "entrega"], [
        ("Criterios de la rúbrica", 0, 0, 24, 8),
        ("Indicadores que no se cumplen", 8, 0, 12, 9),
        ("Señales de proceso", 8, 12, 12, 9),
        ("Aporte y factor sugerido por integrante", 17, 0, 24, 6),
        ("Commits por semana e integrante", 23, 0, 14, 7),
        ("Historias de usuario por milestone", 23, 14, 10, 7),
        ("Preguntas para la sustentación", 30, 0, 24, 9),
        ("Pipelines de GitHub Actions", 39, 0, 24, 7),
    ]),
}


def sql_con_filtros(sql: str, filtros: list[str]) -> tuple[str, dict]:
    sql = sql.format(
        equipo=FILTROS["equipo"] if "equipo" in filtros else "",
        entrega=FILTROS["entrega"] if "entrega" in filtros else "",
        equipo_i="[[AND i.equipo = {{equipo}}]]", entrega_r="[[AND r.entrega_nombre = {{entrega}}]]")
    etiquetas = {f: {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"fis-{f}")), "name": f, "display-name": f.capitalize(),
                     "type": "text"} for f in filtros}
    return sql, etiquetas


def tarjetas(db: int, col: int) -> dict[str, int]:
    existentes = {c["name"]: c["id"] for c in api("GET", "/api/card?f=all") if c.get("collection_id") == col and not c.get("archived")}
    ids = {}
    for nombre, (vista, sql, ajustes, filtros) in TARJETAS.items():
        sql, etiquetas = sql_con_filtros(sql, filtros)
        cuerpo = dict(name=nombre, display=vista, collection_id=col, visualization_settings=ajustes,
                      dataset_query={"type": "native", "database": db, "native": {"query": sql, "template-tags": etiquetas}})
        if nombre in existentes:
            api("PUT", f"/api/card/{existentes[nombre]}", **cuerpo)
            ids[nombre] = existentes[nombre]
        else:
            ids[nombre] = api("POST", "/api/card", **cuerpo)["id"]
    return ids


def parametro(filtro: str, ids: dict[str, int]) -> dict:
    tarjeta, campo = {"equipo": ("Equipos", "equipo"), "entrega": ("Entregas", "entrega_nombre")}[filtro]
    extra = {"default": ["Entrega final"]} if filtro == "entrega" else {}
    return {**extra, "id": f"fis_{filtro}", "name": filtro.capitalize(), "slug": filtro, "type": "string/=", "sectionId": "string",
            "values_query_type": "list", "values_source_type": "card",
            "values_source_config": {"card_id": ids[tarjeta], "value_field": ["field", campo, {"base-type": "type/Text"}]}}


def tableros(col: int, ids: dict[str, int]) -> list[dict]:
    existentes = {d["name"]: d["id"] for d in api("GET", "/api/dashboard") if d.get("collection_id") == col and not d.get("archived")}
    listos = []
    for nombre, (filtros, celdas) in TABLEROS.items():
        did = existentes.get(nombre) or api("POST", "/api/dashboard", name=nombre, collection_id=col)["id"]
        dashcards = []
        for n, (tarjeta, fila, columna, ancho, alto) in enumerate(celdas, 1):
            acepta = TARJETAS[tarjeta][3]
            dashcards.append({
                "id": -n, "card_id": ids[tarjeta], "row": fila, "col": columna, "size_x": ancho, "size_y": alto,
                "visualization_settings": {},
                "parameter_mappings": [
                    {"parameter_id": f"fis_{f}", "card_id": ids[tarjeta], "target": ["variable", ["template-tag", f]]}
                    for f in filtros if f in acepta],
            })
        api("PUT", f"/api/dashboard/{did}", parameters=[parametro(f, ids) for f in filtros], dashcards=dashcards)
        print(f"Tablero listo: {nombre} -> /dashboard/{did}")
        listos.append({"id": did, "nombre": nombre.replace("FIS · ", ""), "filtros": filtros})
    return listos


def ajuste(clave: str, valor) -> bool:
    r = S.put(f"{MB}/api/setting/{clave}", json={"value": valor}, timeout=60)
    return r.status_code < 400


def embebido(lista: list[dict]) -> None:
    """Static embedding: el portal muestra los tableros firmando cada URL con el secreto de Metabase."""
    import secrets

    import psycopg

    if not (ajuste("enable-embedding-static", True) or ajuste("enable-embedding", True)):
        print("AVISO: no se pudo activar el embebido en Metabase; los tableros no se mostrarán en el portal")
        return
    r = S.get(f"{MB}/api/setting/embedding-secret-key", timeout=60)
    secreto = r.json() if r.status_code == 200 and r.text.strip() else None
    if not secreto:
        secreto = secrets.token_hex(32)
        ajuste("embedding-secret-key", secreto)
    for t in lista:
        api("PUT", f"/api/dashboard/{t['id']}", enable_embedding=True, embedding_params={f: "enabled" for f in t["filtros"]})
    sys.path.insert(0, "/app")
    from reviewer import configuracion

    with psycopg.connect(os.environ["FIS_PG_DSN"]) as con:
        configuracion.asegurar_esquema(con)
        configuracion.guardar(con, "metabase", {"secreto": secreto, "tableros": [{"id": t["id"], "nombre": t["nombre"]} for t in lista]},
                              "instalador")
    print(f"Tableros incrustables en el portal: {len(lista)}")


if __name__ == "__main__":
    iniciar_sesion()
    db = base_de_datos()
    col = coleccion()
    embebido(tableros(col, tarjetas(db, col)))
