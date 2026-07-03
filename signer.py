#!/usr/bin/env python3
"""
SRI Ecuador — XML Digital Signature (XAdES-BES).

Signs SRI electronic documents using a .p12 (PKCS#12) certificate.

Primary approach: signxml library (Python-native).
Fallback: xmlsec1 command-line tool via subprocess.
"""
import logging
import os
import subprocess
import tempfile
from typing import Optional

log = logging.getLogger("sri.signer")


def sign_xml(xml_str: str, cert_path: str, cert_password: str,
             signing_time_iso: Optional[str] = None) -> str:
    """
    Firma un XML de comprobante electronico con XAdES-BES conforme al SRI Ecuador.

    El SRI NO acepta una firma XML-DSig generica (la RECIBE pero la deja
    NO AUTORIZADO, error 39): exige XAdES-BES con Reference a `#comprobante`,
    SignedProperties (SigningTime + SigningCertificate) y KeyInfo con
    X509Certificate + RSAKeyValue. Eso lo produce `xades_sri.sign`. Los metodos
    genericos (signxml/xmlsec1) quedan solo como respaldo de emergencia.

    Parameters:
        xml_str: XML a firmar (nodo raiz con Id="comprobante").
        cert_path: ruta al .p12 / .pfx (soporta los legacy del SRI Ecuador).
        cert_password: clave del certificado.
        signing_time_iso: marca de tiempo ISO-8601 con offset; si None, ahora.

    Returns:
        XML firmado (string).
    """
    if not os.path.exists(cert_path):
        raise FileNotFoundError(f"Certificate file not found: {cert_path}")

    # Metodo correcto para el SRI: XAdES-BES.
    try:
        from . import xades_sri
    except ImportError:  # ejecucion como modulo suelto (no paquete)
        import xades_sri
    if signing_time_iso is None:
        import datetime
        signing_time_iso = datetime.datetime.now().astimezone().replace(
            microsecond=0).isoformat()
    key_pem, cert_pem = _p12_to_pem(cert_path, cert_password)
    return xades_sri.sign(xml_str, key_pem, cert_pem, signing_time_iso)


def _p12_to_pem(cert_path: str, cert_password: str):
    """Devuelve (key_pem_bytes, cert_pem_bytes) desde un .p12.

    Los certificados de firma del SRI Ecuador (Security Data, ANF, Uanataca,
    Consejo de la Judicatura) suelen venir cifrados con algoritmos PKCS#12
    *legacy* (RC2-40-CBC / PBE-SHA1-3DES) que OpenSSL 3 / la librería
    `cryptography` rechazan por defecto. Estrategia:
      1) intentar `cryptography` (rápido, certs modernos);
      2) si falla, reintentar con `openssl pkcs12 -legacy` (provider legacy),
         que sí descifra esos algoritmos, y cargar los PEM resultantes.
    Fail-closed: si ninguna vía funciona, propaga el error.
    """
    from cryptography.hazmat.primitives.serialization import (
        pkcs12, Encoding, PrivateFormat, NoEncryption,
        load_pem_private_key)
    from cryptography.hazmat.backends import default_backend
    from cryptography.x509 import load_pem_x509_certificate

    pw_bytes = cert_password.encode("utf-8") if cert_password else None
    try:
        with open(cert_path, "rb") as f:
            key, cert, _ = pkcs12.load_key_and_certificates(
                f.read(), pw_bytes, default_backend())
        if key is None or cert is None:
            raise ValueError("no se pudo extraer clave/certificado del .p12")
        return (
            key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
            cert.public_bytes(Encoding.PEM),
        )
    except Exception as modern_err:  # noqa: BLE001 - se reintenta con -legacy
        log.info("carga moderna del .p12 fallo (%s); reintentando con openssl -legacy",
                 modern_err)

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        km, cm = os.path.join(d, "k.pem"), os.path.join(d, "c.pem")
        pass_arg = f"pass:{cert_password}" if cert_password else "pass:"
        for extra, out in ((["-nocerts", "-nodes"], km), (["-clcerts", "-nokeys"], cm)):
            r = subprocess.run(
                ["openssl", "pkcs12", "-in", cert_path, *extra, "-legacy",
                 "-passin", pass_arg, "-out", out],
                capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                raise RuntimeError(
                    f"openssl -legacy no pudo leer el .p12: {r.stderr.strip()[:200]}")
        key = load_pem_private_key(open(km, "rb").read(), None)
        cert = load_pem_x509_certificate(open(cm, "rb").read())
        return (
            key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
            cert.public_bytes(Encoding.PEM),
        )


def _sign_with_signxml(xml_str: str, cert_path: str, cert_password: str) -> str:
    """Sign using the signxml Python library."""
    from lxml import etree
    import signxml

    # Carga tolerante a .p12 legacy (SRI Ecuador).
    key_pem, cert_pem = _p12_to_pem(cert_path, cert_password)

    # Parse XML
    root = etree.fromstring(xml_str.encode("utf-8"))

    # Sign with enveloped signature (XAdES-BES)
    signer = signxml.XMLSigner(
        method=signxml.methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )

    signed_root = signer.sign(
        root,
        key=key_pem,
        cert=cert_pem,
    )

    signed_xml = etree.tostring(
        signed_root, xml_declaration=True, encoding="UTF-8", pretty_print=True,
    ).decode("utf-8")

    log.info("XML signed successfully using signxml library")
    return signed_xml


def _sign_with_xmlsec1(xml_str: str, cert_path: str, cert_password: str) -> str:
    """Sign using xmlsec1 command-line tool as fallback."""
    # Verify xmlsec1 is available
    try:
        subprocess.run(
            ["xmlsec1", "--version"],
            capture_output=True, check=True, timeout=10,
        )
    except FileNotFoundError:
        raise FileNotFoundError("xmlsec1 not found in PATH")

    with tempfile.TemporaryDirectory() as tmpdir:
        xml_path = os.path.join(tmpdir, "document.xml")
        key_path = os.path.join(tmpdir, "key.pem")
        cert_pem_path = os.path.join(tmpdir, "cert.pem")
        signed_path = os.path.join(tmpdir, "signed.xml")

        # Extract key and cert from .p12 using openssl
        _extract_p12(cert_path, cert_password, key_path, cert_pem_path)

        # Add signature template to XML
        xml_with_template = _add_signature_template(xml_str)

        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_with_template)

        # Run xmlsec1
        cmd = [
            "xmlsec1", "--sign",
            "--privkey-pem", f"{key_path},{cert_pem_path}",
            "--output", signed_path,
            xml_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"xmlsec1 signing failed (rc={result.returncode}): {result.stderr}"
            )

        with open(signed_path, "r", encoding="utf-8") as f:
            signed_xml = f.read()

        log.info("XML signed successfully using xmlsec1 command-line")
        return signed_xml


