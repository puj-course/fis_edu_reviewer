"""Portal del profesor: aplicación web sobre PostgreSQL.

- Páginas con los datos vivos de las revisiones (nada estático).
- Usuarios, sesiones y auditoría en la base (`portal.usuarios`, `portal.auditoria`).
- Revisiones bajo demanda: cada solicitud queda en `portal.solicitudes`; el trabajador
  (`python -m reviewer trabajador`) la ejecuta y guarda su registro.
- Rúbricas y configuración del curso administrables, con historial de cambios.
- Tableros de Metabase incrustados (static embedding firmado).

    gunicorn -b 0.0.0.0:8000 "reviewer.portal:crear_app()"
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import secrets
import time
import urllib.parse

import yaml
from flask import Flask, Response, abort, g, redirect, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from . import configuracion, marca, sitio
from .sitio import E, _hero, _kpis, _tabla, pagina

ITERACIONES = 310_000
MAX_FALLOS, VENTANA_MIN = 5, 5
ESTADOS = {"pendiente": "pendiente", "en_curso": "en curso", "terminada": "terminada", "fallida": "fallida", "cancelada": "cancelada"}
TITULOS_CHECK = {
    "aporte_historias": "Aporte individual en historias", "ceremonias": "Ceremonias ágiles", "cobertura": "Cobertura de pruebas",
    "codigo_fuente": "Código fuente (evidencia)", "commits_por_sprint": "Commits por sprint", "conventional_commits": "Conventional Commits",
    "diagramas": "Diagramas de diseño", "docker": "Docker y Docker Compose", "equilibrio": "Equilibrio del equipo",
    "estructura": "Estructura del repositorio", "gitflow": "GitFlow", "historias_estructura": "Estructura de las historias de usuario",
    "historias_por_sprint": "Historias por sprint", "hitos": "Milestones", "issues_completas": "Características de las issues",
    "kanban": "Flujo Kanban", "metricas_docs": "Documentación de métricas", "patrones_gof": "Patrones GoF",
    "pipeline_docker": "Pipeline de CI/CD con Docker", "pipeline_pruebas": "Pruebas en el pipeline", "pipelines": "Pipelines de GitHub Actions",
    "postmortem": "Postmortem", "readme": "README", "sms": "Integración de mensajería", "sonar": "SonarQube",
    "sub_issues": "Sub-issues técnicas", "trazabilidad": "Trazabilidad issue – commit – cierre", "versiones": "Versiones y releases", "wiki": "Wiki",
}


# ---------------------------------------------------------------- contraseñas
def hash_clave(clave: str, iteraciones: int = ITERACIONES) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal, iteraciones)
    return f"pbkdf2_sha256${iteraciones}${base64.b64encode(sal).decode()}${base64.b64encode(dk).decode()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        algoritmo, it, sal, dk = guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", clave.encode(), base64.b64decode(sal), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_HASH_FALSO = hash_clave("x", 1000)


# ---------------------------------------------------------------- base de datos
def _con():
    if "con" not in g:
        import psycopg
        from psycopg.rows import dict_row

        g.con = psycopg.connect(os.environ["FIS_PG_DSN"], row_factory=dict_row,
                                options=f"-c TimeZone={os.environ.get('TZ') or 'America/Bogota'}")
    return g.con


def q(sql: str, *args) -> list[dict]:
    with _con().cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else []


def ejecutar(sql: str, *args) -> list[dict]:
    filas = q(sql, *args)
    _con().commit()
    return filas


def auditar(evento: str, detalle: str = "", usuario: str | None = None) -> None:
    ejecutar("INSERT INTO portal.auditoria (usuario, evento, detalle, origen) VALUES (%s,%s,%s,%s)",
             usuario or (g.get("usuario") or {}).get("login"), evento, detalle[:2000], request.remote_addr)


def crear_usuario(con, login: str, nombre: str, clave: str, rol: str = "colega") -> None:
    with con.cursor() as cur:
        cur.execute("""INSERT INTO portal.usuarios (login, nombre, clave, rol) VALUES (%s,%s,%s,%s)
                       ON CONFLICT (login) DO UPDATE SET clave = EXCLUDED.clave, nombre = EXCLUDED.nombre, rol = EXCLUDED.rol,
                       activo = true, version = portal.usuarios.version + 1""", (login, nombre, hash_clave(clave), rol))
    con.commit()


def preparar_base(dsn: str) -> None:
    """Esquema + configuración sembrada + administrador inicial (de SITIO_USUARIO / SITIO_PASSWORD)."""
    import psycopg

    with psycopg.connect(dsn) as con:
        configuracion.asegurar_esquema(con)
        configuracion.cargar_con(con)
        with con.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(424243)")
            cur.execute("SELECT count(*) FROM portal.usuarios")
            vacio = cur.fetchone()[0] == 0
        con.commit()
        if vacio and os.environ.get("SITIO_PASSWORD"):
            crear_usuario(con, os.environ.get("SITIO_USUARIO") or "profesor", "Profesor", os.environ["SITIO_PASSWORD"], "admin")


# ---------------------------------------------------------------- utilidades web
def raiz() -> str:
    """Prefijo relativo desde la URL actual hasta la raíz del portal."""
    return "../" * max(request.path.count("/") - 1, 0)


def responder(titulo: str, cuerpo: str, activo: str = "", estado: int = 200, refrescar: int = 0) -> Response:
    aviso = session.pop("aviso", None)
    return Response(pagina(titulo, cuerpo, raiz(), activo, g.get("usuario"), aviso[0] if aviso else "",
                           aviso[1] if aviso else "ok", refrescar), estado)


def avisar(texto: str, tipo: str = "ok") -> None:
    session["aviso"] = (texto, tipo)


def csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def campo_csrf() -> str:
    return f'<input type="hidden" name="csrf" value="{csrf()}">'


def es_admin() -> bool:
    return (g.get("usuario") or {}).get("rol") == "admin"


def solo_admin() -> None:
    if not es_admin():
        abort(403)


def destino_seguro(valor: str) -> str:
    valor = (valor or "").strip()
    if not valor or valor.startswith(("/", "\\")) or "//" in valor or ":" in valor.split("/")[0] or ".." in valor:
        return ""
    return valor


def generar_clave() -> str:
    return secrets.token_urlsafe(12)


# ---------------------------------------------------------------- GitHub (estado de los repos)
_cache_repos: dict = {"t": 0.0, "datos": None, "error": None}


def repos_del_periodo(cfg: dict) -> tuple[list[dict], str | None]:
    """Repos del período con su último push en GitHub (cacheado 2 minutos)."""
    if time.time() - _cache_repos["t"] < 120 and _cache_repos["datos"] is not None:
        return _cache_repos["datos"], _cache_repos["error"]
    datos, error = [], None
    try:
        from .github import GitHub

        gh = GitHub()
        excluir = set(cfg.get("repos_excluir") or [])
        for r in gh.paginate(f"/orgs/{cfg['org']}/repos", {"type": "all", "sort": "full_name"}, max_items=500):
            if r["name"].startswith(cfg["repo_prefijo"]) and not r.get("archived"):
                datos.append({"repo": r["full_name"], "equipo": r["name"], "push": r.get("pushed_at"), "excluido": r["name"] in excluir})
    except Exception as e:  # sin red o sin token: el portal sigue funcionando
        error = f"No se pudo consultar GitHub: {e}"
    _cache_repos.update(t=time.time(), datos=datos, error=error)
    return datos, error


def sonar_configurado() -> bool:
    return bool(q("SELECT 1 FROM portal.config WHERE clave = 'sonar_interno'"))


# ---------------------------------------------------------------- Metabase
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token_metabase(secreto: str, tablero: int, minutos: int = 60) -> str:
    cab = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    datos = _b64(json.dumps({"resource": {"dashboard": tablero}, "params": {}, "exp": int(time.time()) + minutos * 60}).encode())
    firma = _b64(hmac.new(secreto.encode(), f"{cab}.{datos}".encode(), hashlib.sha256).digest())
    return f"{cab}.{datos}.{firma}"


# ---------------------------------------------------------------- página de ingreso
INGRESO = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Ingreso · {producto}</title><style>{tokens}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);background:var(--bg);
color:var(--fg);font:15px/1.55 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif}}
.lado{{background:radial-gradient(circle at 20% 15%,rgba(242,183,5,.18),transparent 40%),linear-gradient(150deg,var(--jav-azul-prof),var(--jav-azul-osc) 55%,var(--jav-azul));
color:#fff;padding:48px clamp(24px,5vw,72px);display:flex;flex-direction:column;justify-content:space-between;gap:32px;border-right:4px solid var(--jav-oro)}}
.u{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;opacity:.8}}
.lado h1{{font-family:Georgia,"Times New Roman",serif;font-size:clamp(28px,3.4vw,42px);line-height:1.15;margin:14px 0 12px}}
.lado p{{opacity:.85;max-width:34em;margin:0}}.puntos{{display:grid;gap:12px;margin-top:28px;max-width:34em}}
.puntos>div{{display:flex;gap:12px;align-items:flex-start}}.puntos b{{color:var(--jav-oro)}}
.puntos span.n{{flex:none;width:26px;height:26px;border-radius:50%;background:rgba(255,255,255,.12);display:grid;place-items:center;font-weight:700;font-size:13px}}
.pie{{font-size:12px;opacity:.7}}.form{{display:grid;place-items:center;padding:32px 20px}}
form{{width:100%;max-width:380px;background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:32px 28px;box-shadow:0 10px 40px rgba(16,32,64,.12)}}
form h2{{margin:0 0 4px;font-size:22px}}form .mut{{color:var(--mut);margin:0 0 22px;font-size:14px}}
label{{display:block;font-weight:600;font-size:13px;margin:14px 0 6px}}
input{{width:100%;padding:11px 12px;border:1px solid var(--bd);border-radius:10px;background:var(--bg);color:var(--fg);font:inherit}}
input:focus{{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 25%,transparent)}}
button{{margin-top:22px;width:100%;padding:12px;border:0;border-radius:10px;background:var(--jav-azul);color:#fff;font:inherit;font-weight:700;cursor:pointer}}
button:hover{{background:var(--jav-azul-osc)}}
.error{{background:var(--badbg);color:var(--bad);border-radius:10px;padding:10px 12px;font-size:14px;margin-bottom:6px}}
.info{{background:var(--okbg);color:var(--ok);border-radius:10px;padding:10px 12px;font-size:14px;margin-bottom:6px}}
.escudo{{flex:none}}.cab{{display:flex;align-items:center;gap:14px}}
@media (max-width:820px){{body{{grid-template-columns:1fr}}.lado{{border-right:0;border-bottom:4px solid var(--jav-oro);padding:28px 20px}}
.puntos,.pie{{display:none}}.lado h1{{font-size:26px}}}}
</style></head><body>
<section class="lado"><div><div class="cab">{escudo}<div><div class="u">{universidad}</div><div style="font-weight:700">{curso}</div></div></div>
<h1>{producto}</h1><p>Primer agente de apoyo docente para la revisión de código, arquitectura y proceso ágil de los proyectos de la asignatura.</p>
<div class="puntos"><div><span class="n">1</span><div><b>Evidencia de GitHub</b><br>commits, issues, PR, tableros, pipelines, Sonar y Wiki de cada equipo.</div></div>
<div><span class="n">2</span><div><b>Rúbricas del curso</b><br>indicadores por criterio y pre-nota sugerida con su justificación.</div></div>
<div><span class="n">3</span><div><b>El profesor decide</b><br>revisiones bajo demanda, preguntas de sustentación y señales de proceso.</div></div></div></div>
<div class="pie">{facultad}</div></section>
<section class="form"><form method="post" action="" autocomplete="on"><h2>Ingresar</h2><p class="mut">Acceso para profesores y monitores del curso.</p>
{mensaje}<input type="hidden" name="csrf" value="{csrf}"><label for="u">Usuario</label>
<input id="u" name="usuario" autocomplete="username" required autofocus value="{usuario}">
<label for="c">Contraseña</label><input id="c" name="clave" type="password" autocomplete="current-password" required>
<button type="submit">Ingresar</button></form></section></body></html>"""


