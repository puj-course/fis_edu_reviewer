import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from reviewer import acceso


@pytest.fixture(autouse=True)
def entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("SITIO_SECRETO", "secreto-de-prueba")
    monkeypatch.setenv("SITIO_USUARIO", "profesor")
    monkeypatch.setenv("SITIO_PASSWORD", "clave-principal-123")
    monkeypatch.setattr(acceso, "RUTA_USUARIOS", str(tmp_path / "auth" / "usuarios"))
    acceso.FALLOS = acceso._Fallos()


def test_hash_y_verificacion_de_clave():
    h = acceso.hash_clave("una clave larga", 1000)
    assert acceso.verificar_clave("una clave larga", h)
    assert not acceso.verificar_clave("otra", h)
    assert not acceso.verificar_clave("x", "basura")


def test_sesion_firmada_y_con_vencimiento():
    s = acceso.crear_sesion("ana", ahora=1000)
    assert acceso.leer_sesion(s, ahora=1001) == "ana"
    assert acceso.leer_sesion(s, ahora=1000 + acceso.DURACION + 1) is None
    datos, firma = s.rsplit(".", 1)
    assert acceso.leer_sesion(datos + "." + "0" * len(firma), ahora=1001) is None
    assert acceso.leer_sesion("", ahora=1001) is None


def test_usuarios_principal_y_colegas():
    assert acceso.autenticar("profesor", "clave-principal-123")
    assert not acceso.autenticar("profesor", "mala")
    acceso.guardar_usuario("colega", "clave-colega-123")
    assert acceso.autenticar("colega", "clave-colega-123")
    assert not acceso.autenticar("colega", "clave-principal-123")
    acceso.guardar_usuario("colega", None)
    assert not acceso.autenticar("colega", "clave-colega-123")
    with pytest.raises(ValueError):
        acceso.guardar_usuario("con espacio", "x" * 12)


def test_flujo_http_de_ingreso():
    servidor = acceso.ThreadingHTTPServer(("127.0.0.1", 0), acceso.Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    sin_redireccion = urllib.request.build_opener(urllib.request.HTTPErrorProcessor)

    def pedir(ruta, datos=None, cookie=None, cabeceras=None):
        req = urllib.request.Request(base + ruta, data=datos, headers={**({"Cookie": cookie} if cookie else {}), **(cabeceras or {})})
        try:
            r = sin_redireccion.open(req)
            return r.status, r.headers, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read().decode()

    try:
        assert pedir("/verificar")[0] == 401
        codigo, _, cuerpo = pedir("/equipo/G1.html")
        assert codigo == 200 and "Ingresar" in cuerpo and "Javeriana" in cuerpo
        malo = urllib.parse.urlencode({"usuario": "profesor", "clave": "mala"}).encode()
        assert pedir("/index.html", malo)[0] == 401
        bueno = urllib.parse.urlencode({"usuario": "profesor", "clave": "clave-principal-123"}).encode()
        codigo, cab, _ = pedir("/index.html", bueno, cabeceras={"X-Forwarded-Proto": "https"})
        assert codigo == 200
        galleta = cab["Set-Cookie"]
        assert "HttpOnly" in galleta and "SameSite=Lax" in galleta and "Secure" in galleta
        cookie = galleta.split(";")[0]
        assert pedir("/verificar", cookie=cookie)[0] == 204
        _, cab, _ = pedir("/salir", cookie=cookie)
        assert "Max-Age=0" in cab["Set-Cookie"]
        for _ in range(acceso.MAX_FALLOS):
            pedir("/", malo)
        assert pedir("/", bueno)[0] == 429
    finally:
        servidor.shutdown()
