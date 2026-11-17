"""Informes: uno formativo para el equipo (sin nota) y uno privado para el profesor."""
from __future__ import annotations

import html
import json
import os

from .checks import nota_parcial

# Pregunta guía por verificación: funciona aunque no haya IA configurada.
PREGUNTAS = {
    "estructura": "Si alguien nuevo llegara hoy al equipo, ¿encontraría cada cosa donde la plantilla dice que debe estar?",
    "readme": "¿Qué necesita saber una persona que nunca ha visto el proyecto para instalarlo y ejecutarlo?",
    "wiki": "¿Qué decisiones del equipo hoy solo viven en la cabeza de alguien y deberían estar en la Wiki?",
    "gitflow": "¿Qué problema evita que nadie haga commits directos a `main`? ¿Para qué sirve `develop`?",
    "conventional_commits": "Si mañana tuvieran que generar el changelog solo con los mensajes de commit, ¿se entendería qué cambió?",
    "issues_completas": "¿Cómo sabe el equipo qué tarea es más urgente y cuánto esfuerzo cuesta si la issue no lo dice?",
    "kanban": "¿El tablero refleja lo que el equipo está haciendo hoy, o lo que hacía la semana pasada?",
    "historias_estructura": "Para cada historia: ¿cómo sabrían, sin preguntarle al autor, que ya está terminada? ¿Cabe en un sprint (INVEST)?",
    "ceremonias": "¿Qué acordaron en la última retrospectiva y dónde quedó escrito para revisarlo en la siguiente?",
    "hitos": "¿Qué pasó con las issues que no alcanzaron a cerrar en el sprint? ¿Quién decidió replanificarlas?",
    "trazabilidad": "Dado un commit cualquiera, ¿pueden decir a qué historia pertenece y por qué se hizo?",
    "aporte_historias": "¿El historial muestra el trabajo real de cada integrante, o alguien está subiendo el trabajo de otros?",
    "sub_issues": "¿Qué tareas técnicas concretas hacen falta para terminar cada historia? ¿Están a la vista?",
    "pipelines": "¿Qué verifica cada pipeline y qué pasaría en el proyecto si lo apagaran?",
    "diagramas": "¿Por qué eligieron esta arquitectura y no otra? ¿El diagrama coincide con el código que tienen hoy?",
    "patrones_gof": "¿Qué problema concreto de su proyecto resuelve cada patrón? ¿Cómo sería el código sin él?",
    "docker": "¿Otra persona podría levantar el sistema completo con un solo comando siguiendo su README?",
    "pipeline_docker": "¿Qué pasos manuales quedan hoy entre hacer merge y tener la nueva versión corriendo?",
    "cobertura": "¿Qué partes críticas del sistema no están cubiertas por pruebas? ¿Qué podría fallar ahí sin que lo noten?",
    "pipeline_pruebas": "¿Qué impide hoy que se fusione un cambio que rompe las pruebas?",
    "sonar": "¿Qué significa en la práctica la calificación que les da Sonar en mantenibilidad?",
    "metricas_docs": "Para cada métrica: ¿qué mide exactamente y qué decisión tomarían si el valor empeora?",
    "historias_por_sprint": "¿Su velocidad por sprint fue estable? ¿Qué explica los sprints más lentos?",
    "equilibrio": "¿La distribución del trabajo que muestra el historial coincide con la que acordaron como equipo?",
    "versiones": "¿Qué historias incluye cada versión publicada? ¿Cómo lo sabría un usuario?",
    "postmortem": "¿Cuál fue la causa de fondo del mayor problema que tuvieron, más allá del síntoma?",
}

ICONO = {True: "✅", False: "❌", None: "ℹ️"}


def _semaforo(criterio: dict) -> str:
    if criterio["tipo"] == "humano":
        return "⚪ lo revisa el profesor"
    razones = [ch["razon"] for ch in criterio["checks"] if ch["razon"] is not None]
    if not razones:
        return "⚪ sin datos suficientes"
    media = sum(razones) / len(razones)
    return "🟢 va bien" if media >= 0.8 else "🟡 en progreso" if media >= 0.5 else "🔴 necesita atención"


