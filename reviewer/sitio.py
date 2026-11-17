"""Sitio web del profesor: avance de cada equipo, hallazgos, uso de IA y récord por estudiante.

Genera páginas HTML estáticas a partir de PostgreSQL, con la identidad de la Pontificia
Universidad Javeriana y de Fundamentos de Ingeniería de Software:

    index.html                 panorama del curso (indicadores, gráficas y equipos)
    agente.html                qué hace el agente, cómo trabaja y qué revisa en cada entrega
    ia.html                    uso de IA en todo el curso
    estudiantes.html           listado de estudiantes
    equipo/<equipo>.html       detalle de un equipo
    estudiante/<login>.html    récord de un estudiante

    python -m reviewer sitio --salida /datos/sitio

Todos los enlaces son relativos: el sitio funciona igual en la raíz de un dominio o bajo una
ruta de un proxy reverso (https://servidor/fis/).
"""
from __future__ import annotations

import datetime as dt
import html
import os
from collections import defaultdict

from . import marca

ORG = "puj-course"
E = html.escape
SERIES = [f"var(--s{i})" for i in range(1, 7)]

CSS = marca.TOKENS + """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif}
a{color:var(--acc)}code{font-size:12px}
.barra{background:linear-gradient(120deg,var(--jav-azul-prof),var(--jav-azul-osc) 55%,var(--jav-azul));color:#fff;border-bottom:3px solid var(--jav-oro)}
.barra .in{max-width:1200px;margin:0 auto;padding:12px 16px 0;display:flex;flex-direction:column;gap:10px}
.marca{display:flex;align-items:center;gap:12px;color:#fff;text-decoration:none}
.marca .u{font-size:11px;letter-spacing:.12em;text-transform:uppercase;opacity:.8}
.marca .c{font-family:Georgia,"Times New Roman",serif;font-size:19px;font-weight:700;line-height:1.15}
.fila{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.salir{color:#fff;opacity:.85;font-size:13px;text-decoration:none;border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:4px 12px}
.salir:hover{opacity:1;background:rgba(255,255,255,.1)}
nav{display:flex;gap:4px;flex-wrap:wrap;overflow-x:auto}
nav a{color:#dce6f7;text-decoration:none;font-weight:600;font-size:14px;padding:8px 12px;border-radius:8px 8px 0 0;white-space:nowrap}
nav a:hover{background:rgba(255,255,255,.08);color:#fff}nav a.on{background:var(--bg);color:var(--fg)}
main{max-width:1200px;margin:0 auto;padding:24px 16px 56px}
.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.hero h1{font-family:Georgia,"Times New Roman",serif;font-size:28px;line-height:1.2;margin:0}
.kicker{color:var(--acc);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px}
h2{font-size:18px;margin:32px 0 12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
h2::before{content:"";width:4px;height:18px;border-radius:2px;background:var(--jav-oro)}
h3{font-size:15px;margin:0 0 6px}.mut{color:var(--mut)}p{margin:0 0 10px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.g2{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px;box-shadow:var(--sombra);min-width:0}
.card h3 a{text-decoration:none;color:var(--fg)}.card h3 a:hover{color:var(--acc)}
.kpis{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-bottom:6px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px 16px;box-shadow:var(--sombra);border-top:3px solid var(--jav-azul)}
.kpi:nth-child(2n){border-top-color:var(--jav-oro)}
.kpi .v{font-size:30px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}.kpi .v .chip{font-size:24px;padding:2px 12px}.kpi .l{color:var(--mut);font-size:13px}
.chip{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.ok{background:var(--okbg);color:var(--ok)}.warn{background:var(--warnbg);color:var(--warn)}.bad{background:var(--badbg);color:var(--bad)}
.neu{background:var(--grid);color:var(--mut)}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--bd);border-radius:12px;box-shadow:var(--sombra)}
table{border-collapse:collapse;width:100%;min-width:560px}
th,td{padding:9px 12px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:top}
th{font-size:12px;color:var(--mut);font-weight:700;text-transform:uppercase;letter-spacing:.04em;background:var(--card);position:sticky;top:0}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:color-mix(in srgb,var(--acc) 4%,transparent)}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.aviso{background:var(--jav-oro-suave);color:#3b2f00;border:1px solid #f0d77a;border-left:4px solid var(--jav-oro);border-radius:10px;padding:12px 14px}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .aviso{background:#2a2410;color:var(--fg);border-color:#5a4a14}}
ul.lst{margin:6px 0;padding-left:18px}ul.lst li{margin:2px 0}
svg{display:block;max-width:100%}svg text{fill:var(--mut);font-size:11px;font-family:inherit}
svg .eje{stroke:var(--grid)}svg .val{fill:var(--fg);font-weight:600}
.ley{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--mut);margin-top:8px}
.ley i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.mapa td.c{text-align:center;font-weight:700;font-variant-numeric:tabular-nums;min-width:68px}
.mapa .n5{background:color-mix(in srgb,var(--ok) 30%,transparent)}.mapa .n4{background:color-mix(in srgb,var(--ok) 16%,transparent)}
.mapa .n3{background:color-mix(in srgb,var(--s2) 24%,transparent)}.mapa .n2{background:color-mix(in srgb,var(--bad) 22%,transparent)}
.mapa .nh{color:var(--mut);font-weight:400;font-size:12px}
.flujo{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));counter-reset:paso}
.paso{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px;position:relative;box-shadow:var(--sombra)}
.paso::before{counter-increment:paso;content:counter(paso);position:absolute;top:-10px;left:12px;background:var(--jav-oro);color:#2b2100;
font-weight:800;font-size:12px;width:22px;height:22px;border-radius:50%;display:grid;place-items:center}
.paso b{display:block;margin:6px 0 4px}.paso p{font-size:13px;color:var(--mut);margin:0}
.lin{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))}
.ent{border-left:4px solid var(--jav-azul)}.ent.prox{border-left-color:var(--jav-oro)}
.peso{display:grid;grid-template-columns:1fr auto;gap:2px 10px;font-size:13px;margin-top:8px}
.peso .b{grid-column:1/-1;height:6px;border-radius:3px;background:var(--grid);overflow:hidden;margin-bottom:6px}
.peso .b span{display:block;height:100%;background:var(--jav-azul)}
.t-auto{background:color-mix(in srgb,var(--s3) 18%,transparent);color:var(--fg)}.t-asistido{background:color-mix(in srgb,var(--s5) 22%,transparent);color:var(--fg)}
.t-humano{background:var(--grid);color:var(--fg)}
details summary{cursor:pointer;color:var(--acc);font-weight:600}
footer{color:var(--mut);font-size:12px;text-align:center;padding:24px 16px;border-top:1px solid var(--bd)}
@media (max-width:600px){.hero h1{font-size:23px}.marca .c{font-size:16px}.kpi .v{font-size:24px}}
"""

