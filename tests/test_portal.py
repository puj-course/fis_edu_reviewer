import base64
import hashlib
import hmac
import json

from reviewer import configuracion, portal, trabajador


def test_hash_y_verificacion_de_clave():
    h = portal.hash_clave("una clave larga", 1000)
    assert portal.verificar_clave("una clave larga", h)
    assert not portal.verificar_clave("otra", h)
    assert not portal.verificar_clave("x", "basura")


def test_token_metabase_firmado():
    t = portal.token_metabase("secreto", 7)
    cab, datos, firma = t.split(".")
    esperado = base64.urlsafe_b64encode(hmac.new(b"secreto", f"{cab}.{datos}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    assert firma == esperado
    carga = json.loads(base64.urlsafe_b64decode(datos + "=" * (-len(datos) % 4)))
    assert carga["resource"] == {"dashboard": 7} and carga["exp"] > 0


def test_destino_seguro_solo_rutas_relativas_internas():
    assert portal.destino_seguro("equipos/G1") == "equipos/G1"
    for malo in ("/etc", "//evil.com", "https://evil.com", "../x", "\\\\x"):
        assert portal.destino_seguro(malo) == ""


def test_rubricas_del_repo_son_validas_y_se_detectan_errores():
    cfg = configuracion.desde_yaml()
    for clave, r in cfg["_rubricas"].items():
        assert configuracion.validar_rubrica(r, clave) == []
    assert configuracion.validar_curso(cfg) == []
    mala = {"entrega": "entrega1", "nombre": "x", "criterios": [
        {"id": "a", "nombre": "A", "peso": 0.8, "tipo": "auto", "checks": ["no_existe"], "niveles": []},
        {"id": "a", "nombre": "B", "peso": 0.5, "tipo": "otro", "checks": [], "niveles": []}]}
    errores = " ".join(configuracion.validar_rubrica(mala, "entrega1"))
    assert "desconocidas" in errores and "repetido" in errores and "tipo" in errores and "suman" in errores


def test_comando_del_trabajador():
    cmd = trabajador.comando("puj-course/FIS_X_G1", "entrega2", True)
    assert cmd[2:6] == ["reviewer", "revisar", "--repo", "puj-course/FIS_X_G1"] and cmd[-1] == "--ia"
    cmd = trabajador.comando("todos", "auto", False)
    assert "revisar-todos" in cmd and "--ia" not in cmd
