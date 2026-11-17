# Cómo trabajamos en este repositorio

Estas son las reglas del curso Fundamentos de Ingeniería de Software. El workflow
`Guardas FIS` las revisa en cada pull request y el agente del curso deja cada semana
una revisión formativa en la issue «Bitácora de revisión formativa FIS».

## Flujo de ramas (GitFlow)

- `main`: solo versiones entregables. Nadie hace commits directos.
- `develop`: integración del sprint.
- `feature/<issue>-<descripcion>`, `fix/…`: salen de `develop` y vuelven a `develop` por pull request.
- `release/<version>` y `hotfix/<descripcion>`: los únicos que se integran a `main`.

## Commits

Formato [Conventional Commits](https://www.conventionalcommits.org/es/) y referencia a la issue:

```
feat(inventario): registra lotes con fecha de vencimiento (#34)
```

Commits pequeños y frecuentes, hechos por quien escribió el código, con el correo de su
cuenta de GitHub. Un commit enorme la noche antes de la entrega no muestra el proceso.

## Issues

- Las historias de usuario usan la plantilla (Como/Quiero/Para, criterios de aceptación, DoD).
- Cada historia tiene sub-issues técnicas, responsable, milestone (sprint), estimación y prioridad.
- Una issue se cierra con el pull request que la resuelve (`Closes #n`), después de que el QA Lead verifica el DoD.

## Uso de inteligencia artificial

El objetivo del curso es que cada integrante entienda el proceso completo de desarrollo.
Por eso:

- Lo que se entrega debe ser trabajo que su autor pueda explicar y modificar en vivo en la sustentación.
- Si usaron un asistente de IA para algo, decláralo en el pull request (qué pidieron y qué cambiaron).
- El aporte individual se califica con el historial del repositorio **y** con la sustentación:
  quien no pueda explicar sus propios commits no recibe el crédito por ellos.
