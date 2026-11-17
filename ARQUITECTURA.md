# Arquitectura del agente revisor FIS

## En una frase

Un proceso en Python lee de GitHub todo lo que hicieron los equipos, lo compara contra las
rúbricas del curso, le pide a DeepSeek el juicio de los criterios cualitativos, guarda el
resultado en PostgreSQL y MongoDB, y Metabase lo muestra en dos tableros para el profesor.

## Diagrama

```
                       ┌────────────────────────── GitHub (org puj-course) ───────────────────────────┐
                       │  FIS_2630_1204_G1 … G4: commits, ramas, issues, milestones, PRs, revisiones,  │
                       │  Actions, releases, Wiki, tablero Projects                                     │
                       └───────────────▲───────────────────────────────────────────────────────────────┘
                                       │ solo lectura (REST + GraphQL, token FIS_GH_TOKEN)
┌──────────────────────── servidor (Docker Compose, proyecto "fis") ──────────────────────────────────────┐
│                                                                                                          │
│  ┌──────────── revisor (python) ─────────────┐        ┌──────────── DeepSeek API ───────────┐           │
│  │ cada 24 h:                                 │  HTTPS │ deepseek-flash, salida JSON          │           │
│  │ 1. collect.py   junta evidencia            │───────▶│ recibe textos con alias              │           │
│  │ 2. checks.py    indicadores por criterio   │◀───────│ (Estudiante A, B…), nunca nombres    │           │
│  │ 3. qualitative  IA: criterios y preguntas  │        └──────────────────────────────────────┘           │
│  │ 4. report.py    informes Markdown/HTML     │                                                           │
│  │ 5. store.py     guarda en las dos bases    │                                                           │
│  └───────┬───────────────────────┬────────────┘                                                           │
│          │ psycopg                │ pymongo                                                               │
│  ┌───────▼──────────────┐  ┌──────▼────────────────┐   ┌──────────── metabase ─────────────┐             │
│  │ postgres:16          │  │ mongo:7                │   │ v0.64.6, en español                │             │
│  │  base fis            │  │  base fis              │   │ lee fis.* con usuario fis_lectura  │◀── profesor │
│  │   esquema fis.*      │◀─┼──────────────────────────────│ guarda su config en base metabase │   :3000     │
│  │  base metabase       │  │  revisiones            │   └────────────────────────────────────┘             │
│  └──────────────────────┘  │  evidencias            │                                                     │
│                            └────────────────────────┘   volumen informes: /datos/<fecha>/…/profesor.md    │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Cómo funciona una revisión

1. **Descubrir repos.** Lista los repos de `puj-course` que empiezan por `repo_prefijo`
   (`FIS_2630_`), omitiendo los archivados y los de `repos_excluir`.
2. **Elegir la entrega.** `ENTREGA=auto` toma la próxima fecha de `config/course.yaml`. La
   evidencia se corta en esa fecha (fin del día, hora de Bogotá); antes de la fecha se usa "hoy".
3. **Recolectar** (`reviewer/collect.py`), unas 150 llamadas por repo:
   commits de `main` y `develop` con autor, fecha y tamaño; árbol de archivos; README, docs,
   Dockerfile, Compose y archivos de build; issues con labels, asignados, milestone y sub-issues;
   PRs con ramas y aprobaciones; milestones; workflows y sus ejecuciones; releases y tags; páginas
   de la Wiki (clonando su repo git); campos del tablero Projects; medidas públicas de SonarCloud.
4. **Verificar** (`reviewer/checks.py`): 29 verificaciones deterministas, cada una con
   indicadores "cumple / no cumple / informativo" y, cuando la rúbrica es numérica (porcentaje de
   issues, número de pipelines, cobertura), el nivel exacto que le corresponde.
5. **Juicio de IA** (`reviewer/qualitative.py`), solo en los criterios marcados `asistido`:
   DeepSeek recibe la descripción de los niveles, los indicadores y extractos de los documentos,
   y devuelve nivel, puntaje, justificación, preguntas guía para el equipo y lo que el profesor
   debe verificar a mano. Después genera 3 preguntas de sustentación por estudiante a partir de
   sus propios commits.
6. **Aporte individual y señales**: commits, semanas activas, issues cerradas, PRs y revisiones
   por integrante, con un factor sugerido (1 / 0.9 / 0.5 / 0.3) como el de su rúbrica. Señales:
   commits de más de 800 líneas, trabajo concentrado en las 48 h previas, commits sin issue,
   firmas de asistentes de IA, correos sin vincular y texto que intenta manipular al revisor.
7. **Guardar**: Markdown y HTML en el volumen `informes`, filas en PostgreSQL y documentos en
   MongoDB.

## Qué guarda cada base

**PostgreSQL** (base `fis`, esquema `fis`): lo que se consulta y grafica.

| Tabla | Una fila por | Uso |
|---|---|---|
| `corridas` | ejecución del revisor | historial |
| `revisiones` | equipo × entrega × corrida | pre-nota y cobertura del peso |
| `criterios` | criterio de la rúbrica | nivel y puntaje final, el de los indicadores, justificación de la IA |
| `indicadores` | indicador medido | qué se cumple y qué no |
| `aporte` | integrante | métricas individuales y factor sugerido |
| `senales` | señal de proceso | a quién preguntar y sobre qué |
| `preguntas` | pregunta de sustentación | guion para la sustentación oral |
| `commits`, `issues`, `pull_requests`, `pipelines`, `milestones` | hecho del repo | foto actual de cada repo (se reemplaza en cada corrida) |

Las vistas `v_*` devuelven siempre la revisión más reciente de cada equipo y entrega; los
tableros consultan las vistas. Las tablas de revisión acumulan historia: cada corrida agrega
filas, así se puede ver la evolución semana a semana.

**MongoDB** (base `fis`): lo que no cabe bien en tablas.

- `revisiones`: el resultado completo de cada revisión, tal como lo produjo el agente.
- `evidencias`: la evidencia cruda por repo y fecha de corte (textos de issues, documentos,
  Wiki, workflows). Sirve para auditar una nota o reprocesar con otra rúbrica sin volver a GitHub.

## Tableros en Metabase (colección "FIS")

- **FIS · Resumen del curso** (filtro: entrega): pre-nota por equipo, matriz de puntaje por
  criterio y equipo, actividad comparada (commits, % conventional commits, % commits con issue,
  historias, PRs fusionados, pipelines en verde), commits por semana y aporte de cada integrante.
- **FIS · Detalle por proyecto** (filtros: equipo, entrega): criterios con su nivel, fuente y
  justificación de la IA; indicadores que no se cumplen; señales de proceso; aporte individual;
  commits por semana e integrante; historias por milestone; preguntas de sustentación; pipelines.

Metabase lee con el usuario `fis_lectura`, que solo tiene `SELECT` sobre el esquema `fis`.

## Calidad del código con Sonar (`collect._sonar` y `checks.sonar`)

El agente **no ejecuta análisis**: la rúbrica evalúa que el equipo integró Sonar en su pipeline, así que
lee los análisis que ese pipeline produjo. Encuentra la clave del proyecto (`sonar.projectKey` o, si
no aparece, `<org>_<repo>` y `<repo>`) y consulta, en SonarCloud y en el SonarQube del curso si
`FIS_SONAR_URL` está definido:

- medidas: cobertura, bugs, vulnerabilidades, code smells, security hotspots, duplicación, deuda
  técnica, calificaciones de mantenibilidad, fiabilidad y seguridad, líneas de código;
- el **quality gate** y las condiciones que fallan;
- el historial de **análisis** hasta la fecha de corte (cuántos, en cuántos días, el último), para ver
  si Sonar corre de forma continua o solo se ejecutó una vez antes de la entrega;
- qué pipelines del repo ejecutan Sonar y si su última ejecución fue exitosa.

El resultado queda en `fis.sonar` (una fila por repo) y en el portal: tabla en el Panorama y en cada equipo.

## Portal del profesor (aplicación web sobre PostgreSQL)

`reviewer/portal.py` es una aplicación Flask (gunicorn) que arma cada página en el momento con los
datos vivos de la base (`reviewer/sitio.py` dibuja las páginas, `reviewer/marca.py` tiene la
identidad Javeriana/FIS). nginx (`deploy/nginx.conf`) es la única entrada: reenvía al portal y
publica Metabase en `/metabase/` solo para quien tiene sesión en el portal.

```
navegador ─▶ nginx «sitio» ─┬─▶ portal (Flask) ──▶ PostgreSQL: fis.* (revisiones) y portal.* (usuarios, config, cola)
                            └─▶ /metabase/ (auth_request al portal) ─▶ Metabase (tableros incrustados)
