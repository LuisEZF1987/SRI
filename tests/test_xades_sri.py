"""Tests del firmador XAdES-BES del SRI (xades_sri).

No requiere un .p12 real: genera un par RSA + certificado autofirmado en
memoria, firma un comprobante y valida la ESTRUCTURA que exige el SRI y la
VALIDEZ CRIPTOGRAFICA (la firma de SignedInfo y el digest del comprobante).
"""
import base64
import datetime
import hashlib

import pytest

from lxml import etree
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

import xades_sri

DS = "http://www.w3.org/2000/09/xmldsig#"
ETSI = "http://uri.etsi.org/01903/v1.3.2#"
NS = {"ds": DS, "etsi": ETSI}


@pytest.fixture(scope="module")
def key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "PRUEBA FIRMANTE"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(123456789)
        .not_valid_before(datetime.datetime(2024, 1, 1))
        .not_valid_after(datetime.datetime(2030, 1, 1))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key, cert, key_pem, cert_pem


FACTURA = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<factura id="comprobante" version="2.1.0">'
           '<infoTributaria><ruc>1793193550001</ruc>'
           '<claveAcceso>0307202601179319355000120010010000000666545582515</claveAcceso>'
           '</infoTributaria></factura>')


@pytest.fixture(scope="module")
def signed(key_and_cert):
    _key, _cert, key_pem, cert_pem = key_and_cert
    return xades_sri.sign(FACTURA, key_pem, cert_pem, "2026-07-03T10:25:51-05:00")


def test_estructura_xades(signed):
    root = etree.fromstring(signed.encode())
    # Reference al comprobante con transform enveloped
    refs = root.findall(".//ds:SignedInfo/ds:Reference", NS)
    assert len(refs) == 3, "SRI exige 3 References (SignedProperties, KeyInfo, comprobante)"
    uris = {r.get("URI") for r in refs}
    assert "#comprobante" in uris
    env = root.find(".//ds:Reference[@URI='#comprobante']//ds:Transform", NS)
    assert env is not None and "enveloped-signature" in env.get("Algorithm")
    # SignedProperties con SigningTime + SigningCertificate
    assert root.find(".//etsi:SignedProperties/etsi:SignedSignatureProperties/etsi:SigningTime", NS) is not None
    assert root.find(".//etsi:SigningCertificate/etsi:Cert/etsi:CertDigest/ds:DigestValue", NS) is not None
    # KeyInfo con X509 + RSAKeyValue
    assert root.find(".//ds:KeyInfo/ds:X509Data/ds:X509Certificate", NS).text.strip()
    assert root.find(".//ds:KeyInfo/ds:KeyValue/ds:RSAKeyValue/ds:Modulus", NS) is not None
    # ningun DigestValue vacio
    for dv in root.findall(".//ds:SignedInfo//ds:DigestValue", NS):
        assert dv.text and dv.text.strip()


def test_firma_criptografica_valida(signed, key_and_cert):
    key, _cert, _kp, _cp = key_and_cert
    root = etree.fromstring(signed.encode())
    signed_info = root.find(".//ds:SignedInfo", NS)
    c14n = etree.tostring(signed_info, method="c14n", exclusive=False)
    sigval = base64.b64decode(root.find(".//ds:SignatureValue", NS).text)
    # No lanza => firma valida con la clave publica del firmante
    key.public_key().verify(sigval, c14n, padding.PKCS1v15(), hashes.SHA1())


def test_digest_comprobante_correcto(signed):
    """El DigestValue del #comprobante debe ser SHA1(C14N(factura sin Signature))."""
    root = etree.fromstring(signed.encode())
    sig = root.find("ds:Signature", NS)
    # digest declarado en la Reference #comprobante
    ref = root.find(".//ds:Reference[@URI='#comprobante']", NS)
    declarado = ref.find("ds:DigestValue", NS).text
    # recomputar: root sin el nodo Signature (efecto del transform enveloped)
    root.remove(sig)
    recomputado = base64.b64encode(
        hashlib.sha1(etree.tostring(root, method="c14n", exclusive=False)).digest()).decode()
    assert declarado == recomputado
