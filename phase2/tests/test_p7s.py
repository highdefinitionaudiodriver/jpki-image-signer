"""
phase2.tests.test_p7s: PKCS#7 分離署名の生成/検証ユニットテスト (カード非依存).

戦略:
  - cryptography で一時的なRSA-2048鍵 + 自己署名X.509(DER) を生成
  - その秘密鍵で b"test123" を直接署名し「ICカードが返す生RSA署名値」をシミュレート
  - build_p7s で p7s を構築
  - verify_p7s_against_data で検証 → True
  - データを改変して検証 → False (改ざん検知)
  - その他: 証明書パディング除去、verify ラッパー、補助関数

実行:
  python -m unittest phase2.tests.test_p7s -v
  または
  python phase2/tests/test_p7s.py
"""
from __future__ import annotations

import sys
import unittest
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

# プロジェクトルートをsys.pathに追加(直接実行時のため)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cryptography import x509 as c_x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

from phase2.crypto.p7s import (
    build_p7s,
    verify_p7s_against_data,
    extract_signer_cert_der,
    P7sVerificationError,
)
from phase2.crypto.der_utils import actual_der_length, trim_der
from phase2.crypto.verify import verify_signed_image


# ==============================================================
# 共通フィクスチャ
# ==============================================================

class _MockJpkiCard:
    """
    JPKIカードのシミュレータ. 秘密鍵を持ち、DigestInfo→署名 を行う.

    Args:
        key_size: RSA鍵長 (デフォルト 2048)
        subject_cn: Subject CN に格納する文字列(JPKIでは識別符号)。
                    デフォルト "Test JPKI Mock"
        san_kanji_name: SAN内 DirectoryName に CN として格納する漢字氏名。
                    None なら SAN を含めない(従来動作)。
                    指定すると JPKI仕様風に SAN→DirectoryName(CN=氏名) を含む証明書になる。
    """

    def __init__(
        self,
        key_size: int = 2048,
        *,
        subject_cn: str = "Test JPKI Mock",
        san_kanji_name: str | None = None,           # SAN内 DirectoryName.CN
        san_jpki_kanji_name: str | None = None,      # SAN内 OtherName (JPKI規格)
    ):
        self.subject_cn = subject_cn
        self.san_kanji_name = san_kanji_name
        self.san_jpki_kanji_name = san_jpki_kanji_name

        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
        )
        subject = issuer = c_x509.Name([
            c_x509.NameAttribute(NameOID.COMMON_NAME, subject_cn),
            c_x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Phase2 Tests"),
            c_x509.NameAttribute(NameOID.COUNTRY_NAME, "JP"),
        ])
        builder = (
            c_x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(self.private_key.public_key())
            .serial_number(c_x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365 * 5))
        )

        # ---- SAN を組み立て(必要なら) ----
        san_entries: list = []

        if san_jpki_kanji_name is not None:
            # JPKI実機構造: SAN内 OtherName(OID=1.2.392.200149.8.5.5.1)
            # value は ASN.1 UTF8String でラップ
            from asn1crypto.core import UTF8String
            from cryptography.x509 import ObjectIdentifier
            other = c_x509.OtherName(
                type_id=ObjectIdentifier("1.2.392.200149.8.5.5.1"),
                value=UTF8String(san_jpki_kanji_name).dump(),
            )
            san_entries.append(other)

        if san_kanji_name is not None:
            # 旧実装互換: SAN内 DirectoryName(CN=氏名)
            san_dn = c_x509.Name([
                c_x509.NameAttribute(NameOID.COMMON_NAME, san_kanji_name),
            ])
            san_entries.append(c_x509.DirectoryName(san_dn))

        if san_entries:
            san_ext = c_x509.SubjectAlternativeName(san_entries)
            builder = builder.add_extension(san_ext, critical=False)

        self.cert = builder.sign(self.private_key, hashes.SHA256())
        self.cert_der = self.cert.public_bytes(serialization.Encoding.DER)

    def sign_jpki_style(self, content: bytes) -> bytes:
        """
        JPKIカードのCOMPUTE DIGITAL SIGNATUREをシミュレート.

        実カードの動作:
          入力 = DigestInfo(SHA-256(content)) (51B)
          出力 = RSASSA-PKCS1-v1_5 署名 (256B)

        cryptography の RSAPrivateKey.sign(content, PKCS1v15, SHA256) は
        内部で「SHA-256(content) → DigestInfo構築 → PKCS#1 v1.5 → RSA暗号化」
        を行うため、JPKIカードと完全に等価な出力が得られる。
        """
        return self.private_key.sign(
            content,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

    def cert_with_padding(self, padding_size: int = 100, fill: int = 0xFF) -> bytes:
        """EF領域のような末尾パディング付き証明書を返す(trim_der テスト用)."""
        return self.cert_der + bytes([fill] * padding_size)


# ==============================================================
# テストケース
# ==============================================================

class TestDerUtils(unittest.TestCase):
    """ASN.1 DER 長さ算出 / トリムのテスト."""

    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def test_actual_der_length_pure(self):
        """パディングなしDERで正しい全長を返す."""
        n = actual_der_length(self.card.cert_der)
        self.assertEqual(n, len(self.card.cert_der))

    def test_actual_der_length_with_padding(self):
        """パディングありでも実DER長を正しく算出."""
        padded = self.card.cert_with_padding(padding_size=200, fill=0x00)
        n = actual_der_length(padded)
        self.assertEqual(n, len(self.card.cert_der))
        self.assertLess(n, len(padded))

    def test_actual_der_length_short_form(self):
        """短形式(長さ < 128)の DER もOK."""
        # 短い SEQUENCE: 30 0A <10B>
        d = bytes([0x30, 0x0A]) + b"0123456789" + b"\xff" * 50
        self.assertEqual(actual_der_length(d), 12)

    def test_actual_der_length_long_form_3byte(self):
        """0x83 形式(3バイト長)も解析可能."""
        # 30 83 00 00 05 <5B>: 全長 9 = 5(header) + 5(content)
        # 注: DERでは 0x83 00 00 05 は不正(最小エンコーディング違反)だが
        #     パーサとしては許容する
        d = bytes([0x30, 0x83, 0x00, 0x00, 0x05]) + b"abcde"
        self.assertEqual(actual_der_length(d), 10)

    def test_actual_der_length_invalid_first_byte(self):
        with self.assertRaises(ValueError):
            actual_der_length(b"\x31\x05abcde")

    def test_actual_der_length_too_short(self):
        with self.assertRaises(ValueError):
            actual_der_length(b"\x30")

    def test_trim_der(self):
        padded = self.card.cert_with_padding(padding_size=300)
        trimmed = trim_der(padded)
        self.assertEqual(trimmed, self.card.cert_der)


class TestBuildP7s(unittest.TestCase):
    """build_p7s の構造的検証 (asn1crypto側のパースで再ロード可能か)."""

    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def test_build_p7s_basic(self):
        content = b"hello world"
        sig = self.card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)

        self.assertIsInstance(p7s, bytes)
        self.assertGreater(len(p7s), 256 + 100)  # 署名値 + 構造的オーバーヘッド

    def test_build_p7s_starts_with_sequence(self):
        """p7s も DER SEQUENCE で始まる."""
        sig = self.card.sign_jpki_style(b"abc")
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)
        self.assertEqual(p7s[0], 0x30)

    def test_build_p7s_with_padded_cert(self):
        """EFパディング付き証明書を渡しても OK (内部でtrim)."""
        sig = self.card.sign_jpki_style(b"abc")
        padded_cert = self.card.cert_with_padding(padding_size=500)
        p7s = build_p7s(signature=sig, cert_der=padded_cert)
        # 検証も通ること
        self.assertTrue(verify_p7s_against_data(p7s, b"abc"))

    def test_build_p7s_unsupported_digest(self):
        sig = b"\x00" * 256
        with self.assertRaises(ValueError):
            build_p7s(signature=sig, cert_der=self.card.cert_der,
                      digest_algorithm="sha512")


