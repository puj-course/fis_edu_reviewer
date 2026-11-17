"""Recolecta la evidencia de un repositorio de equipo y la deja en un diccionario
serializable (evidencia.json). Nada de aquí juzga: solo junta hechos."""
from __future__ import annotations

import base64
import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile

from .github import GitHub, GitHubError

MAX_TEXTO = 8000


def corte_utc(fecha: str) -> str:
    """Fin del día en Bogotá (UTC-5) expresado en UTC."""
    d = dt.date.fromisoformat(fecha) + dt.timedelta(days=1)
    return f"{d.isoformat()}T04:59:59Z"


def collect(gh: GitHub, repo: str, hasta: str, con_wiki: bool = True) -> dict:
    """`repo` = "org/nombre"; `hasta` = fecha de corte YYYY-MM-DD."""
    limite = corte_utc(hasta)
    avisos: list[str] = []
    if not gh.token:
        avisos.append(
            "Sin token de GitHub: no se consultan el tablero Kanban (Projects), "
            "las revisiones de PR ni el tamaño de los commits."
        )

    meta = gh.get(f"/repos/{repo}")
    rama = meta["default_branch"]
    ramas = [b["name"] for b in gh.paginate(f"/repos/{repo}/branches", opcional=True)]

    ramas_commits = [rama] + [r for r in ("develop", "dev", "development") if r in ramas and r != rama][:1]
    commits = _commits(gh, repo, ramas_commits, limite)
    cabeza = next((c["sha"] for c in commits if rama in c["ramas"]), None)

    if len(ramas_commits) > 1:
        cmp_ = gh.get(f"/repos/{repo}/compare/{rama}...{ramas_commits[1]}", opcional=True)
        if cmp_ and cmp_.get("ahead_by", 0) > 0:
            avisos.append(
                f"La rama `{ramas_commits[1]}` tiene {cmp_['ahead_by']} commits que aún no están en `{rama}`; "
                f"los archivos se revisan sobre `{rama}`."
            )

    paths: list[str] = []
    if cabeza:
        arbol = gh.get(f"/repos/{repo}/git/trees/{cabeza}", {"recursive": "1"}, opcional=True)
        if arbol:
            paths = [t["path"] for t in arbol.get("tree", []) if t["type"] == "blob"]
            if arbol.get("truncated"):
                avisos.append("El árbol de archivos es muy grande y GitHub lo devolvió truncado.")

    if gh.token:
        _tamano_commits(gh, repo, ramas_commits, commits, avisos)

    issues, prs = _issues_y_prs(gh, repo, limite)
    if gh.token:
        _reviews(gh, repo, prs)

    ev = {
        "repo": repo,
        "hasta": hasta,
        "limite_utc": limite,
        "recolectado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "con_token": bool(gh.token),
        "meta": {
            "rama_principal": rama,
            "descripcion": meta.get("description"),
            "lenguaje": meta.get("language"),
            "tiene_wiki": meta.get("has_wiki"),
            "privado": meta.get("private"),
        },
        "ramas": ramas,
        "paths": paths,
        "commits": commits,
        "issues": issues,
        "prs": prs,
        "milestones": _milestones(gh, repo),
        "workflows": _workflows(gh, repo, cabeza, paths, limite),
        "releases": _releases(gh, repo, limite),
        "tags": [t["name"] for t in gh.paginate(f"/repos/{repo}/tags", max_items=200, opcional=True)],
        "archivos": _archivos(gh, repo, cabeza, paths),
        "wiki": _wiki(repo, gh.token) if con_wiki and meta.get("has_wiki") else {"existe": False, "paginas": {}},
        "proyecto": _proyecto(gh, repo, avisos) if gh.token else None,
        "avisos": avisos,
    }
    ev["sonar"] = _sonar(ev)
    return ev


# ---------------------------------------------------------------- commits

def _commits(gh, repo, ramas, limite) -> list[dict]:
    vistos: dict[str, dict] = {}
    for rama in ramas:
        for c in gh.paginate(f"/repos/{repo}/commits", {"sha": rama, "until": limite}, max_items=4000, opcional=True):
            sha = c["sha"]
            if sha in vistos:
                vistos[sha]["ramas"].append(rama)
                continue
            autor = c["commit"]["author"] or {}
            vistos[sha] = {
                "sha": sha,
                "login": (c.get("author") or {}).get("login"),
                "nombre": autor.get("name"),
                "fecha": autor.get("date"),
                "mensaje": c["commit"]["message"],
                "padres": len(c.get("parents", [])),
                "adiciones": None,
                "eliminaciones": None,
                "archivos": None,
                "ramas": [rama],
            }
    return sorted(vistos.values(), key=lambda c: c["fecha"] or "", reverse=True)