PAGINAS = [("index.html", "Panorama"), ("agente.html", "El agente"), ("estudiantes.html", "Estudiantes"), ("ia.html", "Uso de IA")]


def _pagina(titulo: str, cuerpo: str, profundidad: int = 0, activo: str = "") -> str:
    r = "../" * profundidad
    ahora = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    nav = "".join(f'<a href="{r}{ruta}"{" class=on" if ruta == activo else ""}>{nombre}</a>' for ruta, nombre in PAGINAS)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>{E(titulo)} · {marca.PRODUCTO}</title><style>{CSS}</style></head>
<body><header class="barra"><div class="in"><div class="fila">
<a class="marca" href="{r}index.html">{marca.escudo(42)}<span><span class="u">{marca.UNIVERSIDAD}</span><br>
<span class="c">{marca.CURSO}</span></span></a><a class="salir" href="{r}salir">Salir</a></div>
<nav>{nav}</nav></div></header>
<main>{cuerpo}</main><footer>{marca.PRODUCTO} · {marca.FACULTAD}<br>Actualizado el {ahora}.
Las notas son sugerencias: la calificación la decide el profesor.</footer>
</body></html>"""


def _hero(kicker: str, titulo: str, sub: str = "", derecha: str = "") -> str:
    return (f'<div class="hero"><div><div class="kicker">{kicker}</div><h1>{titulo}</h1>'
            + (f'<p class="mut" style="margin:6px 0 0">{sub}</p>' if sub else "") + f"</div>{derecha}</div>")


def _kpis(items: list[tuple[str, str]]) -> str:
    return '<div class="kpis">' + "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{E(l)}</div></div>'
                                          for v, l in items) + "</div>"


def _tabla(encabezados: list[str], filas: list[list], numericas: set[int] = frozenset(), clase: str = "") -> str:
    if not filas:
        return '<p class="mut">Sin datos.</p>'
    th = "".join(f"<th>{E(h)}</th>" for h in encabezados)
    tr = "".join("<tr>" + "".join(f'<td class="n">{c}</td>' if i in numericas else f"<td>{c}</td>" for i, c in enumerate(f)) + "</tr>"
                 for f in filas)
    return f'<div class="tw"><table class="{clase}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _clase_nota(v) -> str:
    return "neu" if v is None else "ok" if float(v) >= 4 else "warn" if float(v) >= 3 else "bad"


def _chip_nota(v) -> str:
    if v is None:
        return '<span class="mut">—</span>'
    return f'<span class="chip {_clase_nota(v)}">{float(v):.2f}</span>'


def _chip_ia(directas: int, indirectas: int) -> str:
    if directas:
        return f'<span class="chip bad">{directas} evidencia(s) directa(s)</span>'
    if indirectas:
        return f'<span class="chip warn">sin evidencia directa · {indirectas} señal(es)</span>'
    return '<span class="chip ok">sin evidencia ni señales</span>'


# ---------------------------------------------------------------- gráficas SVG
def _color_nota(v) -> str:
    return {"ok": "var(--ok)", "warn": "var(--s2)", "bad": "var(--bad)"}.get(_clase_nota(v), "var(--mut)")


def _barras(puntos: list[tuple[str, float]], ancho=640, alto=140, unidad="commits") -> str:
    """Columnas por semana (semana, valor)."""
    if not puntos:
        return f'<p class="mut">Sin {unidad}.</p>'
    maximo = max(v for _, v in puntos) or 1
    paso = ancho / len(puntos)
    util = alto - 34
    guias = "".join(f'<line class="eje" x1="0" x2="{ancho}" y1="{alto - 18 - util * k / 4:.1f}" y2="{alto - 18 - util * k / 4:.1f}"/>'
                    for k in range(1, 5))
    barras = "".join(
        f'<rect x="{i * paso + paso * .12:.1f}" y="{alto - 18 - (v / maximo) * util:.1f}" width="{max(paso * .76, 2):.1f}" '
        f'height="{(v / maximo) * util:.1f}" rx="3" fill="url(#gb)"><title>{E(s)}: {int(v)} {unidad}</title></rect>'
        for i, (s, v) in enumerate(puntos))
    etiquetas = "".join(f'<text x="{i * paso + paso / 2:.1f}" y="{alto - 4}" text-anchor="middle">{E(s[5:])}</text>'
                        for i, (s, _) in enumerate(puntos) if len(puntos) <= 16 or i % 2 == 0)
    return (f'<svg viewBox="0 0 {ancho} {alto}" width="100%" role="img" aria-label="{E(unidad)} por semana">'
            f'<defs><linearGradient id="gb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--s1)"/>'
            f'<stop offset="1" stop-color="var(--s1)" stop-opacity=".55"/></linearGradient></defs>'
            f'<text x="0" y="10">máx. {int(maximo)}</text>{guias}{barras}{etiquetas}</svg>')


def _barras_h(items: list[tuple[str, float | None, str]], maximo: float = 5.0, ancho: int = 560) -> str:
    """Barras horizontales de pre-nota (etiqueta, valor, enlace)."""
    if not items:
        return '<p class="mut">Sin datos.</p>'
    fila, izq = 30, 200
    alto = fila * len(items) + 22
    util = ancho - izq - 50
    partes = [f'<line class="eje" x1="{izq + util * k / 5:.1f}" x2="{izq + util * k / 5:.1f}" y1="0" y2="{alto - 18}"/>'
              f'<text x="{izq + util * k / 5:.1f}" y="{alto - 4}" text-anchor="middle">{k}</text>' for k in range(0, 6)]
    for i, (etq, v, enlace) in enumerate(items):
        y = i * fila + 6
        texto = E(etq if len(etq) <= 30 else etq[:29] + "…")
        partes.append(f'<a href="{E(enlace)}"><text x="{izq - 8}" y="{y + 15}" text-anchor="end" style="fill:var(--fg)">{texto}</text></a>'
                      if enlace else f'<text x="{izq - 8}" y="{y + 15}" text-anchor="end">{texto}</text>')
        if v is None:
            partes.append(f'<text x="{izq + 4}" y="{y + 15}">sin pre-nota</text>')
            continue
        w = max(util * float(v) / maximo, 2)
        partes.append(f'<rect x="{izq}" y="{y}" width="{w:.1f}" height="20" rx="4" fill="{_color_nota(v)}"><title>{E(etq)}: {float(v):.2f}</title></rect>'
                      f'<text class="val" x="{izq + w + 6:.1f}" y="{y + 15}">{float(v):.2f}</text>')
    return (f'<svg viewBox="0 0 {ancho} {alto}" width="100%" style="max-width:{ancho}px" role="img" aria-label="Puntajes">'
            f'{"".join(partes)}</svg>')


def _lineas(series: dict[str, list[tuple[dt.date, float]]], ancho=600, alto=230, maximo=5.0) -> str:
    """Evolución de la pre-nota por equipo (una línea por equipo)."""
    puntos = [p for s in series.values() for p in s if p[1] is not None]
    if not puntos:
        return '<p class="mut">Aún no hay historia de revisiones.</p>'
    dias = sorted({d for d, _ in puntos})
    izq, der, arr, aba = 30, 12, 10, 26
    w, h = ancho - izq - der, alto - arr - aba
    x = (lambda d: izq + w / 2) if len(dias) == 1 else (lambda d: izq + w * (d - dias[0]).days / max((dias[-1] - dias[0]).days, 1))
    y = lambda v: arr + h * (1 - float(v) / maximo)
    partes = [f'<line class="eje" x1="{izq}" x2="{ancho - der}" y1="{y(k):.1f}" y2="{y(k):.1f}"/><text x="{izq - 6}" y="{y(k) + 4:.1f}" text-anchor="end">{k}</text>'
              for k in range(0, 6)]
    marcas = dias if len(dias) <= 8 else dias[:: max(len(dias) // 6, 1)]
    partes += [f'<text x="{x(d):.1f}" y="{alto - 6}" text-anchor="middle">{d:%d/%m}</text>' for d in marcas]
    ley = []
    for i, (nombre, serie) in enumerate(sorted(series.items())):
        c = SERIES[i % len(SERIES)]
        s = [(d, v) for d, v in serie if v is not None]
        if not s:
            continue
        pts = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in s)
        partes.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        partes += [f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="3.5" fill="var(--card)" stroke="{c}" stroke-width="2">'
                   f'<title>{E(nombre)} · {d:%d/%m}: {float(v):.2f}</title></circle>' for d, v in s]
        ley.append(f'<span><i style="background:{c}"></i>{E(nombre)}</span>')
    return (f'<svg viewBox="0 0 {ancho} {alto}" width="100%" role="img" aria-label="Evolución de la pre-nota">{"".join(partes)}</svg>'
            f'<div class="ley">{"".join(ley)}</div>')


def _dona(partes: list[tuple[str, float, str]], centro: str = "", sub: str = "", tam: int = 150) -> str:
    """Gráfica de dona con leyenda (etiqueta, valor, color)."""
    total = sum(v for _, v, _ in partes)
    if not total:
        return '<p class="mut">Sin datos.</p>'
    r, grosor = 54, 20
    circ = 2 * 3.141592653589793 * r
    arcos, acumulado = [], 0.0
    for etq, v, c in partes:
        if v <= 0:
            continue
        largo = circ * v / total
        arcos.append(f'<circle r="{r}" cx="75" cy="75" fill="none" stroke="{c}" stroke-width="{grosor}" '
                     f'stroke-dasharray="{largo:.2f} {circ - largo:.2f}" stroke-dashoffset="{-acumulado:.2f}" transform="rotate(-90 75 75)">'
                     f'<title>{E(etq)}: {v:g} ({100 * v / total:.0f}%)</title></circle>')
        acumulado += largo
    ley = "".join(f'<span><i style="background:{c}"></i>{E(etq)} · <b>{v:g}</b></span>' for etq, v, c in partes if v > 0)
    return (f'<div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">'
            f'<svg viewBox="0 0 150 150" width="{tam}" height="{tam}" role="img" aria-label="{E(sub or centro)}">'
            f'<circle r="{r}" cx="75" cy="75" fill="none" stroke="var(--grid)" stroke-width="{grosor}"/>{"".join(arcos)}'
            f'<text x="75" y="78" text-anchor="middle" class="val" style="font-size:24px">{E(centro)}</text>'
            f'<text x="75" y="96" text-anchor="middle">{E(sub)}</text></svg>'
            f'<div class="ley" style="flex-direction:column;margin:0">{ley}</div></div>')


def _mapa_calor(equipos: list[str], criterios: list[str], celdas: dict, enlace=lambda eq: "") -> str:
    """Tabla equipo × criterio coloreada por puntaje."""
    if not equipos or not criterios:
        return '<p class="mut">Sin datos.</p>'
    filas = []
    for eq in equipos:
        fila = [f'<a href="{E(enlace(eq))}">{E(eq)}</a>' if enlace(eq) else E(eq)]
        for cr in criterios:
            v = celdas.get((eq, cr))
            if v is None:
                fila.append('<span class="nh">profesor</span>')
            else:
                fila.append(f"{float(v):.1f}")
        filas.append(fila)
    th = "".join(f"<th>{E(h)}</th>" for h in ["Equipo"] + criterios)

    def celda(i, c, eq):
        if i == 0:
            return f"<td>{c}</td>"
        v = celdas.get((eq, criterios[i - 1]))
        k = "nh" if v is None else "n5" if v >= 4.5 else "n4" if v >= 4 else "n3" if v >= 3 else "n2"
        return f'<td class="c {k}">{c}</td>'

    tr = "".join("<tr>" + "".join(celda(i, c, eq) for i, c in enumerate(f)) + "</tr>" for eq, f in zip(equipos, filas))
    return f'<div class="tw"><table class="mapa"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _gh(repo: str, ref: str) -> str:
    ref = ref.strip()
    if ref.startswith("#"):
        return f'<a href="https://github.com/{E(repo)}/issues/{E(ref[1:])}">{E(ref)}</a>'
    if len(ref) >= 7 and all(ch in "0123456789abcdef" for ch in ref.lower()):
        return f'<a href="https://github.com/{E(repo)}/commit/{E(ref)}"><code>{E(ref)}</code></a>'
    return f"<code>{E(ref)}</code>"


def _consultar(cur, sql: str, *args) -> list[dict]:
    cur.execute(sql, args)
    columnas = [d.name for d in cur.description]
    return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def _num(n) -> str:
    return f"{int(n or 0):,}".replace(",", ".")


# ---------------------------------------------------------------- página del agente
GRUPOS = [
    ("Gestión ágil del proyecto", "Issues, tablero Kanban, historias de usuario, sprints y retrospectivas.",
     {"issues_completas", "kanban", "historias_estructura", "ceremonias", "hitos", "sub_issues", "aporte_historias",
      "historias_por_sprint", "commits_por_sprint", "equilibrio", "postmortem"}),
    ("Repositorio y código", "Estructura, GitFlow, Conventional Commits, trazabilidad commit → historia y código fuente.",
     {"estructura", "readme", "wiki", "gitflow", "conventional_commits", "trazabilidad", "codigo_fuente", "versiones"}),
    ("Diseño y arquitectura", "Diagramas, coherencia con el código y patrones de diseño GoF.",
     {"diagramas", "patrones_gof"}),
    ("Calidad y DevOps", "Pipelines, pruebas y cobertura, SonarCloud, Docker y despliegue.",
     {"pipelines", "docker", "pipeline_docker", "cobertura", "pipeline_pruebas", "sonar", "metricas_docs", "sms"}),
]
TIPOS = {"auto": "Medible en GitHub", "asistido": "Indicadores + lectura con IA", "humano": "Lo decide el profesor"}


def _pagina_agente(cfg: dict, rubricas: dict, resumen: dict) -> str:
    hoy = dt.date.today().isoformat()
    entregas = sorted((cfg.get("entregas") or {}).items(), key=lambda kv: kv[1]["fecha"])
    proxima = next((k for k, v in entregas if v["fecha"] >= hoy), None)
    revisados = set()
    tarjetas = []
    for clave, ent in entregas:
        rub = rubricas.get(clave) or {}
        crit = rub.get("criterios", [])
        for c in crit:
            revisados |= set(c.get("checks", []))
        pesos = "".join(
            f'<span>{E(c["nombre"])} <span class="chip t-{E(c["tipo"])}">{E(c["tipo"])}</span></span><b>{float(c["peso"]) * 100:.0f}%</b>'
            f'<span class="b"><span style="width:{min(float(c["peso"]) * 300, 100):.0f}%"></span></span>' for c in crit)
        estado = ("<span class='chip warn'>próxima</span>" if clave == proxima
                  else "<span class='chip ok'>cerrada</span>" if ent["fecha"] < hoy else "<span class='chip neu'>pendiente</span>")
        tarjetas.append(f'<div class="card ent{" prox" if clave == proxima else ""}"><div class="fila"><h3>{E(rub.get("nombre", clave))}</h3>{estado}</div>'
                        f'<div class="mut" style="font-size:13px">Corte: {dt.date.fromisoformat(ent["fecha"]):%d/%m/%Y}</div>'
                        f'<div class="peso">{pesos}</div></div>')
    grupos = "".join(
        f'<div class="card"><h3>{E(n)}</h3><p class="mut" style="font-size:14px">{E(d)}</p>'
        f'<div class="mut" style="font-size:12px">{len(ids & revisados)} verificaciones en las rúbricas</div></div>'
        for n, d, ids in GRUPOS)
    tipos = "".join(f'<span><span class="chip t-{k}">{k}</span> {E(v)}</span>' for k, v in TIPOS.items())
    flujo = [
        ("Recolecta", "Lee de GitHub (solo lectura) commits, ramas, issues, PR, revisiones, Actions, Wiki, tablero y SonarCloud."),
        ("Verifica", "Compara la evidencia contra la rúbrica de la entrega con indicadores deterministas y reproducibles."),
        ("Interpreta", "La IA lee historias, diagramas, patrones y postmortem con alias, nunca con nombres de estudiantes."),
        ("Propone", "Pre-nota por criterio con su evidencia, factor de aporte individual y preguntas de sustentación."),
        ("Decide el profesor", "Nada se califica solo: el profesor revisa, ajusta y califica en la sustentación oral."),
    ]
    pasos = "".join(f'<div class="paso"><b>{E(t)}</b><p>{E(d)}</p></div>' for t, d in flujo)
    return (_hero("Primer agente de apoyo docente · FIS", "Un revisor formativo para los proyectos de la asignatura",
                  "Acompaña la revisión de código, arquitectura y proceso ágil de los equipos, entrega a entrega.")
            + _kpis([(str(resumen.get("equipos", 0)), "equipos revisados"), (str(resumen.get("estudiantes", 0)), "estudiantes"),
                     (str(len(entregas)), "entregas con rúbrica"), (str(len(revisados)), "verificaciones automáticas")])
            + f"""<h2>Cómo trabaja</h2><div class="flujo">{pasos}</div>
