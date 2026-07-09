#!/usr/bin/env python3
"""
SRI Ecuador — XML Builder for Electronic Documents.

Builds SRI-compliant XML for:
  - Factura (tipo_comprobante = '01')
  - Nota de Credito (tipo_comprobante = '04')

Follows SRI schema v2.1.0.

Clave de acceso (49 digits):
  fecha(8) + tipo_comprobante(2) + ruc(13) + ambiente(1) + serie(6)
  + secuencial(9) + codigo_numerico(8) + tipo_emision(1) + digito_verificador(1)
"""
import random
import logging
from datetime import datetime

from lxml import etree

log = logging.getLogger("sri.xml_builder")


# ---------------------------------------------------------------------------
# Modulo 11 — SRI check digit algorithm
# ---------------------------------------------------------------------------
def _modulo11(clave48: str) -> int:
    """
    Compute the modulo 11 check digit for a 48-character string.

    Weights cycle 2,3,4,5,6,7 from right to left.
    Result = 11 - (sum % 11), with special cases:
      - if result == 11 -> 0
      - if result == 10 -> 1
    """
    if len(clave48) != 48:
        raise ValueError(f"clave48 must be exactly 48 chars, got {len(clave48)}")

    weights = [2, 3, 4, 5, 6, 7]
    total = 0
    for i, ch in enumerate(reversed(clave48)):
        total += int(ch) * weights[i % len(weights)]

    remainder = total % 11
    check = 11 - remainder

    if check == 11:
        return 0
    if check == 10:
        return 1
    return check


def build_clave_acceso(
    fecha: str,
    tipo_comprobante: str,
    ruc: str,
    ambiente: str,
    establecimiento: str,
    punto_emision: str,
    secuencial: str,
    codigo_numerico: str = "",
) -> str:
    """
    Build the 49-digit clave de acceso for SRI.

    Parameters:
        fecha: dd/mm/yyyy format (8 digits without separators internally)
        tipo_comprobante: '01' (factura), '04' (nota de credito), etc.
        ruc: 13-digit RUC
        ambiente: '1' (pruebas) or '2' (produccion)
        establecimiento: 3-digit establishment code (e.g. '001')
        punto_emision: 3-digit emission point (e.g. '001')
        secuencial: 9-digit sequential number (zero-padded)
        codigo_numerico: 8-digit random code (auto-generated if empty)

    Returns:
        49-character string (the clave de acceso)
    """
    # Parse and reformat date
    if "/" in fecha:
        parts = fecha.split("/")
        fecha_digits = f"{parts[0]:0>2}{parts[1]:0>2}{parts[2]:0>4}"
    elif "-" in fecha:
        parts = fecha.split("-")
        # Assume yyyy-mm-dd
        fecha_digits = f"{parts[2]:0>2}{parts[1]:0>2}{parts[0]:0>4}"
    else:
        fecha_digits = fecha[:8]

    tipo_emision = "1"  # Normal emission

    if not codigo_numerico:
        codigo_numerico = f"{random.randint(0, 99999999):08d}"

    # Pad fields
    ruc = ruc.ljust(13, "0")[:13]
    establecimiento = establecimiento.zfill(3)[:3]
    punto_emision = punto_emision.zfill(3)[:3]
    secuencial = secuencial.zfill(9)[:9]
    tipo_comprobante = tipo_comprobante.zfill(2)[:2]
    ambiente = ambiente[:1]

    serie = f"{establecimiento}{punto_emision}"

    clave48 = (
        f"{fecha_digits}"
        f"{tipo_comprobante}"
        f"{ruc}"
        f"{ambiente}"
        f"{serie}"
        f"{secuencial}"
        f"{codigo_numerico}"
        f"{tipo_emision}"
    )

    if len(clave48) != 48:
        raise ValueError(
            f"clave48 construction error: expected 48 chars, got {len(clave48)} "
            f"({clave48})"
        )

    digito = _modulo11(clave48)
    clave49 = f"{clave48}{digito}"

    log.debug("Clave de acceso generada: %s", clave49)
    return clave49


