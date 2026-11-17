"""Línea de comandos del agente revisor.

    python -m reviewer revisar --repo puj-course/FIS_2630_1204_G1 --entrega entrega1
    python -m reviewer revisar-todos --entrega auto --ia
    python -m reviewer revisar-todos --entrega auto --ia --publicar
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import traceback

import yaml

from . import checks, ia, report
from .collect import collect, descubrir_repos, detectar_monitores
from .github import GitHub, GitHubError
from .llm import DeepSeek
from .store import Almacen

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cargar_yaml(ruta: str) -> dict:
    with open(ruta if os.path.isabs(ruta) else os.path.join(RAIZ, ruta), encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_env() -> None:
    """Lee el archivo .env de la raíz (si existe) sin pisar variables ya definidas."""
    ruta = os.path.join(RAIZ, ".env")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            clave, sep, valor = linea.strip().partition("=")
            if sep and clave and not clave.startswith("#") and valor.strip() and clave not in os.environ:
                os.environ[clave] = valor.strip()


def elegir_entrega(cfg: dict, pedida: str) -> str:
    """`auto` = la próxima entrega cuya fecha aún no pasó (o la última)."""
    if pedida != "auto":
        if pedida not in cfg["entregas"]:
            sys.exit(f"Entrega desconocida: {pedida}. Opciones: {', '.join(cfg['entregas'])}, auto")
        return pedida
    hoy = dt.date.today().isoformat()
    ordenadas = sorted(cfg["entregas"].items(), key=lambda kv: kv[1]["fecha"])
    return next((k for k, v in ordenadas if v["fecha"] >= hoy), ordenadas[-1][0])


def revisar_repo(gh: GitHub, llm: DeepSeek, cfg: dict, repo: str, entrega: str, args, almacen=None) -> dict:
    rubrica = cargar_yaml(cfg["entregas"][entrega]["rubrica"])
    # Antes de la fecha de entrega se revisa "a hoy"; después, la foto del día de la entrega.
    hasta = args.hasta or min(cfg["entregas"][entrega]["fecha"], dt.date.today().isoformat())
    carpeta = os.path.join(args.salida, repo.split("/")[-1], entrega)
    if args.evidencia:
        with open(args.evidencia, encoding="utf-8") as f:
            ev = json.load(f)
    else:
        ev = collect(gh, repo, hasta, con_wiki=not args.sin_wiki)
    res = checks.evaluar(rubrica, ev, cfg)
    res["uso_ia"] = ia.refinar(gh, repo, res["uso_ia"])
    if args.ia:
        if llm.disponible:
            from . import qualitative

            try:
                qualitative.evaluar_criterios(llm, ev, res)
                qualitative.preguntas_sustentacion(llm, gh, ev, res, cfg)
            except RuntimeError as e:
                res["avisos"].append(f"La capa de IA falló y se omitió: {e}")
        else:
            res["avisos"].append("Se pidió IA pero no hay DEEPSEEK_API_KEY configurada.")
    rutas = report.guardar(res, ev, carpeta)
    if almacen is not None and almacen.activo:
        almacen.guardar(res, ev, cfg)
    # Sin notas en la salida: los registros de Actions de un repo público son públicos.
    print(f"  {repo}: listo -> {rutas['profesor.md']}", flush=True)
    if args.publicar:
        publicar(gh, cfg, repo, rutas["equipo.md"])
    return res


def publicar(gh: GitHub, cfg: dict, repo: str, ruta_md: str) -> None:
    """Agrega el informe formativo como comentario en la bitácora del repo del equipo."""
    if not gh.token:
        sys.exit("Para publicar se necesita FIS_GH_TOKEN con permiso de escritura de issues.")
    etiqueta = cfg.get("etiqueta_bitacora", "fis-reviewer")
    with open(ruta_md, encoding="utf-8") as f:
        cuerpo = f.read()
    abiertas = gh.get(f"/repos/{repo}/issues", {"labels": etiqueta, "state": "open"}) or []
    if abiertas:
        numero = abiertas[0]["number"]
    else:
        if gh.get(f"/repos/{repo}/labels/{etiqueta}", opcional=True) is None:
            gh.post(f"/repos/{repo}/labels", {"name": etiqueta, "color": "5319e7",
                                              "description": "Bitácora del agente revisor de FIS"})
        numero = gh.post(f"/repos/{repo}/issues", {
            "title": "🤖 Bitácora de revisión formativa FIS",
            "labels": [etiqueta],
            "body": "Aquí el agente del curso deja, en cada revisión, lo que se ve en el repositorio frente a la "
                    "rúbrica. No es una nota. Esta issue no cuenta en las métricas del equipo: no la cierren.",
        })["number"]
    gh.post(f"/repos/{repo}/issues/{numero}/comments", {"body": cuerpo[:64000]})
    print(f"    publicado en {repo}#{numero}")


def administrar_usuarios(accion: str, login: str | None) -> int:
    """Cuentas de colegas para el sitio (además del usuario principal de deploy/.env)."""
    import getpass

    from . import acceso

    if accion == "listar":
        principal = os.environ.get("SITIO_USUARIO") or "profesor"
        print(f"{principal} (principal, en deploy/.env)")
        for u in sorted(acceso.leer_usuarios()):
            print(u)
        return 0
    if not login:
        sys.exit("Indique el usuario: python -m reviewer usuario agregar <usuario>")
    if accion == "quitar":
        acceso.guardar_usuario(login, None)
        print(f"Usuario {login} eliminado.")
        return 0
    clave = os.environ.get("CLAVE_NUEVA")
    if not clave:
        if sys.stdin.isatty():
            clave = getpass.getpass(f"Contraseña para {login} (mínimo 10 caracteres; vacía = generar una): ")
        if not clave:
            import secrets

            clave = secrets.token_urlsafe(12)
            print(f"Contraseña generada para {login}: {clave}")
    if len(clave) < 10:
        sys.exit("La contraseña debe tener al menos 10 caracteres.")
    acceso.guardar_usuario(login, clave)
    print(f"Usuario {login} listo. Ya puede ingresar al sitio.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="reviewer", description="Agente revisor formativo de FIS")
    sub = p.add_subparsers(dest="comando", required=True)
    for nombre in ("revisar", "revisar-todos"):
        s = sub.add_parser(nombre)
        if nombre == "revisar":
            s.add_argument("--repo", required=True, help="org/nombre")
            s.add_argument("--evidencia", help="reutilizar un evidencia.json ya recolectado")
        s.add_argument("--entrega", default="auto")
        s.add_argument("--hasta", help="fecha de corte YYYY-MM-DD (por defecto, la de la entrega o hoy)")
        s.add_argument("--config", default="config/course.yaml")
        s.add_argument("--salida", default="salida")
        s.add_argument("--ia", action="store_true", help="usar DeepSeek para los criterios cualitativos")
        s.add_argument("--publicar", action="store_true", help="comentar el informe formativo en el repo del equipo")
        s.add_argument("--sin-wiki", action="store_true")
    s = sub.add_parser("sitio", help="generar el sitio web del profesor desde PostgreSQL")
    s.add_argument("--salida", default="salida/sitio")
    s.add_argument("--config", default="config/course.yaml")
    s = sub.add_parser("acceso", help="servicio de ingreso (inicio de sesión) del sitio del profesor")
    s.add_argument("--puerto", type=int, default=8000)
    s = sub.add_parser("usuario", help="administrar las cuentas de colegas en el sitio del profesor")
    s.add_argument("accion", choices=["agregar", "quitar", "listar"])
    s.add_argument("login", nargs="?")
    args = p.parse_args(argv)
    if args.comando == "revisar-todos":
        args.evidencia = None

    cargar_env()
    if args.comando == "acceso":
        from . import acceso

        acceso.servir(args.puerto)
        return 0
    if args.comando == "usuario":
        return administrar_usuarios(args.accion, args.login)
    if args.comando == "sitio":
        from . import sitio

        dsn = os.environ.get("FIS_PG_DSN")
        if not dsn:
            sys.exit("Falta FIS_PG_DSN para generar el sitio.")
        cfg = cargar_yaml(args.config)
        rubricas = {k: cargar_yaml(v["rubrica"]) for k, v in cfg.get("entregas", {}).items()}
        n = sitio.generar(dsn, args.salida, cfg, rubricas)
        print(f"Sitio generado en {args.salida} ({n} estudiantes)")
        return 0
    cfg = cargar_yaml(args.config)
    gh, llm = GitHub(), DeepSeek()
    # `todas` revisa las tres entregas, cada una con su fecha de corte.
    entregas = sorted(cfg["entregas"], key=lambda k: cfg["entregas"][k]["fecha"]) if args.entrega == "todas"         else [elegir_entrega(cfg, args.entrega)]
    con_ia = args.ia and llm.disponible
    almacen = Almacen()
    fallos = 0
    try:
        if args.comando == "revisar":
            repos = [args.repo]
        else:
            repos = descubrir_repos(gh, cfg["org"], cfg["repo_prefijo"], cfg.get("repos_excluir", []))
            # Monitores y profesor: están en todos los repos del período. No cuentan como integrantes.
            if cfg.get("detectar_monitores", True):
                monitores = detectar_monitores(gh, repos)
                ya = {u.lower() for u in cfg.get("ignorar_usuarios", [])}
                nuevos = [m for m in monitores if m.lower() not in ya]
                cfg["ignorar_usuarios"] = list(cfg.get("ignorar_usuarios", [])) + nuevos
                if monitores:
                    print(f"Cuentas presentes en todos los repos (se excluyen como monitores): {', '.join(monitores)}", flush=True)
        if almacen.activo:
            almacen.iniciar_corrida(con_ia)
        for entrega in entregas:
            print(f"Revisando {len(repos)} repositorio(s) contra {entrega}" + (" con IA" if con_ia else ""), flush=True)
            resultados = []
            for repo in repos:
                try:
                    resultados.append(revisar_repo(gh, llm, cfg, repo, entrega, args, almacen))
                except Exception as e:  # un repo con problemas no detiene a los demás
                    fallos += 1
                    print(f"  {repo}: ERROR {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                    if not isinstance(e, GitHubError):
                        traceback.print_exc()
            nombre = "index.html" if len(entregas) == 1 else f"index-{entrega}.html"
            report.tablero(resultados, os.path.join(args.salida, nombre))
    finally:
        for error in almacen.errores:
            print(f"AVISO almacenamiento: {error}", file=sys.stderr)
        almacen.cerrar()
        print(f"Llamadas a la API de GitHub: {gh.llamadas}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