<h2>Qué revisa</h2><div class="grid">{grupos}</div>
<h2>Las entregas y sus rúbricas</h2><div class="ley" style="margin:0 0 12px">{tipos}</div><div class="lin">{''.join(tarjetas)}</div>
<h2>Principios</h2><div class="grid">
<div class="card"><h3>Formativo, no sancionatorio</h3><p class="mut">A los equipos les muestra lo que se ve en su repositorio y les deja
preguntas para discutir. Nunca les da la nota ni la solución.</p></div>
<div class="card"><h3>Evidencia antes que opinión</h3><p class="mut">Cada pre-nota trae los indicadores y los commits, issues o PR que la
sustentan, con enlace a GitHub.</p></div>
<div class="card"><h3>No «detecta IA»</h3><p class="mut">Marca evidencia directa y señales de proceso, y las convierte en preguntas para
la sustentación, donde se premia entender el propio trabajo.</p></div>
<div class="card"><h3>Privacidad</h3><p class="mut">Datos de estudiantes solo en el servidor del curso. A la IA se le envían alias,
nunca nombres, usuarios ni correos.</p></div></div>""")


# ---------------------------------------------------------------- generación
def generar(dsn: str, salida: str, cfg: dict | None = None, rubricas: dict | None = None) -> int:
    import psycopg

    cfg, rubricas = cfg or {}, rubricas or {}
    os.makedirs(os.path.join(salida, "equipo"), exist_ok=True)
    os.makedirs(os.path.join(salida, "estudiante"), exist_ok=True)
    with psycopg.connect(dsn) as con, con.cursor() as cur:
        q = lambda sql, *a: _consultar(cur, sql, *a)
        revisiones = q("SELECT * FROM fis.v_revision_actual ORDER BY equipo, entrega")
        if not revisiones:
            _sin_datos(salida, cfg, rubricas)
            return 0
        historia = q("""SELECT DISTINCT ON (equipo, entrega, revisada::date) equipo, entrega, entrega_nombre,
                               revisada::date AS dia, pre_nota
                        FROM fis.revisiones ORDER BY equipo, entrega, revisada::date, id DESC""")
        criterios = q("SELECT * FROM fis.v_criterios ORDER BY equipo, entrega, orden")
        fallas = q("SELECT equipo, entrega, criterio, verificacion, indicador FROM fis.v_indicadores WHERE cumple = false ORDER BY equipo, entrega")
        aporte = q("SELECT * FROM fis.v_aporte ORDER BY equipo, entrega, commits DESC")
        record = q("""SELECT DISTINCT ON (a.login, r.entrega, r.revisada::date) a.login, r.equipo, r.entrega, r.entrega_nombre,
                             r.hasta, r.revisada::date AS dia, a.commits, a.semanas_activas, a.semanas_equipo, a.issues_cerradas,
                             a.prs, a.revisiones, a.lineas, a.indice_aporte, a.factor_sugerido
                      FROM fis.aporte a JOIN fis.revisiones r ON r.id = a.revision_id
                      ORDER BY a.login, r.entrega, r.revisada::date, r.id DESC""")
        uso_ia = q("SELECT * FROM fis.v_uso_ia ORDER BY equipo, entrega, nivel, login")
        senales = q("SELECT * FROM fis.v_senales ORDER BY equipo, entrega, login")
        preguntas = q("SELECT * FROM fis.v_preguntas ORDER BY equipo, entrega, login, orden")
        semanas = q("""SELECT equipo, login, semana, commits, lineas FROM fis.v_commits_semana ORDER BY semana""")
        commits_top = q("""SELECT * FROM (SELECT repo, equipo, login, sha, fecha, mensaje, adiciones,
                                  row_number() OVER (PARTITION BY repo, login ORDER BY fecha DESC) AS n
                           FROM fis.commits WHERE NOT es_merge) t WHERE n <= 12""")
        actividad = {r["equipo"]: r for r in q("""
            SELECT equipo, count(*) FILTER (WHERE NOT es_merge) AS commits,
                   round(100.0 * avg(convencional::int) FILTER (WHERE NOT es_merge)) AS conv,
                   round(100.0 * avg(referencia_issue::int) FILTER (WHERE NOT es_merge)) AS ref,
                   max(fecha) AS ultimo FROM fis.commits GROUP BY equipo""")}

    # Uso de IA y señales: solo la revisión más reciente de cada equipo (ya incluye todos los commits);
    # mostrar las de cada entrega repetiría el mismo commit varias veces.
    nombre_entrega = {r["entrega"]: r["entrega_nombre"] for r in revisiones}
    ultima_de = {}
    for r in revisiones:
        if r["equipo"] not in ultima_de or str(r["hasta"]) > str(ultima_de[r["equipo"]][1]):
            ultima_de[r["equipo"]] = (r["entrega"], r["hasta"])
    vigente = lambda f: ultima_de.get(f["equipo"], (None,))[0] == f["entrega"]
    uso_ia = [f for f in uso_ia if vigente(f)]
    senales = [f for f in senales if vigente(f)]

    por = lambda filas, *claves: _agrupar(filas, claves)
    rev_eq, crit_eq, fal_eq = por(revisiones, "equipo"), por(criterios, "equipo", "entrega"), por(fallas, "equipo", "entrega")
    ap_eq, ia_eq, sen_eq = por(aporte, "equipo"), por(uso_ia, "equipo"), por(senales, "equipo")
    preg_lg, rec_lg, ia_lg = por(preguntas, "login"), por(record, "login"), por(uso_ia, "login")
    sem_lg, sem_eq, top_lg, hist_eq = por(semanas, "login"), por(semanas, "equipo"), por(commits_top, "login"), por(historia, "equipo")
    sen_lg = por(senales, "login")
    repo_de = {r["equipo"]: r["repo"] for r in revisiones}
    equipo_de = {}
    for a in aporte:
        equipo_de.setdefault(a["login"], a["equipo"])

    def ia_cuenta(filas):
        d = {(f["tipo"], f["login"], f["detalle"]) for f in filas if f["nivel"] == "directa"}
        i = {(f["tipo"], f["login"]) for f in filas if f["nivel"] == "indirecta"}
        return len(d), len(i)

    def ia_estudiante(login):
        return ia_cuenta([f for f in uso_ia if f["login"] == login])

    entregas = sorted({(r["entrega"], r["entrega_nombre"]) for r in revisiones})
    ent_actual = max((e for e, _ in entregas), default=None)
    periodo = (cfg.get("periodo") or (revisiones[0]["repo"].split("_") + ["", ""])[1])
    total_commits = sum(int(a.get("commits") or 0) for a in actividad.values())
    notas_actuales = [float(r["pre_nota"]) for r in revisiones if r["entrega"] == ent_actual and r["pre_nota"] is not None]
    promedio = sum(notas_actuales) / len(notas_actuales) if notas_actuales else None
    total_d = sum(ia_cuenta(v)[0] for v in ia_eq.values())
    estados_ia = [ia_estudiante(l) for l in equipo_de]
    n_dir = sum(1 for d, _ in estados_ia if d)
    n_ind = sum(1 for d, i in estados_ia if not d and i)
    resumen = {"equipos": len(rev_eq), "estudiantes": len(equipo_de)}

    # ------------------------------------------------------------ index
    tarjetas = []
    for eq, filas in rev_eq.items():
        d, i = ia_cuenta(ia_eq.get(eq, []))
        notas = "".join(f'<div class="fila" style="margin:3px 0"><span>{E(f["entrega_nombre"])}</span>{_chip_nota(f["pre_nota"])}</div>' for f in filas)
        act = actividad.get(eq, {})
        tarjetas.append(f"""<div class="card"><h3><a href="equipo/{E(eq)}.html">{E(eq)}</a></h3>