class TestVerifyP7s(unittest.TestCase):
    """検証の正常系・改ざん検知 (★ 本タスクの核心)."""

    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def test_verify_valid_signature(self):
        """正しい署名は True を返す."""
        content = b"test123"
        sig = self.card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)

        self.assertTrue(verify_p7s_against_data(p7s, content))

    def test_verify_tampered_one_bit_flip(self):
        """1ビット改変 → False (改ざん検知)."""
        content = bytearray(b"test123" * 100)  # 700B
        sig = self.card.sign_jpki_style(bytes(content))
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)

        # 中央付近の1バイトの最下位ビットを反転
        tampered = bytearray(content)
        tampered[len(tampered) // 2] ^= 0x01

        self.assertFalse(verify_p7s_against_data(p7s, bytes(tampered)))

    def test_verify_tampered_capitalize(self):
        """文字を変えても改ざん検知される."""
        content = b"test123"
        sig = self.card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)

        self.assertFalse(verify_p7s_against_data(p7s, b"Test123"))
        self.assertFalse(verify_p7s_against_data(p7s, b"test1234"))
        self.assertFalse(verify_p7s_against_data(p7s, b"test12"))
        self.assertFalse(verify_p7s_against_data(p7s, b""))

    def test_verify_different_content_with_same_signature(self):
        """別データの署名で別データを検証 → False."""
        sig_for_A = self.card.sign_jpki_style(b"DATA_A")
        p7s = build_p7s(signature=sig_for_A, cert_der=self.card.cert_der)

        self.assertTrue(verify_p7s_against_data(p7s, b"DATA_A"))
        self.assertFalse(verify_p7s_against_data(p7s, b"DATA_B"))

    def test_verify_with_image_like_data(self):
        """実画像を模した1MB相当のランダム風データでも検証成功."""
        import os
        content = os.urandom(1024 * 1024)  # 1MB
        sig = self.card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)
        self.assertTrue(verify_p7s_against_data(p7s, content))

    def test_verify_invalid_p7s_raises(self):
        """壊れた p7s は P7sVerificationError."""
        with self.assertRaises(P7sVerificationError):
            verify_p7s_against_data(b"not a valid asn1", b"any")

    def test_verify_p7s_with_wrong_cert_pair(self):
        """別の鍵ペアの証明書 → 検証 False."""
        other_card = _MockJpkiCard()
        # 自分の鍵で署名するが、他人のcertでp7sを構築
        sig = self.card.sign_jpki_style(b"hello")
        p7s = build_p7s(signature=sig, cert_der=other_card.cert_der)
        # 他人の証明書では検証通らない(鍵ペア不一致)
        self.assertFalse(verify_p7s_against_data(p7s, b"hello"))


