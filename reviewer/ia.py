"""Refina las señales indirectas de uso de IA mirando los archivos de cada commit marcado.

Un commit de miles de líneas suele ser un `package-lock.json`, imágenes o datos. Aquí se cuentan
solo las líneas de código o documentación escritas a mano y se descartan las señales que no pasan
el umbral, para no señalar a un estudiante por un archivo generado.
"""
from __future__ import annotations

import re

# Archivos que no escribe una persona: dependencias bloqueadas, compilados, datos, binarios.
RE_GENERADO = re.compile(
    r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|pubspec\.lock|composer\.lock|gradle\.lockfile"
    r"|\.min\.(js|css)$|\.map$|(^|/)(node_modules|dist|build|target|\.gradle|\.idea|\.vscode|vendor|coverage|__pycache__)/"
    r"|\.(png|jpe?g|gif|svg|ico|pdf|drawio|vpp|zip|jar|class|exe|dll|woff2?|ttf|mp4|csv|xlsx?|sqlite|db)$"
    r"|(^|/)(mvnw(\.cmd)?|gradlew(\.bat)?)$|\.mvn/wrapper/)",
    re.I,
)
RE_CODIGO = re.compile(r"\.(java|py|js|jsx|ts|tsx|dart|kt|cs|go|php|rb|cpp|c|h|sql|html|css|scss|vue|fxml|xml)$", re.I)
TIPOS_INDIRECTOS = {"codigo_en_bloque"}


def refinar(gh, repo: str, evidencias: list[dict], umbral: int = 400, tope: int = 40) -> list[dict]:
    if gh is None or not gh.token:
        return evidencias
    cache: dict[str, dict | None] = {}
    salida = []
    for e in evidencias:
        if e["tipo"] not in TIPOS_INDIRECTOS:
            salida.append(e)
            continue
        quedan, detalle_commits = [], []
        for sha in e["refs"]:
            if sha not in cache:
                cache[sha] = gh.get(f"/repos/{repo}/commits/{sha}", opcional=True) if len(cache) < tope else None
            info = cache[sha]
            if not info:
                quedan.append(sha)  # sin detalle: se conserva tal cual
                continue
            archivos = [f for f in info.get("files", []) if not RE_GENERADO.search(f["filename"])]
            codigo = sum(f.get("additions", 0) for f in archivos if RE_CODIGO.search(f["filename"]))
            docs = sum(f.get("additions", 0) for f in archivos if not RE_CODIGO.search(f["filename"]))
            if codigo + docs >= umbral:
                quedan.append(sha)
                principales = sorted(archivos, key=lambda f: -f.get("additions", 0))[:3]
                detalle_commits.append(
                    f"{sha}: +{codigo} de código, +{docs} de documentación/config ("
                    + ", ".join(f"{f['filename'].split('/')[-1]} +{f.get('additions', 0)}" for f in principales) + ")")
        if quedan:
            e = dict(e, refs=quedan,
                     detalle=f"{len(quedan)} commit(s) con {umbral}+ líneas escritas (sin contar archivos generados): "
                             + "; ".join(detalle_commits[:4]))
            salida.append(e)
    return salida
