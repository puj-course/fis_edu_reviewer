"""Pestaña «Ágil» del portal: sprints, ceremonias y cada registro que escribieron los equipos."""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from .agil import NOMBRE, ORDEN
from .sitio import E, _hero, _kpis, _tabla, barra_equipo

CSS_EXTRA = """<style>
.reg{border:1px solid var(--bd);border-radius:12px;background:var(--card);margin-bottom:10px;box-shadow:var(--sombra)}
.reg>summary{list-style:none;padding:12px 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;cursor:pointer;color:var(--fg);font-weight:400}
.reg>summary::-webkit-details-marker{display:none}.reg[open]>summary{border-bottom:1px solid var(--bd)}
.reg .cuerpo{padding:12px 14px}.reg .meta{font-size:13px;color:var(--mut);margin-bottom:8px}
pre.texto{white-space:pre-wrap;word-wrap:break-word;font-family:inherit;font-size:14px;background:var(--bg);border:1px solid var(--bd);
border-radius:10px;padding:12px;margin:6px 0;max-height:none}
.com{border-left:3px solid var(--jav-oro);padding-left:10px;margin:10px 0}
.t-planning{background:color-mix(in srgb,var(--s1) 18%,transparent)}.t-daily{background:color-mix(in srgb,var(--s3) 18%,transparent)}
.t-review{background:color-mix(in srgb,var(--s5) 22%,transparent)}.t-retro{background:color-mix(in srgb,var(--s6) 22%,transparent)}
.sem td.c{text-align:center;font-weight:700}.sem .si{background:color-mix(in srgb,var(--ok) 22%,transparent)}
.sem .no{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad)}.sem .medio{background:color-mix(in srgb,var(--s2) 22%,transparent)}
.filtros{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 14px}
</style>"""


def _pct(v) -> str:
    return "—" if v is None else f"{float(v) * 100:.0f}%"


def _chip_pct(v, bueno=0.8, medio=0.5) -> str:
    if v is None:
        return '<span class="chip neu">—</span>'
    v = float(v)
    return f'<span class="chip {"ok" if v >= bueno else "warn" if v >= medio else "bad"}">{v * 100:.0f}%</span>'


def _chip_calidad(v) -> str:
    v = int(v or 0)
    return f'<span class="chip {"ok" if v >= 70 else "warn" if v >= 40 else "bad"}" title="calidad del registro">calidad {v}</span>'


def _chip_ia(estilo, llm) -> str:
    partes = []
    if llm is not None:
        v = float(llm)
        partes.append(f'<span class="chip {"bad" if v >= 0.7 else "warn" if v >= 0.4 else "ok"}" title="juicio de la IA">IA {v * 100:.0f}%</span>')
    if estilo and float(estilo) >= 0.3:
        v = float(estilo)
        partes.append(f'<span class="chip {"bad" if v >= 0.6 else "warn"}" title="rasgos de estilo">estilo {v * 100:.0f}%</span>')
    return " ".join(partes)


def resumen(q, r: str) -> str:
    filas = q("SELECT * FROM fis.agil_resumen ORDER BY equipo")
    explicacion = (_hero("Metodología ágil", "Sprints y ceremonias de los equipos",
                         "Lo que cada equipo registró en GitHub: sprints del tablero (Projects) y las issues de Sprint Planning, "
                         "Dailies, Sprint Review y Retrospectiva, con sus comentarios.")
                   + '<div class="aviso"><b>Cómo leerlo.</b> <i>Cumplimiento</i> combina planning, dailies, review y retro por sprint y '
                     'la continuidad (que siempre haya un sprint en curso). <i>Calidad</i> mide si cada registro dice lo que debe '
                     '(el daily: qué se hizo, qué se hará e impedimentos; la retro: qué salió bien, qué mejorar y acciones). '
                     '<i>IA</i> es un indicio, nunca una prueba: rasgos de estilo y el juicio de la IA sobre si el texto suena generado. '
                     'Úselo para decidir qué preguntar.</div>')
    if not filas:
        return explicacion + f'<p class="mut" style="margin-top:14px">Aún no hay análisis ágil. Pida una revisión en <a href="{r}revisiones">Revisiones</a>.</p>'
    faltas = {x["equipo"]: x for x in q("""
        SELECT equipo, count(*) FILTER (WHERE coalesce(planning, '') = '') AS planning,
               count(*) FILTER (WHERE coalesce(review, '') = '') AS review, count(*) FILTER (WHERE coalesce(retro, '') = '') AS retro
        FROM fis.agil_sprints WHERE NOT en_curso GROUP BY equipo""")}

    def alertas(f) -> str:
        """Lo que conviene revisar primero en cada equipo, con enlace directo."""
        base = f'{r}agil/{E(f["equipo"])}'
        x = faltas.get(f["equipo"]) or {}
        items = []
        if not f["sprint_activo"]:
            items.append('<span class="chip bad">sin sprint en curso</span>')
        sin = [f'{x[k]} sin {n}' for k, n in (("planning", "planning"), ("review", "review"), ("retro", "retro")) if x.get(k)]
        if sin:
            items.append(f'<span class="chip warn">sprints: {", ".join(sin)}</span>')
        if f["sin_contenido"]:
            items.append(f'<a class="chip warn" href="{base}?orden=calidad">{f["sin_contenido"]} vacíos</a>')
        if f["ia_llm_altos"]:
            items.append(f'<a class="chip bad" href="{base}?orden=ia">{f["ia_llm_altos"]} con IA</a>')
        return " ".join(items) or '<span class="chip ok">sin alertas</span>'

    tabla = _tabla(["Equipo", "Cumplimiento", "Qué revisar", "Planning", "Dailies", "Review", "Retro", "Continuidad", "Sprint en curso",
                    "Calidad media", "Sin contenido", "IA (media · altos)"],
                   [[f'<a href="{r}agil/{E(f["equipo"])}">{E(f["equipo"])}</a>', _chip_pct(f["cumplimiento"]), alertas(f), _pct(f["planning"]),
                     _pct(f["dailies"]), _pct(f["review"]), _pct(f["retro"]), _pct(f["continuidad"]),
                     '<span class="chip ok">sí</span>' if f["sprint_activo"] else '<span class="chip bad">no</span>',
                     _chip_calidad(f["calidad_media"]), f["sin_contenido"],
                     (f'{_pct(f["ia_llm_media"])} · <b>{f["ia_llm_altos"] or 0}</b>' if f["ia_llm_media"] is not None
                      else f'estilo {_pct(f["ia_estilo_media"])}')] for f in filas])
    return CSS_EXTRA + explicacion + "<h2>Comparación de equipos</h2>" + tabla


