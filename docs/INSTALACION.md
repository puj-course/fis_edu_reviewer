# Instalación en un servidor

Guía paso a paso para dejar el agente corriendo en un servidor Linux de la universidad. Toma unos
15 minutos más la primera revisión (unos 15 minutos con IA para cuatro equipos).

## 1. Requisitos

| Qué | Para qué | Cómo comprobarlo |
|---|---|---|
| Linux con Docker 24+ y Docker Compose v2 | Corre los cinco servicios | `docker --version` y `docker compose version` |
| Una cuenta con acceso a Docker | Levantar los contenedores sin `sudo` | `docker ps` no dice *permission denied* |
| Git | Clonar el repositorio | `git --version` |
| Salida a internet (HTTPS) | Hablar con GitHub, DeepSeek y SonarCloud | `curl -sI https://api.github.com` |
| ~4 GB de RAM libres y ~5 GB de disco | Metabase, PostgreSQL y MongoDB | `free -h`, `df -h` |

Si la cuenta no tiene acceso a Docker, alguien con `sudo` debe agregarla al grupo:

```bash
sudo usermod -aG docker <usuario>
```

La cuenta debe cerrar sesión y volver a entrar para que el cambio aplique.

## 2. Credenciales

Necesita dos credenciales, que nunca se suben al repositorio:

1. **Token de GitHub** *fine-grained* con dueño `puj-course`, vencimiento de hasta 366 días (la
   organización rechaza tokens sin vencimiento) y estos permisos:

   | Sección | Permiso | Nivel |
   |---|---|---|
   | Repository | Actions | Read-only |
   | Repository | Contents | Read-only |
   | Repository | Issues | Read and write (solo si se publicará retroalimentación) |
   | Repository | Pull requests | Read-only |
   | Repository | Metadata | Read-only |
   | Organization | Projects | Read-only (para leer los tableros Kanban) |

2. **Clave de la API de DeepSeek** (opcional: sin ella el agente trabaja solo con indicadores).

3. **Sonar del equipo** (opcional). Con proyectos públicos en SonarCloud no hace falta nada. Para proyectos
   privados de SonarCloud, `FIS_SONARCLOUD_TOKEN`; para un SonarQube propio del curso, `FIS_SONAR_URL`
   y `FIS_SONAR_TOKEN` (usuario con permiso *Browse* sobre los proyectos). Van en `deploy/.env`.

## 3. Instalar

```bash
git clone https://github.com/puj-course/fis_edu_reviewer.git ~/fis_edu_reviewer
```

```bash
cd ~/fis_edu_reviewer && cp .env.example .env && chmod 600 .env
```

Edite `.env` y ponga `FIS_GH_TOKEN` y `DEEPSEEK_API_KEY`. Luego:

```bash
sh deploy/instalar.sh
```

El instalador:

1. Genera `deploy/.env` con contraseñas aleatorias para PostgreSQL, MongoDB, Metabase y el portal.
2. Construye y levanta los contenedores (`sitio` (nginx), `portal`, `revisor` (trabajador), `postgres`, `mongo`, `metabase`,
   `sonarqube`). SonarQube necesita unos 4 GB de RAM y `vm.max_map_count` ≥ 524288 en el servidor
   (`sysctl vm.max_map_count`).
3. Crea la base de SonarQube y lo configura para el análisis interno (`deploy/sonar_setup.py`).
3. Espera a Metabase, crea el administrador, la conexión a los datos y los dos tableros.
4. Arranca la primera revisión de la próxima entrega.

Los puertos por defecto son 8090 (sitio) y 3000 (Metabase). Para cambiarlos, antes de instalar:

```bash
SITIO_PORT=50060 METABASE_PORT=50061 sh deploy/instalar.sh
```

Si ya estaba instalado, cambie `SITIO_PORT` y `METABASE_PORT` en `deploy/.env` y ejecute
`docker compose -f deploy/docker-compose.yml up -d sitio metabase`.

## 4. Publicar con un proxy reverso

El sitio está pensado para quedar detrás de un proxy reverso con HTTPS y una URL propia (por ejemplo
`https://fis.<dominio>/` o `https://<dominio>/fis/`). El inicio de sesión ya está dentro del sitio:
no hace falta autenticación en el proxy.

```
navegador ──HTTPS──▶ proxy reverso ──HTTP──▶ servidor:SITIO_PORT (nginx «sitio») ──▶ portal y /metabase/
```

Lo que debe hacer el proxy:

| Qué | Por qué |
|---|---|
| Reenviar a `http://<servidor>:<SITIO_PORT>/` | Es el único puerto que se publica |
| Enviar `X-Forwarded-Proto: https` | La cookie de sesión se marca `Secure` |
| Si usa una ruta (`/fis/`), quitar el prefijo al reenviar | Todos los enlaces del sitio son relativos y funcionan bajo cualquier ruta |
| Agregar HSTS si lo desea | el portal ya envía CSP, `nosniff`, `noindex` y `no-store` |
| Chequeo de salud: `GET /salud` | Responde `ok` sin sesión y sin datos |

Ejemplo con nginx como proxy, bajo `/fis/`:

```nginx
location /fis/ {
    proxy_pass http://<servidor>:<SITIO_PORT>/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Con un túnel de Cloudflare (`cloudflared`) en el mismo servidor no hace falta abrir ningún puerto:
ponga `SITIO_BIND=127.0.0.1` y apunte el túnel a `http://127.0.0.1:<SITIO_PORT>` (cloudflared ya envía
`X-Forwarded-Proto: https`).