<div class="mut" style="font-size:13px">{filas[0]['integrantes']} integrantes · {_num(act.get('commits'))} commits · último {E(str(act.get('ultimo') or '')[:10])}</div>
<div style="margin:10px 0">{notas}</div><div>{_chip_ia(d, i)}</div></div>""")
    barras_eq = _barras_h([(eq, next((f["pre_nota"] for f in filas if f["entrega"] == ent_actual), None), f"equipo/{eq}.html")
                           for eq, filas in rev_eq.items()])
    series = {eq: [(f["dia"], f["pre_nota"]) for f in filas if f["entrega"] == ent_actual] for eq, filas in hist_eq.items()}
    nombres_cr, celdas = [], {}
    for c in criterios:
        if c["entrega"] != ent_actual:
            continue
        if c["criterio"] not in nombres_cr:
            nombres_cr.append(c["criterio"])
        if c["puntaje"] is not None:
            celdas[(c["equipo"], c["criterio"])] = float(c["puntaje"])
    hallazgos = []
    for eq in rev_eq:
        ultima = max((e for e, _ in entregas if (eq, e) in fal_eq), default=None)
        if ultima:
            hallazgos.append([f'<a href="equipo/{E(eq)}.html">{E(eq)}</a>', E(dict(entregas)[ultima]),
                              "<ul class='lst'>" + "".join(f"<li>{E(f['indicador'])}</li>" for f in fal_eq[(eq, ultima)][:5]) + "</ul>"])
    nombre_actual = E(dict(entregas).get(ent_actual, ""))
    cuerpo = (_hero(f"Período {E(str(periodo))} · {nombre_actual}", "Panorama del curso",
                    "Revisión automática diaria de los repositorios de los equipos en GitHub (solo lectura).")
              + _kpis([(str(len(rev_eq)), "equipos"), (str(len(equipo_de)), "estudiantes"), (_num(total_commits), "commits revisados"),
                       (f"{promedio:.2f}" if promedio is not None else "—", f"pre-nota promedio · {dict(entregas).get(ent_actual, '')}"),
                       (str(total_d), "evidencias directas de IA")])
              + f"""<div class="aviso" style="margin-top:14px"><b>Uso de IA:</b> {'ningún equipo tiene evidencia directa de herramientas de IA en GitHub' if not total_d else f'{total_d} evidencia(s) directa(s)'}.