def pagina_ingreso(mensaje: str = "", tipo: str = "error", usuario: str = "") -> str:
    aviso = f'<div class="{tipo}" role="alert">{html.escape(mensaje)}</div>' if mensaje else ""
    return INGRESO.format(tokens=marca.TOKENS, escudo=marca.escudo(52), universidad=marca.UNIVERSIDAD, curso=marca.CURSO,
                          producto=marca.PRODUCTO, facultad=marca.FACULTAD, mensaje=aviso, usuario=html.escape(usuario), csrf=csrf())


# ---------------------------------------------------------------- aplicación
def crear_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.config.update(
        SECRET_KEY=os.environ["SITIO_SECRETO"],
        SESSION_COOKIE_NAME="fis_sesion", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SITIO_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=int(os.environ.get("SITIO_SESION_HORAS", "12"))),
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    if os.environ.get("FIS_PG_DSN") and not app.config.get("TESTING"):
        preparar_base(os.environ["FIS_PG_DSN"])

    publicas = {"ingresar", "salud", "sesion"}

    @app.teardown_appcontext
    def cerrar(_exc):
        con = g.pop("con", None)
        if con is not None:
            con.close()

    @app.before_request
    def proteger():
        g.usuario = None
        if session.get("login"):
            filas = q("SELECT login, nombre, rol, activo, version FROM portal.usuarios WHERE login = %s", session["login"])
            if filas and filas[0]["activo"] and filas[0]["version"] == session.get("version"):
                g.usuario = {**filas[0], "csrf": csrf()}
            else:
                session.clear()
        if request.endpoint in publicas:
            return None
        if g.usuario is None:
            siguiente = request.full_path.lstrip("/").rstrip("?")
            return redirect(raiz() + "ingresar" + (f"?siguiente={urllib.parse.quote(siguiente)}" if siguiente else ""))
        if request.method == "POST" and not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400)
        return None

    @app.after_request
    def cabeceras(resp):
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; form-action 'self'; "
                                "frame-src 'self'; frame-ancestors 'self'; base-uri 'none'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(403)
    def prohibido(_e):
        return responder("Sin permiso", _hero("Acceso restringido", "Sin permiso", "Esta sección es solo para administradores."), estado=403)

    @app.errorhandler(404)
    def no_existe(_e):
        if g.get("usuario") is None:
            return Response("No encontrado", 404)
        return responder("No encontrado", _hero("404", "No encontrado", f'<a href="{raiz()}">Volver al panorama</a>'), estado=404)

    # ------------------------------------------------------------ sesión
    @app.get("/salud")
    def salud():
        return Response("ok\n", mimetype="text/plain")

    @app.get("/_sesion")
    def sesion():
        return Response(status=204 if g.usuario else 401)

    @app.route("/ingresar", methods=["GET", "POST"])
    def ingresar():
        siguiente = destino_seguro(request.args.get("siguiente", ""))
        if g.usuario:
            return redirect(siguiente or "./")
        if request.method == "GET":
            return Response(pagina_ingreso())
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            return Response(pagina_ingreso("La sesión del formulario expiró. Intente de nuevo."), 400)
        login = request.form.get("usuario", "").strip()[:64]
        clave = request.form.get("clave", "")[:256]
        recientes = q("""SELECT count(*) FILTER (WHERE usuario = %s) AS u, count(*) FILTER (WHERE origen = %s) AS ip
                         FROM portal.auditoria WHERE evento = 'ingreso_fallido' AND fecha > now() - make_interval(mins => %s)""",
                      login, request.remote_addr, VENTANA_MIN)[0]
        if recientes["u"] >= MAX_FALLOS or recientes["ip"] >= MAX_FALLOS * 4:
            return Response(pagina_ingreso("Demasiados intentos fallidos. Espere unos minutos.", usuario=login), 429)
        filas = q("SELECT login, clave, activo, version FROM portal.usuarios WHERE login = %s", login)
        ok = bool(filas) and filas[0]["activo"] and verificar_clave(clave, filas[0]["clave"])
        if not filas:
            verificar_clave(clave, _HASH_FALSO)
        if not ok:
            auditar("ingreso_fallido", "", login)
            return Response(pagina_ingreso("Usuario o contraseña incorrectos.", usuario=login), 401)
        session.clear()
        session.permanent = True
        session.update(login=login, version=filas[0]["version"], csrf=secrets.token_urlsafe(24))
        ejecutar("UPDATE portal.usuarios SET ultimo_ingreso = now() WHERE login = %s", login)
        auditar("ingreso", "", login)
        return redirect(siguiente or "./")

    @app.post("/salir")
    def salir():
        auditar("salida")
        session.clear()
        return redirect("ingresar")

    # ------------------------------------------------------------ datos de las revisiones
    def datos():
        with _con().cursor() as cur:
            from psycopg.rows import tuple_row

            cur.row_factory = tuple_row
            return sitio.Datos(cur)

    def cfg():
        return configuracion.cargar_con(_con())

    @app.get("/")
    def panorama():
        return responder("Panorama", sitio.panorama(datos(), cfg(), raiz()), "")

    @app.get("/agente")
    def agente():
        return responder("El agente", sitio.agente(datos(), cfg(), raiz()), "agente")

    @app.get("/ia")
    def ia():
        return responder("Uso de IA", sitio.uso_ia(datos(), raiz()), "ia")

    @app.get("/estudiantes")
    def estudiantes():
        return responder("Estudiantes", sitio.estudiantes(datos(), raiz()), "estudiantes")

    @app.get("/estudiantes/<login>")
    def estudiante(login):
        cuerpo = sitio.estudiante(datos(), raiz(), login)
        if cuerpo is None:
            abort(404)
        return responder(login, cuerpo, "estudiantes")

    @app.get("/equipos/<eq>")
    def equipo(eq):
        d = datos()
        c = cfg()
        r = raiz()
        acciones = (f'<form method="post" action="{r}revisiones" class="enlinea">{campo_csrf()}'
                    f'<input type="hidden" name="alcance" value="{E(d.repo_de.get(eq, ""))}"><input type="hidden" name="entrega" value="auto">'
                    f'<input type="hidden" name="con_ia" value="1"><input type="hidden" name="sonar_interno" value="{1 if sonar_configurado() else 0}">'
                    f'<button class="btn">Revisar este equipo ahora</button></form>') if eq in d.repo_de else ""
        cuerpo = sitio.equipo(d, r, eq, acciones)
        if cuerpo is None:
            abort(404)
        return responder(eq, cuerpo, "")

    # ------------------------------------------------------------ revisiones bajo demanda
    def chip_estado(e: str) -> str:
        return f'<span class="chip e-{E(e)}">{E(ESTADOS.get(e, e))}</span>'

    @app.get("/revisiones")
    def revisiones():
        r = raiz()
        c = cfg()
        d = datos()
        repos, error = repos_del_periodo(c)
        opciones_ent = "".join(f'<option value="{E(k)}">{E(c["_rubricas"].get(k, {}).get("nombre", k))} · corte {E(v["fecha"])}</option>'
                               for k, v in sorted(c["entregas"].items(), key=lambda kv: kv[1]["fecha"]))
        opciones_rep = "".join(f'<option value="{E(x["repo"])}">{E(x["equipo"])}</option>' for x in repos if not x["excluido"])
        if not repos:
            opciones_rep = "".join(f'<option value="{E(rp)}">{E(eq)}</option>' for eq, rp in d.repo_de.items())
        con_ia = bool((os.environ.get("FIS_IA_DISPONIBLE") or os.environ.get("DEEPSEEK_API_KEY")))
        hay_sonar = sonar_configurado()
        form = f"""<div class="card"><form method="post" action="{r}revisiones" class="f">{campo_csrf()}<div class="campos">
<div><label for="a">Qué revisar</label><select id="a" name="alcance"><option value="todos">Todos los equipos del período</option>{opciones_rep}</select></div>
<div><label for="e">Rúbrica</label><select id="e" name="entrega"><option value="auto">La próxima entrega (automático)</option>{opciones_ent}
<option value="todas">Las tres entregas</option></select></div>
<div><label for="i">Capa de IA</label><select id="i" name="con_ia"><option value="1"{'' if con_ia else ' disabled'}>Con IA (criterios cualitativos y preguntas)</option>
<option value="0"{'' if con_ia else ' selected'}>Solo indicadores (más rápido)</option></select></div>
<div><label for="s">Sonar interno</label><select id="s" name="sonar_interno"><option value="1"{'' if hay_sonar else ' disabled'}>Analizar con el perfil del curso</option>
<option value="0"{'' if hay_sonar else ' selected'}>No</option></select></div></div>
<div><button class="btn">Solicitar revisión</button> <span class="mut" style="font-size:13px">Queda en cola y se ejecuta en orden; cada solicitud guarda su registro.</span></div>
</form></div>"""
        filas_rep = []
        for x in repos:
            rev = d.revisada.get(x["equipo"])
            push = dt.datetime.fromisoformat(x["push"].replace("Z", "+00:00")) if x["push"] else None
            nuevo = push is not None and (rev is None or push > rev)
            estado = ('<span class="chip warn">hay cambios sin revisar</span>' if nuevo
                      else '<span class="chip ok">al día</span>' if rev else '<span class="chip neu">sin revisar</span>')
            boton = (f'<form method="post" action="{r}revisiones" class="enlinea">{campo_csrf()}<input type="hidden" name="alcance" value="{E(x["repo"])}">'
                     f'<input type="hidden" name="entrega" value="auto"><input type="hidden" name="con_ia" value="{1 if con_ia else 0}">'
                     f'<input type="hidden" name="sonar_interno" value="{1 if hay_sonar else 0}">'
                     f'<button class="btn peq">Revisar</button></form>') if not x["excluido"] else '<span class="mut">excluido</span>'
            filas_rep.append([f'<a href="{r}equipos/{E(x["equipo"])}">{E(x["equipo"])}</a>', f"{push:%d/%m/%Y %H:%M}" if push else "—",
                              f"{rev:%d/%m/%Y %H:%M}" if rev else "—", estado, boton])
        sol = q("SELECT id, creada, usuario, origen, alcance, entrega, con_ia, sonar_interno, estado, inicio, fin FROM portal.solicitudes ORDER BY id DESC LIMIT 40")
        filas_sol = [[f'<a href="{r}revisiones/{s["id"]}">#{s["id"]}</a>', f'{s["creada"]:%d/%m %H:%M}', E(s["usuario"]),
                      E(s["alcance"].split("/")[-1] if s["alcance"] != "todos" else "todos"), E(s["entrega"]), ("IA" if s["con_ia"] else "—") + (" · Sonar" if s["sonar_interno"] else ""),
                      chip_estado(s["estado"]),
                      _duracion(s["inicio"], s["fin"])] for s in sol]
        activos = any(s["estado"] in ("pendiente", "en_curso") for s in sol)
        cuerpo = (_hero("Bajo demanda", "Revisiones", "Lance una revisión cuando quiera verificar si los equipos ya actualizaron su repositorio. "
                        "Además, el agente hace una revisión programada según la configuración.")
                  + form + (f'<div class="flash bad">{E(error)}</div>' if error else "")
                  + "<h2>Estado de los repositorios</h2><p class='mut'>Último push en GitHub frente a la última revisión del agente.</p>"
                  + _tabla(["Equipo", "Último push", "Última revisión", "Estado", ""], filas_rep)
                  + "<h2>Historial de solicitudes</h2>" + _tabla(["#", "Creada", "Por", "Alcance", "Rúbrica", "Extras", "Estado", "Duración"], filas_sol))
        return responder("Revisiones", cuerpo, "revisiones", refrescar=10 if activos else 0)

    @app.post("/revisiones")
    def solicitar():
        c = cfg()
        alcance = request.form.get("alcance", "todos")
        entrega = request.form.get("entrega", "auto")
        con_ia = request.form.get("con_ia") == "1" and bool((os.environ.get("FIS_IA_DISPONIBLE") or os.environ.get("DEEPSEEK_API_KEY")))
        sonar = request.form.get("sonar_interno") == "1" and sonar_configurado()
        if entrega not in ("auto", "todas") and entrega not in c["entregas"]:
            abort(400)
        if alcance != "todos" and not (alcance.startswith(c["org"] + "/") and alcance.split("/")[-1].startswith(c["repo_prefijo"])):
            abort(400)
        fila = ejecutar("""INSERT INTO portal.solicitudes (usuario, alcance, entrega, con_ia, sonar_interno) VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                        g.usuario["login"], alcance, entrega, con_ia, sonar)[0]
        auditar("solicitud_revision", f"#{fila['id']} {alcance} {entrega} ia={con_ia} sonar={sonar}")
        avisar(f"Solicitud #{fila['id']} en cola. Esta página se actualiza sola mientras se ejecuta.")
        return redirect(raiz() + f"revisiones/{fila['id']}")

    @app.get("/revisiones/<int:sid>")
    def solicitud(sid):
        filas = q("SELECT * FROM portal.solicitudes WHERE id = %s", sid)
        if not filas:
            abort(404)
        s = filas[0]
        r = raiz()
        activa = s["estado"] in ("pendiente", "en_curso")
        cancelar = (f'<form method="post" action="{r}revisiones/{sid}/cancelar" class="enlinea">{campo_csrf()}'
                    f'<button class="btn peligro">Cancelar</button></form>') if activa and not s["cancelar"] else ""
        cola = q("SELECT count(*) AS n FROM portal.solicitudes WHERE estado = 'pendiente' AND id < %s", sid)[0]["n"] if s["estado"] == "pendiente" else 0
        cuerpo = (_hero(f'<a href="{r}revisiones">Revisiones</a>', f"Solicitud #{sid}",
                        f"{chip_estado(s['estado'])} · pedida por {E(s['usuario'])} el {s['creada']:%d/%m/%Y %H:%M}"
                        + (f" · {cola} solicitud(es) antes en la cola" if cola else ""), cancelar)
                  + _kpis([(E(s["alcance"].split("/")[-1]), "alcance"), (E(s["entrega"]), "rúbrica"), ("sí" if s["con_ia"] else "no", "con IA"), ("sí" if s["sonar_interno"] else "no", "Sonar interno"),
                           (_duracion(s["inicio"], s["fin"]), "duración")])
                  + f'<h2>Registro</h2><pre class="log">{E(s["log"] or "Esperando turno…")}</pre>'
                  + (f'<p><a class="btn sec" href="{r}">Ver el panorama actualizado</a></p>' if s["estado"] == "terminada" else ""))
        return responder(f"Solicitud #{sid}", cuerpo, "revisiones", refrescar=5 if activa else 0)

    @app.post("/revisiones/<int:sid>/cancelar")
    def cancelar(sid):
        ejecutar("""UPDATE portal.solicitudes SET cancelar = true,
                    estado = CASE WHEN estado = 'pendiente' THEN 'cancelada' ELSE estado END,
                    fin = CASE WHEN estado = 'pendiente' THEN now() ELSE fin END WHERE id = %s""", sid)
        auditar("cancelar_revision", f"#{sid}")
        avisar(f"Se pidió cancelar la solicitud #{sid}.")
        return redirect(f"../../revisiones/{sid}")

    # ------------------------------------------------------------ rúbricas
    @app.get("/rubricas")
    def rubricas():
        r = raiz()
        c = cfg()
        d = datos()
        repos, _ = repos_del_periodo(c)
        equipos = [x["equipo"] for x in repos if not x["excluido"]] or list(d.rev_eq)
        hoy = dt.date.today().isoformat()
        tarjetas = []
        for k, v in sorted(c["entregas"].items(), key=lambda kv: kv[1]["fecha"]):
            rub = c["_rubricas"].get(k, {})
            crit = rub.get("criterios", [])
            total = sum(float(x.get("peso", 0)) for x in crit)
            tipos = {t: sum(1 for x in crit if x.get("tipo") == t) for t in configuracion.TIPOS}
            barras = "".join(f'<span>{E(x["nombre"])}</span><b>{float(x["peso"]) * 100:.0f}%</b>'
                             f'<span class="b"><span style="width:{min(float(x["peso"]) * 300, 100):.0f}%"></span></span>' for x in crit)
            estado = "cerrada" if v["fecha"] < hoy else "próxima" if v["fecha"] == min(x["fecha"] for x in c["entregas"].values() if x["fecha"] >= hoy) else "pendiente"
            tarjetas.append(f"""<div class="card ent{' prox' if estado == 'próxima' else ''}"><div class="fila"><h3><a href="{r}rubricas/{E(k)}">{E(rub.get('nombre', k))}</a></h3>
<span class="chip {'warn' if estado == 'próxima' else 'ok' if estado == 'cerrada' else 'neu'}">{estado}</span></div>
<div class="mut" style="font-size:13px">Corte {E(v['fecha'])} · {len(crit)} criterios · {total * 100:.0f}% del peso ·
{tipos['auto']} auto, {tipos['asistido']} asistidos, {tipos['humano']} del profesor</div><div class="peso">{barras}</div>
<p style="margin-top:10px"><a class="btn peq sec" href="{r}rubricas/{E(k)}">Ver detalle</a></p></div>""")
        cuerpo = (_hero(f"Período {E(str(c.get('periodo')))}", "Rúbricas de evaluación",
                        "Cada rúbrica se aplica a todos los equipos del período en su fecha de corte.")
                  + f'<div class="card"><b>Se aplican a {len(equipos)} equipos:</b> '
                  + ", ".join(f'<a href="{r}equipos/{E(e)}">{E(e)}</a>' for e in equipos)
                  + (f' · <a href="{r}admin">administrar equipos y fechas</a>' if es_admin() else "") + "</div>"
                  + f'<div class="lin" style="margin-top:14px">{"".join(tarjetas)}</div>')
        return responder("Rúbricas", cuerpo, "rubricas")

    @app.get("/rubricas/<clave>")
    def rubrica(clave):
        c = cfg()
        rub = c["_rubricas"].get(clave)
        if rub is None:
            abort(404)
        r = raiz()
        bloques = []
        for x in rub["criterios"]:
            checks = ", ".join(E(TITULOS_CHECK.get(ch, ch)) for ch in x.get("checks", []))
            niveles = "".join(f'<div class="nivel"><b>{E(n["nombre"])} · {n["rango"][0]}–{n["rango"][1]}</b>{E(n.get("descripcion", ""))}</div>'
                              for n in x.get("niveles", []))
            conceptos = ", ".join(E(cc) for cc in x.get("conceptos", []))
            bloques.append(f"""<div class="card" style="margin-bottom:12px"><div class="fila"><h3>{E(x['nombre'])}</h3>
<span><span class="chip t-{E(x['tipo'])}">{E(x['tipo'])}</span> <b>{float(x['peso']) * 100:.0f}%</b></span></div>
<div class="mut" style="font-size:13px"><b>Qué verifica el agente:</b> {checks or '—'}{f' · <b>Conceptos:</b> {conceptos}' if conceptos else ''}</div>
<div class="niveles">{niveles}</div></div>""")
        editar = f'<a class="btn sec" href="{r}rubricas/{E(clave)}/editar">Editar rúbrica</a>' if es_admin() else ""
        fecha = c["entregas"].get(clave, {}).get("fecha", "")
        cuerpo = (_hero(f'<a href="{r}rubricas">Rúbricas</a> · corte {E(fecha)}', E(rub["nombre"]),
                        f"{len(rub['criterios'])} criterios · {sum(float(x['peso']) for x in rub['criterios']) * 100:.0f}% del peso del curso. "
                        "auto = medible en GitHub · asistido = indicadores + IA · humano = lo decide el profesor.", editar)
                  + "".join(bloques))
        return responder(rub["nombre"], cuerpo, "rubricas")

    @app.route("/rubricas/<clave>/editar", methods=["GET", "POST"])
    def editar_rubrica(clave):
        solo_admin()
        c = cfg()
        if clave not in c["_rubricas"]:
            abort(404)
        r = raiz()
        texto = yaml.safe_dump(c["_rubricas"][clave], allow_unicode=True, sort_keys=False, width=140)
        errores = []
        if request.method == "POST":
            texto = request.form.get("yaml", "")
            try:
                nueva = yaml.safe_load(texto)
                errores = configuracion.validar_rubrica(nueva, clave)
            except yaml.YAMLError as e:
                errores = [f"YAML inválido: {e}"]
            if not errores:
                configuracion.guardar(_con(), f"rubrica:{clave}", nueva, g.usuario["login"])
                auditar("cambio_rubrica", clave)
                avisar("Rúbrica guardada. Se usará en las próximas revisiones.")
                return redirect(f"../{clave}")
        checks = ", ".join(f"<code>{k}</code>" for k in sorted(TITULOS_CHECK))
        cuerpo = (_hero(f'<a href="{r}rubricas/{E(clave)}">Volver a la rúbrica</a>', f"Editar · {E(c['_rubricas'][clave].get('nombre', clave))}",
                        "Cada cambio queda en el historial con su autor y fecha.")
                  + (f'<div class="flash bad"><b>No se guardó:</b><ul class="lst">{"".join(f"<li>{E(x)}</li>" for x in errores)}</ul></div>' if errores else "")
                  + f"""<div class="card"><form method="post" action="" class="f">{campo_csrf()}
<label for="y">Rúbrica en YAML</label><textarea id="y" name="yaml" spellcheck="false">{E(texto)}</textarea>
<p class="mut" style="font-size:13px">Verificaciones disponibles: {checks}.</p>
<div><button class="btn">Guardar</button> <a class="btn sec" href="{r}rubricas/{E(clave)}">Cancelar</a></div></form></div>""")
        return responder("Editar rúbrica", cuerpo, "rubricas")

    # ------------------------------------------------------------ tableros de Metabase
    @app.get("/tableros")
    @app.get("/tableros/<int:tid>")
    def tableros(tid: int | None = None):
        r = raiz()
        mb = q("SELECT valor FROM portal.config WHERE clave = 'metabase'")
        mb = mb[0]["valor"] if mb else {}
        lista = mb.get("tableros") or []
        if not mb.get("secreto") or not lista:
            cuerpo = _hero("Metabase", "Tableros", "") + ('<div class="aviso">Los tableros aún no están habilitados para mostrarse aquí. '
                                                          'Ejecute <code>sh deploy/instalar.sh</code> en el servidor para configurarlos.</div>')
            return responder("Tableros", cuerpo, "tableros")
        actual = next((t for t in lista if t["id"] == tid), lista[0])
        pestanas = " ".join(f'<a class="btn {"" if t["id"] == actual["id"] else "sec"} peq" href="{r}tableros/{t["id"]}">{E(t["nombre"])}</a>' for t in lista)
        src = f'{r}metabase/embed/dashboard/{token_metabase(mb["secreto"], actual["id"])}#bordered=false&titled=true'
        cuerpo = (_hero("Metabase", "Tableros", "Los mismos datos del agente, con filtros por equipo y entrega.",
                        f'<a class="btn sec peq" href="{r}metabase/">Abrir Metabase completo</a>' if es_admin() else "")
                  + f'<div class="fila" style="justify-content:flex-start;margin-bottom:12px;gap:8px">{pestanas}</div>'
                  + f'<iframe class="tablero" src="{E(src)}" title="{E(actual["nombre"])}" loading="lazy"></iframe>')
        return responder("Tableros", cuerpo, "tableros")

    # ------------------------------------------------------------ SonarQube del curso
    @app.get("/calidad")
    def calidad():
        r = raiz()
        if not sonar_configurado():
            cuerpo = _hero("Calidad del código", "Sonar interno") + ('<div class="aviso">El SonarQube del curso aún no está configurado. '
                                                                     'Ejecute <code>sh deploy/instalar.sh</code> en el servidor.</div>')
            return responder("Sonar", cuerpo, "calidad")
        filas = q("SELECT equipo, clave, quality_gate, commit, entrega, actualizado, error FROM fis.sonar_interno ORDER BY equipo")
        pestanas = " ".join(f'<a class="btn sec peq" href="{r}equipos/{E(x["equipo"])}">{E(x["equipo"])}</a>' for x in filas)
        cuerpo = (_hero("Revisión interna del profesor", "Sonar interno",
                        "SonarQube del curso: el agente analiza cada equipo en el commit de la fecha de corte con el mismo perfil de calidad. "
                        "Sin compilar ni ejecutar pruebas (no mide cobertura; las reglas de Java que requieren bytecode no aplican).")
                  + (f'<div class="fila" style="justify-content:flex-start;gap:8px;margin-bottom:12px">{pestanas}</div>' if filas else "")
                  + f'<iframe class="tablero" src="{r}sonar/projects" title="SonarQube del curso" loading="lazy"></iframe>')
        return responder("Sonar", cuerpo, "calidad")

    # ------------------------------------------------------------ cuenta propia
    @app.route("/cuenta", methods=["GET", "POST"])
    def cuenta():
        r = raiz()
        if request.method == "POST":
            actual, nueva, otra = (request.form.get(k, "") for k in ("actual", "nueva", "otra"))
            fila = q("SELECT clave FROM portal.usuarios WHERE login = %s", g.usuario["login"])[0]
            if not verificar_clave(actual, fila["clave"]):
                avisar("La contraseña actual no es correcta.", "bad")
            elif len(nueva) < 10 or nueva != otra:
                avisar("La nueva contraseña debe tener al menos 10 caracteres y coincidir en los dos campos.", "bad")
            else:
                ejecutar("UPDATE portal.usuarios SET clave = %s, version = version + 1 WHERE login = %s", hash_clave(nueva), g.usuario["login"])
                auditar("clave_cambiada")
                session["version"] = g.usuario["version"] + 1
                avisar("Contraseña actualizada.")
            return redirect("cuenta")
        ingresos = q("SELECT fecha, evento, origen FROM portal.auditoria WHERE usuario = %s AND evento LIKE 'ingreso%%' ORDER BY id DESC LIMIT 10",
                     g.usuario["login"])
        cuerpo = (_hero("Mi cuenta", E(g.usuario["nombre"]), f"Usuario <b>{E(g.usuario['login'])}</b> · rol {E(g.usuario['rol'])}")
                  + f"""<div class="g2"><div class="card"><h3>Cambiar contraseña</h3><form method="post" action="{r}cuenta" class="f">{campo_csrf()}
<div><label for="a">Contraseña actual</label><input id="a" type="password" name="actual" required autocomplete="current-password"></div>
<div><label for="n">Nueva contraseña (mínimo 10 caracteres)</label><input id="n" type="password" name="nueva" required minlength="10" autocomplete="new-password"></div>
<div><label for="o">Repita la nueva contraseña</label><input id="o" type="password" name="otra" required minlength="10" autocomplete="new-password"></div>
<div><button class="btn">Cambiar</button></div></form></div>
<div><h3>Últimos ingresos</h3>{_tabla(["Fecha", "Evento", "Origen"], [[f"{x['fecha']:%d/%m/%Y %H:%M}", E(x["evento"]), E(x["origen"] or "")] for x in ingresos])}</div></div>""")
        return responder("Mi cuenta", cuerpo, "")

    # ------------------------------------------------------------ administración
    @app.get("/admin")
    def admin():
        solo_admin()
        r = raiz()
        c = cfg()
        prog = c.get("programacion") or {}
        repos, error = repos_del_periodo(c)
        excl = set(c.get("repos_excluir") or [])
        filas_ent = "".join(
            f'<div><label for="f_{E(k)}">{E(c["_rubricas"].get(k, {}).get("nombre", k))}</label>'
            f'<input id="f_{E(k)}" type="date" name="fecha_{E(k)}" value="{E(v["fecha"])}" required></div>'
            for k, v in sorted(c["entregas"].items(), key=lambda kv: kv[1]["fecha"]))
        checks_rep = "".join(f'<label style="font-weight:400"><input type="checkbox" name="incluir" value="{E(x["equipo"])}"'
                             f'{"" if x["equipo"] in excl else " checked"}> {E(x["equipo"])}</label>' for x in repos)
        form = f"""<form method="post" action="{r}admin/curso" class="f">{campo_csrf()}
<h3>Curso y período</h3><div class="campos">
<div><label for="cu">Curso</label><input id="cu" type="text" name="curso" value="{E(c.get('curso', ''))}"></div>
<div><label for="pe">Período</label><input id="pe" type="text" name="periodo" value="{E(str(c.get('periodo', '')))}"></div>
<div><label for="or">Organización de GitHub</label><input id="or" type="text" name="org" value="{E(c.get('org', ''))}"></div>
<div><label for="pr">Prefijo de los repos de equipo</label><input id="pr" type="text" name="repo_prefijo" value="{E(c.get('repo_prefijo', ''))}"></div></div>
<h3 style="margin-top:8px">Fechas de corte</h3><div class="campos">{filas_ent}</div>
<h3 style="margin-top:8px">Equipos que se revisan</h3>
<div class="campos">{checks_rep or '<span class="mut">' + E(error or 'No se encontraron repos con ese prefijo.') + '</span>'}</div>
<div><label for="ig">Cuentas que no son estudiantes (monitores, bots), separadas por coma</label>
<input id="ig" type="text" name="ignorar" value="{E(', '.join(c.get('ignorar_usuarios') or []))}"></div>
<h3 style="margin-top:8px">Revisión programada</h3><div class="campos">
<div><label for="pa">Estado</label><select id="pa" name="prog_activa"><option value="1"{' selected' if prog.get('activa', True) else ''}>Activa</option>
<option value="0"{'' if prog.get('activa', True) else ' selected'}>Pausada (solo bajo demanda)</option></select></div>
<div><label for="pi">Cada cuántas horas</label><input id="pi" type="number" min="1" max="168" name="prog_horas" value="{int(prog.get('intervalo_horas', 24))}"></div>
<div><label for="pc">Con IA</label><select id="pc" name="prog_ia"><option value="1"{' selected' if prog.get('con_ia', True) else ''}>Sí</option>
<option value="0"{'' if prog.get('con_ia', True) else ' selected'}>No</option></select></div>
<div><label for="ps">Con Sonar interno</label><select id="ps" name="prog_sonar"><option value="1"{' selected' if prog.get('sonar_interno', True) else ''}>Sí</option>
<option value="0"{'' if prog.get('sonar_interno', True) else ' selected'}>No</option></select></div></div>
<div><button class="btn">Guardar configuración</button> <a class="btn sec" href="{r}admin/avanzado">Configuración avanzada (YAML)</a></div></form>"""
        usuarios = q("SELECT login, nombre, rol, activo, creado, ultimo_ingreso FROM portal.usuarios ORDER BY rol, login")
        filas_u = []
        for u in usuarios:
            propio = u["login"] == g.usuario["login"]
            acciones = "" if propio else (
                f'<form method="post" action="{r}admin/usuarios/{E(u["login"])}/estado" class="enlinea">{campo_csrf()}'
                f'<button class="btn peq sec">{"Desactivar" if u["activo"] else "Activar"}</button></form> '
                f'<form method="post" action="{r}admin/usuarios/{E(u["login"])}/clave" class="enlinea">{campo_csrf()}'
                f'<button class="btn peq sec">Nueva contraseña</button></form>')
            filas_u.append([E(u["login"]), E(u["nombre"]), E(u["rol"]), '<span class="chip ok">activo</span>' if u["activo"] else '<span class="chip neu">inactivo</span>',
                            f"{u['ultimo_ingreso']:%d/%m/%Y %H:%M}" if u["ultimo_ingreso"] else "—", acciones])
        nuevo = f"""<form method="post" action="{r}admin/usuarios" class="f" style="margin-top:12px">{campo_csrf()}<div class="campos">
<div><label for="nl">Usuario</label><input id="nl" type="text" name="login" required pattern="[A-Za-z0-9._@-]{{3,64}}"></div>
<div><label for="nn">Nombre</label><input id="nn" type="text" name="nombre" required></div>
<div><label for="nr">Rol</label><select id="nr" name="rol"><option value="colega">Colega (consulta y revisiones)</option><option value="admin">Administrador</option></select></div></div>
<div><button class="btn">Crear usuario</button> <span class="mut" style="font-size:13px">La contraseña se genera y se muestra una sola vez.</span></div></form>"""
        audit = q("SELECT fecha, usuario, evento, detalle, origen FROM portal.auditoria ORDER BY id DESC LIMIT 30")
        cuerpo = (_hero("Solo administradores", "Administración del agente")
                  + f'<div class="card">{form}</div>'
                  + "<h2>Usuarios</h2>" + _tabla(["Usuario", "Nombre", "Rol", "Estado", "Último ingreso", ""], filas_u)
                  + f'<div class="card" style="margin-top:12px"><h3>Nuevo usuario</h3>{nuevo}</div>'
                  + "<h2>Auditoría</h2><p class='mut'>Ingresos, solicitudes de revisión y cambios de configuración.</p>"
                  + _tabla(["Fecha", "Usuario", "Evento", "Detalle", "Origen"],
                           [[f"{a['fecha']:%d/%m %H:%M}", E(a["usuario"] or ""), E(a["evento"]), E(a["detalle"] or ""), E(a["origen"] or "")] for a in audit]))
        return responder("Administración", cuerpo, "admin")

    @app.post("/admin/curso")
    def admin_curso():
        solo_admin()
        c = configuracion.sin_rubricas(cfg())
        f = request.form
        for campo in ("curso", "periodo", "org", "repo_prefijo"):
            if f.get(campo, "").strip():
                c[campo] = f[campo].strip()
        for k in c["entregas"]:
            if f.get(f"fecha_{k}"):
                c["entregas"][k]["fecha"] = f[f"fecha_{k}"]
        repos, error = repos_del_periodo(c)
        if repos and not error:
            incluidos = set(f.getlist("incluir"))
            c["repos_excluir"] = sorted(x["equipo"] for x in repos if x["equipo"] not in incluidos)
        c["ignorar_usuarios"] = [x.strip() for x in f.get("ignorar", "").split(",") if x.strip()]
        c["programacion"] = {"activa": f.get("prog_activa") == "1", "intervalo_horas": max(1, min(168, int(f.get("prog_horas") or 24))),
                             "con_ia": f.get("prog_ia") == "1", "sonar_interno": f.get("prog_sonar") == "1"}
        errores = configuracion.validar_curso(c)
        if errores:
            avisar("No se guardó: " + " ".join(errores), "bad")
        else:
            configuracion.guardar(_con(), "curso", c, g.usuario["login"])
            _cache_repos["t"] = 0
            auditar("cambio_config", "curso")
            avisar("Configuración guardada.")
        return redirect("../admin")

    @app.route("/admin/avanzado", methods=["GET", "POST"])
    def admin_avanzado():
        solo_admin()
        r = raiz()
        c = configuracion.sin_rubricas(cfg())
        texto = yaml.safe_dump(c, allow_unicode=True, sort_keys=False, width=140)
        errores = []
        if request.method == "POST":
            texto = request.form.get("yaml", "")
            try:
                nuevo = yaml.safe_load(texto)
                errores = configuracion.validar_curso(nuevo) if isinstance(nuevo, dict) else ["Debe ser un objeto YAML."]
                if not errores and set(nuevo["entregas"]) != set(c["entregas"]):
                    errores.append("No se pueden agregar ni quitar entregas aquí: cada entrega necesita su rúbrica.")
            except yaml.YAMLError as e:
                errores = [f"YAML inválido: {e}"]
            if not errores:
                configuracion.guardar(_con(), "curso", nuevo, g.usuario["login"])
                auditar("cambio_config", "curso (avanzado)")
                avisar("Configuración guardada.")
                return redirect("../admin")
        cuerpo = (_hero(f'<a href="{r}admin">Administración</a>', "Configuración avanzada",
                        "Estructura esperada del repositorio, secciones del README, umbrales de señales y demás parámetros.")
                  + (f'<div class="flash bad"><ul class="lst">{"".join(f"<li>{E(x)}</li>" for x in errores)}</ul></div>' if errores else "")
                  + f"""<div class="card"><form method="post" action="" class="f">{campo_csrf()}
<label for="y">Configuración del curso (YAML)</label><textarea id="y" name="yaml" spellcheck="false">{E(texto)}</textarea>
<div><button class="btn">Guardar</button> <a class="btn sec" href="{r}admin">Cancelar</a></div></form></div>""")
        return responder("Configuración avanzada", cuerpo, "admin")

    @app.post("/admin/usuarios")
    def admin_crear_usuario():
        solo_admin()
        login = request.form.get("login", "").strip()
        nombre = request.form.get("nombre", "").strip()[:120]
        rol = "admin" if request.form.get("rol") == "admin" else "colega"
        import re

        if not re.fullmatch(r"[A-Za-z0-9._@-]{3,64}", login) or not nombre:
            avisar("Usuario inválido: 3 a 64 caracteres (letras, números, . _ @ -) y un nombre.", "bad")
            return redirect("../admin")
        if q("SELECT 1 FROM portal.usuarios WHERE login = %s", login):
            avisar(f"El usuario {login} ya existe.", "bad")
            return redirect("../admin")
        clave = generar_clave()
        crear_usuario(_con(), login, nombre, clave, rol)
        auditar("usuario_creado", f"{login} ({rol})")
        avisar(f"Usuario <b>{E(login)}</b> creado. Contraseña inicial: <code>{E(clave)}</code> — compártala por un canal seguro; "
               "no se volverá a mostrar y el usuario puede cambiarla en «Mi cuenta».")
        return redirect("../admin")

    @app.post("/admin/usuarios/<login>/estado")
    def admin_estado(login):
        solo_admin()
        if login == g.usuario["login"]:
            abort(400)
        fila = ejecutar("UPDATE portal.usuarios SET activo = NOT activo, version = version + 1 WHERE login = %s RETURNING activo", login)
        if not fila:
            abort(404)
        auditar("usuario_" + ("activado" if fila[0]["activo"] else "desactivado"), login)
        avisar(f"Usuario {E(login)} {'activado' if fila[0]['activo'] else 'desactivado'}.")
        return redirect("../../../admin")

    @app.post("/admin/usuarios/<login>/clave")
    def admin_clave(login):
        solo_admin()
        clave = generar_clave()
        fila = ejecutar("UPDATE portal.usuarios SET clave = %s, version = version + 1 WHERE login = %s RETURNING login", hash_clave(clave), login)
        if not fila:
            abort(404)
        auditar("clave_restablecida", login)
        avisar(f"Nueva contraseña para <b>{E(login)}</b>: <code>{E(clave)}</code> — no se volverá a mostrar.")
        return redirect("../../../admin")

    return app


def _duracion(inicio, fin) -> str:
    if not inicio:
        return "—"
    seg = int(((fin or dt.datetime.now(inicio.tzinfo)) - inicio).total_seconds())
    return f"{seg // 60} min {seg % 60:02d} s"
