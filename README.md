# fis_edu_reviewer

Agente revisor formativo para **Fundamentos de Ingeniería de Software** (Pontificia Universidad Javeriana).
Revisa los repositorios de los equipos en la organización `puj-course` contra las rúbricas de las tres
entregas del proyecto y produce:

| Para quién | Qué | Dónde queda |
|---|---|---|
| El equipo | Revisión formativa semanal: qué se ve en su repo frente a la rúbrica y preguntas para discutir. **Sin nota y sin soluciones.** | Comentario en la issue «Bitácora de revisión formativa FIS» de su repo |
| El profesor | Pre-nota sugerida por criterio con la evidencia, factor de aporte individual sugerido, señales de proceso y preguntas de sustentación por estudiante | Repositorio privado o servidor propio (nunca en este repo, que es público) |

El agente no califica: propone. Tampoco «detecta IA»: marca señales de proceso (commits enormes, trabajo
de última hora, commits sin issue, firmas de asistentes) y las convierte en preguntas para la sustentación
oral, que es donde la rúbrica premia a quien entiende su propio trabajo.

## Documentación

- [docs/INSTALACION.md](docs/INSTALACION.md): instalar en un servidor, paso a paso.
- [docs/GUIA_PROFESOR.md](docs/GUIA_PROFESOR.md): cómo usar el portal, leer la pre-nota y el uso de IA.
- [ARQUITECTURA.md](ARQUITECTURA.md): cómo funciona por dentro.
- [docs/README.md](docs/README.md): índice y temas pendientes.

## Cómo está armado

```
config/course.yaml      período, prefijo de repos, fechas de entrega, umbrales
rubrics/entrega*.yaml   las rúbricas como datos (criterios, pesos, niveles, verificaciones)
reviewer/collect.py     junta la evidencia de GitHub (commits, issues, PRs, tablero, Actions, wiki, Sonar)
reviewer/checks.py      verificaciones deterministas y nivel sugerido por criterio
reviewer/llm.py         cliente de DeepSeek + anonimización de estudiantes
reviewer/qualitative.py criterios cualitativos y preguntas de sustentación (IA)
reviewer/report.py      informe del equipo, informe del profesor y tablero HTML
reviewer/portal.py      portal web del profesor (Flask): usuarios, revisiones bajo demanda, rúbricas, tableros
reviewer/sitio.py       páginas del portal con los datos vivos de PostgreSQL
reviewer/trabajador.py  atiende la cola de revisiones y la revisión programada
reviewer/configuracion.py configuración del curso y rúbricas guardadas en la base, con historial
reviewer/marca.py       identidad visual Javeriana / FIS
.github/workflows/      revisión programada (lunes 6 a. m.) y pruebas
plantilla-equipo/       archivos para copiar a Repository_Template_FIS
deploy/                 Docker Compose para correrlo en un servidor propio
```

Cada criterio de la rúbrica tiene un tipo:

- **auto**: el nivel sale de indicadores medibles (porcentaje de issues completas, pipelines en verde, cobertura…).
- **asistido**: hay indicadores, y la IA lee historias, diagramas, patrones o postmortem para proponer el nivel.
- **humano**: solo se muestra evidencia; decide el profesor (avance funcional, prototipo, SMS).

## Uso local

```bash
pip install -r requirements.txt
```

```bash
python -m reviewer revisar --repo puj-course/FIS_2630_1204_G1 --entrega entrega1
```

```bash
python -m reviewer revisar-todos --entrega auto --ia
```

Los informes quedan en `salida/<repo>/<entrega>/` (`equipo.md`, `profesor.md`, `resultado.json`) y el
tablero en `salida/index.html`. `--entrega auto` usa la próxima entrega según `config/course.yaml`.
`--publicar` comenta el informe formativo en el repo del equipo.

Variables de entorno (ver `.env.example`):

| Variable | Para qué |
|---|---|
| `FIS_GH_TOKEN` | Token de GitHub. Sin él funciona con la API pública (60 llamadas/hora) pero no ve el tablero Kanban, las revisiones de PR ni el tamaño de los commits |
| `DEEPSEEK_API_KEY` | Activa la capa de IA (`--ia`). Sin ella el agente trabaja solo con indicadores |
| `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL` | Opcionales (`deepseek-flash`, `https://api.deepseek.com`) |

## Puesta en marcha en GitHub Actions

1. Crear un token *fine-grained* sobre `puj-course` con: Contents (lectura), Issues (lectura y escritura),
   Pull requests (lectura), Actions (lectura), Metadata (lectura) y, a nivel de organización, Projects (lectura).
2. En este repo, *Settings → Secrets and variables → Actions*:
   - Secretos: `FIS_GH_TOKEN`, `DEEPSEEK_API_KEY`.
   - Variables: `FIS_DATA_REPO` = repo **privado** donde guardar los informes del profesor (el token necesita
     Contents de escritura ahí); `FIS_PUBLICAR` = `true` cuando quiera que la corrida semanal comente en los repos.
3. Probar desde *Actions → Revisión formativa FIS → Run workflow* con un solo repo y `publicar` apagado.
4. Copiar el contenido de `plantilla-equipo/` a `Repository_Template_FIS` para que los repos nuevos nazcan con
   las guardas de PR, las plantillas de issues y el `CONTRIBUTING.md`.

Cada período: actualizar `periodo`, `repo_prefijo` y las fechas en `config/course.yaml`, y agregar a
`ignorar_usuarios` las cuentas que no son estudiantes (profesor, monitores).

## En un servidor propio

`deploy/` levanta el stack completo con Docker Compose: el revisor (cada 24 horas, solo lectura sobre
GitHub), PostgreSQL, MongoDB y Metabase con dos tableros ya armados. En el servidor, desde la raíz del repo:

```bash
sh deploy/instalar.sh
```

La primera vez genera `deploy/.env` con contraseñas aleatorias y toma el token y la clave del `.env` de la
raíz. El detalle de cómo funciona, qué guarda cada base y cómo se opera está en [ARQUITECTURA.md](ARQUITECTURA.md).

## Privacidad

- Los informes del profesor contienen pre-notas: no se suben como artefactos ni se imprimen en los registros.
- Antes de llamar a DeepSeek se reemplazan usuarios, nombres y correos por alias (Estudiante A, B…).
- El contenido de los repos se trata como material a evaluar, no como instrucciones; si aparece texto dirigido
  a manipular al revisor, se reporta como señal.

## Límites conocidos

- Los archivos se revisan sobre la rama principal; si `develop` va adelante, el informe lo avisa.
- La cobertura se lee de SonarCloud cuando el proyecto es público; con SonarQube propio hay que verla a mano.
- Diagramas y patrones se detectan por nombres y menciones: su calidad la juzga la IA y la confirma el profesor.
- El factor individual es una sugerencia calculada con commits e issues; la sustentación tiene la última palabra.
