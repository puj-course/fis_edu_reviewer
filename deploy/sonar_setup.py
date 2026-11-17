"""Configura el SonarQube del curso para el análisis interno del agente. Idempotente.

- Cambia la contraseña inicial del administrador (admin/admin) por SONAR_ADMIN_PASSWORD.
- Lectura sin iniciar sesión en SonarQube: solo se llega a él a través del portal (/sonar/), que ya
  exige sesión; así el profesor y los colegas ven los proyectos sin una segunda cuenta.
- Genera el token del agente y lo guarda en portal.config ('sonar_interno').
Variables: SONAR_URL (http://sonarqube:9000/sonar), SONAR_ADMIN_PASSWORD, FIS_PG_DSN.
"""
from __future__ import annotations

import os
import sys
import time

import requests

URL = os.environ.get("SONAR_URL", "http://sonarqube:9000/sonar").rstrip("/")
CLAVE = os.environ["SONAR_ADMIN_PASSWORD"]


def esperar() -> None:
    for _ in range(120):
        try:
            if requests.get(f"{URL}/api/system/status", timeout=10).json().get("status") == "UP":
                return
        except (requests.RequestException, ValueError):
            pass
        time.sleep(5)
    sys.exit("SonarQube no arrancó; revise: docker compose logs sonarqube")


def sesion() -> requests.Session:
    s = requests.Session()
    s.auth = ("admin", CLAVE)
    if s.get(f"{URL}/api/authentication/validate", timeout=30).json().get("valid"):
        return s
    r = requests.post(f"{URL}/api/users/change_password", auth=("admin", "admin"), timeout=30,
                      data={"login": "admin", "previousPassword": "admin", "password": CLAVE})
    if r.status_code >= 400:
        sys.exit(f"No se pudo cambiar la contraseña inicial de SonarQube: {r.status_code} {r.text[:300]}")
    print("Contraseña del administrador de SonarQube configurada")
    return s


def post(s: requests.Session, ruta: str, **datos) -> requests.Response:
    r = s.post(URL + ruta, data=datos, timeout=60)
    if r.status_code >= 400:
        sys.exit(f"SonarQube {ruta} -> {r.status_code}: {r.text[:300]}")
    return r


if __name__ == "__main__":
    esperar()
    s = sesion()
    post(s, "/api/settings/set", key="sonar.forceAuthentication", value="false")
    post(s, "/api/projects/update_default_visibility", projectVisibility="public")
    for t in s.get(f"{URL}/api/user_tokens/search", timeout=30).json().get("userTokens", []):
        if t["name"].startswith("fis-agente"):
            post(s, "/api/user_tokens/revoke", name=t["name"])
    token = post(s, "/api/user_tokens/generate", name=f"fis-agente-{int(time.time())}").json()["token"]

    import psycopg

    sys.path.insert(0, "/app")
    from reviewer import configuracion

    with psycopg.connect(os.environ["FIS_PG_DSN"]) as con:
        configuracion.asegurar_esquema(con)
        configuracion.guardar(con, "sonar_interno", {"url": URL, "token": token}, "instalador")
    print("SonarQube del curso listo para el análisis interno")