_Q_HIST = """
query($owner:String!, $name:String!, $ref:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    ref(qualifiedName:$ref) { target { ... on Commit {
      history(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { oid additions deletions changedFilesIfAvailable }
      } } } }
  }
}"""


def _tamano_commits(gh, repo, ramas, commits, avisos):
    owner, name = repo.split("/")
    por_sha = {c["sha"]: c for c in commits}
    for rama in ramas:
        cursor = None
        for _ in range(40):
            data, errores = gh.graphql(_Q_HIST, {"owner": owner, "name": name, "ref": f"refs/heads/{rama}", "cursor": cursor})
            try:
                hist = data["repository"]["ref"]["target"]["history"]
            except (TypeError, KeyError):
                avisos.append(f"No se pudo leer el tamaño de los commits de `{rama}`: {'; '.join(errores)[:150]}")
                break
            for n in hist["nodes"]:
                c = por_sha.get(n["oid"])
                if c:
                    c["adiciones"], c["eliminaciones"], c["archivos"] = n["additions"], n["deletions"], n["changedFilesIfAvailable"]
            if not hist["pageInfo"]["hasNextPage"]:
                break
            cursor = hist["pageInfo"]["endCursor"]


# ---------------------------------------------------------------- issues / PRs

def _issues_y_prs(gh, repo, limite):
    issues, prs_idx = [], {}
    for i in gh.paginate(f"/repos/{repo}/issues", {"state": "all", "direction": "asc"}, max_items=2000, opcional=True):
        if i["created_at"] > limite:
            continue
        if "pull_request" in i:
            prs_idx[i["number"]] = i
            continue
        sub = i.get("sub_issues_summary") or {}
        cerrada = i.get("closed_at") if (i.get("closed_at") or "") <= limite else None
        issues.append(
            {
                "numero": i["number"],
                "titulo": i["title"],
                "cuerpo": (i.get("body") or "")[:MAX_TEXTO],
                "labels": [l["name"] for l in i.get("labels", [])],
                "asignados": [a["login"] for a in i.get("assignees", [])],
                "milestone": (i.get("milestone") or {}).get("title"),
                "estado": "closed" if cerrada else "open",
                "creada": i["created_at"],
                "cerrada": cerrada,
                # El tablero Kanban solo guarda su estado actual: para compararlo se usa el estado de hoy.
                "cerrada_hoy": i.get("state") == "closed",
                "autor": (i.get("user") or {}).get("login"),
                "tipo": (i.get("type") or {}).get("name") if isinstance(i.get("type"), dict) else None,
                "sub_total": sub.get("total", 0),
                "sub_hechas": sub.get("completed", 0),
            }
        )
    prs = []
    if prs_idx:
        for p in gh.paginate(f"/repos/{repo}/pulls", {"state": "all", "direction": "asc"}, max_items=1000, opcional=True):
            if p["created_at"] > limite:
                continue
            fusionado = p.get("merged_at") if (p.get("merged_at") or "") <= limite else None
            prs.append(
                {
                    "numero": p["number"],
                    "titulo": p["title"],
                    "cuerpo": (p.get("body") or "")[:3000],
                    "head": p["head"]["ref"],
                    "base": p["base"]["ref"],
                    "creado": p["created_at"],
                    "fusionado": fusionado,
                    "autor": (p.get("user") or {}).get("login"),
                    "reviews": [],
                }
            )
    return issues, prs


def _reviews(gh, repo, prs, tope=80):
    for p in prs[-tope:]:
        for r in gh.paginate(f"/repos/{repo}/pulls/{p['numero']}/reviews", max_items=50, opcional=True):
            p["reviews"].append({"login": (r.get("user") or {}).get("login"), "estado": r.get("state")})


def _milestones(gh, repo):
    return [
        {
            "titulo": m["title"],
            "estado": m["state"],
            "vence": m.get("due_on"),
            "cerrado": m.get("closed_at"),
            "abiertas": m["open_issues"],
            "cerradas": m["closed_issues"],
        }
        for m in gh.paginate(f"/repos/{repo}/milestones", {"state": "all"}, max_items=100, opcional=True)
    ]


