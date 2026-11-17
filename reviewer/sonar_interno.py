"""Análisis interno del profesor con el SonarQube propio del curso.

A diferencia de la lectura de SonarCloud (lo que el equipo configuró en su pipeline), aquí el agente
analiza el código de cada equipo **en el commit de la fecha de corte** con el mismo perfil de calidad
para todos, aunque el equipo no haya configurado Sonar.

Seguridad: el código de los estudiantes nunca se ejecuta (no se compila ni se instalan dependencias)
y el escáner corre sin las credenciales del agente; solo recibe el token de análisis de SonarQube.
Limitación: sin compilar, las reglas de Java que necesitan bytecode no se aplican, y la cobertura
de pruebas no se mide (para eso sigue sirviendo el SonarCloud del equipo).
"""
from __future__ import annotations

import base64
import datetime as dt
import os
import shutil
import subprocess
import tempfile
import time

from .collect import _sonar_get, leer_proyecto

ESCANER = os.environ.get("SONAR_SCANNER", "/opt/sonar-scanner/bin/sonar-scanner")
EXCLUSIONES = ("**/node_modules/**,**/build/**,**/target/**,**/dist/**,**/out/**,**/.venv/**,**/venv/**,"
               "**/vendor/**,**/*.min.js,**/*.min.css,**/coverage/**,**/.gradle/**,**/.idea/**")


def configuracion() -> dict | None:
    """URL y token del SonarQube del curso (los deja `deploy/sonar_setup.py` en portal.config)."""
    dsn = os.environ.get("FIS_PG_DSN")
    if not dsn:
        return None
    import psycopg

    with psycopg.connect(dsn) as con:
        fila = con.execute("SELECT valor FROM portal.config WHERE clave = 'sonar_interno'").fetchone()
    return fila[0] if fila and fila[0].get("token") else None


def _commit_de_corte(ev: dict) -> str | None:
    rama = ev["meta"]["rama_principal"]
    return next((c["sha"] for c in ev["commits"] if rama in c.get("ramas", [])), None)


def _clonar(repo: str, sha: str, destino: str) -> None:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": destino, "GIT_TERMINAL_PROMPT": "0"}
    token = os.environ.get("FIS_GH_TOKEN")
    if token:  # por variables de entorno, no en la línea de comandos
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0="Authorization: Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode())
    codigo = os.path.join(destino, "codigo")
    for cmd in (["git", "init", "-q", codigo], ["git", "-C", codigo, "fetch", "-q", "--depth", "1", f"https://github.com/{repo}.git", sha],
                ["git", "-C", codigo, "checkout", "-q", "FETCH_HEAD"]):
        subprocess.run(cmd, check=True, env=env, timeout=600, capture_output=True)


def analizar(ev: dict, entrega: str) -> dict | None:
    """Analiza el repo en el commit de corte y devuelve el mismo formato que la lectura de SonarCloud."""
    conf = configuracion()
    if not conf:
        return None
    sha = _commit_de_corte(ev)
    if not sha:
        return {"error": "No se encontró el commit de la fecha de corte."}
    repo = ev["repo"]
    clave = "fis-interno_" + repo.split("/")[-1]
    url, token = conf["url"], conf["token"]
    base = tempfile.mkdtemp(prefix="fis-sonar-")
    try:
        _clonar(repo, sha, base)
        codigo = os.path.join(base, "codigo")
        # Perfil común del curso: se ignora la configuración de Sonar que traiga el equipo.
        for raiz_, _dirs, archivos in os.walk(codigo):
            for nombre in archivos:
                if nombre in ("sonar-project.properties", ".sonarcloud.properties"):
                    os.remove(os.path.join(raiz_, nombre))
        vacio = os.path.join(base, "sin-binarios")
        os.makedirs(vacio)
        args = [ESCANER, f"-Dsonar.host.url={url}", f"-Dsonar.projectKey={clave}", f"-Dsonar.projectName={repo.split('/')[-1]} (interno)",
                f"-Dsonar.projectVersion={entrega} · {sha[:7]}", "-Dsonar.sources=.", f"-Dsonar.exclusions={EXCLUSIONES}",
                f"-Dsonar.java.binaries={vacio}", "-Dsonar.scm.disabled=true", "-Dsonar.sourceEncoding=UTF-8",
                f"-Dsonar.working.directory={os.path.join(base, 'scannerwork')}"]
        env = {"PATH": os.environ.get("PATH", ""), "HOME": base, "SONAR_TOKEN": token, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
               "SONAR_SCANNER_OPTS": "-Xmx2g -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8",
               "SONAR_USER_HOME": os.path.join(base, "sonar-home")}
        r = subprocess.run(args, cwd=codigo, env=env, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            return {"error": "El escáner falló: " + (r.stdout + r.stderr)[-600:].strip()}
        tarea = None
        with open(os.path.join(base, "scannerwork", "report-task.txt"), encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("ceTaskId="):
                    tarea = linea.split("=", 1)[1].strip()
        for _ in range(180):  # el servidor procesa el informe en segundo plano
            estado = ((_sonar_get(url, token, "/api/ce/task", {"id": tarea}) or {}).get("task") or {}).get("status")
            if estado in ("SUCCESS", "FAILED", "CANCELED"):
                break
            time.sleep(5)
        if estado != "SUCCESS":
            return {"error": f"SonarQube no terminó de procesar el análisis (estado {estado})."}
        info = leer_proyecto(url, token, clave, dt.date.today().isoformat()) or {}
        info.update(servidor="SonarQube del curso", commit=sha, analizado=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        return info
    except subprocess.TimeoutExpired:
        return {"error": "El análisis superó el tiempo máximo."}
    except subprocess.CalledProcessError as e:
        return {"error": f"No se pudo descargar el código en {sha[:7]}: {(e.stderr or b'').decode(errors='replace')[-300:]}"}
    finally:
        shutil.rmtree(base, ignore_errors=True)
