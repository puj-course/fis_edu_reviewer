#!/bin/sh
# Resumen del estado del stack:   sh deploy/estado.sh
cd "$(dirname "$0")"
docker compose ps --format '{{.Service}}: {{.Status}}'
echo
echo "== Última actividad del revisor"
docker compose logs --tail 8 revisor
echo
echo "== PostgreSQL (revisión vigente por equipo y entrega)"
docker compose exec -T postgres psql -U fis -d fis -c \
  "SELECT equipo, entrega, hasta, pre_nota, peso_cubierto, integrantes, senales FROM fis.v_revision_actual ORDER BY 1, 2" -c \
  "SELECT (SELECT count(*) FROM fis.corridas) corridas, (SELECT count(*) FROM fis.revisiones) revisiones,
          (SELECT count(*) FROM fis.commits) commits, (SELECT count(*) FROM fis.issues) issues,
          (SELECT count(*) FROM fis.pull_requests) prs, (SELECT count(*) FROM fis.preguntas) preguntas"
echo "== MongoDB"
docker compose exec -T mongo sh -c 'mongosh -u fis -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --quiet --eval "
  const d = db.getSiblingDB(\"fis\");
  printjson({revisiones: d.revisiones.countDocuments(), evidencias: d.evidencias.countDocuments()})"'