def _releases(gh, repo, limite):
    return [
        {"tag": r["tag_name"], "nombre": r.get("name"), "fecha": r.get("published_at")}
        for r in gh.paginate(f"/repos/{repo}/releases", max_items=100, opcional=True)
        if (r.get("published_at") or "") <= limite
    ]


# ---------------------------------------------------------------- workflows

def _workflows(gh, repo, ref, paths, limite):
    archivos = [p for p in paths if re.match(r"\.github/workflows/[^/]+\.ya?ml$", p)]
    runs = gh.paginate(f"/repos/{repo}/actions/runs", max_items=400, clave="workflow_runs", opcional=True)
    por_path: dict[str, list] = {}
    for r in runs:
        if r["created_at"] <= limite:
            por_path.setdefault(r.get("path", ""), []).append(r)
    salida = []
    for p in archivos[:15]:
        contenido = gh.raw(repo, ref, p, 12000) or ""
        m = re.search(r"^name:\s*['\"]?(.+?)['\"]?\s*$", contenido, re.M)
        rs = sorted(por_path.get(p, []), key=lambda r: r["created_at"], reverse=True)
        terminados = [r for r in rs if r.get("conclusion")]
        salida.append(
            {
                "path": p,
                "nombre": m.group(1) if m else os.path.basename(p),
                "contenido": contenido,
                "ejecuciones": len(rs),
                "exitosas": sum(1 for r in rs if r.get("conclusion") == "success"),
                "fallidas": sum(1 for r in rs if r.get("conclusion") == "failure"),
                "ultima": terminados[0]["conclusion"] if terminados else None,
                "eventos": sorted({r["event"] for r in rs}),
            }
        )
    return salida


# ---------------------------------------------------------------- archivos

_PATRON_DOCS = re.compile(r"\.(md|markdown|txt|adoc)$", re.I)


def _archivos(gh, repo, ref, paths) -> dict[str, str]:
    """Descarga solo los archivos de texto que las rúbricas necesitan leer."""
    if not ref:
        return {}
    elegidos: list[str] = []

    def tomar(patron, tope):
        encontrados = [p for p in paths if re.search(patron, p, re.I) and "node_modules/" not in p]
        elegidos.extend(sorted(encontrados, key=lambda p: (p.count("/"), len(p)))[:tope])

    tomar(r"^readme\.md$", 1)
    tomar(r"^contributing\.md$", 1)
    tomar(r"(^|/)dockerfile[^/]*$", 2)
    tomar(r"(^|/)(docker-)?compose[^/]*\.ya?ml$", 2)
    tomar(r"(^|/)sonar-project\.properties$", 1)
    tomar(r"(^|/)(pom\.xml|build\.gradle(\.kts)?|package\.json|requirements\.txt|pyproject\.toml|pubspec\.yaml)$", 4)
    docs = [p for p in paths if _PATRON_DOCS.search(p) and re.match(r"(docs?|documentacion|wiki)/", p, re.I)]
    elegidos.extend(sorted(docs, key=lambda p: (p.count("/"), len(p)))[:25])

    salida = {}
    for p in dict.fromkeys(elegidos):
        # El README se lee completo: sus títulos se comparan con la plantilla.
        texto = gh.raw(repo, ref, p, 60000 if p.lower() == "readme.md" else MAX_TEXTO)
        if texto is not None:
            salida[p] = texto
    return salida


def _wiki(repo: str, token: str | None) -> dict:
    """La wiki no tiene API: se clona su repositorio git."""
    destino = tempfile.mkdtemp(prefix="fiswiki_")
    url = f"https://github.com/{repo}.wiki.git"
    cmd = ["git"]
    if token:
        # git sobre HTTPS no acepta "Bearer" con tokens fine-grained: va como autenticación básica.
        basica = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        cmd += ["-c", f"http.extraheader=Authorization: Basic {basica}"]
    cmd += ["clone", "--depth", "1", "--quiet", url, destino]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            timeout=90,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
        if r.returncode != 0:
            return {"existe": False, "paginas": {}}
        paginas = {}
        for nombre in sorted(os.listdir(destino)):
            if nombre.startswith(".") or not _PATRON_DOCS.search(nombre):
                continue
            if len(paginas) >= 40:
                break
            with open(os.path.join(destino, nombre), encoding="utf-8", errors="replace") as f:
                paginas[nombre] = f.read(MAX_TEXTO)
        return {"existe": bool(paginas), "paginas": paginas}
    except (subprocess.SubprocessError, OSError):
        return {"existe": False, "paginas": {}}
    finally:
        shutil.rmtree(destino, ignore_errors=True)