class TestVerifyHighLevel(unittest.TestCase):
    """verify.py の高レベルラッパー."""

    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def test_verify_signed_image_valid(self):
        content = b"sample image bytes"
        sig = self.card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)

        result = verify_signed_image(content, p7s)
        self.assertTrue(result["valid"])
        # SAN無しのため signer_name は Subject CN にフォールバック
        self.assertEqual(result["signer_name"], "Test JPKI Mock")
        self.assertEqual(result["signer_name_source"], "subject_cn")
        # 後方互換: signer_cn も Subject CN
        self.assertEqual(result["signer_cn"], "Test JPKI Mock")
        self.assertIsNone(result["error"])
        self.assertIsNotNone(result["not_valid_before"])
        self.assertIsNotNone(result["not_valid_after"])

    def test_verify_signed_image_tampered(self):
        content = b"original"
        sig = self.card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)

        result = verify_signed_image(b"tampered", p7s)
        self.assertFalse(result["valid"])
        self.assertEqual(result["signer_name"], "Test JPKI Mock")
        self.assertEqual(result["signer_cn"], "Test JPKI Mock")
        self.assertIsNone(result["error"])  # 構造的にはOK、署名値だけ不一致

    def test_verify_signed_image_broken_p7s(self):
        result = verify_signed_image(b"any", b"\x00\x01\x02")
        self.assertFalse(result["valid"])
        self.assertIsNotNone(result["error"])


