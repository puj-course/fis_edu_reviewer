#!/bin/sh
# Instala o actualiza el stack en este servidor. Ejecutar desde la raíz del repo:
#     sh deploy/instalar.sh
# La primera vez genera deploy/.env con contraseñas aleatorias (quedan solo en este servidor).
set -eu
cd "$(dirname "$0")"

secreto() { od -An -N16 -tx1 /dev/urandom | tr -d ' \n'; }
tomar() { [ -f ../.env ] && sed -n "s/^$1=//p" ../.env | head -1 || true; }

if [ ! -f .env ]; then
  umask 077
  cat > .env <<EOF
# Generado por instalar.sh. No versionar.
FIS_GH_TOKEN=$(tomar FIS_GH_TOKEN)
DEEPSEEK_API_KEY=$(tomar DEEPSEEK_API_KEY)
DEEPSEEK_MODEL=
ENTREGA=auto
INTERVALO_HORAS=24

METABASE_PORT=${METABASE_PORT:-3000}
METABASE_BIND=${METABASE_BIND:-127.0.0.1}
MB_ADMIN_EMAIL=${MB_ADMIN_EMAIL:-admin@fis.local}
MB_ADMIN_PASSWORD=$(secreto)Aa1

PG_PASSWORD=$(secreto)
MONGO_PASSWORD=$(secreto)
MB_DB_PASSWORD=$(secreto)
LECTURA_PASSWORD=$(secreto)
EOF
  echo "Se creó deploy/.env"
fi

# Claves agregadas en versiones posteriores: se completan sin tocar las existentes.
agregar() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }
agregar SITIO_USUARIO profesor
agregar SITIO_PASSWORD "$(secreto)"
agregar SITIO_PORT "${SITIO_PORT:-8090}"
agregar SITIO_BIND "${SITIO_BIND:-0.0.0.0}"
agregar SITIO_SECRETO "$(secreto)$(secreto)"
# 1 cuando el sitio se publique solo por HTTPS (proxy reverso): la cookie de sesión viaja solo cifrada.
agregar SITIO_HTTPS 0
# URL con la que se entra al portal (la del proxy reverso cuando exista). Metabase la usa para incrustar tableros.
agregar SONAR_DB_PASSWORD "$(secreto)"
agregar SONAR_ADMIN_PASSWORD "$(secreto)Aa1@"
agregar SITIO_URL "http://localhost:$(sed -n 's/^SITIO_PORT=//p' .env)"

if ! grep -q '^FIS_GH_TOKEN=.\+' .env; then
  echo "Falta FIS_GH_TOKEN en deploy/.env: edítelo y vuelva a ejecutar." >&2
  exit 1
fi

# Base de datos de SonarQube dentro del mismo PostgreSQL (idempotente).
docker compose up -d postgres
until docker compose exec -T postgres pg_isready -U fis -d fis >/dev/null 2>&1; do sleep 2; done
sonar_pw="$(sed -n 's/^SONAR_DB_PASSWORD=//p' .env)"
docker compose exec -T postgres psql -q -U fis -d fis -v ON_ERROR_STOP=1 -v pw="$sonar_pw" <<'SQL'
SELECT format('CREATE ROLE sonar LOGIN PASSWORD %L', :'pw') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sonar') \gexec
SELECT format('ALTER ROLE sonar PASSWORD %L', :'pw') \gexec
SELECT 'CREATE DATABASE sonar OWNER sonar' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'sonar') \gexec
SQL

docker compose up -d --build --remove-orphans

echo "Esperando a Metabase (la primera vez tarda uno o dos minutos)..."
n=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q metabase)")" = "healthy" ]; do
  n=$((n + 1))
  [ "$n" -gt 90 ] && { echo "Metabase no arrancó; revise: docker compose logs metabase" >&2; exit 1; }
  sleep 5
done

docker compose exec -T revisor python /app/deploy/metabase_setup.py
echo "Configurando el SonarQube del curso (la primera vez tarda unos minutos)..."
docker compose exec -T -e SONAR_ADMIN_PASSWORD="$(sed -n 's/^SONAR_ADMIN_PASSWORD=//p' .env)" revisor python /app/deploy/sonar_setup.py

psitio="$(sed -n 's/^SITIO_PORT=//p' .env)"
echo
echo "Listo."
echo "  Portal del profesor: $(sed -n 's/^SITIO_URL=//p' .env)  (servidor: puerto ${psitio}; SITIO_USUARIO / SITIO_PASSWORD en deploy/.env)"
echo "  Usuarios, revisiones bajo demanda, rúbricas y tableros se administran desde el portal."
echo "  Publicación con URL propia: ver docs/INSTALACION.md, sección «Publicar con un proxy reverso»."
echo "La primera revisión programada empieza en segundos: docker compose -f deploy/docker-compose.yml logs -f revisor"
