"""Verificaciones deterministas sobre la evidencia. Cada verificación devuelve:

    {"id", "titulo", "indicadores": [{"texto", "ok"}], "razon", "nivel", "textos"}

- razon: 0..1 (qué tanto se cumple) o None si es solo informativa.
- nivel: nombre de nivel de la rúbrica cuando esta lo define con un número
  (porcentaje de issues, cantidad de pipelines, cobertura...).
- textos: extractos (título, texto) que la capa de IA puede leer.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import Counter, defaultdict

ORDEN = ["Excelente", "Bueno", "Regular", "Deficiente"]

RE_CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]+\))?!?: \S.*", re.I
)
RE_REF = re.compile(r"#(\d+)")
# Un comando de pruebas en un workflow (admite wrappers y comandos partidos en varias líneas).
RE_PRUEBAS = re.compile(
    r"\b(mvnw?|gradlew?|npm|yarn|pnpm|flutter|dotnet|go|cargo)\b[^\n]*(\\\n[^\n]*){0,4}\b(test|verify)\b|pytest|unittest|jest|vitest",
    re.I,
)
RE_RAMA_FLUJO = re.compile(r"^(feature|feat|fix|bugfix|hotfix|release|docs|chore|test|refactor)[/\-_]", re.I)
RE_IA = re.compile(
    r"co-authored-by:.*(claude|copilot|cursor|chatgpt|openai|codex|gemini|devin|aider|windsurf)"
    r"|generated (with|by) .*(claude|copilot|chatgpt|cursor|gemini|ai)|🤖",
    re.I,
)
RE_INYECCION = re.compile(
    r"(ignor[ae]\w* (las |all |any |todas las )?(instrucciones|previous|prior|instructions)"
    r"|eres un (revisor|evaluador)|you are an? (grader|reviewer)|asigna\w* (la )?(nota|calificaci)"
    r"|give (this|the) (team|project) (a |the )?(maximum|highest|5))",
    re.I,
)

PATRONES_GOF = {
    "creacional": ["abstractfactory", "factory", "singleton", "builder", "prototype"],
    "estructural": ["adapter", "facade", "fachada", "proxy", "decorator", "composite", "bridge", "flyweight"],
    "comportamiento": ["observer", "strategy", "command", "state", "templatemethod", "template", "iterator",
                       "mediator", "memento", "visitor", "chainofresponsibility"],
}
EXT_CODIGO = {".java", ".py", ".js", ".ts", ".tsx", ".jsx", ".dart", ".kt", ".cs", ".go", ".php", ".rb", ".cpp", ".c"}


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def ind(texto: str, ok=None) -> dict:
    return {"texto": texto, "ok": ok}


def pct(a: int, b: int) -> float:
    return a / b if b else 0.0


def nivel_por_umbral(valor: float, umbrales: list[tuple[float, str]]) -> str:
    for minimo, nombre in umbrales:
        if valor >= minimo:
            return nombre
    return "Deficiente"


class Contexto:
    """Vistas derivadas de la evidencia que comparten varias verificaciones."""

    def __init__(self, ev: dict, cfg: dict):
        self.ev, self.cfg = ev, cfg
        self.ignorar = {u.lower() for u in cfg.get("ignorar_usuarios", [])}
        # Commits hechos con un correo sin vincular: se atribuyen a la cuenta que
        # usa ese mismo nombre en otros commits (o cuyo usuario es ese nombre).
        self._por_nombre = {k["login"].lower(): k["login"] for k in ev["commits"] if k.get("login")}
        self._por_nombre.update({(k["nombre"] or "").lower(): k["login"] for k in ev["commits"] if k.get("login") and k.get("nombre")})
        bitacora = cfg.get("etiqueta_bitacora", "fis-reviewer")
        self.issues = [i for i in ev["issues"] if bitacora not in i["labels"]]
        self.commits = [c for c in ev["commits"] if c["padres"] <= 1 and self.quien(c) is not None]
        self.prs = ev["prs"]
        self.paths = ev["paths"]
        self.paths_norm = [norm(p) for p in self.paths]
        self.proyecto = (ev.get("proyecto") or {}).get("items")
        self.hus = [i for i in self.issues if self.es_hu(i)]
        self.documentos = {**ev["archivos"], **{f"wiki/{k}": v for k, v in ev["wiki"]["paginas"].items()}}
        self.docs_md = {k: v for k, v in self.documentos.items() if re.search(r"\.(md|markdown|txt|adoc)$", k, re.I)}
        self.wf_texto = "\n".join(w["contenido"] for w in ev["workflows"])

    def quien(self, c: dict) -> str | None:
        login = c.get("login") or self._por_nombre.get((c.get("nombre") or "").lower())
        if login:
            return None if login.lower() in self.ignorar or login.endswith("[bot]") else login
        nombre = c.get("nombre") or "desconocido"
        return None if nombre.lower() in self.ignorar else f"~{nombre}"

    def es_estudiante(self, login: str | None) -> bool:
        return bool(login) and login.lower() not in self.ignorar and not login.endswith("[bot]")

    def es_hu(self, i: dict) -> bool:
        if norm(i.get("tipo")) in ("user story", "historia de usuario", "story", "feature"):
            return True
        if any(re.search(r"(historia|user.?stor|\bhu\b|\bstory\b)", norm(l)) for l in i["labels"]):
            return True
        if re.match(r"\s*\[?\s*(hu|us|historia)\b", norm(i["titulo"])):
            return True
        cuerpo = norm(i["titulo"] + " " + i["cuerpo"])
        return bool(re.search(r"\bcomo\b.{0,160}\b(quiero|deseo|necesito)\b", cuerpo, re.S))

    def campo(self, numero: int, patron: str):
        """Valor de un campo del tablero Kanban cuyo nombre calza con `patron`."""
        if self.proyecto is None:
            return None
        for nombre, valor in (self.proyecto.get(str(numero)) or {}).items():
            if re.search(patron, norm(nombre)):
                return valor
        return None

    def miembros(self) -> list[str]:
        vistos = Counter()
        for c in self.commits:
            vistos[self.quien(c)] += 1
        for i in self.issues:
            for a in i["asignados"]:
                if self.es_estudiante(a):
                    vistos[a] += 0
        for p in self.prs:
            if self.es_estudiante(p["autor"]):
                vistos[p["autor"]] += 0
        return sorted(vistos, key=lambda m: (-vistos[m], m.lower()))

    def buscar_docs(self, patron: str) -> list[str]:
        return [k for k, v in self.docs_md.items() if re.search(patron, norm(k)) or re.search(patron, norm(v))]


# ====================================================================== entrega 1

def estructura(c: Contexto):
    esperado = c.cfg.get("estructura_esperada", {})
    inds = []
    for carpeta in esperado.get("carpetas", []):
        inds.append(ind(f"Carpeta `{carpeta}/`", any(p.lower().startswith(carpeta.lower() + "/") for p in c.paths)))
    raiz = {p.lower() for p in c.paths if "/" not in p}
    for archivo in esperado.get("archivos", []):
        inds.append(ind(f"Archivo `{archivo}`", archivo.lower() in raiz))
    return _res("estructura", "Estructura del repositorio", inds)


def readme(c: Contexto):
    texto = next((v for k, v in c.ev["archivos"].items() if k.lower() == "readme.md"), None)
    if texto is None:
        return _res("readme", "README", [ind("No hay README.md en la raíz", False)], razon=0.0)
    titulos = [norm(l) for l in texto.splitlines() if l.lstrip().startswith("#")]
    inds = [
        ind(f"Sección «{s}»", any(s in t for t in titulos))
        for s in c.cfg.get("readme_secciones", [])
    ]
    return _res("readme", "README según la plantilla", inds, textos=[("README.md", texto[:5000])])


def wiki(c: Contexto):
    paginas = c.ev["wiki"]["paginas"]
    n = len(paginas)
    inds = [ind(f"Wiki con {n} página(s)" if n else "La Wiki está vacía o no existe", n >= 2 if n else False)]
    return _res("wiki", "Wiki", inds, razon=1.0 if n >= 3 else 0.5 if n >= 1 else 0.0)


def gitflow(c: Contexto):
    ramas = [r.lower() for r in c.ev["ramas"]]
    tiene_develop = any(r in ("develop", "dev", "development") for r in ramas)
    de_trabajo = {p["head"] for p in c.prs if RE_RAMA_FLUJO.match(p["head"])} | {
        r for r in c.ev["ramas"] if RE_RAMA_FLUJO.match(r)
    }
    fusionados = [p for p in c.prs if p["fusionado"]]
    principal = c.ev["meta"]["rama_principal"]
    bien_dirigidos = [
        p for p in fusionados
        if p["base"] != principal or re.match(r"(release|hotfix|develop|dev)", p["head"], re.I)
    ]
    inds = [
        ind("Existe la rama `develop`", tiene_develop),
        ind(f"{len(de_trabajo)} ramas de trabajo con prefijo (feature/, fix/, hotfix/…)", len(de_trabajo) >= 3),
        ind(f"{len(fusionados)} pull requests fusionados", len(fusionados) >= 3),
        ind(
            f"{len(bien_dirigidos)}/{len(fusionados)} PR fusionados respetan el flujo "
            f"(feature → develop; solo release/hotfix → {principal})",
            pct(len(bien_dirigidos), len(fusionados)) >= 0.8 if fusionados else False,
        ),
    ]
    con_review = [p for p in fusionados if any(r["estado"] == "APPROVED" for r in p["reviews"])]
    if c.ev["con_token"]:
        inds.append(ind(f"{len(con_review)}/{len(fusionados)} PR fusionados tuvieron aprobación de un compañero",
                        pct(len(con_review), len(fusionados)) >= 0.5 if fusionados else False))
    return _res("gitflow", "GitFlow", inds)


def conventional_commits(c: Contexto):
    total = len(c.commits)
    buenos = sum(1 for k in c.commits if RE_CONVENTIONAL.match(k["mensaje"].splitlines()[0]))
    r = pct(buenos, total)
    malos = [k["mensaje"].splitlines()[0][:70] for k in c.commits if not RE_CONVENTIONAL.match(k["mensaje"].splitlines()[0])][:3]
    inds = [ind(f"{buenos}/{total} commits ({r:.0%}) siguen Conventional Commits", r >= 0.8)]
    if malos:
        inds.append(ind("Ejemplos que no lo siguen: " + "; ".join(f"«{m}»" for m in malos)))
    return _res("conventional_commits", "Conventional Commits", inds, razon=r if total else 0.0)


def issues_completas(c: Contexto):
    total = len(c.issues)
    if not total:
        return _res("issues_completas", "Características de las issues", [ind("No hay issues", False)], razon=0.0, nivel="Deficiente")
    cuenta = Counter()
    completas = 0
    for i in c.issues:
        attrs = {"asignación": bool(i["asignados"]), "labels": bool(i["labels"]), "milestone": bool(i["milestone"])}
        if c.proyecto is not None:
            attrs["estimación"] = c.campo(i["numero"], r"estim|punto|size|story|esfuerzo|effort|tama") is not None
            attrs["prioridad"] = c.campo(i["numero"], r"priori") is not None or any("prior" in norm(l) for l in i["labels"])
            attrs["sprint"] = c.campo(i["numero"], r"sprint|iteraci") is not None
        for k, v in attrs.items():
            cuenta[k] += v
        completas += all(attrs.values())
    r = pct(completas, total)
    inds = [ind(f"{completas}/{total} issues ({r:.0%}) tienen todas sus características", r >= 0.8)]
    inds += [ind(f"Con {k}: {v}/{total}", pct(v, total) >= 0.8) for k, v in cuenta.items()]
    if c.proyecto is None:
        inds.append(ind("Estimación, prioridad y sprint no se pudieron verificar (sin acceso al tablero)"))
    return _res("issues_completas", "Características de las issues", inds, razon=r,
                nivel=nivel_por_umbral(r, [(0.8, "Excelente"), (0.6, "Bueno"), (0.5, "Regular")]))


def kanban(c: Contexto):
    if c.proyecto is None:
        return _res("kanban", "Flujo Kanban", [ind("No se pudo leer el tablero Kanban; revisar manualmente")], razon=None)
    total = len(c.issues)
    en_tablero = [i for i in c.issues if str(i["numero"]) in c.proyecto]
    coherentes = 0
    for i in en_tablero:
        estado = norm(str(c.campo(i["numero"], r"status|estado") or ""))
        hecho = bool(re.search(r"done|hech|termin|cerrad|complet|finaliz", estado))
        cerrada_hoy = i.get("cerrada_hoy", i["estado"] == "closed")
        coherentes += bool(estado) and (hecho == cerrada_hoy)
    r_tab, r_coh = pct(len(en_tablero), total), pct(coherentes, len(en_tablero))
    inds = [
        ind(f"{len(en_tablero)}/{total} issues están en el tablero", r_tab >= 0.8),
        ind(f"{coherentes}/{len(en_tablero)} tienen la columna coherente con su estado actual (cerrada ↔ Done; el tablero no guarda historia)", r_coh >= 0.8),
    ]
    return _res("kanban", "Flujo Kanban", inds, razon=(r_tab + r_coh) / 2)


def historias_estructura(c: Contexto):
    total = len(c.hus)
    if not total:
        return _res("historias_estructura", "Estructura de las historias de usuario",
                    [ind("No se identificaron historias de usuario (label, tipo o formato «Como… quiero… para…»)", False)],
                    razon=0.0, nivel="Deficiente")
    cuenta, completas, incompletas = Counter(), 0, []
    for i in c.hus:
        t = norm(i["titulo"] + "\n" + i["cuerpo"])
        partes = {
            "formato Como/Quiero/Para": bool(re.search(r"\bcomo\b.{0,160}\b(quiero|deseo|necesito)\b.{0,300}\bpara\b", t, re.S)),
            "criterios de aceptación": bool(re.search(r"criterios? de aceptacion|acceptance criteria|\bdado\b.{0,200}\bcuando\b|\bgiven\b", t, re.S)),
            "Definition of Done": bool(re.search(r"definition of done|\bdod\b|definicion de (hecho|terminado|listo)", t)),
        }
        for k, v in partes.items():
            cuenta[k] += v
        if all(partes.values()):
            completas += 1
        else:
            incompletas.append(f"#{i['numero']}")
    r = pct(completas, total)
    inds = [ind(f"{completas}/{total} historias ({r:.0%}) tienen la estructura completa", r >= 0.8)]
    inds += [ind(f"Con {k}: {v}/{total}", pct(v, total) >= 0.8) for k, v in cuenta.items()]
    if incompletas:
        inds.append(ind("Historias por completar: " + ", ".join(incompletas[:15])))
    textos = [(f"HU #{i['numero']}: {i['titulo']}", i["cuerpo"][:1500]) for i in c.hus[:12]]
    return _res("historias_estructura", "Estructura de las historias de usuario", inds, razon=r,
                nivel=nivel_por_umbral(r, [(0.8, "Excelente"), (0.6, "Bueno"), (0.5, "Regular")]), textos=textos)


def ceremonias(c: Contexto):
    fuentes = {f"issue #{i['numero']}": i["titulo"] for i in c.ev["issues"]}
    fuentes.update({k: k + "\n" + v[:3000] for k, v in c.docs_md.items()})
    fuentes.update({p: p for p in c.paths})
    tipos = {
        "Sprint Planning": r"sprint.?planning|planning|planeacion del sprint|planificacion del sprint",
        "Dailies": r"\bdaily\b|\bdailies\b|reunion diaria",
        "Retrospectiva": r"retrospectiv|\bretro\b",
        "Sprint Review": r"sprint.?review|revision del sprint",
    }
    inds, hallados, textos = [], 0, []
    for nombre, patron in tipos.items():
        donde = [k for k, v in fuentes.items() if re.search(patron, norm(v))]
        hallados += bool(donde)
        inds.append(ind(f"{nombre}: " + (f"evidencia en {', '.join(donde[:3])}" if donde else "sin evidencia escrita"), bool(donde)))
        textos += [(k, c.docs_md[k][:2500]) for k in donde[:2] if k in c.docs_md]
    return _res("ceremonias", "Ceremonias ágiles", inds, razon=min(1.0, hallados / 3), textos=textos[:6])


def hitos(c: Contexto):
    ms = c.ev["milestones"]
    if not ms:
        return _res("hitos", "Milestones", [ind("No hay milestones definidos", False)], razon=0.0)
    vencidos = [m for m in ms if m["vence"] and m["vence"] <= c.ev["limite_utc"]]
    a_tiempo = [m for m in vencidos if m["estado"] == "closed" and m["abiertas"] == 0]
    con_ms = sum(1 for i in c.issues if i["milestone"])
    r_issues = pct(con_ms, len(c.issues))
    inds = [
        ind(f"{len(ms)} milestones definidos, {sum(1 for m in ms if m['vence'])} con fecha", all(m["vence"] for m in ms)),
        ind(f"{con_ms}/{len(c.issues)} issues asociadas a un milestone", r_issues >= 0.8),
    ]
    razones = [r_issues, pct(sum(1 for m in ms if m["vence"]), len(ms))]
    if vencidos:
        r = pct(len(a_tiempo), len(vencidos))
        inds.append(ind(f"{len(a_tiempo)}/{len(vencidos)} milestones vencidos se cerraron sin issues pendientes", r >= 0.8))
        razones.append(r)
    return _res("hitos", "Milestones", inds, razon=sum(razones) / len(razones))


def trazabilidad(c: Contexto):
    total = len(c.commits)
    con_ref = [k for k in c.commits if RE_REF.search(k["mensaje"])]
    referidas = {int(n) for k in c.commits for n in RE_REF.findall(k["mensaje"])}
    referidas |= {int(n) for p in c.prs if p["fusionado"] for n in RE_REF.findall(p["titulo"] + " " + p["cuerpo"])}
    cerradas = [i for i in c.issues if i["estado"] == "closed"]
    trazadas = [i for i in cerradas if i["numero"] in referidas]
    r1, r2 = pct(len(con_ref), total), pct(len(trazadas), len(cerradas))
    inds = [
        ind(f"{len(con_ref)}/{total} commits ({r1:.0%}) referencian una issue (#n)", r1 >= 0.7),
        ind(f"{len(trazadas)}/{len(cerradas)} issues cerradas ({r2:.0%}) tienen un commit o PR que las referencia", r2 >= 0.7),
    ]
    sin = [f"#{i['numero']}" for i in cerradas if i["numero"] not in referidas][:12]
    if sin:
        inds.append(ind("Cerradas sin commit ni PR asociado: " + ", ".join(sin)))
    return _res("trazabilidad", "Trazabilidad issue – commit – cierre", inds, razon=(r1 + r2) / 2 if total else 0.0)


def aporte_historias(c: Contexto):
    numeros_validos = {i["numero"] for i in c.issues}
    por_miembro = defaultdict(set)
    for k in c.commits:
        por_miembro[c.quien(k)] |= {int(n) for n in RE_REF.findall(k["mensaje"]) if int(n) in numeros_validos}
    miembros = c.miembros()
    cumplen = [m for m in miembros if len(por_miembro[m]) >= 2]
    inds = [ind(f"{len(cumplen)}/{len(miembros)} integrantes tienen commits ligados a 2 o más issues", len(cumplen) == len(miembros) and bool(miembros))]
    inds += [ind(f"@{m}: commits ligados a {len(por_miembro[m])} issue(s)", len(por_miembro[m]) >= 2) for m in miembros]
    return _res("aporte_historias", "Aporte individual en historias", inds, razon=pct(len(cumplen), len(miembros)))


def codigo_fuente(c: Contexto):
    codigo = [p for p in c.paths if any(p.lower().endswith(e) for e in EXT_CODIGO) and "node_modules/" not in p]
    pruebas = [p for p in codigo if re.search(r"(^|/)(tests?|__tests__|spec)/|test[^/]*$|\.spec\.", p, re.I)]
    datos = [p for p in c.paths if re.search(r"\.sql$|(dao|repository|repositorio|migration|jdbc|entity|model)", p, re.I)]
    inds = [
        ind(f"{len(codigo)} archivos de código fuente ({len(pruebas)} de pruebas)"),
        ind(f"{len(datos)} archivos relacionados con persistencia (SQL, DAO, repositorios, modelos)"),
    ]
    return _res("codigo_fuente", "Código fuente (evidencia)", inds, razon=None)


# ====================================================================== entrega 2

def sub_issues(c: Contexto):
    if not c.hus:
        return _res("sub_issues", "Sub-issues técnicas", [ind("No hay historias de usuario identificadas", False)], razon=0.0)
    con = [i for i in c.hus if i["sub_total"] > 0]
    r = pct(len(con), len(c.hus))
    return _res("sub_issues", "Sub-issues técnicas",
                [ind(f"{len(con)}/{len(c.hus)} historias ({r:.0%}) tienen sub-issues técnicas", r >= 0.8)], razon=r)


def pipelines(c: Contexto):
    wfs = c.ev["workflows"]
    funcionales = [w for w in wfs if w["exitosas"] > 0 and w["ultima"] == "success"]
    tipos = {
        "CI (build/pruebas)": RE_PRUEBAS.pattern + r"|\b(mvnw?|gradlew?|npm|yarn|pnpm|flutter|dotnet)\b[^\n]*\b(build|package|compile)\b",
        "CD (publicación/despliegue)": r"docker(/| )(login|push|build-push)|deploy|release|ssh-action|compose up|pages",
        "Automatización del tablero/issues": r"add-to-project|projects?v2|project_id|actions/labeler|github-script|issues:|gh (issue|project)",
    }
    inds = [ind(f"{len(funcionales)} de {len(wfs)} pipelines con ejecuciones exitosas y última ejecución en verde", len(funcionales) >= 4)]
    for w in wfs:
        ok = w in funcionales
        inds.append(ind(f"`{w['path'].split('/')[-1]}` ({w['nombre']}): {w['exitosas']} exitosas, {w['fallidas']} fallidas, última: {w['ultima'] or 'sin ejecuciones'}", ok))
    for nombre, patron in tipos.items():
        hay = any(re.search(patron, w["contenido"], re.I) for w in funcionales)
        inds.append(ind(f"Tipo cubierto — {nombre}", hay))
    n = len(funcionales)
    nivel = "Excelente" if n >= 4 else "Bueno" if n == 3 else "Regular" if n == 2 else "Deficiente"
    return _res("pipelines", "Pipelines de GitHub Actions", inds, razon=min(1.0, n / 4), nivel=nivel,
                textos=[(w["path"], w["contenido"][:2500]) for w in wfs[:6]])


def diagramas(c: Contexto):
    tipos = {
        "Base de datos": r"base.?de.?datos|\bbd\b|\bdb\b|database|entidad.?relacion|\bmer\b|\ber\b|relacional",
        "Clases": r"clases|class",
        "Componentes": r"componentes|component",
        "Despliegue": r"despliegue|deployment|deploy",
    }
    candidatos = [p for p in c.paths if re.search(r"\.(png|jpe?g|svg|puml|plantuml|drawio|mmd|pdf|vpp|md)$", p, re.I)
                  and re.search(r"diagram|uml|arquitect|architect|model|dise", norm(p))]
    textos_md = {k: v for k, v in c.docs_md.items()}
    inds, hallados, textos = [], 0, []
    for nombre, patron in tipos.items():
        en_paths = [p for p in candidatos if re.search(patron, norm(p.split("/")[-1]))]
        en_docs = [k for k, v in textos_md.items()
                   if re.search(r"diagrama[^\n]{0,40}(" + patron + ")", norm(v)) or (re.search(patron, norm(k)) and "diagram" in norm(k + v[:400]))]
        hay = bool(en_paths or en_docs)
        hallados += hay
        donde = (en_paths + en_docs)[:2]
        inds.append(ind(f"Diagrama de {nombre}: " + (", ".join(f"`{d}`" for d in donde) if hay else "no encontrado"), hay))
        textos += [(k, textos_md[k][:2500]) for k in en_docs[:1]]
    nivel = {4: "Excelente", 3: "Bueno", 2: "Regular"}.get(hallados, "Deficiente")
    return _res("diagramas", "Diagramas de diseño", inds, razon=hallados / 4, nivel=nivel, textos=textos[:5])


def patrones_gof(c: Contexto):
    nombres = [norm(p.split("/")[-1]).replace("_", "").replace("-", "") for p in c.paths
               if any(p.lower().endswith(e) for e in EXT_CODIGO)]
    docs = norm("\n".join(c.docs_md.values()))
    inds, por_tipo, textos = [], {}, []
    for tipo, lista in PATRONES_GOF.items():
        en_codigo = sorted({pat for pat in lista if any(pat in n for n in nombres)})
        en_docs = sorted({pat for pat in lista if re.search(r"\b" + pat, docs)})
        sinonimos = {"fachada": "facade", "templatemethod": "template", "abstractfactory": "factory"}
        por_tipo[tipo] = len({sinonimos.get(p, p) for p in en_codigo + en_docs})
        inds.append(ind(
            f"Patrones de tipo {tipo}: en nombres de clases/archivos {en_codigo or '—'}; mencionados en la documentación {en_docs or '—'}",
            por_tipo[tipo] >= 2))
    minimo = min(por_tipo.values())
    nivel = "Excelente" if minimo >= 2 else "Bueno" if minimo >= 1 else "Deficiente"
    inds.append(ind("La detección es por nombres de archivo y menciones en la documentación: "
                    "que estén bien implementados lo valida el profesor"))
    for k in c.buscar_docs(r"patron(es)? (de diseno|gof)|design pattern")[:3]:
        textos.append((k, c.docs_md[k][:3000]))
    return _res("patrones_gof", "Patrones GoF", inds, razon=min(1.0, sum(min(v, 2) for v in por_tipo.values()) / 6),
                nivel=nivel, textos=textos)


# ====================================================================== entrega 3

def docker(c: Contexto):
    dockerfiles = [p for p in c.paths if re.search(r"(^|/)dockerfile[^/]*$", p, re.I)]
    composes = [k for k in c.ev["archivos"] if re.search(r"compose[^/]*\.ya?ml$", k, re.I)]
    compose_txt = "\n".join(c.ev["archivos"][k] for k in composes)
    servicios = len(re.findall(r"^\s{2}[\w\-]+:\s*$", compose_txt.split("services:")[-1], re.M)) if "services:" in compose_txt else 0
    readme_txt = norm(next((v for k, v in c.ev["archivos"].items() if k.lower() == "readme.md"), ""))
    inds = [
        ind(f"Dockerfile: {', '.join(dockerfiles[:3]) or 'no encontrado'}", bool(dockerfiles)),
        ind(f"Docker Compose: {', '.join(composes) or 'no encontrado'}", bool(composes)),
        ind("El Compose define una red (`networks:`) entre servicios", "networks:" in compose_txt),
        ind(f"El Compose declara aproximadamente {servicios} servicio(s)", servicios >= 2),
        ind("El README documenta la ejecución con Docker", "docker" in readme_txt),
        ind("Hay ejemplo de variables de entorno (.env.example)", any(re.search(r"(^|/)\.?env.*example|environment\.example", p, re.I) for p in c.paths)),
    ]
    return _res("docker", "Docker y Docker Compose", inds, textos=[(k, c.ev["archivos"][k][:2500]) for k in composes[:1]])


def pipeline_docker(c: Contexto):
    t = c.wf_texto
    pasos = {
        "Construye la imagen Docker": r"docker build|build-push-action|docker compose build|docker-compose build",
        "Valida build y pruebas": RE_PRUEBAS.pattern,
        "Publica en Docker Hub": r"docker/login-action|docker login|docker push|push:\s*true",
        "Versiona la imagen (tags)": r"metadata-action|tags:|github\.sha|github\.ref_name|:\$\{\{",
        "Despliega con Docker Compose": r"compose[^\n]*\bup\b|ssh-action|deploy",
    }
    inds = [ind(nombre, bool(re.search(patron, t, re.I))) for nombre, patron in pasos.items()]
    return _res("pipeline_docker", "Pipeline de CI/CD con Docker", inds)


def cobertura(c: Contexto):
    sonar_ = c.ev.get("sonar") or {}
    valor = (sonar_.get("medidas") or {}).get("coverage")
    herramienta = bool(re.search(r"jacoco|coverage|lcov|--cov|istanbul|nyc", c.wf_texto + "\n".join(c.ev["archivos"].values()), re.I))
    if valor is None:
        inds = [
            ind("No se pudo leer la cobertura desde SonarCloud (proyecto privado, SonarQube propio o sin configurar); "
                "verificar en el tablero de Sonar"),
            ind("Hay herramienta de cobertura configurada (JaCoCo, coverage, lcov…)", herramienta),
        ]
        return _res("cobertura", "Cobertura de pruebas", inds, razon=None)
    v = float(valor)
    nivel = nivel_por_umbral(v, [(80, "Excelente"), (60, "Bueno"), (40, "Regular")])
    return _res("cobertura", "Cobertura de pruebas",
                [ind(f"Cobertura en SonarCloud: {v:.1f}%", v >= 80), ind("Herramienta de cobertura configurada", herramienta)],
                razon=min(1.0, v / 80), nivel=nivel)


def pipeline_pruebas(c: Contexto):
    con_pruebas = [w for w in c.ev["workflows"] if RE_PRUEBAS.search(w["contenido"])]
    en_eventos = [w for w in con_pruebas if re.search(r"\bpush\b|pull_request", w["contenido"])]
    verdes = [w for w in con_pruebas if w["ultima"] == "success"]
    archivos_prueba = [p for p in c.paths if re.search(r"(^|/)(tests?|__tests__)/|Test\.java$|_test\.(py|dart|go)$|test_[^/]*\.py$|\.(spec|test)\.[jt]sx?$", p)]
    inds = [
        ind(f"{len(archivos_prueba)} archivos de pruebas en el repositorio", len(archivos_prueba) >= 3),
        ind(f"{len(con_pruebas)} pipeline(s) ejecutan pruebas", bool(con_pruebas)),
        ind("Las pruebas corren en push y/o pull request", bool(en_eventos)),
        ind("La última ejecución del pipeline de pruebas fue exitosa", bool(verdes)),
    ]
    return _res("pipeline_pruebas", "Pruebas en el pipeline", inds)


def sonar(c: Contexto):
    s = c.ev.get("sonar")
    if not s:
        return _res("sonar", "SonarQube", [ind("No hay configuración de SonarQube/SonarCloud en el repositorio", False)], razon=0.0)
    medidas = s.get("medidas") or {}
    inds = [ind(f"Sonar configurado (projectKey: {s.get('clave') or 'no identificado'})", True)]
    if medidas:
        inds.append(ind("Medidas públicas en SonarCloud: " + ", ".join(f"{k}={v}" for k, v in medidas.items()), True))
    else:
        inds.append(ind("No se pudieron leer las medidas (no está en SonarCloud o no es público)"))
    return _res("sonar", "SonarQube", inds, razon=1.0 if medidas else 0.6)


def metricas_docs(c: Contexto):
    docs = c.buscar_docs(r"metrica|complejidad ciclomatica|throughput|latencia|mantenibilidad|code smell")
    inds = [ind("Documentos que hablan de métricas de calidad: " + (", ".join(f"`{d}`" for d in docs[:5]) or "ninguno"), bool(docs))]
    return _res("metricas_docs", "Documentación de métricas", inds, razon=None,
                textos=[(k, c.docs_md[k][:3500]) for k in docs[:3]])


def sms(c: Contexto):
    patron = r"twilio|telegram|vonage|nexmo|\bsms\b|whatsapp|messagebird|aws.?sns"
    en_paths = [p for p in c.paths if re.search(patron, norm(p))]
    en_deps = [k for k, v in c.ev["archivos"].items() if re.search(patron, norm(v))]
    inds = [
        ind("Archivos relacionados con mensajería: " + (", ".join(f"`{p}`" for p in en_paths[:5]) or "ninguno"), bool(en_paths)),
        ind("Mencionado en dependencias o documentación: " + (", ".join(f"`{p}`" for p in en_deps[:5]) or "ninguno"), bool(en_deps)),
        ind("El envío real del mensaje se verifica en la sustentación"),
    ]
    return _res("sms", "Integración de mensajería (evidencia)", inds, razon=None)


def historias_por_sprint(c: Contexto):
    if not c.hus:
        return _res("historias_por_sprint", "Historias por sprint", [ind("No hay historias de usuario identificadas", False)], razon=0.0)
    cerradas = [i for i in c.hus if i["estado"] == "closed"]
    por_sprint = Counter(i["milestone"] or "(sin milestone)" for i in cerradas)
    r = pct(len(cerradas), len(c.hus))
    inds = [ind(f"{len(cerradas)}/{len(c.hus)} historias cerradas ({r:.0%})", r >= 0.9)]
    inds += [ind(f"{sprint}: {n} historias cerradas") for sprint, n in sorted(por_sprint.items())]
    sprints = [s for s in por_sprint if s != "(sin milestone)"]
    if sprints:
        inds.append(ind(f"Promedio: {sum(por_sprint[s] for s in sprints) / len(sprints):.1f} historias por sprint"))
    return _res("historias_por_sprint", "Historias por sprint", inds, razon=r)


def _ventanas(c: Contexto):
    ms = sorted((m for m in c.ev["milestones"] if m["vence"]), key=lambda m: m["vence"])
    inicio, ventanas = "", []
    for m in ms:
        ventanas.append((m["titulo"], inicio, m["vence"]))
        inicio = m["vence"]
    return ventanas


def commits_por_sprint(c: Contexto):
    ventanas = _ventanas(c)
    if not ventanas:
        return _res("commits_por_sprint", "Commits por sprint", [ind("Los milestones no tienen fechas: no se pueden calcular commits por sprint", False)], razon=None)
    inds, cuentas = [], []
    for titulo, ini, fin in ventanas:
        n = sum(1 for k in c.commits if ini < (k["fecha"] or "") <= fin)
        cuentas.append(n)
        inds.append(ind(f"{titulo}: {n} commits"))
    inds.append(ind(f"Promedio: {sum(cuentas) / len(cuentas):.1f} commits por sprint"))
    return _res("commits_por_sprint", "Commits por sprint", inds, razon=None)


def equilibrio(c: Contexto):
    cuenta = Counter(c.quien(k) for k in c.commits)
    miembros = c.miembros()
    total = sum(cuenta.values())
    if not total or not miembros:
        return _res("equilibrio", "Equilibrio del equipo", [ind("Sin commits", False)], razon=0.0)
    partes = sorted(cuenta.get(m, 0) / total for m in miembros)
    n = len(partes)
    gini = sum((2 * (k + 1) - n - 1) * x for k, x in enumerate(partes)) / n if n > 1 else 0.0
    inds = [ind(f"Índice de desigualdad de commits (Gini): {gini:.2f} (0 = parejo, 1 = uno solo hace todo)", gini <= 0.35)]
    inds += [ind(f"@{m}: {cuenta.get(m, 0)} commits ({cuenta.get(m, 0) / total:.0%})") for m in miembros]
    return _res("equilibrio", "Equilibrio del equipo", inds, razon=max(0.0, 1 - gini))


def versiones(c: Contexto):
    rel, tags = c.ev["releases"], c.ev["tags"]
    semver = [t for t in tags if re.match(r"v?\d+\.\d+(\.\d+)?", t)]
    inds = [
        ind(f"{len(rel)} release(s) publicadas: " + (", ".join(r["tag"] for r in rel[:6]) or "—"), len(rel) >= 2),
        ind(f"{len(semver)}/{len(tags)} tags con versionado semántico", bool(semver)),
        ind("Existe CHANGELOG", any(re.match(r"changelog", p, re.I) for p in c.paths)),
    ]
    return _res("versiones", "Versiones y releases", inds, razon=1.0 if len(rel) >= 2 else 0.5 if rel or semver else 0.0)


def postmortem(c: Contexto):
    docs = [k for k in c.docs_md if re.search(r"post.?mortem|lecciones.?aprendidas", norm(k))] or c.buscar_docs(r"post.?mortem")
    if not docs:
        return _res("postmortem", "Postmortem", [ind("No se encontró un documento de postmortem (docs/ o Wiki)", False)], razon=0.0)
    texto = c.docs_md[docs[0]]
    t = norm(texto)
    inds = [
        ind(f"Postmortem en `{docs[0]}` ({len(texto.split())} palabras leídas)", len(texto.split()) >= 300),
        ind("Habla de causas raíz", bool(re.search(r"causa.?raiz|causas|por que", t))),
        ind("Propone acciones de mejora", bool(re.search(r"accion(es)? de mejora|mejora|leccion", t))),
    ]
    return _res("postmortem", "Postmortem", inds, textos=[(docs[0], texto[:6000])])


# ====================================================================== aporte individual y señales

def aporte_individual(c: Contexto) -> list[dict]:
    miembros = c.miembros()
    semanas_equipo = {_semana(k["fecha"]) for k in c.commits}
    filas = []
    for m in miembros:
        mios = [k for k in c.commits if c.quien(k) == m]
        filas.append({
            "login": m,
            "commits": len(mios),
            "dias_activos": len({(k["fecha"] or "")[:10] for k in mios}),
            "semanas_activas": len({_semana(k["fecha"]) for k in mios}),
            "semanas_equipo": len(semanas_equipo),
            "issues_cerradas": sum(1 for i in c.issues if i["estado"] == "closed" and m in i["asignados"]),
            "issues_asignadas": sum(1 for i in c.issues if m in i["asignados"]),
            "prs": sum(1 for p in c.prs if p["autor"] == m),
            "revisiones": sum(1 for p in c.prs for r in p["reviews"] if r["login"] == m and p["autor"] != m),
            "lineas": sum(k["adiciones"] or 0 for k in mios) if any(k["adiciones"] is not None for k in mios) else None,
        })
    n = len(filas) or 1
    tot_c = sum(f["commits"] for f in filas) or 1
    tot_i = sum(f["issues_cerradas"] for f in filas) or 1
    for f in filas:
        # 1.0 = aporta exactamente la parte que le corresponde en un equipo parejo
        relativo = min(1.5, (f["commits"] / tot_c * n + f["issues_cerradas"] / tot_i * n) / 2)
        regular = f["semanas_activas"] / f["semanas_equipo"] if f["semanas_equipo"] else 0
        f["indice_aporte"] = round(relativo, 2)
        f["regularidad"] = round(regular, 2)
        if relativo >= 0.7 and regular >= 0.5:
            f["factor_sugerido"] = 1.0
        elif relativo >= 0.5 and regular >= 0.35:
            f["factor_sugerido"] = 0.9
        elif relativo >= 0.2:
            f["factor_sugerido"] = 0.5
        else:
            f["factor_sugerido"] = 0.3
    return filas


def _semana(fecha: str | None) -> str:
    if not fecha:
        return ""
    y, w, _ = dt.date.fromisoformat(fecha[:10]).isocalendar()
    return f"{y}-W{w:02d}"


def senales(c: Contexto) -> list[dict]:
    """Señales de proceso. No prueban nada: indican qué preguntar en la sustentación."""
    cfg = c.cfg.get("senales", {})
    grande = cfg.get("commit_grande_lineas", 800)
    horas = cfg.get("horas_antes_de_entrega", 48)
    limite = dt.datetime.fromisoformat(c.ev["limite_utc"].replace("Z", "+00:00"))
    desde = (limite - dt.timedelta(hours=horas)).isoformat().replace("+00:00", "Z")
    salida = []
    for m in c.miembros():
        mios = [k for k in c.commits if c.quien(k) == m]
        if not mios:
            salida.append({"login": m, "tipo": "sin_commits", "texto": "No tiene commits en las ramas revisadas.", "commits": []})
            continue
        enormes = [k for k in mios if (k["adiciones"] or 0) >= grande]
        if enormes:
            salida.append({"login": m, "tipo": "commits_grandes",
                           "texto": f"{len(enormes)} commit(s) con {grande}+ líneas añadidas de una sola vez.",
                           "commits": [k["sha"][:7] for k in enormes[:5]]})
        ultima = [k for k in mios if (k["fecha"] or "") >= desde]
        if len(mios) >= 4 and len(ultima) / len(mios) >= cfg.get("max_fraccion_ultima_hora", 0.4):
            salida.append({"login": m, "tipo": "ultima_hora",
                           "texto": f"{len(ultima)}/{len(mios)} de sus commits son de las últimas {horas} horas antes del corte.",
                           "commits": [k["sha"][:7] for k in ultima[:5]]})
        con_ia = [k for k in mios if RE_IA.search(k["mensaje"])]
        if con_ia:
            salida.append({"login": m, "tipo": "marca_ia",
                           "texto": f"{len(con_ia)} commit(s) llevan firma de un asistente de IA en el mensaje.",
                           "commits": [k["sha"][:7] for k in con_ia[:5]]})
        sin_ref = [k for k in mios if not RE_REF.search(k["mensaje"])]
        if len(mios) >= 4 and len(sin_ref) / len(mios) >= 0.6:
            salida.append({"login": m, "tipo": "sin_trazabilidad",
                           "texto": f"{len(sin_ref)}/{len(mios)} de sus commits no referencian ninguna issue.",
                           "commits": [k["sha"][:7] for k in sin_ref[:5]]})
        if m.startswith("~"):
            salida.append({"login": m, "tipo": "cuenta_sin_vincular",
                           "texto": "Commits hechos con un correo que no está vinculado a una cuenta de GitHub.",
                           "commits": [k["sha"][:7] for k in mios[:3]]})
    sospechosos = [k for k, v in c.documentos.items() if RE_INYECCION.search(v)]
    sospechosos += [f"issue #{i['numero']}" for i in c.issues if RE_INYECCION.search(i["cuerpo"])]
    if sospechosos:
        salida.append({"login": "(equipo)", "tipo": "texto_dirigido_al_revisor",
                       "texto": "Hay texto que parece dirigido a manipular a un revisor automático en: " + ", ".join(sospechosos[:5]),
                       "commits": []})
    return salida


# ====================================================================== evidencias de uso de IA

RE_BOT_IA = re.compile(r"copilot|claude|devin|cursor|codex|openhands|sweep|aider|gemini|jules|coderabbit|windsurf|chatgpt", re.I)
RE_RAMA_IA = re.compile(r"^(copilot|claude|codex|cursor|devin|jules|openhands|ai)[/\-_]", re.I)
RE_TEXTO_IA = re.compile(
    r"generated (with|by) \[?(claude|copilot|chatgpt|cursor|gemini|codex)|co-authored-by:\s*(copilot|claude|cursor)"
    r"|🤖 generated|as an ai language model|como (un )?modelo de lenguaje|copilot-swe-agent",
    re.I,
)
AGENTES_IA = {"copilot", "copilot-swe-agent", "claude", "devin-ai-integration", "cursoragent", "codex",
              "google-labs-jules", "openhands-agent", "sweep-ai", "coderabbitai", "chatgpt-codex-connector"}


def es_agente_ia(login: str) -> bool:
    """Cuenta de un agente de IA (no la de un estudiante que se llame parecido)."""
    l = (login or "").lower().removesuffix("[bot]")
    return l in AGENTES_IA or ((login or "").lower().endswith("[bot]") and bool(RE_BOT_IA.search(l)))


ARCHIVOS_IA = [
    (r"(^|/)claude\.md$", "Claude Code"), (r"(^|/)\.claude/", "Claude Code"), (r"(^|/)agents\.md$", "agentes (Codex/otros)"),
    (r"(^|/)\.cursorrules$|(^|/)\.cursor/", "Cursor"), (r"(^|/)\.github/copilot-instructions\.md$", "GitHub Copilot"),
    (r"(^|/)\.windsurfrules$", "Windsurf"), (r"(^|/)\.aider", "Aider"), (r"(^|/)gemini\.md$", "Gemini CLI"),
    (r"(^|/)\.continue/", "Continue"), (r"(^|/)\.github/prompts/", "Copilot prompts"),
]


def evidencias_ia(c: Contexto) -> list[dict]:
    """Rastros verificables de herramientas de IA en el repositorio.

    nivel "directa": huella explícita de una herramienta (firma en el commit, commits o PR hechos
    por un agente de IA, ramas creadas por un agente, archivos de configuración de asistentes).
    nivel "indirecta": patrones de proceso compatibles con generar código en bloque. No prueban nada.
    Ninguna herramienta puede asegurar que NO hubo uso de IA: copiar y pegar desde un chat no deja rastro.
    """
    salida = []

    def agregar(login, nivel, tipo, detalle, refs=()):
        salida.append({"login": login, "nivel": nivel, "tipo": tipo, "detalle": detalle, "refs": list(refs)[:8]})

    # 1. Commits firmados por un asistente (Co-authored-by, "Generated with…")
    por_autor = defaultdict(list)
    for k in c.ev["commits"]:
        if RE_IA.search(k["mensaje"] or "") or RE_TEXTO_IA.search(k["mensaje"] or ""):
            por_autor[c.quien(k) or k.get("login") or k.get("nombre")].append(k["sha"][:7])
    for login, shas in por_autor.items():
        agregar(login, "directa", "commit_firmado_por_ia", f"{len(shas)} commit(s) con firma de un asistente de IA en el mensaje.", shas)

    # 2. Commits cuyo autor es un agente de IA (Copilot coding agent, Devin, Claude…)
    bots = defaultdict(list)
    for k in c.ev["commits"]:
        autor = k.get("login") or k.get("nombre") or ""
        if es_agente_ia(autor):
            bots[autor].append(k["sha"][:7])
    for autor, shas in bots.items():
        agregar("(equipo)", "directa", "commits_de_agente_ia", f"{len(shas)} commit(s) hechos por la cuenta de un agente de IA ({autor}).", shas)

    # 3. Pull requests abiertos por un agente o con texto generado
    for p in c.prs:
        autor = p.get("autor") or ""
        if es_agente_ia(autor):
            agregar("(equipo)", "directa", "pr_de_agente_ia", f"PR #{p['numero']} abierto por un agente de IA ({autor}).", [f"#{p['numero']}"])
        elif RE_TEXTO_IA.search(p.get("cuerpo") or "") or RE_TEXTO_IA.search(p.get("titulo") or ""):
            agregar(autor or "(equipo)", "directa", "pr_con_texto_generado", f"PR #{p['numero']} declara contenido generado por IA.", [f"#{p['numero']}"])
        for r in p.get("reviews", []):
            if es_agente_ia(r.get("login") or ""):
                agregar("(equipo)", "indirecta", "revision_automatica_ia", f"PR #{p['numero']} revisado por un bot de IA ({r['login']}).", [f"#{p['numero']}"])
                break

    # 4. Issues con texto que declara haber sido generado
    for i in c.issues:
        if RE_TEXTO_IA.search(i["cuerpo"] or ""):
            agregar(i.get("autor") or "(equipo)", "directa", "issue_con_texto_generado", f"Issue #{i['numero']} declara contenido generado por IA.", [f"#{i['numero']}"])

    # 5. Ramas creadas por agentes de IA
    ramas = sorted({r for r in c.ev["ramas"] if RE_RAMA_IA.match(r)} | {p["head"] for p in c.prs if RE_RAMA_IA.match(p["head"])})
    if ramas:
        agregar("(equipo)", "directa", "ramas_de_agente_ia", f"{len(ramas)} rama(s) con nombre de agente de IA.", ramas)

    # 6. Archivos de configuración de asistentes en el repositorio
    for patron, herramienta in ARCHIVOS_IA:
        hallados = [p for p in c.paths if re.search(patron, p, re.I) and "node_modules/" not in p]
        if hallados:
            agregar("(equipo)", "directa", "config_asistente_ia", f"Archivos de configuración de {herramienta} en el repo.", hallados)

    # 7. Indirectas por estudiante: bloques enormes de código escritos demasiado rápido
    grande = c.cfg.get("senales", {}).get("commit_grande_lineas", 800)
    for m in c.miembros():
        mios = sorted((k for k in c.commits if c.quien(k) == m and k["fecha"]), key=lambda k: k["fecha"])
        marcados = []
        for previo, k in zip([None] + mios, mios):
            minutos = None if previo is None else (
                dt.datetime.fromisoformat(k["fecha"].replace("Z", "+00:00"))
                - dt.datetime.fromisoformat(previo["fecha"].replace("Z", "+00:00"))).total_seconds() / 60
            rapido = (k["adiciones"] or 0) >= 500 and minutos is not None and 0 <= minutos <= 15
            enorme = (k["adiciones"] or 0) >= grande * 3
            if rapido or enorme:
                marcados.append(k)
        if marcados:
            marcados.sort(key=lambda k: -(k["adiciones"] or 0))
            agregar(m, "indirecta", "codigo_en_bloque",
                    f"{len(marcados)} commit(s) con bloques grandes de código ({grande * 3}+ líneas de una vez, "
                    "o 500+ líneas a menos de 15 minutos del commit anterior).", [k["sha"][:7] for k in marcados])
    return salida


# ====================================================================== evaluación por rúbrica

def _res(id_, titulo, indicadores, razon="auto", nivel=None, textos=None):
    if razon == "auto":
        medibles = [i["ok"] for i in indicadores if i["ok"] is not None]
        razon = sum(medibles) / len(medibles) if medibles else None
    return {"id": id_, "titulo": titulo, "indicadores": indicadores, "razon": razon, "nivel": nivel, "textos": textos or []}


CHECKS = {f.__name__: f for f in [
    estructura, readme, wiki, gitflow, conventional_commits, issues_completas, kanban, historias_estructura,
    ceremonias, hitos, trazabilidad, aporte_historias, codigo_fuente, sub_issues, pipelines, diagramas,
    patrones_gof, docker, pipeline_docker, cobertura, pipeline_pruebas, sonar, metricas_docs, sms,
    historias_por_sprint, commits_por_sprint, equilibrio, versiones, postmortem,
]}


def _nivel_disponible(criterio: dict, nombre: str) -> dict:
    """El nivel pedido o, si la rúbrica de ese criterio no lo tiene, el más cercano hacia abajo."""
    niveles = criterio["niveles"]
    por_nombre = {n["nombre"]: n for n in niveles}
    for candidato in ORDEN[ORDEN.index(nombre):]:
        if candidato in por_nombre:
            return por_nombre[candidato]
    return niveles[-1]


def sugerir(criterio: dict, resultados: list[dict]) -> dict | None:
    """Nivel y puntaje sugeridos a partir de los indicadores (None si es de juicio humano)."""
    if criterio["tipo"] == "humano":
        return None
    explicitos = [r["nivel"] for r in resultados if r["nivel"]]
    libres = [r["razon"] for r in resultados if r["razon"] is not None and not r["nivel"]]
    if explicitos:
        peor = max(explicitos, key=ORDEN.index)
        nivel = _nivel_disponible(criterio, peor)
        cayo = nivel["nombre"] != peor
        posicion = 0.0 if cayo and ORDEN.index(peor) > ORDEN.index(nivel["nombre"]) else (sum(libres) / len(libres) if libres else 0.5)
    elif libres:
        media = sum(libres) / len(libres)
        puntaje = 1 + 4 * media
        nivel = min(criterio["niveles"], key=lambda n: 0 if n["rango"][0] <= puntaje <= n["rango"][1]
                    else min(abs(puntaje - n["rango"][0]), abs(puntaje - n["rango"][1])))
        bajo, alto = nivel["rango"]
        return {"nivel": nivel["nombre"], "puntaje": round(min(max(puntaje, bajo), alto), 1), "fuente": "indicadores"}
    else:
        return None
    bajo, alto = nivel["rango"]
    return {"nivel": nivel["nombre"], "puntaje": round(bajo + (alto - bajo) * posicion, 1), "fuente": "indicadores"}


def evaluar(rubrica: dict, ev: dict, cfg: dict) -> dict:
    c = Contexto(ev, cfg)
    cache: dict[str, dict] = {}
    criterios = []
    for crit in rubrica["criterios"]:
        resultados = []
        for nombre in crit["checks"]:
            if nombre not in cache:
                cache[nombre] = CHECKS[nombre](c)
            resultados.append(cache[nombre])
        criterios.append({
            "id": crit["id"], "nombre": crit["nombre"], "peso": crit["peso"], "tipo": crit["tipo"],
            "conceptos": crit.get("conceptos", []), "niveles": crit["niveles"],
            "checks": resultados, "sugerencia": sugerir(crit, resultados), "ia": None,
        })
    return {
        "repo": ev["repo"], "entrega": rubrica["entrega"], "entrega_nombre": rubrica["nombre"], "hasta": ev["hasta"],
        "criterios": criterios, "aporte": aporte_individual(c), "senales": senales(c), "uso_ia": evidencias_ia(c),
        "avisos": ev.get("avisos", []), "preguntas_sustentacion": {},
    }


def nota_parcial(resultado: dict) -> tuple[float | None, float]:
    """(nota ponderada sobre los criterios con sugerencia, fracción del peso cubierta)."""
    suma = peso = 0.0
    for c in resultado["criterios"]:
        s = c["ia"] or c["sugerencia"]
        if s and c["peso"] > 0:
            suma += s["puntaje"] * c["peso"]
            peso += c["peso"]
    return (round(suma / peso, 2) if peso else None), round(peso, 2)