revisor (trabajador) ◀── portal.solicitudes ── el profesor pide una revisión desde el portal
```

Todo queda en el esquema `portal` (Metabase no lo ve: su usuario de lectura solo tiene el esquema `fis`):

| Tabla | Qué guarda |
|---|---|
| `portal.usuarios` | cuentas (PBKDF2), rol `admin` o `colega`, activo, último ingreso |
| `portal.auditoria` | ingresos, ingresos fallidos, salidas, solicitudes de revisión, cambios de configuración y de usuarios |
| `portal.config` / `portal.config_historial` | configuración del curso y rúbricas vigentes, y cada versión anterior con autor y fecha |
| `portal.solicitudes` | cada revisión pedida (o programada): alcance, rúbrica, IA, estado, duración y registro completo |

Páginas: **Panorama**, **Revisiones** (pedir una revisión de todos o de un equipo, estado de cada
repo frente a su último push en GitHub, historial y registro en vivo, cancelar), **Rúbricas** (las
de cada entrega con criterios, pesos, niveles y qué verifica el agente; los administradores las
editan), **Tableros** (Metabase incrustado con *static embedding* firmado), **Estudiantes**,
**Uso de IA**, **El agente**, **Administración** (curso, fechas de corte, equipos incluidos, cuentas que
no son estudiantes, revisión programada, usuarios y auditoría) y **Mi cuenta**.

La sesión es una cookie firmada (HttpOnly, SameSite=Lax, Secure detrás de HTTPS) que se valida contra
la base en cada petición: desactivar un usuario o cambiarle la contraseña cierra sus sesiones.
Los formularios llevan token CSRF; tras 5 intentos fallidos en 5 minutos la cuenta espera.

### Revisiones bajo demanda (`reviewer/trabajador.py`)

El contenedor `revisor` es un trabajador que toma las solicitudes de `portal.solicitudes` en orden,
ejecuta `revisar` o `revisar-todos` y guarda la salida en la base cada 2 segundos (el portal la
muestra en vivo). Revisa la marca de cancelación con la misma frecuencia. Si la revisión programada
está activa, encola una revisión de todos los equipos cada `intervalo_horas`. Una solicitud que
quedó a medias por un reinicio se marca como interrumpida.

## Cómo se verifica el uso de IA (`checks.evidencias_ia` y `reviewer/ia.py`)

- **Evidencia directa**: firmas de asistentes en commits, PR o issues (`Co-authored-by: Copilot/Claude`,
  «Generated with…»); commits, PR o revisiones hechos por cuentas de agentes de IA (Copilot coding agent,
  Devin, Claude, Jules…); ramas creadas por agentes (`copilot/…`, `claude/…`); archivos de configuración
  de asistentes en el repo (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `copilot-instructions.md`…).
- **Señal indirecta**: commits con bloques grandes de código (2.400+ líneas de una vez, o 500+ líneas a
  menos de 15 minutos del commit anterior). Se abre cada commit marcado y se descartan los archivos
  generados (lockfiles, compilados, imágenes, datos); si lo escrito no llega a 400 líneas, la señal se elimina.
- **Límite**: ninguna revisión del repositorio puede asegurar que *no* se usó IA, porque copiar código
  desde un chat no deja rastro. Las señales sirven para decidir qué preguntar en la sustentación.

## Modo de esta cohorte: solo evaluar

El despliegue del servidor **solo lee** de GitHub: el trabajador no publica comentarios ni
crea issues en los repos de los equipos, y nada de `plantilla-equipo/` se ha copiado a
`Repository_Template_FIS`. Lo único que el agente escribió en GitHub fue una issue de prueba en
este mismo repositorio (`fis_edu_reviewer#1`).

