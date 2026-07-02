"""Pruebas del constructor de XML del SRI: dígito verificador (módulo 11), clave
de acceso de 49 dígitos, tipo de identificación y XML de factura / nota de crédito.
Solo requiere lxml (firma y web service se prueban aparte, necesitan cert/red)."""
import pytest

pytest.importorskip("lxml")
from lxml import etree                                    # noqa: E402
import xml_builder as xb                                  # noqa: E402

CONFIG = {
    "ambiente": "1",
    "ruc": "1790012345001",
    "razon_social": "CLINICA DEMO SA",
    "nombre_comercial": "CLINICA DEMO",
    "direccion_matriz": "Av. Siempre Viva 123, Quito",
    "obligado_contabilidad": "SI",
}


# ── Módulo 11 (dígito verificador) ───────────────────────────────────────────
def test_modulo11_casos_deterministas():
    assert xb._modulo11("0" * 48) == 0            # resultado 11 -> 0
    assert xb._modulo11("0" * 47 + "6") == 1      # resultado 10 -> 1
    assert xb._modulo11("0" * 47 + "1") == 9      # caso normal
    assert 0 <= xb._modulo11("123456789012345678901234567890123456789012345678") <= 9


def test_modulo11_exige_48_chars():
    with pytest.raises(ValueError):
        xb._modulo11("123")


# ── Clave de acceso ──────────────────────────────────────────────────────────
def test_clave_acceso_49_digitos_y_verificador_correcto():
    clave = xb.build_clave_acceso(
        fecha="02/07/2026", tipo_comprobante="01", ruc=CONFIG["ruc"],
        ambiente="1", establecimiento="001", punto_emision="001",
        secuencial="000000123", codigo_numerico="12345678",
    )
    assert len(clave) == 49 and clave.isdigit()
    assert int(clave[-1]) == xb._modulo11(clave[:48])     # dígito verificador consistente


def test_clave_acceso_acepta_fecha_iso_y_barra_equivalentes():
    args = dict(tipo_comprobante="01", ruc=CONFIG["ruc"], ambiente="1",
                establecimiento="001", punto_emision="001", secuencial="000000123",
                codigo_numerico="12345678")
    assert xb.build_clave_acceso(fecha="02/07/2026", **args) == \
           xb.build_clave_acceso(fecha="2026-07-02", **args)


# ── Tipo de identificación ───────────────────────────────────────────────────
def test_tipo_identificacion():
    assert xb._tipo_identificacion("1790012345001") == "04"   # RUC (13)
    assert xb._tipo_identificacion("1712345678") == "05"      # cédula (10)
    assert xb._tipo_identificacion("") == "07"                # consumidor final
    assert xb._tipo_identificacion("9999999999999") == "07"
    assert xb._tipo_identificacion("AB1234") == "06"          # pasaporte / otro


# ── Factura XML ──────────────────────────────────────────────────────────────
def _invoice():
    return {
        "created_at": "2026-07-02", "establecimiento": "001", "punto_emision": "001",
        "secuencial": 123, "patient_document": "1712345678", "patient_name": "JUAN PEREZ",
        "subtotal_0": 10.0, "subtotal_iva": 100.0, "iva_amount": 15.0, "total": 125.0,
    }


def _lines():
    return [
        {"description": "Consulta", "quantity": 1, "unit_price": 100, "line_total": 100,
         "tax_rate": 15, "tax_amount": 15, "catalog_id": "C1"},
        {"description": "Examen 0%", "quantity": 1, "unit_price": 10, "line_total": 10,
         "tax_rate": 0, "tax_amount": 0, "catalog_id": "C2"},
    ]


def test_factura_xml_bien_formado_y_totales():
    xml = xb.build_factura_xml(CONFIG, _invoice(), _lines())
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == "factura" and root.get("version") == "2.1.0"
    clave = root.findtext("infoTributaria/claveAcceso")
    assert len(clave) == 49 and clave.isdigit()
    assert root.findtext("infoTributaria/ruc") == CONFIG["ruc"]
    assert root.findtext("infoTributaria/codDoc") == "01"
    assert root.findtext("infoFactura/importeTotal") == "125.00"
    assert root.findtext("infoFactura/tipoIdentificacionComprador") == "05"  # cédula
    assert len(root.findall("detalles/detalle")) == 2


# ── Nota de crédito XML ──────────────────────────────────────────────────────
def test_nota_credito_referencia_factura_original():
    nc = dict(_invoice(), notes="Devolución total")
    original = {"invoice_number": "FAC-001-001-000000123", "created_at": "2026-06-01"}
    xml = xb.build_nota_credito_xml(CONFIG, nc, _lines(), original)
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == "notaCredito"
    assert root.findtext("infoTributaria/codDoc") == "04"
    # El prefijo FAC- se quita para dejar el número SRI puro.
    assert root.findtext("infoNotaCredito/numDocModificado") == "001-001-000000123"
    assert root.findtext("infoNotaCredito/codDocModificado") == "01"
