# Guía del profesor

Cómo leer lo que produce el agente y cómo usarlo en el curso. La decisión de la nota siempre es del
profesor: el agente propone y deja la evidencia a la vista.

## Qué hace el agente cada día

1. Lee de GitHub, en solo lectura, todos los repos `FIS_<periodo>_*` de la organización.
2. Aplica la rúbrica de la próxima entrega (según las fechas de `config/course.yaml`).
3. Para los criterios cualitativos pide a DeepSeek una propuesta de nivel con justificación.
4. Guarda todo en PostgreSQL y MongoDB; el portal y Metabase lo muestran al instante.

Nada se publica en los repos de los estudiantes mientras no se active `--publicar`.

## El portal del profesor

Se entra con usuario y contraseña desde la propia página de ingreso; **Salir** (arriba a la derecha)
cierra la sesión. Todo lo que se ve sale en el momento de la base de datos.

| Para… | Vaya a |
|---|---|
| Ver si un equipo ya actualizó y revisarlo ya | **Revisiones**: último push frente a última revisión, botón «Revisar»; o en el equipo, «Revisar este equipo ahora» |
| Seguir una revisión | **Revisiones → #n**: estado, duración y registro en vivo; se puede cancelar |
| Ver con qué se evalúa cada entrega | **Rúbricas**: criterios, pesos, niveles y qué verifica el agente; los administradores las editan |
| Ver los tableros de Metabase | **Tableros** (incrustados, con filtros por equipo y entrega) |
| Cambiar fechas de corte, equipos o la revisión programada | **Administración** |
| Dar acceso a un colega | **Administración → Nuevo usuario** (la contraseña se muestra una sola vez) |
| Cambiar su contraseña | Su nombre, arriba a la derecha → **Mi cuenta** |

| Página | Para qué usarla |
|---|---|
| **Panorama** | Ver de un vistazo cómo va cada equipo: indicadores del curso, pre-nota por equipo, evolución entre revisiones, mapa de criterios (equipo × criterio), estado de uso de IA y hallazgos principales. |
| **El agente** | Presentar el agente a colegas: cómo trabaja, qué revisa (gestión ágil, código, arquitectura, calidad y DevOps) y las rúbricas de cada entrega con sus pesos. |
| **Estudiantes** | Listado con commits, semanas activas, factor sugerido y uso de IA de cada estudiante. |
| **Uso de IA** | Revisar, estudiante por estudiante, si hay evidencia directa o señales indirectas, con enlace al commit en GitHub. |
| **Equipo** | Preparar la revisión de una entrega: criterios con su nivel y justificación, indicadores que no se cumplen, actividad semanal e integrantes. |
| **Estudiante** | Preparar la sustentación individual: récord por entrega, uso de IA, señales, preguntas sugeridas y últimos commits. |

## Cómo leer la pre-nota

- Es un promedio ponderado **solo sobre los criterios que el agente puede evaluar**. El porcentaje
  que aparece al lado («90 % del peso») indica cuánto de la rúbrica cubre; el resto (avance
  funcional, prototipo, SMS) lo califica el profesor.
- **Fuente «indicadores»**: el nivel sale de mediciones (porcentaje de issues completas, pipelines en
  verde, cobertura). **Fuente «IA (DeepSeek)»**: la IA leyó historias, diagramas, patrones o
  postmortem y propuso el nivel; revise su justificación y la lista «verificar manualmente».
- En el período 2630 el agente resultó más severo que el profesor en trazabilidad, historias de
  usuario y GitFlow (ver la calibración en `ARQUITECTURA.md`). Úselo para encontrar qué revisar, no
  como nota final.

## Cómo leer el uso de IA

| Marca | Qué significa | Qué hacer |
|---|---|---|
| 🔴 Evidencia directa | Hay una huella explícita de una herramienta: firma en el commit, commits o PR hechos por un agente, ramas de agentes, archivos de configuración de asistentes. | Conversarlo con el estudiante; la evidencia está enlazada. |
| 🟡 Señal indirecta | Bloques grandes de código escritos de una vez o a minutos del commit anterior (ya sin contar archivos generados). | Preguntar en la sustentación por ese commit concreto: qué hace, por qué así, qué cambiaría. |
| Sin marca | No hay rastro. | No demuestra que no se usó IA: copiar desde un chat no deja huella. |

Una señal indirecta puede ser trabajo legítimo: subir de golpe lo trabajado en local, un *squash*
de una rama o código generado por el IDE. Por eso solo orienta la sustentación.

## El factor individual

El factor sugerido (1 / 0,9 / 0,5 / 0,3) sigue la escala de la rúbrica de trabajo en equipo y se
calcula con la parte de commits e issues cerradas que aporta cada integrante y con la regularidad
semanal. Los monitores (cuentas presentes en todos los repos) se excluyen solos. La sustentación
tiene la última palabra.

## Preparar una sustentación

1. Abra la página del estudiante.
2. Revise el récord: ¿aporta de forma regular o todo llegó al final?
3. Revise uso de IA y señales: anote los commits a preguntar.
4. Use las preguntas sugeridas; están escritas sobre sus propios commits.

## Metabase

Para análisis propios (filtros, nuevas preguntas, exportar a Excel). Dos tableros listos:
**FIS · Resumen del curso** y **FIS · Detalle por proyecto**. Metabase lee con un usuario de solo
lectura, así que no se pueden dañar los datos desde ahí.

## Cada período

1. Actualizar en `config/course.yaml`: `periodo`, `repo_prefijo`, fechas de las tres entregas (de la
   programación académica) y `ignorar_usuarios` si hay cuentas nuevas del curso.
2. Regenerar el token de GitHub si está por vencer.
3. En el servidor: `git pull && sh deploy/instalar.sh`.
4. Para la nueva cohorte, decidir si se activan la retroalimentación semanal a los equipos
   (`--publicar`) y las plantillas de `plantilla-equipo/` en `Repository_Template_FIS`.
