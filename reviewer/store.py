"""Almacenamiento de las revisiones.

- PostgreSQL (FIS_PG_DSN): tablas relacionales para los tableros (Metabase).
- MongoDB   (FIS_MONGO_URI): la evidencia cruda y el resultado completo de cada revisión.

Ambos son opcionales: si la variable no está, ese almacén se omite.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from .checks import RE_CONVENTIONAL, RE_REF, Contexto, nota_parcial

DDL = """
CREATE SCHEMA IF NOT EXISTS fis;

CREATE TABLE IF NOT EXISTS fis.corridas (
    id        serial PRIMARY KEY,
    iniciada  timestamptz NOT NULL DEFAULT now(),
    con_ia    boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS fis.revisiones (
    id            serial PRIMARY KEY,
    corrida_id    int NOT NULL REFERENCES fis.corridas(id) ON DELETE CASCADE,
    repo          text NOT NULL,
    equipo        text NOT NULL,
    entrega       text NOT NULL,
    entrega_nombre text NOT NULL,
    hasta         date NOT NULL,
    revisada      timestamptz NOT NULL DEFAULT now(),
    pre_nota      numeric(3,2),
    peso_cubierto numeric(3,2),
    integrantes   int,
    senales       int,
    avisos        jsonb
);
CREATE TABLE IF NOT EXISTS fis.criterios (
    revision_id  int NOT NULL REFERENCES fis.revisiones(id) ON DELETE CASCADE,
    orden        int,
    criterio_id  text NOT NULL,
    criterio     text NOT NULL,
    peso         numeric(4,2),
    tipo         text,
    nivel        text,
    puntaje      numeric(3,1),
    fuente       text,
    nivel_indicadores   text,
    puntaje_indicadores numeric(3,1),
    justificacion_ia    text,
    confianza_ia        text,
    verificar_manual    text
);
CREATE TABLE IF NOT EXISTS fis.indicadores (
    revision_id  int NOT NULL REFERENCES fis.revisiones(id) ON DELETE CASCADE,
    criterio_id  text NOT NULL,
    criterio     text NOT NULL,
    verificacion text NOT NULL,
    indicador    text NOT NULL,
    cumple       boolean
);
CREATE TABLE IF NOT EXISTS fis.aporte (
    revision_id  int NOT NULL REFERENCES fis.revisiones(id) ON DELETE CASCADE,
    login text NOT NULL, commits int, dias_activos int, semanas_activas int, semanas_equipo int,
    issues_cerradas int, issues_asignadas int, prs int, revisiones int, lineas bigint,
    indice_aporte numeric(4,2), regularidad numeric(4,2), factor_sugerido numeric(2,1)
);
CREATE TABLE IF NOT EXISTS fis.senales (
    revision_id int NOT NULL REFERENCES fis.revisiones(id) ON DELETE CASCADE,
    login text, tipo text, detalle text, commits text
);
CREATE TABLE IF NOT EXISTS fis.uso_ia (
    revision_id int NOT NULL REFERENCES fis.revisiones(id) ON DELETE CASCADE,
    login text, nivel text, tipo text, detalle text, refs text
);
CREATE TABLE IF NOT EXISTS fis.preguntas (
    revision_id int NOT NULL REFERENCES fis.revisiones(id) ON DELETE CASCADE,
    login text, orden int, pregunta text
);

-- Hechos del repositorio: una foto por repo, se reemplaza en cada revisión.
CREATE TABLE IF NOT EXISTS fis.commits (
    repo text NOT NULL, equipo text NOT NULL, sha text NOT NULL, login text, fecha timestamptz,
    mensaje text, adiciones int, eliminaciones int, es_merge boolean,
    convencional boolean, referencia_issue boolean, PRIMARY KEY (repo, sha)
);
CREATE TABLE IF NOT EXISTS fis.issues (
    repo text NOT NULL, equipo text NOT NULL, numero int NOT NULL, titulo text, estado text,
    creada timestamptz, cerrada timestamptz, milestone text, asignados text, labels text,
    es_historia boolean, sub_issues int, PRIMARY KEY (repo, numero)
);
CREATE TABLE IF NOT EXISTS fis.pull_requests (
    repo text NOT NULL, equipo text NOT NULL, numero int NOT NULL, titulo text, autor text,
    rama_origen text, rama_destino text, creado timestamptz, fusionado timestamptz,
    aprobaciones int, PRIMARY KEY (repo, numero)
);
CREATE TABLE IF NOT EXISTS fis.pipelines (
    repo text NOT NULL, equipo text NOT NULL, archivo text NOT NULL, nombre text,
    ejecuciones int, exitosas int, fallidas int, ultima text, PRIMARY KEY (repo, archivo)
);
CREATE TABLE IF NOT EXISTS fis.milestones (
    repo text NOT NULL, equipo text NOT NULL, titulo text NOT NULL, estado text,
    vence timestamptz, cerrado timestamptz, abiertas int, cerradas int, PRIMARY KEY (repo, titulo)
);
CREATE TABLE IF NOT EXISTS fis.sonar (
    repo text PRIMARY KEY, equipo text NOT NULL, servidor text, clave text, url text, quality_gate text,
    condiciones_fallidas text, analisis int, dias_con_analisis int, ultimo_analisis date, pipelines int,
    pipeline_ok boolean, cobertura numeric, bugs int, vulnerabilidades int, code_smells int, hotspots int,
    duplicacion numeric, deuda_min int, mantenibilidad text, fiabilidad text, seguridad text, lineas int,
    actualizado timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fis.sonar_interno (
    repo text PRIMARY KEY, equipo text NOT NULL, servidor text, clave text, url text, quality_gate text,
    condiciones_fallidas text, analisis int, dias_con_analisis int, ultimo_analisis date, pipelines int,
    pipeline_ok boolean, cobertura numeric, bugs int, vulnerabilidades int, code_smells int, hotspots int,
    duplicacion numeric, deuda_min int, mantenibilidad text, fiabilidad text, seguridad text, lineas int,
    actualizado timestamptz DEFAULT now(), commit text, entrega text, error text
);

-- Vistas para los tableros: siempre la revisión más reciente de cada equipo y entrega.
CREATE OR REPLACE VIEW fis.v_revision_actual AS
    SELECT DISTINCT ON (repo, entrega) * FROM fis.revisiones ORDER BY repo, entrega, id DESC;
CREATE OR REPLACE VIEW fis.v_criterios AS
    SELECT r.equipo, r.entrega, r.entrega_nombre, r.hasta, c.* FROM fis.criterios c JOIN fis.v_revision_actual r ON r.id = c.revision_id;
CREATE OR REPLACE VIEW fis.v_indicadores AS
    SELECT r.equipo, r.entrega, i.* FROM fis.indicadores i JOIN fis.v_revision_actual r ON r.id = i.revision_id;
CREATE OR REPLACE VIEW fis.v_aporte AS
    SELECT r.equipo, r.entrega, a.* FROM fis.aporte a JOIN fis.v_revision_actual r ON r.id = a.revision_id;
CREATE OR REPLACE VIEW fis.v_senales AS
    SELECT r.equipo, r.entrega, s.* FROM fis.senales s JOIN fis.v_revision_actual r ON r.id = s.revision_id;
CREATE OR REPLACE VIEW fis.v_uso_ia AS
    SELECT r.equipo, r.entrega, r.repo, u.* FROM fis.uso_ia u JOIN fis.v_revision_actual r ON r.id = u.revision_id;
CREATE OR REPLACE VIEW fis.v_preguntas AS
    SELECT r.equipo, r.entrega, p.* FROM fis.preguntas p JOIN fis.v_revision_actual r ON r.id = p.revision_id;
CREATE OR REPLACE VIEW fis.v_commits_semana AS
    SELECT equipo, login, date_trunc('week', fecha)::date AS semana, count(*) AS commits,
           coalesce(sum(adiciones), 0) AS lineas
    FROM fis.commits WHERE NOT es_merge GROUP BY 1, 2, 3;
"""


class Almacen:
    def __init__(self):
        self.pg = self.mongo = None
        self.corrida = None
        self.errores: list[str] = []
        dsn, uri = os.environ.get("FIS_PG_DSN"), os.environ.get("FIS_MONGO_URI")
        if dsn:
            try:
                import psycopg

                self.pg = psycopg.connect(dsn, autocommit=False)
                with self.pg.cursor() as cur:
                    cur.execute(DDL)
                self.pg.commit()
            except Exception as e:  # la revisión no debe caerse por el almacén
                self.pg = None
                self.errores.append(f"PostgreSQL no disponible: {e}")
        if uri:
            try:
                import pymongo

                cliente = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)
                cliente.admin.command("ping")
                self.mongo = cliente[os.environ.get("FIS_MONGO_DB") or "fis"]
            except Exception as e:
                self.mongo = None
                self.errores.append(f"MongoDB no disponible: {e}")

    @property
    def activo(self) -> bool:
        return self.pg is not None or self.mongo is not None

    def iniciar_corrida(self, con_ia: bool) -> None:
        if self.pg is not None:
            with self.pg.cursor() as cur:
                cur.execute("INSERT INTO fis.corridas (con_ia) VALUES (%s) RETURNING id", (con_ia,))
                self.corrida = cur.fetchone()[0]
            self.pg.commit()

    def guardar(self, res: dict, ev: dict, cfg: dict) -> None:
        if self.pg is not None:
            try:
                self._postgres(res, ev, cfg)
                self.pg.commit()
            except Exception as e:
                self.pg.rollback()
                self.errores.append(f"{res['repo']}: no se guardó en PostgreSQL: {e}")
        if self.mongo is not None:
            try:
                self._mongo(res, ev)
            except Exception as e:
                self.errores.append(f"{res['repo']}: no se guardó en MongoDB: {e}")

    # ------------------------------------------------------------ PostgreSQL

    def _postgres(self, res: dict, ev: dict, cfg: dict) -> None:
        repo, equipo = res["repo"], res["repo"].split("/")[-1]
        nota, cubierto = nota_parcial(res)
        with self.pg.cursor() as cur:
            cur.execute(
                """INSERT INTO fis.revisiones (corrida_id, repo, equipo, entrega, entrega_nombre, hasta, pre_nota,
                       peso_cubierto, integrantes, senales, avisos)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (self.corrida, repo, equipo, res["entrega"], res["entrega_nombre"], res["hasta"], nota, cubierto,
                 len(res["aporte"]), len(res["senales"]), json.dumps(res["avisos"], ensure_ascii=False)),
            )
            rid = cur.fetchone()[0]
            for orden, c in enumerate(res["criterios"], 1):
                final, ia, ind = c["ia"] or c["sugerencia"] or {}, c["ia"] or {}, c["sugerencia"] or {}
                cur.execute(
                    "INSERT INTO fis.criterios VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (rid, orden, c["id"], c["nombre"], c["peso"], c["tipo"], final.get("nivel"), final.get("puntaje"),
                     final.get("fuente", "profesor"), ind.get("nivel"), ind.get("puntaje"), ia.get("justificacion"),
                     ia.get("confianza"), "\n".join(ia.get("verificar_manual", [])) or None),
                )
                cur.executemany(
                    "INSERT INTO fis.indicadores VALUES (%s,%s,%s,%s,%s,%s)",
                    [(rid, c["id"], c["nombre"], ch["titulo"], i["texto"], i["ok"]) for ch in c["checks"] for i in ch["indicadores"]],
                )
            cur.executemany(
                "INSERT INTO fis.aporte VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(rid, f["login"], f["commits"], f["dias_activos"], f["semanas_activas"], f["semanas_equipo"],
                  f["issues_cerradas"], f["issues_asignadas"], f["prs"], f["revisiones"], f["lineas"],
                  f["indice_aporte"], f["regularidad"], f["factor_sugerido"]) for f in res["aporte"]],
            )
            cur.executemany(
                "INSERT INTO fis.senales VALUES (%s,%s,%s,%s,%s)",
                [(rid, s["login"], s["tipo"], s["texto"], ", ".join(s["commits"])) for s in res["senales"]],
            )
            cur.executemany(
                "INSERT INTO fis.uso_ia VALUES (%s,%s,%s,%s,%s,%s)",
                [(rid, e["login"], e["nivel"], e["tipo"], e["detalle"], ", ".join(e["refs"])) for e in res.get("uso_ia", [])],
            )
            cur.executemany(
                "INSERT INTO fis.preguntas VALUES (%s,%s,%s,%s)",
                [(rid, login, n, p) for login, ps in res["preguntas_sustentacion"].items() for n, p in enumerate(ps, 1)],
            )
            self._hechos(cur, ev, cfg, repo, equipo)

    @staticmethod
    def _sonar(cur, s: dict | None, repo: str, equipo: str, tabla: str = "fis.sonar", extra: tuple = ()) -> None:
        if tabla == "fis.sonar_interno" and s is None:
            return  # sin análisis interno en esta revisión: se conserva el último
        cur.execute(f"DELETE FROM {tabla} WHERE repo = %s", (repo,))
        if not s:
            return
        m, an, wf = s.get("medidas") or {}, s.get("analisis") or {}, s.get("pipeline") or []
        num = lambda k, f=float: f(float(m[k])) if m.get(k) not in (None, "") else None
        letra = lambda k: {"1.0": "A", "2.0": "B", "3.0": "C", "4.0": "D", "5.0": "E"}.get(str(m.get(k))) if m.get(k) else None
        columnas = ("repo, equipo, servidor, clave, url, quality_gate, condiciones_fallidas, analisis, dias_con_analisis, "
                    "ultimo_analisis, pipelines, pipeline_ok, cobertura, bugs, vulnerabilidades, code_smells, hotspots, "
                    "duplicacion, deuda_min, mantenibilidad, fiabilidad, seguridad, lineas")
        if extra:
            columnas += ", commit, entrega, error"
        valores = (repo, equipo, s.get("servidor"), s.get("clave"), s.get("url"), s.get("quality_gate"),
             "; ".join(s.get("condiciones_fallidas") or []) or None, an.get("hasta_corte"), an.get("dias_con_analisis"),
             an.get("ultimo"), len(wf), any(w.get("ultima") == "success" for w in wf) if wf else None,
             num("coverage"), num("bugs", int), num("vulnerabilities", int), num("code_smells", int),
             num("security_hotspots", int), num("duplicated_lines_density"), num("sqale_index", int),
             letra("sqale_rating"), letra("reliability_rating"), letra("security_rating"), num("ncloc", int))
        cur.execute(f"INSERT INTO {tabla} ({columnas}) VALUES ({', '.join(['%s'] * (len(valores) + len(extra)))})", valores + extra)

    def _hechos(self, cur, ev: dict, cfg: dict, repo: str, equipo: str) -> None:
        c = Contexto(ev, cfg)
        self._sonar(cur, ev.get("sonar"), repo, equipo)
        si = ev.get("sonar_interno")
        if si is not None:
            self._sonar(cur, si if not si.get("error") else {"servidor": "SonarQube del curso"}, repo, equipo,
                        "fis.sonar_interno", (si.get("commit"), si.get("entrega"), si.get("error")))
        for tabla in ("commits", "issues", "pull_requests", "pipelines", "milestones"):
            cur.execute(f"DELETE FROM fis.{tabla} WHERE repo = %s", (repo,))
        cur.executemany(
            "INSERT INTO fis.commits VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(repo, equipo, k["sha"], c.quien(k) or k.get("login") or k.get("nombre"), k["fecha"],
              k["mensaje"].splitlines()[0][:300] if k["mensaje"] else "", k["adiciones"], k["eliminaciones"],
              k["padres"] > 1, bool(RE_CONVENTIONAL.match(k["mensaje"] or "")), bool(RE_REF.search(k["mensaje"] or "")))
             for k in ev["commits"]],
        )
        cur.executemany(
            "INSERT INTO fis.issues VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(repo, equipo, i["numero"], i["titulo"][:300], i["estado"], i["creada"], i["cerrada"], i["milestone"],
              ", ".join(i["asignados"]), ", ".join(i["labels"]), c.es_hu(i), i["sub_total"]) for i in c.issues],
        )
        cur.executemany(
            "INSERT INTO fis.pull_requests VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(repo, equipo, p["numero"], p["titulo"][:300], p["autor"], p["head"], p["base"], p["creado"], p["fusionado"],
              sum(1 for r in p["reviews"] if r["estado"] == "APPROVED")) for p in ev["prs"]],
        )
        cur.executemany(
            "INSERT INTO fis.pipelines VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(repo, equipo, w["path"].split("/")[-1], w["nombre"], w["ejecuciones"], w["exitosas"], w["fallidas"], w["ultima"])
             for w in ev["workflows"]],
        )
        cur.executemany(
            "INSERT INTO fis.milestones VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            [(repo, equipo, m["titulo"], m["estado"], m["vence"], m["cerrado"], m["abiertas"], m["cerradas"])
             for m in ev["milestones"]],
        )

    # ------------------------------------------------------------ MongoDB

    def _mongo(self, res: dict, ev: dict) -> None:
        ahora = dt.datetime.now(dt.timezone.utc)
        ligero = json.loads(json.dumps(res))
        for c in ligero["criterios"]:
            for ch in c["checks"]:
                ch.pop("textos", None)
        ligero.update(corrida=self.corrida, guardada=ahora)
        self.mongo.revisiones.insert_one(ligero)

        doc = json.loads(json.dumps(ev))
        # Las claves con rutas de archivo (llevan puntos) se pasan a listas.
        doc["archivos"] = [{"ruta": k, "contenido": v} for k, v in ev["archivos"].items()]
        doc["wiki"] = {"existe": ev["wiki"]["existe"],
                       "paginas": [{"nombre": k, "contenido": v} for k, v in ev["wiki"]["paginas"].items()]}
        if doc.get("proyecto"):
            doc["proyecto"]["items"] = [{"issue": int(k), "campos": [{"campo": a, "valor": b} for a, b in v.items()]}
                                        for k, v in ev["proyecto"]["items"].items()]
        doc.update(_id=f"{ev['repo']}@{ev['hasta']}", guardada=ahora)
        try:
            self.mongo.evidencias.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        except Exception:
            # Un documento de Mongo no puede pasar de 16 MB: se guarda sin los textos largos.
            doc["archivos"], doc["wiki"]["paginas"], doc["recortada"] = [], [], True
            for w in doc["workflows"]:
                w["contenido"] = ""
            for i in doc["issues"]:
                i["cuerpo"] = i["cuerpo"][:500]
            self.mongo.evidencias.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def cerrar(self) -> None:
        if self.pg is not None:
            self.pg.close()