<a href="ia.html">Ver el detalle por estudiante</a>.</div>
<div class="g2" style="margin-top:14px"><div class="card"><h3>Pre-nota por equipo · {nombre_actual}</h3>{barras_eq}</div>
<div class="card"><h3>Evolución de la pre-nota · {nombre_actual}</h3>{_lineas(series)}</div></div>
<h2>Mapa de criterios · {nombre_actual}</h2><p class="mut">Puntaje sugerido por criterio (0 a 5). «profesor» = criterio que solo califica el profesor.</p>
{_mapa_calor(list(rev_eq), nombres_cr, celdas, lambda eq: f"equipo/{eq}.html")}
<h2>Equipos</h2><div class="grid">{''.join(tarjetas)}</div>
<h2>Hallazgos principales (última entrega revisada)</h2>{_tabla(['Equipo', 'Entrega', 'Lo que no se cumple'], hallazgos)}""")
    _escribir(salida, "index.html", _pagina("Panorama", cuerpo, activo="index.html"))
    _escribir(salida, "agente.html", _pagina("El agente", _pagina_agente(cfg, rubricas, resumen), activo="agente.html"))

    # ------------------------------------------------------------ ia.html
    filas_ia = []
    for login in sorted(equipo_de, key=lambda l: (equipo_de[l], l.lower())):
        propias = [f for f in uso_ia if f["login"] == login]
        d, i = ia_cuenta(propias)
        detalle = "<ul class='lst'>" + "".join(
            f"<li>{'🔴' if f['nivel'] == 'directa' else '🟡'} {E(f['detalle'])}</li>"
            for f in {(f['nivel'], f['detalle']): f for f in propias}.values()) + "</ul>" if propias else '<span class="mut">—</span>'
        filas_ia.append([f'<a href="estudiante/{E(login)}.html">{E(login)}</a>', E(equipo_de[login]), _chip_ia(d, i), detalle])
    de_equipo = [f for f in uso_ia if f["login"] == "(equipo)"]
    filas_eq = [[E(f["equipo"]), "🔴 directa" if f["nivel"] == "directa" else "🟡 indirecta", E(f["detalle"]),
                 " ".join(_gh(f["repo"], r) for r in (f["refs"] or "").split(",")[:6] if r.strip())]
                for f in {(f["equipo"], f["detalle"]): f for f in de_equipo}.values()]
    dona_ia = _dona([("Con evidencia directa", n_dir, "var(--bad)"), ("Solo señales indirectas", n_ind, "var(--s2)"),
                     ("Sin evidencia ni señales", len(equipo_de) - n_dir - n_ind, "var(--ok)")],
                    str(len(equipo_de)), "estudiantes")
    cuerpo = _hero("Transparencia en el proceso", "Uso de inteligencia artificial") + f"""