def equipo(q, r: str, eq: str, tipo: str = "", orden: str = "fecha", abrir: int | None = None, acciones: str = "") -> str | None:
    res = q("SELECT * FROM fis.agil_resumen WHERE equipo = %s", eq)
    if not res:
        return None
    a = res[0]
    sprints = q("SELECT * FROM fis.agil_sprints WHERE equipo = %s ORDER BY orden", eq)
    regs = q("SELECT * FROM fis.agil_registros WHERE equipo = %s ORDER BY fecha, numero", eq)
    todos = [x["equipo"] for x in q("SELECT equipo FROM fis.agil_resumen ORDER BY equipo")]
    base = f"{r}agil/{E(eq)}"

    # Sprints: cada #n lleva al registro ya abierto (sin JavaScript: el servidor lo marca abierto).
    filas_s = []
    for s in sprints:
        enl = lambda nums: " ".join(f'<a href="{base}?abrir={n}#r{n}">#{n}</a>' for n in (nums or "").split(",") if n) or '<span class="chip bad">falta</span>'
        filas_s.append([f'<b>{E(s["titulo"])}</b>' + (' <span class="chip warn">en curso</span>' if s["en_curso"] else ""),
                        f'{s["inicio"]:%d/%m} – {s["fin"]:%d/%m}', f'{s["hechos"]}/{s["items"]}', f'{float(s["estimacion"] or 0):g}',
                        enl(s["planning"]), f'{s["dailies"]}/{s["dailies_esperados"]} {_chip_pct(min(s["dailies"] / max(s["dailies_esperados"], 1), 1), 0.7, 0.4)}',
                        enl(s["review"]), enl(s["retro"])])

    # Semana a semana
    por_semana = defaultdict(lambda: defaultdict(int))
    for x in regs:
        fechas = (x["fechas"] or "").split(",") if x["tipo"] == "daily" else [x["fecha"].isoformat()]
        for f in fechas:
            if f:
                d = dt.date.fromisoformat(f)
                por_semana[d - dt.timedelta(days=d.weekday())][x["tipo"]] += 1
    filas_w = []
    if por_semana:
        lunes = min(por_semana)
        fin = max(max(por_semana), a["hasta"] - dt.timedelta(days=a["hasta"].weekday()))
        while lunes <= fin:
            c = por_semana.get(lunes, {})
            celda = lambda n, meta: f'<td class="c {"si" if n >= meta else "medio" if n else "no"}">{n or "—"}</td>'
            filas_w.append(f'<tr><td>{lunes:%d/%m} – {lunes + dt.timedelta(days=6):%d/%m}</td>{celda(c.get("planning", 0), 1)}'
                           f'{celda(c.get("daily", 0), a["dailies_por_semana"])}{celda(c.get("review", 0), 1)}{celda(c.get("retro", 0), 1)}</tr>')
            lunes += dt.timedelta(days=7)
    semanas = ('<div class="tw"><table class="sem"><thead><tr><th>Semana</th><th>Planning</th><th>Dailies</th><th>Review</th><th>Retro</th>'
               f'</tr></thead><tbody>{"".join(filas_w)}</tbody></table></div>') if filas_w else '<p class="mut">Sin registros.</p>'

    # Registros
    lista = [x for x in regs if not tipo or x["tipo"] == tipo]
    if orden == "ia":
        lista.sort(key=lambda x: -max(float(x["ia_llm"] or 0), float(x["ia_estilo"] or 0)))
    elif orden == "calidad":
        lista.sort(key=lambda x: x["calidad"])
    tarjetas = []
    for x in lista:
        comentarios = x["comentarios"] if isinstance(x["comentarios"], list) else json.loads(x["comentarios"] or "[]")
        coms = "".join(f'<div class="com"><div class="meta"><b>@{E(c.get("autor") or "")}</b> · {E((c.get("fecha") or "")[:16].replace("T", " "))}</div>'
                       f'<pre class="texto">{E(c.get("cuerpo") or "")}</pre></div>' for c in comentarios)
        detalles = []
        if x["faltan"]:
            detalles.append(f'<b>Le falta:</b> {E(x["faltan"])}')
        if x["ia_rasgos"]:
            detalles.append(f'<b>Rasgos de estilo:</b> {E(x["ia_rasgos"])}')
        if x["ia_razones"]:
            detalles.append(f'<b>Juicio de la IA:</b> {E(x["ia_razones"])}')
        tarjetas.append(f"""<details class="reg" id="r{x['numero']}"{' open' if x['numero'] == abrir else ''}><summary><span class="chip t-{E(x['tipo'])}">{E(NOMBRE.get(x['tipo'], x['tipo']))}</span>
<b>{x['fecha']:%d/%m/%Y}</b> <span>#{x['numero']} {E(x['titulo'])}</span> <span class="mut">{E(x['sprint'] or 'sin sprint')}</span>
{_chip_calidad(x['calidad'])} {_chip_ia(x['ia_estilo'], x['ia_llm'])} {f'<span class="chip neu">{len(comentarios)} comentario(s)</span>' if comentarios else ''}</summary>
<div class="cuerpo"><div class="meta">Autor <b>@{E(x['autor'] or '')}</b> · participantes: {E(', '.join('@' + p for p in (x['participantes'] or '').split(',') if p)) or '—'}
· <a href="{E(x['url'])}">ver en GitHub</a>{(' · días: ' + E(x['fechas'])) if x['tipo'] == 'daily' and ',' in (x['fechas'] or '') else ''}</div>
{('<p style="font-size:14px">' + '<br>'.join(detalles) + '</p>') if detalles else ''}
<pre class="texto">{E(x['texto'] or '(sin texto en la issue)')}</pre>{coms}</div></details>""")

    filtro = lambda t, n: f'<a class="btn peq {"" if tipo == t else "sec"}" href="{base}?tipo={t}&orden={orden}">{n}</a>'
    ordenar = lambda o, n: f'<a class="btn peq {"" if orden == o else "sec"}" href="{base}?tipo={tipo}&orden={o}">{n}</a>'
    conteo = defaultdict(int)
    for x in regs:
        conteo[x["tipo"]] += 1
    avisos = []
    if not a["sprint_activo"]:
        avisos.append("No hay un sprint en curso a la fecha de corte.")
    if a["huecos"]:
        avisos.append(f"Días hábiles sin sprint: {E(a['huecos'])}.")
    altos = [x for x in regs if (x["ia_llm"] is not None and float(x["ia_llm"]) >= 0.7) or float(x["ia_estilo"] or 0) >= 0.6]
    if altos:
        avisos.append(f"{len(altos)} registro(s) con fuerte indicio de texto generado con IA: "
                      + " ".join(f'<a href="{base}?abrir={x["numero"]}#r{x["numero"]}">#{x["numero"]}</a>' for x in altos[:15])
                      + f' · <a href="{base}?orden=ia">verlos ordenados</a>')
    return (CSS_EXTRA + barra_equipo(r, eq, todos, "agil", a.get("repo") or "", acciones)
            + _hero(f'<a href="{r}agil">Metodología ágil</a> · comparación de equipos', E(eq),
                    f"Corte {a['hasta']:%d/%m/%Y} · sprints según {E(a['fuente_sprints'])} · se esperan {a['dailies_por_semana']} dailies por semana.")
            + _kpis([(_chip_pct(a["cumplimiento"]), "cumplimiento ágil"), (str(len(sprints)), "sprints"),
                     ('sí' if a["sprint_activo"] else 'no', "sprint en curso"), (str(len(regs)), "registros de ceremonias"),
                     (_chip_calidad(a["calidad_media"]), "calidad media"), (str(len(altos)), "con indicio fuerte de IA")])
            + (f'<div class="aviso" style="margin-top:12px">{"<br>".join(avisos)}</div>' if avisos else "")
            + "<h2>Sprints</h2>" + _tabla(["Sprint", "Fechas", "Ítems hechos", "Estimación", "Planning", "Dailies", "Review", "Retro"], filas_s)
            + "<h2>Semana a semana</h2>" + semanas
            + f"<h2>Registros ({len(lista)})</h2>"
            + '<div class="filtros">' + filtro("", f"Todos ({len(regs)})")
            + "".join(filtro(t, f"{NOMBRE[t]} ({conteo[t]})") for t in ORDEN)
            + '<span style="width:12px"></span>' + ordenar("fecha", "Por fecha") + ordenar("ia", "Más sospechosos de IA")
            + ordenar("calidad", "Menor calidad") + "</div>"
            + ("".join(tarjetas) or '<p class="mut">Sin registros de este tipo.</p>'))