def informe_equipo(res: dict) -> str:
    """Retroalimentación formativa. Nunca incluye notas ni factores individuales."""
    l = [
        f"## 🤖 Revisión formativa — {res['entrega_nombre']} (corte {res['hasta']})",
        "",
        "> Esto **no es una nota**. Es lo que hoy se puede ver en su repositorio frente a la rúbrica, "
        "para que el equipo decida qué mejorar. El agente no les dirá cómo resolverlo: las preguntas "
        "son para que lo discutan entre ustedes. La calificación la hace el profesor en la sustentación.",
        "",
    ]
    for c in res["criterios"]:
        l += [f"### {c['nombre']} — {_semaforo(c)}", ""]
        for ch in c["checks"]:
            l.append(f"**{ch['titulo']}**")
            l += [f"- {ICONO[i['ok']]} {i['texto']}" for i in ch["indicadores"]]
            l.append("")
        preguntas = (c["ia"] or {}).get("preguntas_guia") or [
            PREGUNTAS[ch["id"]] for ch in c["checks"] if ch["id"] in PREGUNTAS and (ch["razon"] is None or ch["razon"] < 0.8)
        ]
        if preguntas:
            l.append("**Para discutir en el equipo:**")
            l += [f"- {p}" for p in preguntas[:3]]
            l.append("")
        if c["conceptos"]:
            l += [f"<sub>Conceptos del curso: {', '.join(c['conceptos'])}</sub>", ""]
    l += ["### Actividad visible por integrante", "", "| Integrante | Commits | Semanas activas | Issues cerradas | PRs | Revisiones |", "|---|---|---|---|---|---|"]
    for f in res["aporte"]:
        l.append(f"| @{f['login'].lstrip('~')} | {f['commits']} | {f['semanas_activas']}/{f['semanas_equipo']} | {f['issues_cerradas']} | {f['prs']} | {f['revisiones']} |")
    l += ["", "<sub>Si su trabajo no aparece aquí, revisen que sus commits estén hechos con el correo de su cuenta de GitHub "
          "y que referencien la issue (`#n`).</sub>"]
    if res["avisos"]:
        l += ["", "**Notas de esta revisión:**"] + [f"- {a}" for a in res["avisos"]]
    return "\n".join(l) + "\n"


