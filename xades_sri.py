#!/usr/bin/env python3
"""Firma XAdES-BES conforme al SRI Ecuador.

El SRI NO acepta una firma XML-DSig genérica: exige XAdES-BES con
- una Reference al nodo raiz por su Id (`#comprobante`) con transform
  enveloped-signature,
- una Reference al `<ds:KeyInfo>` (certificado),
- una Reference a `<etsi:SignedProperties>` (Type .../01903#SignedProperties)
  que contiene SigningTime + SigningCertificate (CertDigest + IssuerSerial),
- `<ds:KeyInfo>` con X509Certificate y RSAKeyValue (Modulus/Exponent),
- SHA1 + RSA-SHA1 + C14N inclusiva (REC-xml-c14n-20010315).

Referencia: ficha tecnica de comprobantes electronicos del SRI. Interoperable
con el antiguo "firmador" de la MITyC que el SRI valida.

Sin dependencias fuera de lxml + cryptography (ya en la suite).
"""
import base64
import hashlib

from lxml import etree
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509 import load_pem_x509_certificate

DS = "http://www.w3.org/2000/09/xmldsig#"
ETSI = "http://uri.etsi.org/01903/v1.3.2#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"


def _c14n(node) -> bytes:
    """C14N inclusiva (arrastra los namespaces en scope), como exige el SRI."""
    return etree.tostring(node, method="c14n", exclusive=False, with_comments=False)


def _sha1_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha1(data).digest()).decode()


def _b64_chunked(data: bytes, width: int = 76) -> str:
    b = base64.b64encode(data).decode()
    return "\n".join(b[i:i + width] for i in range(0, len(b), width))


