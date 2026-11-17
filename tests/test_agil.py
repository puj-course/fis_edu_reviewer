import datetime as dt

from reviewer import agil


def issue(n, titulo, creada, cuerpo="", comentarios=None, labels=()):
    return {"numero": n, "titulo": titulo, "cuerpo": cuerpo, "labels": list(labels), "asignados": ["ana"], "autor": "ana",
            "estado": "closed", "creada": creada, "comentarios": comentarios or []}


def test_clasifica_ceremonias_por_titulo_y_etiqueta():
    assert agil.tipo_ceremonia(issue(1, "Sprint Planning 2", "")) == "planning"
    assert agil.tipo_ceremonia(issue(1, "Realizar la Sprint Retrospective para el Sprint #2", "")) == "retro"
    assert agil.tipo_ceremonia(issue(1, "Sprinter Review 1", "")) == "review"
    assert agil.tipo_ceremonia(issue(1, "Daily 19/08/26", "")) == "daily"
    assert agil.tipo_ceremonia(issue(1, "Avance", "", labels=["Daily Sprint"])) == "daily"
    assert agil.tipo_ceremonia(issue(1, "HU-12 login", "")) is None


def test_fechas_en_titulos():
    assert agil.fecha_en_titulo("Daily 19/08/26", 2026) == dt.date(2026, 8, 19)
    assert agil.fecha_en_titulo("Daily Scrum 20 de Agosto", 2026) == dt.date(2026, 8, 20)
    assert agil.fecha_en_titulo("Sprint Planning 2", 2026) is None


def test_calidad_y_senales_de_estilo():
    bueno, faltan = agil.calidad("daily", "Ayer terminé el login. Hoy voy a hacer el registro. Impedimentos: ninguno.", 3)
    assert bueno >= 70 and faltan == []
    vacio, faltan = agil.calidad("retro", "", 1)
    assert vacio == 0 and faltan == ["sin contenido escrito"]
    generado = ("## Resumen del sprint\n" + "- **Objetivo**: garantizar una arquitectura robusta — integral y eficiente.\n" * 8
                + "En conclusión, cabe destacar el trabajo en equipo — sinergia total. ✅🚀")
    p, rasgos = agil.senales_ia(generado)
    assert p >= 0.6 and any("rayas" in r for r in rasgos)
    assert agil.senales_ia("ayer hice el login, hoy sigo")[0] == 0.0


def test_analisis_por_sprint_y_continuidad():
    ev = {"repo": "org/G1", "hasta": "2026-08-30", "limite_utc": "2026-08-31T04:59:59Z",
          "proyecto": {"items": {}, "sprints": [{"campo": "Sprint", "titulo": "Sprint 1", "inicio": "2026-08-17", "dias": 7},
                                               {"campo": "Sprint", "titulo": "Sprint 2", "inicio": "2026-08-24", "dias": 7}]},
          "issues": [issue(1, "Sprint Planning 1", "2026-08-17T14:00:00Z", "Objetivo: login. HU #3 #4, estimación 8 puntos, responsable @ana"),
                     issue(2, "Daily Sprint 1", "2026-08-18T14:00:00Z", "Ayer hice X. Hoy haré Y. Sin impedimentos.",
                           [{"autor": "beto", "fecha": "2026-08-19T14:00:00Z", "cuerpo": "Ayer avancé. Hoy sigo. Ningún bloqueo."},
                            {"autor": "ana", "fecha": "2026-08-20T14:00:00Z", "cuerpo": "Terminé. Voy a probar. Ninguno."}]),
                     issue(3, "Sprint Review 1", "2026-08-21T20:00:00Z", "Demo del incremento: HU #3 completada. Feedback del PO."),
                     issue(4, "Retrospectiva 1", "2026-08-22T20:00:00Z", "Salió bien: comunicación. Mejorar: pruebas. Acción: TDD.")]}
    a = agil.analizar(ev, {})
    s1, s2 = a["sprints"]
    assert s1["planning"] == [1] and s1["review"] == [3] and s1["retro"] == [4] and s1["dailies"] == 3
    assert s2["planning"] == [] and s2["en_curso"] is True
    assert a["componentes"]["continuidad"] == 1.0 and a["sprint_activo"] is True
    assert all(r["calidad"] > 0 for r in a["registros"])