# ---------------------------------------------------------------------------
# Factura XML (tipo_comprobante = '01')
# ---------------------------------------------------------------------------
def build_factura_xml(config: dict, invoice: dict, lines: list) -> str:
    """
    Build SRI factura XML.

    Parameters:
        config: {ambiente, ruc, razon_social, nombre_comercial,
                 direccion_matriz, obligado_contabilidad}
        invoice: invoice row dict (patient_document, patient_name,
                 patient_address, establecimiento, punto_emision,
                 secuencial, subtotal_0, subtotal_iva, iva_amount, total,
                 created_at, etc.)
        lines: list of invoice line dicts

    Returns:
        XML string
    """
    # Format date
    inv_date = invoice.get("created_at", "")
    if isinstance(inv_date, str):
        fecha_emision = inv_date[:10]
        # Convert to dd/mm/yyyy
        if "-" in fecha_emision:
            parts = fecha_emision.split("-")
            fecha_emision = f"{parts[2]}/{parts[1]}/{parts[0]}"
    elif hasattr(inv_date, "strftime"):
        fecha_emision = inv_date.strftime("%d/%m/%Y")
    else:
        fecha_emision = datetime.now().strftime("%d/%m/%Y")

    establecimiento = str(invoice.get("establecimiento", "001")).zfill(3)
    punto_emision = str(invoice.get("punto_emision", "001")).zfill(3)
    secuencial_raw = str(invoice.get("secuencial", 1))
    secuencial = secuencial_raw.zfill(9)
    ambiente = str(config.get("ambiente", "1"))
    ruc = config.get("ruc", "")
    codigo_numerico = f"{random.randint(0, 99999999):08d}"

    clave_acceso = build_clave_acceso(
        fecha=fecha_emision,
        tipo_comprobante="01",
        ruc=ruc,
        ambiente=ambiente,
        establecimiento=establecimiento,
        punto_emision=punto_emision,
        secuencial=secuencial,
        codigo_numerico=codigo_numerico,
    )

    # Build XML
    root = etree.Element("factura", id="comprobante", version="2.1.0")

    # --- infoTributaria ---
    info_trib = etree.SubElement(root, "infoTributaria")
    _add_text(info_trib, "ambiente", ambiente)
    _add_text(info_trib, "tipoEmision", "1")
    _add_text(info_trib, "razonSocial", config.get("razon_social", ""))
    if config.get("nombre_comercial"):
        _add_text(info_trib, "nombreComercial", config["nombre_comercial"])
    _add_text(info_trib, "ruc", ruc)
    _add_text(info_trib, "claveAcceso", clave_acceso)
    _add_text(info_trib, "codDoc", "01")
    _add_text(info_trib, "estab", establecimiento)
    _add_text(info_trib, "ptoEmi", punto_emision)
    _add_text(info_trib, "secuencial", secuencial)
    _add_text(info_trib, "dirMatriz", config.get("direccion_matriz", ""))

    # --- infoFactura ---
    info_fac = etree.SubElement(root, "infoFactura")
    _add_text(info_fac, "fechaEmision", fecha_emision)
    _add_text(info_fac, "dirEstablecimiento", config.get("direccion_matriz", ""))
    if config.get("obligado_contabilidad"):
        _add_text(info_fac, "obligadoContabilidad", config["obligado_contabilidad"])

    # Buyer identification — comprador: el paciente, o un tercero si "facturar a otro".
    bill_to_doc = (invoice.get("bill_to_document") or "").strip()
    if bill_to_doc:
        buyer_doc = bill_to_doc
        buyer_name = invoice.get("bill_to_name") or "CONSUMIDOR FINAL"
        buyer_addr = invoice.get("bill_to_address")
    else:
        buyer_doc = invoice.get("patient_document", "")
        buyer_name = invoice.get("patient_name", "CONSUMIDOR FINAL")
        buyer_addr = invoice.get("patient_address")
    tipo_id = _tipo_identificacion(buyer_doc)
    _add_text(info_fac, "tipoIdentificacionComprador", tipo_id)
    _add_text(info_fac, "razonSocialComprador", buyer_name)
    _add_text(info_fac, "identificacionComprador", buyer_doc or "9999999999999")
    if buyer_addr:
        _add_text(info_fac, "direccionComprador", buyer_addr)

    # Totals
    subtotal_0 = float(invoice.get("subtotal_0", 0))
    subtotal_iva = float(invoice.get("subtotal_iva", 0))
    iva_amount = float(invoice.get("iva_amount", 0))
    total = float(invoice.get("total", 0))

    _add_text(info_fac, "totalSinImpuestos", f"{subtotal_0 + subtotal_iva:.2f}")
    total_descuento = round(sum(
        round(abs(float(l.get("quantity", 1))) * float(l.get("unit_price", 0))
              * float(l.get("discount_percent", 0)) / 100, 2) for l in lines), 2)
    _add_text(info_fac, "totalDescuento", f"{total_descuento:.2f}")

    # totalConImpuestos
    total_impuestos = etree.SubElement(info_fac, "totalConImpuestos")

    # IVA 0%
    if subtotal_0 > 0:
        ti = etree.SubElement(total_impuestos, "totalImpuesto")
        _add_text(ti, "codigo", "2")       # IVA
        _add_text(ti, "codigoPorcentaje", "0")  # 0%
        _add_text(ti, "baseImponible", f"{subtotal_0:.2f}")
        _add_text(ti, "valor", "0.00")

    # IVA 15% (if any)
    if subtotal_iva > 0:
        ti = etree.SubElement(total_impuestos, "totalImpuesto")
        _add_text(ti, "codigo", "2")
        _add_text(ti, "codigoPorcentaje", "4")  # 15%
        _add_text(ti, "baseImponible", f"{subtotal_iva:.2f}")
        _add_text(ti, "valor", f"{iva_amount:.2f}")

    _add_text(info_fac, "propina", "0.00")
    _add_text(info_fac, "importeTotal", f"{total:.2f}")
    _add_text(info_fac, "moneda", "DOLAR")

    # pagos
    pagos = etree.SubElement(info_fac, "pagos")
    pago = etree.SubElement(pagos, "pago")
    _add_text(pago, "formaPago", "01")  # Sin utilizacion del sistema financiero
    _add_text(pago, "total", f"{total:.2f}")

    # --- detalles ---
    detalles = etree.SubElement(root, "detalles")
    for ln in lines:
        detalle = etree.SubElement(detalles, "detalle")
        _add_text(detalle, "codigoPrincipal", str(ln.get("catalog_id", "001")))
        _add_text(detalle, "descripcion", ln.get("description", "Servicio")[:300])
        _add_text(detalle, "cantidad", f"{abs(float(ln.get('quantity', 1))):.2f}")
        _add_text(detalle, "precioUnitario", f"{float(ln.get('unit_price', 0)):.2f}")
        desc = round(abs(float(ln.get("quantity", 1))) * float(ln.get("unit_price", 0))
                     * float(ln.get("discount_percent", 0)) / 100, 2)
        _add_text(detalle, "descuento", f"{desc:.2f}")
        line_total = abs(float(ln.get("line_total", 0)))
        _add_text(detalle, "precioTotalSinImpuesto", f"{line_total:.2f}")

        impuestos = etree.SubElement(detalle, "impuestos")
        imp = etree.SubElement(impuestos, "impuesto")
        _add_text(imp, "codigo", "2")  # IVA
        tax_rate = float(ln.get("tax_rate", 0))
        if tax_rate > 0:
            _add_text(imp, "codigoPorcentaje", "4")  # 15%
            _add_text(imp, "tarifa", f"{tax_rate:.0f}")
        else:
            _add_text(imp, "codigoPorcentaje", "0")  # 0%
            _add_text(imp, "tarifa", "0")
        _add_text(imp, "baseImponible", f"{line_total:.2f}")
        _add_text(imp, "valor", f"{abs(float(ln.get('tax_amount', 0))):.2f}")

    # --- infoAdicional --- (cuando la factura va a un tercero, el paciente atendido va aqui; + contacto)
    campos = []
    if bill_to_doc and invoice.get("patient_name"):
        campos.append(("Paciente", invoice["patient_name"]))
    email = invoice.get("bill_to_email") if bill_to_doc else invoice.get("patient_email")
    if email:
        campos.append(("Email", email))
    if invoice.get("patient_phone"):
        campos.append(("Telefono", invoice["patient_phone"]))
    if campos:
        info_ad = etree.SubElement(root, "infoAdicional")
        for nombre, valor in campos:
            ca = etree.SubElement(info_ad, "campoAdicional", nombre=nombre)
            ca.text = str(valor)[:300]

    xml_str = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True,
    ).decode("utf-8")

    return xml_str