<div class="g2"><div class="card"><h3>Estudiantes por resultado</h3>{dona_ia}</div>
<div class="aviso"><b>Qué se verifica.</b> Evidencia <b>directa</b> (🔴): firmas de asistentes en commits, PR o issues
(<code>Co-authored-by: Copilot/Claude</code>, «Generated with…»); commits, PR o revisiones hechos por cuentas de agentes de IA;
ramas creadas por agentes (<code>copilot/…</code>, <code>claude/…</code>); archivos de configuración de asistentes en el repo
(<code>CLAUDE.md</code>, <code>AGENTS.md</code>, <code>.cursorrules</code>, <code>copilot-instructions.md</code>).
Señales <b>indirectas</b> (🟡): bloques de código de cientos o miles de líneas escritos de una vez o a minutos del commit anterior,
sin contar archivos generados (lockfiles, imágenes, datos).<br><br>
<b>Límite importante:</b> ninguna revisión de GitHub puede asegurar que <i>no</i> se usó IA. Copiar y pegar desde un chat no deja
rastro. Las señales indirectas solo dicen a quién y sobre qué commit preguntar en la sustentación.</div></div>
<h2>Por estudiante</h2>{_tabla(['Estudiante', 'Equipo', 'Resultado', 'Detalle'], filas_ia)}
<h2>A nivel de equipo</h2>{_tabla(['Equipo', 'Tipo', 'Detalle', 'Referencias'], filas_eq)}"""
    _escribir(salida, "ia.html", _pagina("Uso de IA", cuerpo, activo="ia.html"))

    # ------------------------------------------------------------ equipos
    for eq, filas in rev_eq.items():
        repo = repo_de[eq]
        secciones = []
        for f in filas:
            ent = f["entrega"]
            crs = crit_eq.get((eq, ent), [])
            cr = [[E(c["criterio"]), f'{float(c["peso"]) * 100:.0f}%', f'<span class="chip t-{E(c["tipo"])}">{E(c["tipo"])}</span>',
                   E(c["nivel"] or "—"), _chip_nota(c["puntaje"]) if c["puntaje"] is not None else '<span class="mut">profesor</span>',
                   E(c["justificacion_ia"] or "")] for c in crs]
            grafica = _barras_h([(c["criterio"], c["puntaje"], "") for c in crs if c["puntaje"] is not None])
            fl = "".join(f"<li><b>{E(x['verificacion'])}:</b> {E(x['indicador'])}</li>" for x in fal_eq.get((eq, ent), []))
            secciones.append(f"""<h2>{E(f['entrega_nombre'])} <span class="mut" style="font-weight:400;font-size:14px">corte {f['hasta']} · pre-nota</span>
{_chip_nota(f['pre_nota'])} <span class="mut" style="font-weight:400;font-size:14px">({float(f['peso_cubierto']) * 100:.0f}% del peso)</span></h2>
<div class="card" style="margin-bottom:12px">{grafica}</div>
{_tabla(['Criterio', 'Peso', 'Tipo', 'Nivel', 'Puntaje', 'Justificación (IA)'], cr)}
<details style="margin-top:10px"><summary>Indicadores que no se cumplen ({len(fal_eq.get((eq, ent), []))})</summary><ul class="lst">{fl}</ul></details>""")
        ultima = filas[-1]["entrega"]
        miembros = [a for a in ap_eq.get(eq, []) if a["entrega"] == ultima]
        integrantes = [[f'<a href="../estudiante/{E(a["login"])}.html">{E(a["login"])}</a>', a["commits"],
                        f'{a["semanas_activas"]}/{a["semanas_equipo"]}', a["issues_cerradas"], a["prs"], a["revisiones"],
                        _num(a["lineas"]), f'<b>{a["factor_sugerido"]}</b>'] for a in miembros]
        por_sem = defaultdict(int)
        for s in sem_eq.get(eq, []):
            por_sem[str(s["semana"])] += s["commits"]
        d, i = ia_cuenta(ia_eq.get(eq, []))
        ia_items = "".join(f"<li>{'🔴' if x['nivel'] == 'directa' else '🟡'} <b>{E(x['login'])}</b>: {E(x['detalle'])}</li>"
                           for x in {(x['login'], x['detalle']): x for x in ia_eq.get(eq, [])}.values())
        sn = "".join(f"<li><b>{E(x['login'])}</b>: {E(x['detalle'])}</li>" for x in {(x['login'], x['detalle']): x for x in sen_eq.get(eq, [])}.values())
        act = actividad.get(eq, {})
        dona = _dona([(a["login"], float(a["commits"] or 0), SERIES[k % len(SERIES)]) for k, a in enumerate(miembros)],
                     _num(sum(int(a["commits"] or 0) for a in miembros)), "commits")
        cuerpo = (_hero(f'Equipo · <a href="https://github.com/{E(repo)}" style="color:inherit">{E(repo)}</a>', E(eq))
                  + _kpis([(_chip_nota(filas[-1]["pre_nota"]), f"pre-nota · {filas[-1]['entrega_nombre']}"),
                           (str(filas[0]["integrantes"]), "integrantes"), (_num(act.get("commits")), "commits"),
                           (f'{act.get("conv") or 0:.0f}%', "commits convencionales"), (f'{act.get("ref") or 0:.0f}%', "commits con issue")])
                  + f"""<div class="g2" style="margin-top:14px"><div class="card"><h3>Reparto de commits</h3>{dona}</div>