# ==============================================================
# ★Phase 3 / Step 1: SAN 氏名抽出のテスト
# ==============================================================

class TestExtractSignerName(unittest.TestCase):
    """SAN→DirectoryName→CN 抽出ロジックのテスト."""

    def test_extract_from_san_directory_name(self):
        """JPKI想定: SAN内 DirectoryName に CN=漢字氏名 → SAN由来で抽出される."""
        from cryptography import x509 as c_x509
        from phase2.crypto.verify import extract_signer_name

        card = _MockJpkiCard(
            subject_cn="99999999000000000000FAKETEST",  # 識別符号
            san_kanji_name="山田太郎",                    # 漢字氏名
        )
        cert = c_x509.load_der_x509_certificate(card.cert_der)

        name, source = extract_signer_name(cert)
        self.assertEqual(name, "山田太郎")
        self.assertEqual(source, "san_directory_name")

    def test_fallback_to_subject_cn_when_no_san(self):
        """SAN拡張が無い → Subject CN にフォールバック."""
        from cryptography import x509 as c_x509
        from phase2.crypto.verify import extract_signer_name

        card = _MockJpkiCard(subject_cn="Some-Identifier-12345")  # SAN無し
        cert = c_x509.load_der_x509_certificate(card.cert_der)

        name, source = extract_signer_name(cert)
        self.assertEqual(name, "Some-Identifier-12345")
        self.assertEqual(source, "subject_cn")

    def test_kanji_name_with_special_chars(self):
        """濁点・半角等を含む氏名でも正しく抽出される."""
        from cryptography import x509 as c_x509
        from phase2.crypto.verify import extract_signer_name

        for kanji in ["佐藤花子", "ガブリエル太郎", "李 雷"]:
            card = _MockJpkiCard(san_kanji_name=kanji)
            cert = c_x509.load_der_x509_certificate(card.cert_der)
            name, source = extract_signer_name(cert)
            self.assertEqual(name, kanji)
            self.assertEqual(source, "san_directory_name")

    def test_full_pipeline_signer_name_via_verify_signed_image(self):
        """
        end-to-end: SAN付き証明書で署名→.p7s→verify_signed_image で
                    signer_name に漢字氏名、signer_cn に識別符号が入る。
        """
        card = _MockJpkiCard(
            subject_cn="99999999000000000000FAKETEST",
            san_kanji_name="鈴木一郎",
        )
        content = b"image-bytes-for-pipeline-test"
        sig = card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=card.cert_der)

        result = verify_signed_image(content, p7s)
        self.assertTrue(result["valid"])
        self.assertEqual(result["signer_name"], "鈴木一郎")
        self.assertEqual(result["signer_name_source"], "san_directory_name")
        # 識別符号は signer_cn に残る(参考情報として)
        self.assertEqual(result["signer_cn"], "99999999000000000000FAKETEST")

    def test_full_pipeline_no_san_falls_back(self):
        """SAN無しの cert では signer_name = signer_cn になる."""
        card = _MockJpkiCard(subject_cn="OnlyCNHere")
        content = b"another image"
        sig = card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=card.cert_der)

        result = verify_signed_image(content, p7s)
        self.assertTrue(result["valid"])
        self.assertEqual(result["signer_name"], "OnlyCNHere")
        self.assertEqual(result["signer_cn"], "OnlyCNHere")
        self.assertEqual(result["signer_name_source"], "subject_cn")