def informe_profesor(res: dict) -> str:
    nota, cubierto = nota_parcial(res)
    l = [
        f"# {res['repo']} — {res['entrega_nombre']} (corte {res['hasta']})",
        "",
        "**Documento privado del profesor.** Los niveles y puntajes son sugerencias para agilizar la revisión.",
        "",
        f"**Pre-nota sugerida: {nota if nota is not None else '—'}** "
        f"(calculada sobre el {cubierto:.0%} del peso de la rúbrica; el resto es de juicio del profesor).",
        "",
        "| Criterio | Peso | Tipo | Nivel sugerido | Puntaje | Fuente |",
        "|---|---|---|---|---|---|",
    ]
    for c in res["criterios"]:
        s = c["ia"] or c["sugerencia"]
        l.append(f"| {c['nombre']} | {c['peso']:.0%} | {c['tipo']} | {s['nivel'] if s else '—'} | {s['puntaje'] if s else '—'} | {s['fuente'] if s else 'profesor'} |")
    l.append("")
    for c in res["criterios"]:
        l += [f"## {c['nombre']}", ""]
        if c["ia"]:
            ia = c["ia"]
            l += [f"**IA ({ia['confianza']}):** {ia['nivel']} — {ia['puntaje']}. {ia['justificacion']}", ""]
            if c["sugerencia"] and c["sugerencia"]["nivel"] != ia["nivel"]:
                l += [f"⚠️ Los indicadores solos sugerían **{c['sugerencia']['nivel']}** ({c['sugerencia']['puntaje']}).", ""]
            if ia["verificar_manual"]:
                l += ["Verificar manualmente:"] + [f"- {v}" for v in ia["verificar_manual"]] + [""]
        elif c["tipo"] == "asistido":
            l += ["_Sin evaluación de IA (no hay DEEPSEEK_API_KEY o la llamada falló): el nivel sale solo de los indicadores._", ""]
        for ch in c["checks"]:
            l.append(f"**{ch['titulo']}**" + (f" → {ch['nivel']}" if ch["nivel"] else ""))
            l += [f"- {ICONO[i['ok']]} {i['texto']}" for i in ch["indicadores"]]
            l.append("")
    l += ["## Aporte individual", "",
          "| Integrante | Commits | Días | Semanas | Issues cerradas/asignadas | PRs | Revisiones | Líneas | Índice | Factor sugerido |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for f in res["aporte"]:
        l.append(
            f"| {f['login']} | {f['commits']} | {f['dias_activos']} | {f['semanas_activas']}/{f['semanas_equipo']} | "
            f"{f['issues_cerradas']}/{f['issues_asignadas']} | {f['prs']} | {f['revisiones']} | "
            f"{f['lineas'] if f['lineas'] is not None else '—'} | {f['indice_aporte']} | **{f['factor_sugerido']}** |")
    l += ["", "<sub>Índice 1.0 = aporta la parte que le corresponde en un equipo parejo (commits e issues cerradas). "
          "El factor final depende de la sustentación.</sub>", ""]
    directas = [e for e in res.get("uso_ia", []) if e["nivel"] == "directa"]
    indirectas = [e for e in res.get("uso_ia", []) if e["nivel"] == "indirecta"]
    l += ["## Uso de IA", "",
          f"**Evidencia directa: {'NINGUNA' if not directas else len(directas)}.** "
          "Se buscan firmas de asistentes en commits, PR e issues; commits o PR hechos por agentes de IA; "
          "ramas de agentes; y archivos de configuración de asistentes (CLAUDE.md, .cursorrules, copilot-instructions…).",
          "",
          "Que no haya evidencia directa no demuestra que no se usó IA: copiar código desde un chat no deja rastro. "
          "Las señales indirectas indican dónde preguntar en la sustentación.", ""]
    l += [f"- 🔴 **{e['login']}** — {e['detalle']}" + (f" `{'`, `'.join(e['refs'][:5])}`" if e["refs"] else "") for e in directas]
    l += [f"- 🟡 **{e['login']}** — {e['detalle']}" for e in indirectas]
    l += ["" if directas or indirectas else "- Sin señales.", ""]
    l += ["## Señales de proceso", "",
          "No son prueba de nada (ni de uso de IA ni de copia): indican a quién y sobre qué preguntar.", ""]
    if res["senales"]:
        l += [f"- **{s['login']}** — {s['texto']}" + (f" `{'`, `'.join(s['commits'])}`" if s["commits"] else "") for s in res["senales"]]
    else:
        l.append("- Ninguna.")
    l += ["", "## Preguntas para la sustentación", ""]
    if res["preguntas_sustentacion"]:
        for login, preguntas in res["preguntas_sustentacion"].items():
            l += [f"**{login}**"] + [f"1. {p}" for p in preguntas] + [""]
    else:
        l += ["_Requiere la capa de IA (DEEPSEEK_API_KEY)._", ""]
    if res["avisos"]:
        l += ["## Límites de esta revisión", ""] + [f"- {a}" for a in res["avisos"]]
    return "\n".join(l) + "\n"


def guardar(res: dict, ev: dict, carpeta: str) -> dict:
    os.makedirs(carpeta, exist_ok=True)
    rutas = {n: os.path.join(carpeta, n) for n in ("equipo.md", "profesor.md", "resultado.json", "evidencia.json")}
    with open(rutas["equipo.md"], "w", encoding="utf-8") as f:
        f.write(informe_equipo(res))
    with open(rutas["profesor.md"], "w", encoding="utf-8") as f:
        f.write(informe_profesor(res))
    ligero = json.loads(json.dumps(res))
    for c in ligero["criterios"]:
        for ch in c["checks"]:
            ch.pop("textos", None)
    with open(rutas["resultado.json"], "w", encoding="utf-8") as f:
        json.dump(ligero, f, ensure_ascii=False, indent=1)
    with open(rutas["evidencia.json"], "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False)
    return rutas


def tablero(resultados: list[dict], ruta: str) -> None:
    """Página HTML privada con todos los equipos de una corrida."""
    if not resultados:
        return
    e = html.escape
    criterios = [c["nombre"] for c in resultados[0]["criterios"]]
    filas = []
    for r in sorted(resultados, key=lambda r: r["repo"]):
        nota, cubierto = nota_parcial(r)
        celdas = ""
        for c in r["criterios"]:
            s = c["ia"] or c["sugerencia"]
            clase = "" if not s else "ok" if s["puntaje"] >= 4 else "medio" if s["puntaje"] >= 3 else "mal"
            celdas += f"<td class='{clase}'>{s['puntaje'] if s else '—'}<small>{e(s['nivel']) if s else 'profesor'}</small></td>"
        nombre = r["repo"].split("/")[-1]
        integrantes = "".join(
            f"<li>{e(f['login'])}: {f['commits']} commits, factor {f['factor_sugerido']}</li>" for f in r["aporte"])
        filas.append(
            f"<tr><th><a href='{e(nombre)}/{e(r['entrega'])}/profesor.md'>{e(nombre)}</a>"
            f"<details><summary>{len(r['aporte'])} integrantes · {len(r['senales'])} señales</summary><ul>{integrantes}</ul></details></th>"
            f"{celdas}<td class='nota'>{nota if nota is not None else '—'}<small>{cubierto:.0%} del peso</small></td></tr>")
    pagina = f"""<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tablero FIS</title>
<style>
:root{{--bg:#fff;--fg:#1f2328;--mut:#656d76;--bd:#d0d7de;--ok:#dafbe1;--medio:#fff8c5;--mal:#ffebe9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#8d96a0;--bd:#30363d;--ok:#12261e;--medio:#2b2411;--mal:#2d1416}}}}
body{{font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 4px}} p{{color:var(--mut);margin:0 0 16px}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;min-width:720px}}
th,td{{border:1px solid var(--bd);padding:8px 10px;text-align:center;vertical-align:top}}
tbody th{{text-align:left;font-weight:600}} thead th{{font-size:12px;color:var(--mut);max-width:130px}}
small{{display:block;color:var(--mut);font-size:11px}} .ok{{background:var(--ok)}} .medio{{background:var(--medio)}} .mal{{background:var(--mal)}}
.nota{{font-weight:700}} a{{color:inherit}} details{{font-weight:400;font-size:12px;color:var(--mut)}} ul{{margin:4px 0;padding-left:16px}}
</style>
<h1>{e(resultados[0]['entrega_nombre'])} — corte {e(resultados[0]['hasta'])}</h1>
<p>Pre-notas sugeridas por el agente. Documento privado: la nota la decide el profesor.</p>
<div class="wrap"><table><thead><tr><th>Equipo</th>{''.join(f'<th>{e(c)}</th>' for c in criterios)}<th>Pre-nota</th></tr></thead>
<tbody>{''.join(filas)}</tbody></table></div></html>"""
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(pagina)