# ---------------------------------------------------------------- Projects v2 (Kanban)

_Q_PROY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    projectsV2(first:3) { nodes {
      title
      items(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          content { ... on Issue { number repository { nameWithOwner } } }
          fieldValues(first:20) { nodes {
            ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
            ... on ProjectV2ItemFieldIterationValue { title field { ... on ProjectV2FieldCommon { name } } }
            ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } }
            ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
            ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
          } }
        }
      }
    } }
  }
}"""


def _proyecto(gh, repo, avisos):
    owner, name = repo.split("/")
    items: dict[int, dict] = {}
    titulo, cursor = None, None
    for _ in range(40):
        data, errores = gh.graphql(_Q_PROY, {"owner": owner, "name": name, "cursor": cursor})
        try:
            nodos = data["repository"]["projectsV2"]["nodes"]
        except (TypeError, KeyError):
            avisos.append(
                "No se pudo leer el tablero Kanban (el token necesita permiso de lectura de Projects): "
                + "; ".join(errores)[:150]
            )
            return None
        visibles = [n for n in nodos if n]
        if not visibles:
            # GitHub cuenta el tablero pero lo devuelve vacío cuando el token no tiene permiso.
            if nodos or errores:
                avisos.append("El repo tiene tablero Kanban, pero el token no puede leerlo: "
                              "falta el permiso de organización «Projects: lectura».")
            return None
        proyecto = visibles[0]  # el primer tablero enlazado al repo
        titulo = proyecto["title"]
        for it in proyecto["items"]["nodes"]:
            contenido = it.get("content") or {}
            if not contenido.get("number") or contenido.get("repository", {}).get("nameWithOwner", "").lower() != repo.lower():
                continue
            campos = {}
            for fv in it["fieldValues"]["nodes"]:
                campo = (fv.get("field") or {}).get("name")
                if not campo:
                    continue
                valor = fv.get("name") or fv.get("title") or fv.get("number") or fv.get("text") or fv.get("date")
                if valor not in (None, ""):
                    campos[campo] = valor
            items[contenido["number"]] = campos
        pagina = proyecto["items"]["pageInfo"]
        if not pagina["hasNextPage"]:
            break
        cursor = pagina["endCursor"]
    return {"titulo": titulo, "items": {str(k): v for k, v in items.items()}}


# ---------------------------------------------------------------- Sonar (SonarCloud o SonarQube propio)

METRICAS_SONAR = ("coverage,bugs,vulnerabilities,code_smells,security_hotspots,duplicated_lines_density,"
                  "sqale_index,sqale_rating,reliability_rating,security_rating,ncloc,alert_status")


def _servidores_sonar() -> list[tuple[str, str, str | None]]:
    """(nombre, url, token). SonarCloud siempre; el SonarQube del curso si FIS_SONAR_URL está definido."""
    servidores = [("SonarCloud", "https://sonarcloud.io", os.environ.get("FIS_SONARCLOUD_TOKEN") or None)]
    if os.environ.get("FIS_SONAR_URL"):
        servidores.append(("SonarQube del curso", os.environ["FIS_SONAR_URL"].rstrip("/"), os.environ.get("FIS_SONAR_TOKEN") or None))
    return servidores


def _sonar_get(url: str, token: str | None, ruta: str, params: dict) -> dict | None:
    import requests

    try:
        r = requests.get(url + ruta, params=params, timeout=20, auth=(token, "") if token else None)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _sonar(ev) -> dict | None:
    """Encuentra el proyecto Sonar del equipo y trae medidas, quality gate, análisis y problemas abiertos.

    Lee SonarCloud (público, o privado con FIS_SONARCLOUD_TOKEN) y, si se configura, el SonarQube del
    curso (FIS_SONAR_URL + FIS_SONAR_TOKEN). El agente no ejecuta análisis: verifica los que corre el
    pipeline del equipo, que es lo que evalúa la rúbrica.
    """
    textos = list(ev["archivos"].values()) + [w["contenido"] for w in ev["workflows"]]
    clave = None
    for t in textos:
        m = re.search(r"sonar\.projectKey\s*[=:]\s*['\"]?([\w.:\-]+)", t) or re.search(r"<sonar\.projectKey>([^<]+)<", t)
        if m:
            clave = m.group(1)
            break
    configurado = clave is not None or any(re.search(r"sonar", t, re.I) for t in textos)
    if not configurado:
        return None
    wf_sonar = [w for w in ev["workflows"] if re.search(r"sonar", w["contenido"], re.I)]
    info = {"configurado": True, "clave": clave, "servidor": None, "url": None, "medidas": {},
            "pipeline": [{"nombre": w.get("nombre") or w.get("path"), "ultima": w.get("ultima")} for w in wf_sonar]}
    org, nombre = ev["repo"].split("/")
    candidatas = list(dict.fromkeys([c for c in (clave, f"{org}_{nombre}", nombre) if c]))
    for servidor, url, token in _servidores_sonar():
        for candidata in candidatas:
            datos = leer_proyecto(url, token, candidata, ev["hasta"])
            if datos:
                info.update(servidor=servidor, **datos)
                return info
    return info


def leer_proyecto(url: str, token: str | None, clave: str, hasta: str) -> dict | None:
    """Medidas, quality gate, análisis hasta el corte y problemas abiertos de un proyecto Sonar."""
    datos = _sonar_get(url, token, "/api/measures/component", {"component": clave, "metricKeys": METRICAS_SONAR})
    if not datos or "component" not in datos:
        return None
    info = {"clave": clave, "url": url, "medidas": {m["metric"]: m.get("value") for m in datos["component"].get("measures", [])}}
    qg = _sonar_get(url, token, "/api/qualitygates/project_status", {"projectKey": clave}) or {}
    estado = qg.get("projectStatus") or {}
    info["quality_gate"] = estado.get("status")
    info["condiciones_fallidas"] = [
        f"{c.get('metricKey')} {c.get('comparator', '')} {c.get('errorThreshold', '')} (valor {c.get('actualValue')})"
        for c in estado.get("conditions", []) if c.get("status") == "ERROR"]
    an = _sonar_get(url, token, "/api/project_analyses/search", {"project": clave, "ps": 500}) or {}
    fechas = sorted(a["date"][:10] for a in an.get("analyses", []) if a.get("date"))
    previas = [f for f in fechas if f <= hasta]
    info["analisis"] = {"total": len(fechas), "hasta_corte": len(previas), "primero": fechas[0] if fechas else None,
                        "ultimo": previas[-1] if previas else None, "dias_con_analisis": len(set(previas))}
    iss = _sonar_get(url, token, "/api/issues/search",
                     {"componentKeys": clave, "resolved": "false", "ps": 1, "facets": "severities,types"}) or {}
    info["problemas"] = {f["property"]: {v["val"]: v["count"] for v in f.get("values", [])} for f in iss.get("facets", [])}
    info["problemas_total"] = iss.get("total")
    return info


def detectar_monitores(gh: GitHub, repos: list[str], minimo_repos: int = 3) -> list[str]:
    """Cuentas que aparecen como colaboradoras en TODOS los repos de equipo.

    Un estudiante pertenece a un solo equipo; quien está en todos es monitor o profesor.
    Con menos de `minimo_repos` repos no se puede distinguir y no se detecta nada.
    """
    if len(repos) < minimo_repos:
        return []
    presencia: dict[str, int] = {}
    for repo in repos:
        logins = {c.get("login") for c in gh.paginate(f"/repos/{repo}/contributors", max_items=300, opcional=True)}
        for login in logins - {None}:
            presencia[login] = presencia.get(login, 0) + 1
    return sorted(l for l, n in presencia.items() if n == len(repos) and not l.endswith("[bot]"))


def descubrir_repos(gh: GitHub, org: str, prefijo: str, excluir: list[str]) -> list[str]:
    repos = gh.paginate(f"/orgs/{org}/repos", {"type": "all", "sort": "full_name"}, max_items=500)
    return [r["full_name"] for r in repos if r["name"].startswith(prefijo) and r["name"] not in excluir and not r.get("archived")]


__all__ = ["collect", "descubrir_repos", "corte_utc", "GitHubError"]
