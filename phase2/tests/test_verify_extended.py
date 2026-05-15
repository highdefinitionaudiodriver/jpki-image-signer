"""
verify_signed_image() 拡張機能テスト:
  - 有効期間検証 (validity_period_ok と valid への反映)
  - チェーン検証 (trust_anchors 指定時)
  - 失効確認 (CRL 指定時)
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cryptography import x509 as c_x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

from phase2.crypto.p7s import build_p7s
from phase2.crypto.verify import verify_signed_image


def _make_name(cn: str) -> c_x509.Name:
    return c_x509.Name([
        c_x509.NameAttribute(NameOID.COMMON_NAME, cn),
        c_x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ChainTest"),
        c_x509.NameAttribute(NameOID.COUNTRY_NAME, "JP"),
    ])


def _build_self_signed(cn: str, key_size: int = 2048, *, days_valid: int = 3650):
    """自己署名CA証明書を生成."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    name = _make_name(cn)
    cert = (
        c_x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(c_x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=days_valid))
        .add_extension(c_x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _build_leaf(
    cn: str,
    issuer_key: rsa.RSAPrivateKey,
    issuer_cert: c_x509.Certificate,
    *,
    nvb: datetime | None = None,
    nva: datetime | None = None,
    key_size: int = 2048,
):
    """発行元CAで署名された葉証明書を生成."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    if nvb is None:
        nvb = datetime.now(timezone.utc) - timedelta(minutes=1)
    if nva is None:
        nva = datetime.now(timezone.utc) + timedelta(days=365)
    cert = (
        c_x509.CertificateBuilder()
        .subject_name(_make_name(cn))
        .issuer_name(issuer_cert.subject)
        .public_key(key.public_key())
        .serial_number(c_x509.random_serial_number())
        .not_valid_before(nvb)
        .not_valid_after(nva)
        .sign(issuer_key, hashes.SHA256())
    )
    return key, cert


def _sign_content(key: rsa.RSAPrivateKey, content: bytes) -> bytes:
    return key.sign(content, padding.PKCS1v15(), hashes.SHA256())


def _build_crl(
    issuer_key: rsa.RSAPrivateKey,
    issuer_cert: c_x509.Certificate,
    revoked_serials: list[int],
):
    builder = (
        c_x509.CertificateRevocationListBuilder()
        .issuer_name(issuer_cert.subject)
        .last_update(datetime.now(timezone.utc) - timedelta(hours=1))
        .next_update(datetime.now(timezone.utc) + timedelta(days=30))
    )
    for serial in revoked_serials:
        revoked = (
            c_x509.RevokedCertificateBuilder()
            .serial_number(serial)
            .revocation_date(datetime.now(timezone.utc) - timedelta(hours=1))
            .build()
        )
        builder = builder.add_revoked_certificate(revoked)
    return builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())


class TestValidityPeriod(unittest.TestCase):
    """有効期間が valid に反映されることを検証."""

    def test_within_period_is_valid(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert)
        content = b"image-bytes"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(content, p7s)
        self.assertTrue(result["signature_valid"])
        self.assertTrue(result["validity_period_ok"])
        self.assertTrue(result["valid"])

    def test_expired_cert_makes_invalid(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        # 過去で完結している有効期間
        past_nvb = datetime.now(timezone.utc) - timedelta(days=10)
        past_nva = datetime.now(timezone.utc) - timedelta(days=1)
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert, nvb=past_nvb, nva=past_nva)
        content = b"image-bytes"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(content, p7s)
        # 署名値自体は正しい
        self.assertTrue(result["signature_valid"])
        # ただし有効期間外なので valid=False
        self.assertFalse(result["validity_period_ok"])
        self.assertFalse(result["valid"])

    def test_check_validity_period_disabled(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        past_nva = datetime.now(timezone.utc) - timedelta(days=1)
        past_nvb = datetime.now(timezone.utc) - timedelta(days=10)
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert, nvb=past_nvb, nva=past_nva)
        content = b"x"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        # 有効期間チェックをオフにすれば valid=True (署名値が正しいので)
        result = verify_signed_image(content, p7s, check_validity_period=False)
        self.assertTrue(result["valid"])


class TestChainVerification(unittest.TestCase):
    """trust_anchors を渡したチェーン検証."""

    def test_chain_verified_with_trust_anchor(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert)
        content = b"hello"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(
            content, p7s,
            trust_anchors=[ca_cert.public_bytes(serialization.Encoding.DER)],
        )
        self.assertTrue(result["chain_verified"])
        self.assertIsNone(result["chain_error"])
        self.assertTrue(result["valid"])

    def test_chain_fails_with_unrelated_trust_anchor(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        other_key, other_ca = _build_self_signed("Other CA")
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert)
        content = b"hello"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(
            content, p7s,
            trust_anchors=[other_ca.public_bytes(serialization.Encoding.DER)],
        )
        self.assertFalse(result["chain_verified"])
        self.assertIsNotNone(result["chain_error"])
        self.assertFalse(result["valid"])

    def test_chain_with_intermediate(self):
        # ルートCA → 中間CA → 葉
        root_key, root_cert = _build_self_signed("Root CA")
        inter_key, inter_cert = _build_leaf("Intermediate CA", root_key, root_cert)
        # 中間CAも CA フラグが立っている必要がある厳密PKIXは省略 (本実装は CA フラグ未検査)
        leaf_key, leaf_cert = _build_leaf("Signer", inter_key, inter_cert)
        content = b"hello"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(
            content, p7s,
            trust_anchors=[root_cert.public_bytes(serialization.Encoding.DER)],
            intermediate_certs=[inter_cert.public_bytes(serialization.Encoding.DER)],
        )
        self.assertTrue(result["chain_verified"], msg=result.get("chain_error"))
        self.assertTrue(result["valid"])

    def test_no_trust_anchors_keeps_chain_unchecked(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert)
        content = b"hello"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(content, p7s)
        # trust_anchors 未指定 → chain_verified=None で valid に影響しない
        self.assertIsNone(result["chain_verified"])
        self.assertTrue(result["valid"])


class TestRevocation(unittest.TestCase):
    """CRL に基づく失効確認."""

    def test_revoked_serial_makes_invalid(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert)
        # 葉のシリアル番号を含む CRL を作成
        crl = _build_crl(ca_key, ca_cert, [leaf_cert.serial_number])
        content = b"hello"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(
            content, p7s,
            trust_anchors=[ca_cert.public_bytes(serialization.Encoding.DER)],
            crls=[crl.public_bytes(serialization.Encoding.DER)],
        )
        self.assertEqual(result["revocation_status"], "revoked")
        self.assertFalse(result["valid"])

    def test_non_revoked_serial_is_good(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert)
        # 別シリアルだけを失効登録したCRL
        crl = _build_crl(ca_key, ca_cert, [leaf_cert.serial_number + 1])
        content = b"hello"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(
            content, p7s,
            trust_anchors=[ca_cert.public_bytes(serialization.Encoding.DER)],
            crls=[crl.public_bytes(serialization.Encoding.DER)],
        )
        self.assertEqual(result["revocation_status"], "good")
        self.assertTrue(result["valid"])

    def test_no_crls_keeps_status_not_checked(self):
        ca_key, ca_cert = _build_self_signed("Test CA")
        leaf_key, leaf_cert = _build_leaf("Signer", ca_key, ca_cert)
        content = b"hello"
        sig = _sign_content(leaf_key, content)
        p7s = build_p7s(signature=sig, cert_der=leaf_cert.public_bytes(serialization.Encoding.DER))

        result = verify_signed_image(content, p7s)
        self.assertEqual(result["revocation_status"], "not_checked")


if __name__ == "__main__":
    unittest.main()