# ==============================================================
# ★Phase 3 / Step 1 (v2): JPKI OtherName SAN 抽出のテスト
# ==============================================================

class TestExtractFromJpkiOtherName(unittest.TestCase):
    """実機 JPKI 仕様(OID 1.2.392.200149.8.5.5.1) からの氏名抽出."""

    def test_extract_from_jpki_other_name(self):
        """SAN内 OtherName(JPKI 氏名OID) からUTF-8で漢字氏名を抽出."""
        from cryptography import x509 as c_x509
        from phase2.crypto.verify import extract_signer_name

        card = _MockJpkiCard(
            subject_cn="99999999000000000000FAKETEST",
            san_jpki_kanji_name="山田 太郎",
        )
        cert = c_x509.load_der_x509_certificate(card.cert_der)
        name, source = extract_signer_name(cert)
        self.assertEqual(name, "山田 太郎")
        self.assertEqual(source, "san_jpki_other_name")

    def test_jpki_other_name_priority_over_directory_name(self):
        """JPKI OtherName と DirectoryName の両方がある場合、OtherNameが優先."""
        from cryptography import x509 as c_x509
        from phase2.crypto.verify import extract_signer_name

        card = _MockJpkiCard(
            subject_cn="ID-12345",
            san_jpki_kanji_name="優先される名前",
            san_kanji_name="無視される名前",
        )
        cert = c_x509.load_der_x509_certificate(card.cert_der)
        name, source = extract_signer_name(cert)
        self.assertEqual(name, "優先される名前")
        self.assertEqual(source, "san_jpki_other_name")

    def test_directory_name_used_when_no_jpki_other_name(self):
        """JPKI OtherNameが無く DirectoryName.CN だけある場合は DirectoryName が使われる."""
        from cryptography import x509 as c_x509
        from phase2.crypto.verify import extract_signer_name

        card = _MockJpkiCard(
            subject_cn="ID-X",
            san_kanji_name="DirectoryName経由",
            # san_jpki_kanji_name は指定しない
        )
        cert = c_x509.load_der_x509_certificate(card.cert_der)
        name, source = extract_signer_name(cert)
        self.assertEqual(name, "DirectoryName経由")
        self.assertEqual(source, "san_directory_name")

    def test_full_pipeline_with_jpki_other_name(self):
        """end-to-end: JPKI OtherName 付き証明書 → verify_signed_image で漢字氏名."""
        kanji = "佐藤 花子"
        card = _MockJpkiCard(
            subject_cn="99999999000000000000FAKETEST",
            san_jpki_kanji_name=kanji,
        )
        content = b"image-via-jpki-other-name-pipeline"
        sig = card.sign_jpki_style(content)
        p7s = build_p7s(signature=sig, cert_der=card.cert_der)

        result = verify_signed_image(content, p7s)
        self.assertTrue(result["valid"])
        self.assertEqual(result["signer_name"], kanji)
        self.assertEqual(result["signer_name_source"], "san_jpki_other_name")
        self.assertEqual(result["signer_cn"], "99999999000000000000FAKETEST")

    def test_kanji_with_fullwidth_space(self):
        """JPKI実機の典型: 姓 + 全角空白 + 名 がそのまま抽出される."""
        from cryptography import x509 as c_x509
        from phase2.crypto.verify import extract_signer_name

        kanji = "山田　太郎"  # 全角空白(U+3000)
        card = _MockJpkiCard(san_jpki_kanji_name=kanji)
        cert = c_x509.load_der_x509_certificate(card.cert_der)
        name, source = extract_signer_name(cert)
        self.assertEqual(name, kanji)
        self.assertEqual(source, "san_jpki_other_name")


class TestExtractSignerCert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def test_extract_signer_cert_der(self):
        sig = self.card.sign_jpki_style(b"abc")
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)

        extracted = extract_signer_cert_der(p7s)
        self.assertEqual(extracted, self.card.cert_der)


# ==============================================================
# 直接実行用
# ==============================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