<div class="card"><h3>Commits por semana</h3>{_barras(sorted(por_sem.items()))}</div></div>
<h2>Integrantes</h2>{_tabla(['Estudiante', 'Commits', 'Semanas', 'Issues cerradas', 'PRs', 'Revisiones', 'Líneas', 'Factor sugerido'], integrantes, {1, 3, 4, 5, 6, 7})}
<div class="g2" style="margin-top:6px"><div><h2>Uso de IA {_chip_ia(d, i)}</h2><ul class="lst">{ia_items or '<li class="mut">Sin señales.</li>'}</ul></div>
<div><h2>Señales de proceso</h2><ul class="lst">{sn or '<li class="mut">Ninguna.</li>'}</ul></div></div>
{''.join(secciones)}""")
        _escribir(salida, f"equipo/{eq}.html", _pagina(eq, cuerpo, 1))

    # ------------------------------------------------------------ estudiantes
    filas_est = []
    for login, eq in sorted(equipo_de.items(), key=lambda kv: (kv[1], kv[0].lower())):
        repo = repo_de[eq]
        rec = rec_lg.get(login, [])
        filas_rec = [[E(r["entrega_nombre"]), f'{r["hasta"]:%d/%m/%Y}', f'{r["dia"]:%d/%m/%Y}', r["commits"], f'{r["semanas_activas"]}/{r["semanas_equipo"]}',
                      r["issues_cerradas"], r["prs"], r["revisiones"], _num(r["lineas"]),
                      r["indice_aporte"], f'<b>{r["factor_sugerido"]}</b>'] for r in rec]
        propias = ia_lg.get(login, [])
        d, i = ia_cuenta(propias)
        ia_items = "".join(
            f"<li>{'🔴' if x['nivel'] == 'directa' else '🟡'} {E(x['detalle'])}<br>"
            + " ".join(_gh(repo, r) for r in (x["refs"] or "").split(",")[:8] if r.strip()) + "</li>"
            for x in {(x['nivel'], x['detalle']): x for x in propias}.values())
        sn = "".join(f"<li>{E(x['detalle'])}</li>" for x in {x['detalle']: x for x in sen_lg.get(login, [])}.values())
        pq = defaultdict(list)
        for p in preg_lg.get(login, []):
            pq[p["entrega"]].append(p["pregunta"])
        preguntas_html = "".join(f"<h3>{E(nombre_entrega.get(ent, ent))}</h3><ol>" + "".join(f"<li>{E(x)}</li>" for x in ps) + "</ol>" for ent, ps in sorted(pq.items()))
        ultimos = [[f'{str(c["fecha"])[:10]}', _gh(repo, c["sha"][:7]), E((c["mensaje"] or "")[:110]), c["adiciones"] or 0]
                   for c in sorted(top_lg.get(login, []), key=lambda c: str(c["fecha"]), reverse=True)]
        ultimo = rec[-1] if rec else {}
        cuerpo = (_hero(f'Estudiante · equipo <a href="../equipo/{E(eq)}.html">{E(eq)}</a>', E(login),
                        f'<a href="https://github.com/{E(login)}">perfil en GitHub</a>')
                  + _kpis([(str(ultimo.get("commits", 0)), "commits"),
                           (f'{ultimo.get("semanas_activas", 0)}/{ultimo.get("semanas_equipo", 0)}', "semanas activas"),
                           (str(ultimo.get("issues_cerradas", 0)), "issues cerradas"), (str(ultimo.get("prs", 0)), "PR"),
                           (str(ultimo.get("factor_sugerido", "—")), "factor sugerido")])
                  + f"""<div class="g2" style="margin-top:14px"><div class="card"><h3>Commits por semana</h3>
{_barras([(str(s['semana']), s['commits']) for s in sem_lg.get(login, []) if s['equipo'] == eq])}</div>
<div class="card"><h3>Uso de IA {_chip_ia(d, i)}</h3><ul class="lst">{ia_items or '<li class="mut">Sin evidencia directa ni señales indirectas.</li>'}</ul>
<h3 style="margin-top:14px">Señales de proceso</h3><ul class="lst">{sn or '<li class="mut">Ninguna.</li>'}</ul></div></div>
<h2>Récord por entrega</h2><p class="mut">Una fila por entrega y por día de revisión: así se ve la evolución.</p>
{_tabla(['Entrega', 'Corte', 'Revisado', 'Commits', 'Semanas', 'Issues cerradas', 'PRs', 'Revisiones', 'Líneas', 'Índice', 'Factor'], filas_rec, {3, 5, 6, 7, 8, 9, 10})}
<h2>Preguntas para la sustentación</h2><div class="card">{preguntas_html or '<p class="mut">Sin preguntas generadas.</p>'}</div>
<h2>Últimos commits</h2>{_tabla(['Fecha', 'Commit', 'Mensaje', 'Líneas'], ultimos, {3})}""")
        _escribir(salida, f"estudiante/{login}.html", _pagina(login, cuerpo, 1))
        filas_est.append([f'<a href="estudiante/{E(login)}.html">{E(login)}</a>', f'<a href="equipo/{E(eq)}.html">{E(eq)}</a>',
                          ultimo.get("commits", 0), f'{ultimo.get("semanas_activas", 0)}/{ultimo.get("semanas_equipo", 0)}',
                          ultimo.get("issues_cerradas", 0), f'<b>{ultimo.get("factor_sugerido", "—")}</b>', _chip_ia(d, i)])
    _escribir(salida, "estudiantes.html", _pagina("Estudiantes", _hero("Récord individual", "Estudiantes",
              f"{len(equipo_de)} estudiantes en {len(rev_eq)} equipos. Abra un estudiante para ver su récord y las preguntas de sustentación.")
              + _tabla(["Estudiante", "Equipo", "Commits", "Semanas", "Issues cerradas", "Factor sugerido", "Uso de IA"], filas_est, {2, 4}),
              activo="estudiantes.html"))
    return len(equipo_de)


def _sin_datos(salida: str, cfg: dict, rubricas: dict) -> None:
    """Primera instalación: el sitio ya se ve, aunque la primera revisión siga corriendo."""
    aviso = _hero("Primera revisión en curso", "Panorama del curso") + (
        '<div class="aviso">Todavía no hay revisiones guardadas. La primera corrida tarda unos minutos por equipo; '
        'esta página se actualiza sola cuando termine. Mientras tanto, vea <a href="agente.html">qué hace el agente</a>.</div>')
    _escribir(salida, "index.html", _pagina("Panorama", aviso, activo="index.html"))
    _escribir(salida, "agente.html", _pagina("El agente", _pagina_agente(cfg, rubricas, {}), activo="agente.html"))
    for ruta, nombre in (("estudiantes.html", "Estudiantes"), ("ia.html", "Uso de IA")):
        _escribir(salida, ruta, _pagina(nombre, _hero("Sin datos aún", nombre), activo=ruta))


def _agrupar(filas: list[dict], claves: tuple) -> dict:
    salida: dict = defaultdict(list)
    for f in filas:
        k = f[claves[0]] if len(claves) == 1 else tuple(f[c] for c in claves)
        salida[k].append(f)
    return dict(salida)


def _escribir(base: str, ruta: str, contenido: str) -> None:
    destino = os.path.join(base, ruta)
    temporal = destino + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        f.write(contenido)
    os.replace(temporal, destino)
