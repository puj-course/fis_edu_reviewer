# Documentación

| Documento | Para quién | Qué contiene |
|---|---|---|
| [../README.md](../README.md) | Todos | Qué es el agente y cómo correrlo localmente |
| [../ARQUITECTURA.md](../ARQUITECTURA.md) | Quien mantenga el código | Componentes, flujo de una revisión, modelo de datos, verificación de IA, operación, límites y calibración |
| [INSTALACION.md](INSTALACION.md) | Quien instale el servidor | Requisitos, credenciales, instalación, firewall, carga de entregas pasadas, problemas frecuentes |
| [GUIA_PROFESOR.md](GUIA_PROFESOR.md) | El profesor | Cómo leer el sitio, la pre-nota, el uso de IA y el factor individual; preparar sustentaciones |

## Mapa rápido del código

```
config/course.yaml ─┐
rubrics/*.yaml ─────┤
                    ▼
reviewer/cli.py ── orquesta ──► collect.py  (GitHub: commits, issues, PRs, Actions, Wiki, Projects)
                              ├► checks.py   (29 verificaciones, nivel sugerido, aporte, señales, evidencias de IA)
                              ├► ia.py       (refina señales de IA abriendo cada commit)
                              ├► qualitative.py + llm.py (DeepSeek: criterios cualitativos y preguntas)
                              ├► report.py   (informes Markdown del equipo y del profesor)
                              ├► store.py    (PostgreSQL + MongoDB)
                              └► sitio.py    (sitio web del profesor)
deploy/ ── Docker Compose: revisor, postgres, mongo, metabase, sitio (nginx)
```

## Temas pendientes (plan para la próxima cohorte)

Ordenados por impacto en la calidad de la evaluación:

1. **Calibrar contra las notas reales.** Cargar las notas que el profesor puso en las tres entregas y
   ajustar umbrales hasta que la pre-nota quede a ±0,3 en la mayoría de equipos.
2. **Trazabilidad por PR.** Contar como ligados los commits de un PR que cierra una issue
   (`Closes #n`), no solo los que dicen `#n` en el mensaje.
3. **DoD común.** Aceptar una Definition of Done definida una vez en la Wiki o en la plantilla de
   historias, en lugar de exigirla en cada issue.
4. **GitFlow del curso.** Ajustar la verificación al flujo que efectivamente se enseña.
5. **Retroalimentación semanal a los equipos.** Activar `--publicar` y las plantillas de
   `plantilla-equipo/` en `Repository_Template_FIS` desde el primer día del semestre.
6. **Acceso sin túnel.** Abrir en el firewall del servidor los puertos del sitio y de Metabase, o
   publicarlos detrás del proxy de la universidad con HTTPS.
7. **Respaldos.** Programar `pg_dump` diario de la base `fis` fuera del servidor.
8. **Token con más vida.** Regenerar el token de GitHub con 366 días y documentar quién lo renueva.