# ---------------------------------------------------------------------------
# Nota de Credito XML (tipo_comprobante = '04')
# ---------------------------------------------------------------------------
def build_nota_credito_xml(
    config: dict,
    credit_note: dict,
    lines: list,
    original_invoice: dict,
) -> str:
    """
    Build SRI nota de credito XML.

    Parameters:
        config: SRI configuration dict
        credit_note: credit note invoice dict
        lines: list of credit note lines (quantities/amounts are negative)
        original_invoice: the original invoice being credited

    Returns:
        XML string
    """
    inv_date = credit_note.get("created_at", "")
    if isinstance(inv_date, str):
        fecha_emision = inv_date[:10]
        if "-" in fecha_emision:
            parts = fecha_emision.split("-")
            fecha_emision = f"{parts[2]}/{parts[1]}/{parts[0]}"
    elif hasattr(inv_date, "strftime"):
        fecha_emision = inv_date.strftime("%d/%m/%Y")
    else:
        fecha_emision = datetime.now().strftime("%d/%m/%Y")

    establecimiento = str(credit_note.get("establecimiento", "001")).zfill(3)
    punto_emision = str(credit_note.get("punto_emision", "001")).zfill(3)
    secuencial = str(credit_note.get("secuencial", 1)).zfill(9)
    ambiente = str(config.get("ambiente", "1"))
    ruc = config.get("ruc", "")
    codigo_numerico = f"{random.randint(0, 99999999):08d}"

    clave_acceso = build_clave_acceso(
        fecha=fecha_emision,
        tipo_comprobante="04",
        ruc=ruc,
        ambiente=ambiente,
        establecimiento=establecimiento,
        punto_emision=punto_emision,
        secuencial=secuencial,
        codigo_numerico=codigo_numerico,
    )

    root = etree.Element("notaCredito", id="comprobante", version="1.1.0")

    # --- infoTributaria ---
    info_trib = etree.SubElement(root, "infoTributaria")
    _add_text(info_trib, "ambiente", ambiente)
    _add_text(info_trib, "tipoEmision", "1")
    _add_text(info_trib, "razonSocial", config.get("razon_social", ""))
    if config.get("nombre_comercial"):
        _add_text(info_trib, "nombreComercial", config["nombre_comercial"])
    _add_text(info_trib, "ruc", ruc)
    _add_text(info_trib, "claveAcceso", clave_acceso)
    _add_text(info_trib, "codDoc", "04")
    _add_text(info_trib, "estab", establecimiento)
    _add_text(info_trib, "ptoEmi", punto_emision)
    _add_text(info_trib, "secuencial", secuencial)
    _add_text(info_trib, "dirMatriz", config.get("direccion_matriz", ""))

    # --- infoNotaCredito ---
    info_nc = etree.SubElement(root, "infoNotaCredito")
    _add_text(info_nc, "fechaEmision", fecha_emision)
    _add_text(info_nc, "dirEstablecimiento", config.get("direccion_matriz", ""))
    if config.get("obligado_contabilidad"):
        _add_text(info_nc, "obligadoContabilidad", config["obligado_contabilidad"])

    patient_doc = credit_note.get("patient_document", "")
    tipo_id = _tipo_identificacion(patient_doc)
    _add_text(info_nc, "tipoIdentificacionComprador", tipo_id)
    _add_text(info_nc, "razonSocialComprador",
              credit_note.get("patient_name", "CONSUMIDOR FINAL"))
    _add_text(info_nc, "identificacionComprador",
              patient_doc or "9999999999999")

    # Reference to original document
    _add_text(info_nc, "codDocModificado", "01")  # Factura
    orig_number = original_invoice.get("invoice_number", "")
    # Extract SRI number from FAC-XXX-YYY-ZZZZZZZZZ format
    if orig_number.startswith("FAC-"):
        sri_number = orig_number[4:]  # Remove FAC- prefix
    else:
        sri_number = orig_number
    _add_text(info_nc, "numDocModificado", sri_number)

    # Date of original document
    orig_date = original_invoice.get("created_at", fecha_emision)
    if isinstance(orig_date, str) and "-" in orig_date:
        parts = orig_date[:10].split("-")
        orig_date = f"{parts[2]}/{parts[1]}/{parts[0]}"
    elif hasattr(orig_date, "strftime"):
        orig_date = orig_date.strftime("%d/%m/%Y")
    _add_text(info_nc, "fechaEmisionDocSustento", str(orig_date)[:10])

    subtotal_0 = abs(float(credit_note.get("subtotal_0", 0)))
    subtotal_iva = abs(float(credit_note.get("subtotal_iva", 0)))
    iva_amount = abs(float(credit_note.get("iva_amount", 0)))
    total = abs(float(credit_note.get("total", 0)))

    _add_text(info_nc, "totalSinImpuestos", f"{subtotal_0 + subtotal_iva:.2f}")
    _add_text(info_nc, "valorModificacion", f"{total:.2f}")
    _add_text(info_nc, "moneda", "DOLAR")

    # totalConImpuestos
    total_impuestos = etree.SubElement(info_nc, "totalConImpuestos")
    if subtotal_0 > 0:
        ti = etree.SubElement(total_impuestos, "totalImpuesto")
        _add_text(ti, "codigo", "2")
        _add_text(ti, "codigoPorcentaje", "0")
        _add_text(ti, "baseImponible", f"{subtotal_0:.2f}")
        _add_text(ti, "valor", "0.00")

    if subtotal_iva > 0:
        ti = etree.SubElement(total_impuestos, "totalImpuesto")
        _add_text(ti, "codigo", "2")
        _add_text(ti, "codigoPorcentaje", "4")
        _add_text(ti, "baseImponible", f"{subtotal_iva:.2f}")
        _add_text(ti, "valor", f"{iva_amount:.2f}")

    _add_text(info_nc, "motivo", credit_note.get("notes", "Anulacion de factura"))

    # --- detalles ---
    detalles = etree.SubElement(root, "detalles")
    for ln in lines:
        detalle = etree.SubElement(detalles, "detalle")
        _add_text(detalle, "codigoInterno", str(ln.get("catalog_id", "001")))
        _add_text(detalle, "descripcion", ln.get("description", "Servicio")[:300])
        _add_text(detalle, "cantidad", f"{abs(float(ln.get('quantity', 1))):.2f}")
        _add_text(detalle, "precioUnitario", f"{float(ln.get('unit_price', 0)):.2f}")
        desc = round(abs(float(ln.get("quantity", 1))) * float(ln.get("unit_price", 0))
                     * float(ln.get("discount_percent", 0)) / 100, 2)
        _add_text(detalle, "descuento", f"{desc:.2f}")
        line_total = abs(float(ln.get("line_total", 0)))
        _add_text(detalle, "precioTotalSinImpuesto", f"{line_total:.2f}")

        impuestos = etree.SubElement(detalle, "impuestos")
        imp = etree.SubElement(impuestos, "impuesto")
        _add_text(imp, "codigo", "2")
        tax_rate = float(ln.get("tax_rate", 0))
        if tax_rate > 0:
            _add_text(imp, "codigoPorcentaje", "4")
            _add_text(imp, "tarifa", f"{tax_rate:.0f}")
        else:
            _add_text(imp, "codigoPorcentaje", "0")
            _add_text(imp, "tarifa", "0")
        _add_text(imp, "baseImponible", f"{line_total:.2f}")
        _add_text(imp, "valor", f"{abs(float(ln.get('tax_amount', 0))):.2f}")

    xml_str = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True,
    ).decode("utf-8")

    return xml_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _add_text(parent, tag, text):
    """Add a text subelement."""
    el = etree.SubElement(parent, tag)
    el.text = str(text) if text is not None else ""
    return el


