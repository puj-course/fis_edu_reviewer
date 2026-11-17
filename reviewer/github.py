"""Cliente mínimo de la API de GitHub (REST + GraphQL)."""
from __future__ import annotations

import os
import time
from urllib.parse import quote

import requests

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token: str | None = None):
        self.token = (
            token
            or os.environ.get("FIS_GH_TOKEN")
            or os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
        )
        self.s = requests.Session()
        self.s.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "fis-edu-reviewer",
            }
        )
        if self.token:
            self.s.headers["Authorization"] = f"Bearer {self.token}"
        self.llamadas = 0

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        r = None
        for intento in range(4):
            try:
                r = self.s.request(method, url, timeout=90, **kw)
            except requests.RequestException as e:
                # Cortes de red y lecturas lentas (listados grandes de issues): se reintenta.
                if intento == 3:
                    raise GitHubError(f"{method} {url.replace(API, '')}: sin respuesta de GitHub ({type(e).__name__})") from e
                time.sleep(5 * (intento + 1))
                continue
            self.llamadas += 1
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 * (intento + 1))
                continue
            if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
                reset = int(r.headers.get("x-ratelimit-reset", "0"))
                hora = time.strftime("%H:%M", time.localtime(reset))
                pista = "" if self.token else " Configure FIS_GH_TOKEN para subir el límite a 5000/hora."
                raise GitHubError(f"Límite de la API de GitHub agotado; se restablece a las {hora}.{pista}")
            return r
        return r

    def get(self, path: str, params: dict | None = None, opcional: bool = False):
        r = self._request("GET", API + path, params=params)
        if r.status_code >= 400:
            if opcional and r.status_code in (403, 404, 409, 410, 422):
                return None
            raise GitHubError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def paginate(self, path, params=None, max_items=1500, clave=None, opcional=False) -> list:
        items: list = []
        params = dict(params or {}, per_page=100)
        page = 1
        while len(items) < max_items:
            data = self.get(path, dict(params, page=page), opcional=opcional)
            if data is None:
                break
            lote = data.get(clave, []) if clave else data
            items += lote
            if len(lote) < 100:
                break
            page += 1
        return items[:max_items]

    def post(self, path: str, payload: dict):
        r = self._request("POST", API + path, json=payload)
        if r.status_code >= 400:
            raise GitHubError(f"POST {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def graphql(self, query: str, variables: dict):
        """Devuelve (data, errores). Sin token devuelve (None, [...])."""
        if not self.token:
            return None, ["GraphQL requiere token"]
        r = self._request("POST", API + "/graphql", json={"query": query, "variables": variables})
        if r.status_code >= 400:
            return None, [f"{r.status_code}: {r.text[:200]}"]
        cuerpo = r.json()
        return cuerpo.get("data"), [e.get("message", "") for e in cuerpo.get("errors", [])]

    def raw(self, repo: str, ref: str, path: str, max_chars: int = 20000) -> str | None:
        """Contenido de un archivo. No consume cuota de la API REST."""
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/{quote(path)}"
        headers = {"Authorization": f"token {self.token}"} if self.token else {}
        try:
            r = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        r.encoding = r.encoding or "utf-8"
        try:
            return r.content.decode("utf-8", errors="replace")[:max_chars]
        except Exception:
            return None
