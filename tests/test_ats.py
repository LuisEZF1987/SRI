"""Smoke del generador de ATS (Anexo Transaccional Simplificado). Solo lxml."""
import pytest

pytest.importorskip("lxml")
from lxml import etree           # noqa: E402
import ats                       # noqa: E402

CONFIG = {"ruc": "1790012345001", "razon_social": "CLINICA DEMO SA",
          "establecimiento": "001", "num_establecimientos": 1}

INVOICES = [{
    "tipo_comprobante": "01", "tipo_id_comprador": "cedula", "id_comprador": "1712345678",
    "base_imponible_0": 0.0, "base_imponible_iva": 100.0, "monto_iva": 15.0,
    "numero_comprobante": "001-001-000000001", "fecha_emision": "02/07/2026",
    "forma_pago": "efectivo",
}]


def test_generate_ats_xml_valido():
    xml = ats.generate_ats(2026, 7, INVOICES, [], CONFIG)
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == "iva"
    assert root.findtext("IdInformante") == CONFIG["ruc"]
    assert root.findtext("Anio") == "2026"
    assert root.findtext("Mes") == "07"


def test_generate_ats_sin_movimientos_no_falla():
    xml = ats.generate_ats(2026, 1, [], [], CONFIG)
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == "iva" and root.findtext("Mes") == "01"