def _tipo_identificacion(document_id: str) -> str:
    """
    Determine SRI tipo_identificacion from document ID.
    04 = RUC (13 digits)
    05 = Cedula (10 digits)
    06 = Pasaporte
    07 = Consumidor final
    """
    if not document_id or document_id == "9999999999999":
        return "07"
    doc = document_id.strip()
    if len(doc) == 13 and doc.isdigit():
        return "04"  # RUC
    if len(doc) == 10 and doc.isdigit():
        return "05"  # Cedula
    return "06"  # Pasaporte / otro


def _tipo_identificacion_retencion(document_id: str) -> str:
    """Tabla 7 del SRI — identificacion del SUJETO RETENIDO del comprobante de
    retencion (codDoc 07). NO es la tabla 6 del comprador de factura.
        01 = RUC (13 digitos)
        02 = Cedula (10 digitos)
        03 = Pasaporte / otro
    (08 = identificacion del exterior; lo pasa explicito el origen, ver build_retencion_xml)
    """
    doc = (document_id or "").strip()
    if len(doc) == 13 and doc.isdigit():
        return "01"  # RUC
    if len(doc) == 10 and doc.isdigit():
        return "02"  # Cedula
    return "03"  # Pasaporte / otro


# ---------------------------------------------------------------------------
# Comprobante de Retencion XML (tipo_comprobante = '07', schema v2.0.0)
# ---------------------------------------------------------------------------
def build_retencion_xml(config: dict, ret: dict):
    """
    Construye el XML del Comprobante de Retencion electronico (codDoc '07'), esquema
    del SRI **v2.0.0** (con `docsSustento`). Lo emite el AGENTE DE RETENCION sobre el
    comprobante de un proveedor (la compra registrada en Contabilidad).

    Parameters:
        config: {ambiente, ruc, razon_social, nombre_comercial, direccion_matriz,
                 obligado_contabilidad, contribuyente_especial(opcional)}
        ret: {
          establecimiento, punto_emision, secuencial,           # de esta retencion
          fecha_emision (YYYY-MM-DD | dd/mm/yyyy),
          periodo_fiscal (mm/yyyy),
          sujeto: {identificacion, razon_social, tipo_id(opcional)},   # el proveedor retenido
          doc_sustento: {
             cod_sustento, cod_doc_sustento, num_doc_sustento(estab+pto+secuencial=15),
             fecha_emision, num_autorizacion(opcional),
             total_sin_impuestos, importe_total,
             impuestos: [{cod, cod_porcentaje, base, tarifa, valor}]   # IVA del doc (opcional)
          },
          retenciones: [{codigo(1 renta/2 iva/6 isd), codigo_retencion, base, porcentaje, valor}]
        }

    Returns: (xml_str, clave_acceso)
    """
    fecha_emision = _fmt_fecha(ret.get("fecha_emision"))
    establecimiento = str(ret.get("establecimiento", "001")).zfill(3)
    punto_emision = str(ret.get("punto_emision", "001")).zfill(3)
    secuencial = str(ret.get("secuencial", 1)).zfill(9)
    ambiente = str(config.get("ambiente", "1"))
    ruc = config.get("ruc", "")
    codigo_numerico = f"{random.randint(0, 99999999):08d}"

    clave_acceso = build_clave_acceso(
        fecha=fecha_emision, tipo_comprobante="07", ruc=ruc, ambiente=ambiente,
        establecimiento=establecimiento, punto_emision=punto_emision,
        secuencial=secuencial, codigo_numerico=codigo_numerico)

    root = etree.Element("comprobanteRetencion", id="comprobante", version="2.0.0")

    # --- infoTributaria ---
    it = etree.SubElement(root, "infoTributaria")
    _add_text(it, "ambiente", ambiente)
    _add_text(it, "tipoEmision", "1")
    _add_text(it, "razonSocial", config.get("razon_social", ""))
    if config.get("nombre_comercial"):
        _add_text(it, "nombreComercial", config["nombre_comercial"])
    _add_text(it, "ruc", ruc)
    _add_text(it, "claveAcceso", clave_acceso)
    _add_text(it, "codDoc", "07")
    _add_text(it, "estab", establecimiento)
    _add_text(it, "ptoEmi", punto_emision)
    _add_text(it, "secuencial", secuencial)
    _add_text(it, "dirMatriz", config.get("direccion_matriz", ""))

    # --- infoCompRetencion ---
    ic = etree.SubElement(root, "infoCompRetencion")
    _add_text(ic, "fechaEmision", fecha_emision)
    _add_text(ic, "dirEstablecimiento", config.get("direccion_matriz", ""))
    if config.get("contribuyente_especial"):
        _add_text(ic, "contribuyenteEspecial", config["contribuyente_especial"])
    _add_text(ic, "obligadoContabilidad", config.get("obligado_contabilidad", "SI"))
    suj = ret.get("sujeto", {})
    suj_doc = str(suj.get("identificacion", "")).strip()
    # Tabla 7 del SRI (sujeto retenido): 01=RUC, 02=cédula, 03=pasaporte, 08=exterior.
    # Se deriva SIEMPRE del documento (no de la tabla 6 del comprador); solo se respeta
    # '08' explícito del origen para proveedores del exterior.
    tipo_id = "08" if suj.get("tipo_id") == "08" else _tipo_identificacion_retencion(suj_doc)
    _add_text(ic, "tipoIdentificacionSujetoRetenido", tipo_id)
    # tipoSujetoRetenido: el SRI lo EXIGE solo cuando el retenido es identificación del
    # exterior (tipo '08'); para RUC/cédula nacional NO debe especificarse.
    if tipo_id == "08":
        _add_text(ic, "tipoSujetoRetenido", suj.get("tipo_sujeto") or "01")
    _add_text(ic, "parteRel", suj.get("parte_rel") or "NO")
    _add_text(ic, "razonSocialSujetoRetenido", suj.get("razon_social", ""))
    _add_text(ic, "identificacionSujetoRetenido", suj_doc)
    _add_text(ic, "periodoFiscal", ret.get("periodo_fiscal") or fecha_emision[3:])

    # --- docsSustento / docSustento ---
    ds = etree.SubElement(root, "docsSustento")
    doc = ret.get("doc_sustento", {})
    d = etree.SubElement(ds, "docSustento")
    _add_text(d, "codSustento", str(doc.get("cod_sustento", "01")).zfill(2))
    _add_text(d, "codDocSustento", str(doc.get("cod_doc_sustento", "01")).zfill(2))
    _add_text(d, "numDocSustento", str(doc.get("num_doc_sustento", "")).zfill(15))
    _add_text(d, "fechaEmisionDocSustento", _fmt_fecha(doc.get("fecha_emision")))
    if doc.get("num_autorizacion"):
        _add_text(d, "numAutDocSustento", doc["num_autorizacion"])
    _add_text(d, "pagoLocExt", doc.get("pago_loc_ext", "01"))
    _add_text(d, "totalSinImpuestos", f"{float(doc.get('total_sin_impuestos', 0)):.2f}")
    _add_text(d, "importeTotal", f"{float(doc.get('importe_total', 0)):.2f}")

    imps = doc.get("impuestos") or []
    if imps:
        idt = etree.SubElement(d, "impuestosDocSustento")
        for im in imps:
            i = etree.SubElement(idt, "impuestoDocSustento")
            _add_text(i, "codImpuestoDocSustento", str(im.get("cod", "2")))
            _add_text(i, "codigoPorcentaje", str(im.get("cod_porcentaje", "4")))
            _add_text(i, "baseImponible", f"{float(im.get('base', 0)):.2f}")
            _add_text(i, "tarifa", f"{float(im.get('tarifa', 0)):.0f}")
            _add_text(i, "valorImpuesto", f"{float(im.get('valor', 0)):.2f}")

    rets = etree.SubElement(d, "retenciones")
    for r in (ret.get("retenciones") or []):
        rr = etree.SubElement(rets, "retencion")
        base = round(float(r.get("base", 0) or 0), 2)
        pct = round(float(r.get("porcentaje", 0) or 0), 2)
        # El SRI VALIDA aritméticamente valorRetenido = round(base * %/100, 2). Se
        # recomputa aquí para no depender del 'valor' que envíe el origen (evita
        # rechazos por descuadres de centavos).
        valor = round(base * pct / 100.0, 2)
        _add_text(rr, "codigo", str(r.get("codigo", "1")))
        _add_text(rr, "codigoRetencion", str(r.get("codigo_retencion", "")))
        _add_text(rr, "baseImponible", f"{base:.2f}")
        _add_text(rr, "porcentajeRetener", f"{pct:.2f}")
        _add_text(rr, "valorRetenido", f"{valor:.2f}")

    # pagos (forma de pago del documento de sustento) — requerido por el esquema 2.0.0.
    pagos = etree.SubElement(d, "pagos")
    pago = etree.SubElement(pagos, "pago")
    _add_text(pago, "formaPago", str(doc.get("forma_pago", "20")))  # 20 = con sistema financiero
    _add_text(pago, "total", f"{float(doc.get('importe_total', 0)):.2f}")

    xml_str = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                             pretty_print=True).decode("utf-8")
    return xml_str, clave_acceso


def _tipo_sujeto_retenido(document_id: str) -> str:
    """SRI 2.0.0: '01' persona natural, '02' sociedad. Se deriva del RUC (13 díg): 3er dígito
    9 = sociedad privada, 6 = sector público → '02'; cédula (10) o resto → persona natural '01'."""
    doc = (document_id or "").strip()
    if len(doc) == 13 and doc.isdigit() and doc[2] in ("6", "9"):
        return "02"
    return "01"


def _fmt_fecha(v):
    """A dd/mm/yyyy desde 'YYYY-MM-DD', 'dd/mm/yyyy' o date/datetime. Vacio→hoy."""
    if v in (None, ""):
        return datetime.now().strftime("%d/%m/%Y")
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    s = str(v)[:10]
    if "-" in s:
        p = s.split("-")
        return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else s
    return s
