"""Ingreso al sitio del profesor: página de inicio de sesión y verificación de la sesión.

Corre como un servicio HTTP pequeño (solo biblioteca estándar) detrás del nginx del sitio:

    GET  /verificar   nginx lo consulta en cada petición (auth_request): 204 con sesión válida, 401 sin ella
    GET  <cualquier>  página de ingreso (nginx la sirve en lugar de la página protegida)
    POST <cualquier>  valida usuario y contraseña, crea la sesión y recarga la página pedida
    GET  /salir       cierra la sesión

Usuarios:
  - el principal, de SITIO_USUARIO / SITIO_PASSWORD (deploy/.env);
  - colegas, en /datos/auth/usuarios (una línea `usuario:pbkdf2_sha256$iteraciones$sal$hash`),
    que se administran con `python -m reviewer usuario agregar <usuario>`.

La sesión es una cookie firmada con HMAC (SITIO_SECRETO), HttpOnly, SameSite=Lax y Secure cuando
el proxy reverso indica HTTPS (X-Forwarded-Proto). No guarda estado en el servidor.

    python -m reviewer acceso --puerto 8000
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import marca

COOKIE = "fis_sesion"
DURACION = int(os.environ.get("SITIO_SESION_HORAS", "12")) * 3600
ITERACIONES = 310_000
RUTA_USUARIOS = os.environ.get("SITIO_USUARIOS", "/datos/auth/usuarios")
MAX_FALLOS, BLOQUEO = 5, 300  # 5 intentos fallidos por usuario => 5 minutos de espera


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


def leer_usuarios(ruta: str | None = None) -> dict[str, str]:
    ruta = ruta or RUTA_USUARIOS
    usuarios = {}
    try:
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                u, sep, h = linea.strip().partition(":")
                if sep and u and not u.startswith("#"):
                    usuarios[u] = h
    except FileNotFoundError:
        pass
    return usuarios


def guardar_usuario(usuario: str, clave: str | None, ruta: str | None = None) -> None:
    """Agrega o cambia (clave) o elimina (clave=None) un usuario del archivo."""
    ruta = ruta or RUTA_USUARIOS
    if not usuario or ":" in usuario or any(c.isspace() for c in usuario):
        raise ValueError("Usuario inválido: sin espacios ni dos puntos.")
    usuarios = leer_usuarios(ruta)
    if clave is None:
        usuarios.pop(usuario, None)
    else:
        usuarios[usuario] = hash_clave(clave)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        f.write("".join(f"{u}:{h}\n" for u, h in sorted(usuarios.items())))
    os.chmod(temporal, 0o640)
    os.replace(temporal, ruta)


def autenticar(usuario: str, clave: str) -> bool:
    principal, clave_principal = os.environ.get("SITIO_USUARIO") or "profesor", os.environ.get("SITIO_PASSWORD") or ""
    if clave_principal and hmac.compare_digest(usuario.encode(), principal.encode()):
        return hmac.compare_digest(clave.encode(), clave_principal.encode())
    guardado = leer_usuarios().get(usuario)
    if guardado is None:
        verificar_clave(clave, hash_clave("x", 1000))  # tiempo parecido para usuarios inexistentes
        return False
    return verificar_clave(clave, guardado)


# ---------------------------------------------------------------- sesión
def _secreto() -> bytes:
    s = os.environ.get("SITIO_SECRETO")
    if not s:
        raise RuntimeError("Falta SITIO_SECRETO (ejecute deploy/instalar.sh).")
    return s.encode()


def crear_sesion(usuario: str, ahora: float | None = None) -> str:
    vence = int((ahora or time.time()) + DURACION)
    datos = base64.urlsafe_b64encode(f"{usuario}|{vence}".encode()).decode().rstrip("=")
    firma = hmac.new(_secreto(), datos.encode(), hashlib.sha256).hexdigest()
    return f"{datos}.{firma}"


def leer_sesion(valor: str, ahora: float | None = None) -> str | None:
    """Usuario de una sesión válida y vigente, o None."""
    try:
        datos, firma = valor.rsplit(".", 1)
        if not hmac.compare_digest(firma, hmac.new(_secreto(), datos.encode(), hashlib.sha256).hexdigest()):
            return None
        usuario, vence = base64.urlsafe_b64decode(datos + "=" * (-len(datos) % 4)).decode().rsplit("|", 1)
        return usuario if int(vence) > (ahora or time.time()) else None
    except (ValueError, UnicodeDecodeError):
        return None


def _cookie(cabecera: str | None) -> str:
    for parte in (cabecera or "").split(";"):
        k, _, v = parte.strip().partition("=")
        if k == COOKIE:
            return v
    return ""


# ---------------------------------------------------------------- página
PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
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
.pie{{font-size:12px;opacity:.7}}
.form{{display:grid;place-items:center;padding:32px 20px}}
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
<div class="puntos"><div><span class="n">1</span><div><b>Evidencia de GitHub</b><br>commits, issues, PR, tableros, pipelines y Wiki de cada equipo.</div></div>
<div><span class="n">2</span><div><b>Rúbricas del curso</b><br>indicadores por criterio y pre-nota sugerida con su justificación.</div></div>
<div><span class="n">3</span><div><b>El profesor decide</b><br>preguntas de sustentación y señales de proceso para la evaluación oral.</div></div></div></div>
<div class="pie">{facultad}</div></section>
<section class="form"><form method="post" action="" autocomplete="on"><h2>Ingresar</h2><p class="mut">Acceso para profesores y monitores del curso.</p>
{mensaje}<label for="u">Usuario</label><input id="u" name="usuario" autocomplete="username" required autofocus value="{usuario}">
<label for="c">Contraseña</label><input id="c" name="clave" type="password" autocomplete="current-password" required>
<button type="submit">Ingresar</button></form></section></body></html>"""