Para la próxima cohorte quedan listos, sin activar:

- `--publicar` y el workflow `revision.yml` con `FIS_PUBLICAR=true`: retroalimentación semanal
  a cada equipo en una issue de bitácora, sin notas.
- `plantilla-equipo/`: guardas de PR, plantillas de historia de usuario y tarea, plantilla de
  PR y `CONTRIBUTING.md` con la política de uso de IA.

## Seguridad y privacidad

- Contraseñas aleatorias generadas por `deploy/instalar.sh` en `deploy/.env` (permiso 600,
  ignorado por git). El token de GitHub y la clave de DeepSeek viven solo ahí.
- PostgreSQL, MongoDB y (en instalaciones nuevas) Metabase escuchan solo en `127.0.0.1` del servidor;
  únicamente nginx se publica, pensado para quedar detrás de un proxy reverso HTTPS.
- El portal exige sesión en todas las páginas y en `/metabase/`; contraseñas con PBKDF2, CSRF en los
  formularios, límite de intentos por usuario y por dirección, y auditoría de cada acción.
- Las pre-notas no se imprimen en los registros ni se suben a este repositorio, que es público.
- A DeepSeek se le envían alias en lugar de usuarios, nombres y correos de los estudiantes.
- El contenido de los repos se trata como dato: si alguien escribe instrucciones dirigidas al
  revisor, se reporta como señal y no se obedece.