def sign(xml_str: str, key_pem: bytes, cert_pem: bytes, signing_time_iso: str) -> str:
    """Firma `xml_str` (con nodo raiz Id='comprobante') y devuelve el XML firmado.

    `signing_time_iso`: marca de tiempo ISO-8601 con offset (p.ej.
    '2026-07-03T10:07:35-05:00'). Se recibe de fuera para no depender de reloj
    aqui (el orquestador la pasa).
    """
    key = load_pem_private_key(key_pem, None)
    cert = load_pem_x509_certificate(cert_pem)
    cert_der = cert.public_bytes(encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.DER)

    # IDs deterministas por contenido (no aleatorios -> reproducible en tests).
    tag = hashlib.sha1((signing_time_iso + str(cert.serial_number)).encode()).hexdigest()[:10]
    sig_id = f"Signature{tag}"
    sp_id = f"{sig_id}-SignedProperties"
    si_ref_sp_id = f"{sp_id}-Ref"
    cert_id = f"Certificate{tag}"
    obj_id = f"{sig_id}-Object"
    ref_comp_id = f"Reference-{tag}"

    root = etree.fromstring(xml_str.encode("utf-8"))
    nsmap = {"ds": DS, "etsi": ETSI}

    # --- ds:Signature ---------------------------------------------------------
    sig = etree.SubElement(root, f"{{{DS}}}Signature", nsmap=nsmap)
    sig.set("Id", sig_id)

    signed_info = etree.SubElement(sig, f"{{{DS}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{DS}}}CanonicalizationMethod", Algorithm=C14N)
    etree.SubElement(signed_info, f"{{{DS}}}SignatureMethod",
                     Algorithm=f"{DS}rsa-sha1")

    # Reference 1: SignedProperties
    ref_sp = etree.SubElement(signed_info, f"{{{DS}}}Reference", Id=si_ref_sp_id,
                              Type="http://uri.etsi.org/01903#SignedProperties",
                              URI=f"#{sp_id}")
    etree.SubElement(ref_sp, f"{{{DS}}}DigestMethod", Algorithm=f"{DS}sha1")
    dv_sp = etree.SubElement(ref_sp, f"{{{DS}}}DigestValue")

    # Reference 2: KeyInfo (certificado)
    ref_ki = etree.SubElement(signed_info, f"{{{DS}}}Reference", URI=f"#{cert_id}")
    etree.SubElement(ref_ki, f"{{{DS}}}DigestMethod", Algorithm=f"{DS}sha1")
    dv_ki = etree.SubElement(ref_ki, f"{{{DS}}}DigestValue")

    # Reference 3: el comprobante (nodo raiz, enveloped)
    ref_comp = etree.SubElement(signed_info, f"{{{DS}}}Reference", Id=ref_comp_id,
                                URI="#comprobante")
    transforms = etree.SubElement(ref_comp, f"{{{DS}}}Transforms")
    etree.SubElement(transforms, f"{{{DS}}}Transform",
                     Algorithm=f"{DS}enveloped-signature")
    etree.SubElement(ref_comp, f"{{{DS}}}DigestMethod", Algorithm=f"{DS}sha1")
    dv_comp = etree.SubElement(ref_comp, f"{{{DS}}}DigestValue")

    sig_value = etree.SubElement(sig, f"{{{DS}}}SignatureValue", Id=f"SignatureValue{tag}")

    # --- ds:KeyInfo -----------------------------------------------------------
    key_info = etree.SubElement(sig, f"{{{DS}}}KeyInfo", Id=cert_id)
    x509_data = etree.SubElement(key_info, f"{{{DS}}}X509Data")
    x509_cert = etree.SubElement(x509_data, f"{{{DS}}}X509Certificate")
    x509_cert.text = _b64_chunked(cert_der)
    key_value = etree.SubElement(key_info, f"{{{DS}}}KeyValue")
    rsa_kv = etree.SubElement(key_value, f"{{{DS}}}RSAKeyValue")
    pub_nums = cert.public_key().public_numbers()
    mod = pub_nums.n.to_bytes((pub_nums.n.bit_length() + 7) // 8, "big")
    exp = pub_nums.e.to_bytes((pub_nums.e.bit_length() + 7) // 8, "big")
    etree.SubElement(rsa_kv, f"{{{DS}}}Modulus").text = _b64_chunked(mod)
    etree.SubElement(rsa_kv, f"{{{DS}}}Exponent").text = base64.b64encode(exp).decode()

    # --- ds:Object / etsi:QualifyingProperties / SignedProperties -------------
    obj = etree.SubElement(sig, f"{{{DS}}}Object", Id=obj_id)
    qp = etree.SubElement(obj, f"{{{ETSI}}}QualifyingProperties", Target=f"#{sig_id}")
    sp = etree.SubElement(qp, f"{{{ETSI}}}SignedProperties", Id=sp_id)
    ssp = etree.SubElement(sp, f"{{{ETSI}}}SignedSignatureProperties")
    etree.SubElement(ssp, f"{{{ETSI}}}SigningTime").text = signing_time_iso
    signing_cert = etree.SubElement(ssp, f"{{{ETSI}}}SigningCertificate")
    etsi_cert = etree.SubElement(signing_cert, f"{{{ETSI}}}Cert")
    cert_digest = etree.SubElement(etsi_cert, f"{{{ETSI}}}CertDigest")
    etree.SubElement(cert_digest, f"{{{DS}}}DigestMethod", Algorithm=f"{DS}sha1")
    etree.SubElement(cert_digest, f"{{{DS}}}DigestValue").text = _sha1_b64(cert_der)
    issuer_serial = etree.SubElement(etsi_cert, f"{{{ETSI}}}IssuerSerial")
    etree.SubElement(issuer_serial, f"{{{DS}}}X509IssuerName").text = \
        cert.issuer.rfc4514_string()
    etree.SubElement(issuer_serial, f"{{{DS}}}X509SerialNumber").text = \
        str(cert.serial_number)
    sdop = etree.SubElement(sp, f"{{{ETSI}}}SignedDataObjectProperties")
    dof = etree.SubElement(sdop, f"{{{ETSI}}}DataObjectFormat",
                           ObjectReference=f"#{ref_comp_id}")
    etree.SubElement(dof, f"{{{ETSI}}}Description").text = "contenido comprobante"
    etree.SubElement(dof, f"{{{ETSI}}}MimeType").text = "text/xml"

    # --- Digests --------------------------------------------------------------
    # SignedProperties: C14N del nodo (arrastra ds+etsi en scope).
    dv_sp.text = _sha1_b64(_c14n(sp))
    # KeyInfo:
    dv_ki.text = _sha1_b64(_c14n(key_info))
    # Comprobante enveloped: digest del root SIN el nodo Signature.
    sig_parent = sig.getparent()
    sig_parent.remove(sig)
    dv_comp.text = _sha1_b64(_c14n(root))
    sig_parent.append(sig)

    # --- SignatureValue: firmar SignedInfo canonicalizado ---------------------
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    signature = key.sign(_c14n(signed_info), padding.PKCS1v15(), hashes.SHA1())
    sig_value.text = _b64_chunked(signature)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