def pagina_ingreso(mensaje: str = "", tipo: str = "error", usuario: str = "") -> str:
    aviso = f'<div class="{tipo}" role="alert">{html.escape(mensaje)}</div>' if mensaje else ""
    return PAGINA.format(tokens=marca.TOKENS, escudo=marca.escudo(52), universidad=marca.UNIVERSIDAD, curso=marca.CURSO,
                         producto=marca.PRODUCTO, facultad=marca.FACULTAD, mensaje=aviso, usuario=html.escape(usuario))


RECARGA = ('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0">'
           '<title>Ingresando…</title><p style="font-family:sans-serif">Ingresando…</p>')


# ---------------------------------------------------------------- servidor
class _Fallos:
    def __init__(self):
        self._d: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def bloqueado(self, clave: str) -> bool:
        with self._lock:
            n, desde = self._d.get(clave, (0, 0.0))
            if n >= MAX_FALLOS and time.time() - desde < BLOQUEO:
                return True
            if n >= MAX_FALLOS:
                self._d.pop(clave, None)
            return False

    def registrar(self, clave: str, ok: bool) -> None:
        with self._lock:
            if ok:
                self._d.pop(clave, None)
            else:
                n, _ = self._d.get(clave, (0, 0.0))
                self._d[clave] = (n + 1, time.time())


FALLOS = _Fallos()


class Manejador(BaseHTTPRequestHandler):
    server_version = "acceso"
    sys_version = ""

    def log_message(self, formato, *args):  # sin contraseñas ni cookies en los registros
        if not self.path.startswith("/verificar"):
            super().log_message(formato, *args)

    def _responder(self, codigo: int, cuerpo: str = "", cabeceras: dict | None = None) -> None:
        datos = cuerpo.encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(datos)

    def _cookie_sesion(self, valor: str, edad: int) -> str:
        https = self.headers.get("X-Forwarded-Proto", "").lower() == "https" or os.environ.get("SITIO_HTTPS") == "1"
        segura = "; Secure" if https else ""
        return f"{COOKIE}={valor}; Path=/; Max-Age={edad}; HttpOnly; SameSite=Lax{segura}"

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        ruta = urllib.parse.urlsplit(self.path).path
        if ruta == "/verificar":
            usuario = leer_sesion(_cookie(self.headers.get("Cookie")))
            return self._responder(204 if usuario else 401, cabeceras={"X-Usuario": usuario} if usuario else None)
        if ruta.rstrip("/").endswith("/salir") or ruta == "/salir":
            return self._responder(200, pagina_ingreso("Sesión cerrada.", "info"),
                                   {"Set-Cookie": self._cookie_sesion("", 0)})
        return self._responder(200, pagina_ingreso())

    def do_POST(self):
        largo = min(int(self.headers.get("Content-Length") or 0), 4096)
        datos = urllib.parse.parse_qs(self.rfile.read(largo).decode("utf-8", "replace"))
        usuario = (datos.get("usuario") or [""])[0].strip()[:64]
        clave = (datos.get("clave") or [""])[0][:256]
        if FALLOS.bloqueado(usuario):
            return self._responder(429, pagina_ingreso("Demasiados intentos fallidos. Espere unos minutos.", usuario=usuario))
        ok = bool(usuario and clave) and autenticar(usuario, clave)
        FALLOS.registrar(usuario, ok)
        if not ok:
            self.log_message("ingreso fallido de %r", usuario)
            return self._responder(401, pagina_ingreso("Usuario o contraseña incorrectos.", usuario=usuario))
        self.log_message("ingreso de %r", usuario)
        # 200 + recarga: vuelve a pedir la misma URL con GET, ya con sesión, sin importar el prefijo del proxy.
        return self._responder(200, RECARGA, {"Set-Cookie": self._cookie_sesion(crear_sesion(usuario), DURACION)})


def servir(puerto: int = 8000) -> None:
    _secreto()
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)
    print(f"Servicio de ingreso en el puerto {puerto}", flush=True)
    servidor.serve_forever()