## Operación

| Tarea | Comando (desde la raíz del repo, en el servidor) |
|---|---|
| Instalar o actualizar | `sh deploy/instalar.sh` |
| Ver estado y conteos | `sh deploy/estado.sh` |
| Pedir una revisión | Portal → **Revisiones** (o un equipo → «Revisar este equipo ahora») |
| Crear un usuario | Portal → **Administración** (o `docker compose -f deploy/docker-compose.yml exec revisor python -m reviewer usuario agregar <usuario> [--admin]`) |
| Revisar las tres entregas | `docker compose -f deploy/docker-compose.yml exec revisor python -m reviewer revisar-todos --entrega todas --ia --salida /datos/manual` |
| Ver registros | `docker compose -f deploy/docker-compose.yml logs -f revisor` |
| Respaldar PostgreSQL | `docker compose -f deploy/docker-compose.yml exec postgres pg_dump -U fis fis > fis.sql` |
| Apagar | `docker compose -f deploy/docker-compose.yml down` (los datos quedan en los volúmenes) |

Cambio de período: editar `periodo`, `repo_prefijo`, fechas e `ignorar_usuarios` en
`config/course.yaml` y volver a ejecutar `sh deploy/instalar.sh`.

## Límites conocidos

- Las fechas de corte salen de la programación académica de la universidad: hay que actualizarlas en
  `config/course.yaml` al inicio de cada período.
- Los tableros Projects solo se leen si el token tiene **Projects: lectura** a nivel de organización.
- La cobertura solo se lee si el proyecto está en SonarCloud y es público.
- Diagramas y patrones se detectan por nombres y menciones; su calidad la juzga la IA y la
  confirma el profesor.
- Los puntajes son sugerencias: la nota y el factor individual los decide el profesor tras la
  sustentación.
- El tablero Kanban (Projects) solo guarda su estado actual: en revisiones de entregas pasadas,
  la columna de cada tarjeta se compara con el estado de hoy de la issue, no con el de la fecha de corte.

## Calibración contra las notas del profesor (período 2630)

Comparando las pre-notas del agente con las notas que el profesor puso en las entregas 1 y 2, el
agente resulta más severo, sobre todo en estos puntos (pendientes para la próxima cohorte):

- **Trazabilidad issue – commit**: solo cuenta un commit como ligado si su mensaje dice `#n`. Los
  equipos enlazan mucho trabajo a través del PR (`Closes #n`) o del nombre de la rama; habría que
  contar los commits de un PR que cierra la issue (consulta GraphQL de commits por PR).
- **Historias de usuario**: busca criterios de aceptación y DoD dentro del cuerpo de cada issue. Varios
  equipos definen el DoD una sola vez en la Wiki o en una plantilla; debería aceptarse ese DoD común.
- **GitFlow**: exige feature → `develop` y solo release/hotfix → `main`. Si el curso acepta otro flujo
  (por ejemplo feature → main con revisión), hay que ajustar la verificación a lo que se enseñó.
