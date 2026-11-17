"""Trabajador del agente: atiende la cola de revisiones (`portal.solicitudes`).

- Toma las solicitudes en orden, ejecuta la revisión y va guardando su registro en la base, así el
  portal muestra el avance en vivo. Se puede cancelar desde el portal.
- Si la revisión programada está activa (configuración del curso → `programacion`), encola una
  revisión automática cada `intervalo_horas`.

    python -m reviewer trabajador
"""
from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import time

from . import configuracion

ESPERA = 10  # segundos entre consultas a la cola


def _con():
    import psycopg

    return psycopg.connect(os.environ["FIS_PG_DSN"], autocommit=True)


def _uno(con, sql: str, *args):
    with con.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone() if cur.description else None


def programar(con) -> None:
    """Encola la revisión automática si ya pasó el intervalo desde la última."""
    cfg = configuracion.cargar_con(con)
    prog = cfg.get("programacion") or {}
    if not prog.get("activa", True):
        return
    horas = int(prog.get("intervalo_horas") or os.environ.get("INTERVALO_HORAS") or 24)
    con_ia = bool(prog.get("con_ia", True)) and bool(os.environ.get("DEEPSEEK_API_KEY"))
    with con.transaction():
        _uno(con, "SELECT pg_advisory_xact_lock(424244)")
        reciente = _uno(con, """SELECT 1 FROM portal.solicitudes WHERE origen = 'programada'
                                 AND (estado IN ('pendiente', 'en_curso') OR creada > now() - make_interval(hours => %s))""", horas)
        if not reciente:
            fila = _uno(con, """INSERT INTO portal.solicitudes (usuario, origen, alcance, entrega, con_ia)
                                VALUES ('agente', 'programada', 'todos', 'auto', %s) RETURNING id""", con_ia)
            print(f"Revisión programada encolada: #{fila[0]}", flush=True)


def tomar(con):
    return _uno(con, """UPDATE portal.solicitudes SET estado = 'en_curso', inicio = now()
                        WHERE id = (SELECT id FROM portal.solicitudes WHERE estado = 'pendiente' ORDER BY id
                                    LIMIT 1 FOR UPDATE SKIP LOCKED)
                        RETURNING id, alcance, entrega, con_ia""")


def comando(alcance: str, entrega: str, con_ia: bool) -> list[str]:
    salida = os.path.join(os.environ.get("FIS_SALIDA", "/datos"), dt.date.today().isoformat())
    cmd = [sys.executable, "-m", "reviewer"]
    cmd += ["revisar-todos"] if alcance == "todos" else ["revisar", "--repo", alcance]
    cmd += ["--entrega", entrega, "--salida", salida]
    return cmd + (["--ia"] if con_ia else [])


def correr(con, sid: int, alcance: str, entrega: str, con_ia: bool) -> None:
    cmd = comando(alcance, entrega, con_ia)
    print(f"Solicitud #{sid}: {' '.join(cmd[2:])}", flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                            env={**os.environ, "PYTHONUNBUFFERED": "1"})
    # Un hilo lee la salida; el ciclo principal guarda el registro y revisa la cancelación cada 2 s,
    # aunque el proceso pase minutos sin imprimir (por ejemplo, mientras recolecta de GitHub).
    lineas: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lineas.put(x) for x in proc.stdout], daemon=True).start()
    pendiente, cancelada = [f"$ reviewer {' '.join(cmd[3:])}\n"], False
    while True:
        fin = proc.poll() is not None
        while not lineas.empty():
            pendiente.append(lineas.get())
        if fin:
            time.sleep(0.2)
            while not lineas.empty():
                pendiente.append(lineas.get())
            break
        if pendiente:
            _uno(con, "UPDATE portal.solicitudes SET log = log || %s WHERE id = %s", "".join(pendiente), sid)
            pendiente = []
        if not cancelada and _uno(con, "SELECT cancelar FROM portal.solicitudes WHERE id = %s", sid)[0]:
            proc.terminate()
            cancelada = True
        time.sleep(2)
    codigo = proc.wait()
    estado = "cancelada" if cancelada else "terminada" if codigo == 0 else "fallida"
    pendiente.append(f"\n— {estado} (código {codigo})\n")
    _uno(con, "UPDATE portal.solicitudes SET log = log || %s, estado = %s, codigo = %s, fin = now() WHERE id = %s",
         "".join(pendiente), estado, codigo, sid)
    print(f"Solicitud #{sid}: {estado}", flush=True)


def ejecutar() -> None:
    import psycopg

    with psycopg.connect(os.environ["FIS_PG_DSN"]) as inicial:
        configuracion.asegurar_esquema(inicial)
        configuracion.cargar_con(inicial)
    con = _con()
    # Lo que quedó a medias por un reinicio se marca como interrumpido.
    _uno(con, """UPDATE portal.solicitudes SET estado = 'fallida', fin = now(), log = log || E'\\n— interrumpida por un reinicio del agente\\n'
                 WHERE estado = 'en_curso'""")
    print("Trabajador listo: atendiendo la cola de revisiones", flush=True)
    while True:
        try:
            programar(con)
            s = tomar(con)
            if s:
                correr(con, *s)
                continue
        except Exception as e:  # la base se reinició o perdió la conexión: reintentar
            print(f"Error del trabajador: {type(e).__name__}: {e}", flush=True)
            try:
                con.close()
            except Exception:
                pass
            time.sleep(ESPERA)
            con = _con()
        time.sleep(ESPERA)
