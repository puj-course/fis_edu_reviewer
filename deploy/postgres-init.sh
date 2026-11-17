#!/bin/sh
# Se ejecuta una sola vez, al crear el volumen de PostgreSQL.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
-- Base interna de Metabase (usuarios, preguntas, tableros)
CREATE ROLE metabase LOGIN PASSWORD '${MB_DB_PASSWORD}';
CREATE DATABASE metabase OWNER metabase;

-- Usuario de solo lectura con el que Metabase consulta los datos del curso
CREATE ROLE fis_lectura LOGIN PASSWORD '${LECTURA_PASSWORD}';
CREATE SCHEMA IF NOT EXISTS fis;
GRANT USAGE ON SCHEMA fis TO fis_lectura;
ALTER DEFAULT PRIVILEGES FOR ROLE fis IN SCHEMA fis GRANT SELECT ON TABLES TO fis_lectura;
SQL