Cuando el sitio ya solo se use por HTTPS, ponga `SITIO_HTTPS=1` en `deploy/.env` (la cookie viaja
solo cifrada aunque el proxy no envíe la cabecera) y aplique con
`docker compose -f deploy/docker-compose.yml up -d portal`. Ponga también la URL pública en
`SITIO_URL` (por ejemplo `https://<dominio>/fis`) y aplique con `up -d metabase`: Metabase la necesita
para que los tableros incrustados carguen.

### Firewall

| Puerto | Escucha en | Debe quedar |
|---|---|---|
| `SITIO_PORT` (sitio) | `SITIO_BIND` (por defecto todas las interfaces) | Abierto **solo** para la IP del proxy reverso. Si el proxy corre en el mismo servidor, ponga `SITIO_BIND=127.0.0.1` y no abra nada |
| `METABASE_PORT` | `METABASE_BIND` (por defecto `127.0.0.1` en instalaciones nuevas) | Cerrado: se usa por túnel SSH |
| PostgreSQL `PG_PORT`, MongoDB `MONGO_PORT` | `127.0.0.1` | Cerrados |

Docker publica puertos con sus propias reglas de iptables y **se salta `ufw`**. Hay dos formas
seguras de limitarlo: enlazar el puerto a `127.0.0.1` (variables `*_BIND`) o filtrar en la cadena
`DOCKER-USER` (por ejemplo con `ufw-docker`). Con `ufw-docker`, alguien con `sudo`:

```bash
sudo ufw-docker allow fis-sitio-1 80/tcp
```

y, si el proxy tiene una IP fija, restrinja el origen con `ufw route allow proto tcp from <ip-proxy> to any port 80`.
Para comprobar desde otro equipo de la red qué puertos responden:

```bash
curl -s -m 5 -o /dev/null -w "%{http_code}
" http://<servidor>:<SITIO_PORT>/salud
```

Debe responder `200` desde el proxy y no responder desde el resto de la red; Metabase, PostgreSQL y
MongoDB no deben responder desde ningún otro equipo.

Mientras el proxy no esté listo, se puede entrar por un túnel SSH desde el equipo del profesor (no
cambia nada en el servidor):

```bash
ssh -N -p <puerto-ssh> -L 50060:127.0.0.1:50060 -L 50061:127.0.0.1:50061 <usuario>@<servidor>
```

Con el túnel abierto: portal en http://localhost:50060 (Metabase, dentro de él en `/metabase/`).

## 5. Credenciales de acceso y cuentas para colegas

Las credenciales del profesor quedan en `deploy/.env` del servidor (permiso 600):

```bash
grep -E '^(SITIO_USUARIO|SITIO_PASSWORD|MB_ADMIN_EMAIL|MB_ADMIN_PASSWORD)=' ~/fis_edu_reviewer/deploy/.env
```

El usuario de `deploy/.env` es el primer administrador. Las demás cuentas se crean en el portal
(**Administración → Nuevo usuario**) y se guardan en PostgreSQL con PBKDF2. También por consola:

```bash
cd ~/fis_edu_reviewer/deploy && docker compose exec revisor python -m reviewer usuario agregar <usuario> --admin
```

Genera una contraseña y la muestra una sola vez (o use la de la variable `CLAVE_NUEVA`).
`usuario listar` muestra las cuentas y `usuario quitar <usuario>` desactiva una. La sesión dura 12 horas
(`SITIO_SESION_HORAS`); tras 5 intentos fallidos la cuenta espera 5 minutos.

## 6. Cargar entregas pasadas

La revisión automática solo evalúa la próxima entrega. Para cargar las anteriores (por ejemplo al
instalar a mitad de semestre):

```bash
cd ~/fis_edu_reviewer/deploy && docker compose exec revisor sh -c 'for e in entrega1 entrega2; do python -m reviewer revisar-todos --entrega $e --ia --salida /datos/historico; done'
```

## 7. Comprobar que quedó bien

```bash
sh ~/fis_edu_reviewer/deploy/estado.sh
```

Debe mostrar los seis servicios arriba, una revisión por equipo y entrega, y conteos de commits e
issues. Para verificar que los 13 paneles de Metabase funcionan:

```bash
cd ~/fis_edu_reviewer/deploy && docker compose exec revisor python /app/deploy/verificar_tableros.py
```

## 8. Actualizar a una versión nueva

```bash
cd ~/fis_edu_reviewer && git pull && sh deploy/instalar.sh
```

`deploy/.env` y los datos (volúmenes de Docker) se conservan.

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `permission denied ... docker.sock` | La cuenta no está en el grupo `docker` | Paso 1 |
| GitHub responde 403 «token's lifetime is greater than 366 days» | Token sin vencimiento | Regenerarlo con fecha |
| El informe dice «el token no puede leer el tablero Kanban» | Falta *Projects: Read-only* de organización | Editar el token |
| El sitio responde en el servidor pero no desde otro equipo | Firewall | Paso 4 |
| El sitio vuelve a pedir el ingreso en cada página | El proxy usa HTTPS pero el navegador recibió la cookie sin `Secure`, o se cambió `SITIO_SECRETO` | Paso 4 (`X-Forwarded-Proto`) e ingresar de nuevo |
| La revisión se detiene con *Read timed out* | Red lenta hacia GitHub | Se reintenta sola; si persiste, revisar la salida a internet |
| Metabase muestra paneles vacíos | La primera revisión aún corre | `docker compose logs -f revisor` |
