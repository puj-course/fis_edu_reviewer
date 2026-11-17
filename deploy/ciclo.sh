#!/bin/sh
# Revisa todos los equipos cada INTERVALO_HORAS y regenera el sitio del profesor.
# Solo lee de GitHub: en este despliegue nunca se publica nada en los repos de los equipos.
INTERVALO_HORAS="${INTERVALO_HORAS:-24}"
sitio() { python -m reviewer sitio --salida /datos/sitio || echo "No se pudo generar el sitio"; }
sitio
while true; do
  fecha="$(date -u +%Y-%m-%d)"
  opciones="--entrega ${ENTREGA:-auto} --salida /datos/$fecha"
  [ -n "$DEEPSEEK_API_KEY" ] && opciones="$opciones --ia"
  # shellcheck disable=SC2086
  python -m reviewer revisar-todos $opciones || echo "La corrida terminó con errores"
  ln -sfn "$fecha" /datos/actual
  sitio
  echo "Próxima revisión en $INTERVALO_HORAS horas"
  sleep "$((INTERVALO_HORAS * 3600))"
done