def _extract_p12(
    p12_path: str, password: str,
    key_out: str, cert_out: str,
) -> None:
    """Extract PEM key and cert from a .p12 file using openssl.

    Reutiliza `_p12_to_pem` (que ya maneja los .p12 legacy del SRI Ecuador vía
    `openssl -legacy`) y escribe los PEM a los archivos que consume xmlsec1.
    """
    key_pem, cert_pem = _p12_to_pem(p12_path, password)
    with open(key_out, "wb") as f:
        f.write(key_pem)
    with open(cert_out, "wb") as f:
        f.write(cert_pem)


def _add_signature_template(xml_str: str) -> str:
    """
    Add an XML Signature template for xmlsec1 to fill in.
    This inserts a <ds:Signature> placeholder in the root element.
    """
    from lxml import etree

    DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
    DS = "{%s}" % DSIG_NS
    nsmap = {"ds": DSIG_NS}

    root = etree.fromstring(xml_str.encode("utf-8"))

    # Build Signature template
    sig = etree.SubElement(root, f"{DS}Signature", nsmap=nsmap, Id="Signature")

    signed_info = etree.SubElement(sig, f"{DS}SignedInfo")
    c14n = etree.SubElement(signed_info, f"{DS}CanonicalizationMethod")
    c14n.set("Algorithm", "http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    sig_method = etree.SubElement(signed_info, f"{DS}SignatureMethod")
    sig_method.set("Algorithm", "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256")

    ref = etree.SubElement(signed_info, f"{DS}Reference", URI="")
    transforms = etree.SubElement(ref, f"{DS}Transforms")
    t = etree.SubElement(transforms, f"{DS}Transform")
    t.set("Algorithm", "http://www.w3.org/2000/09/xmldsig#enveloped-signature")
    digest_method = etree.SubElement(ref, f"{DS}DigestMethod")
    digest_method.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    etree.SubElement(ref, f"{DS}DigestValue")

    etree.SubElement(sig, f"{DS}SignatureValue")

    key_info = etree.SubElement(sig, f"{DS}KeyInfo")
    x509_data = etree.SubElement(key_info, f"{DS}X509Data")
    etree.SubElement(x509_data, f"{DS}X509Certificate")

    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True,
    ).decode("utf-8")


def verify_p12(cert_path: str, cert_password: str) -> Optional[dict]:
    """
    Verify a .p12 certificate and return basic info.
    Returns None if invalid.
    """
    try:
        from cryptography.x509 import load_pem_x509_certificate

        # _p12_to_pem tolera los .p12 legacy del SRI Ecuador (openssl -legacy).
        _key_pem, cert_pem = _p12_to_pem(cert_path, cert_password)
        certificate = load_pem_x509_certificate(cert_pem)

        return {
            "subject": str(certificate.subject),
            "issuer": str(certificate.issuer),
            "not_valid_before": certificate.not_valid_before_utc.isoformat(),
            "not_valid_after": certificate.not_valid_after_utc.isoformat(),
            "serial_number": str(certificate.serial_number),
        }
    except Exception as e:
        log.warning("Failed to verify .p12 certificate: %s", e)
        return None
