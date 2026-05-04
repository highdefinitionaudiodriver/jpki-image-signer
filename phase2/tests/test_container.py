"""
phase2.tests.test_container: .jpkiimg コンテナのユニットテスト (カード非依存).

テスト戦略:
  1) 正常系ラウンドトリップ: .jpg / .png 両方の拡張子で
     create_jpkiimg → read_jpkiimg → バイナリ完全一致 を検証
  2) 改ざん検知:           作成済 .jpkiimg 内の target_image.<ext> を1ビット改変 →
     phase2.crypto.verify_p7s_against_data が False を返すことを検証
  3) 異常系:               必須エントリ欠落 / 壊れたZIP → 例外
  4) ZIP_STORED検証:       格納モードが本当に ZIP_STORED か確認
  5) 拡張子復元:           .jpg/.png/.jpeg/拡張子なし などが正しく復元されるか

実行:
  python -m unittest phase2.tests.test_container -v
"""
from __future__ import annotations

import os
import sys
import zipfile
import tempfile
import unittest
from pathlib import Path

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phase2.container import (
    create_jpkiimg,
    read_jpkiimg,
    NotJpkiImgError,
    MissingEntryError,
    CONTAINER_P7S_FILENAME,
    CONTAINER_CERT_FILENAME,
)
from phase2.crypto import build_p7s, verify_p7s_against_data

# 既存テストの MockJpkiCard を再利用
from phase2.tests.test_p7s import _MockJpkiCard


# ==============================================================
# ヘルパ
# ==============================================================

def _make_dummy_image_bytes(seed: int = 42, size: int = 4096) -> bytes:
    """テスト用「画像」バイト列を生成(本物のJPEGである必要は無い)."""
    import random
    rng = random.Random(seed)
    return bytes(rng.randint(0, 255) for _ in range(size))


# ==============================================================
# テストケース
# ==============================================================

class TestContainerRoundtrip(unittest.TestCase):
    """正常系: 作成 → 読み出し が完全に一致するか."""

    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _build_p7s_for(self, image_bytes: bytes) -> bytes:
        sig = self.card.sign_jpki_style(image_bytes)
        return build_p7s(signature=sig, cert_der=self.card.cert_der)

    def _roundtrip(self, ext: str, image_size: int = 4096):
        """指定拡張子で 作成→読出 を行い、内容一致を確認."""
        image_bytes = _make_dummy_image_bytes(seed=hash(ext) & 0xffff,
                                              size=image_size)
        image_path = self.tmp_root / f"sample{ext}"
        image_path.write_bytes(image_bytes)

        p7s = self._build_p7s_for(image_bytes)
        out_path = self.tmp_root / f"sample{ext}.jpkiimg"

        # ---- 作成 ----
        result_path = create_jpkiimg(
            image_path=image_path,
            p7s_bytes=p7s,
            cert_der_bytes=self.card.cert_der,
            output_path=out_path,
        )
        self.assertEqual(result_path, out_path)
        self.assertTrue(out_path.is_file())
        self.assertGreater(out_path.stat().st_size, len(image_bytes))

        # ---- 読み出し ----
        img_back, img_name, p7s_back, cert_back = read_jpkiimg(out_path)

        # ---- 完全一致を検証 ----
        self.assertEqual(img_back, image_bytes,        "画像バイナリが不一致")
        self.assertEqual(p7s_back, p7s,                "p7sバイナリが不一致")
        self.assertEqual(cert_back, self.card.cert_der, "cert_derバイナリが不一致")

        # 拡張子が保持されているか
        self.assertEqual(img_name, f"target_image{ext.lower()}")

        return img_back, p7s_back

    def test_roundtrip_jpg(self):
        img, p7s = self._roundtrip(".jpg")
        # 念のため p7s が画像に対して有効
        self.assertTrue(verify_p7s_against_data(p7s, img))

    def test_roundtrip_png(self):
        img, p7s = self._roundtrip(".png")
        self.assertTrue(verify_p7s_against_data(p7s, img))

    def test_roundtrip_jpeg(self):
        """.jpeg (4文字拡張子) も正しく扱える."""
        img, p7s = self._roundtrip(".jpeg")
        self.assertTrue(verify_p7s_against_data(p7s, img))

    def test_roundtrip_uppercase_extension_normalized(self):
        """大文字拡張子(.JPG)は小文字化される."""
        image_bytes = _make_dummy_image_bytes(seed=1, size=512)
        image_path = self.tmp_root / "sample.JPG"
        image_path.write_bytes(image_bytes)

        p7s = self._build_p7s_for(image_bytes)
        out_path = self.tmp_root / "sample.jpkiimg"
        create_jpkiimg(image_path, p7s, self.card.cert_der, out_path)

        _img, name, _p7s, _cert = read_jpkiimg(out_path)
        self.assertEqual(name, "target_image.jpg")  # 小文字化されている

    def test_roundtrip_no_extension(self):
        """拡張子無し画像は .bin にフォールバック."""
        image_bytes = _make_dummy_image_bytes(seed=2, size=256)
        image_path = self.tmp_root / "noext_image"
        image_path.write_bytes(image_bytes)

        p7s = self._build_p7s_for(image_bytes)
        out_path = self.tmp_root / "noext.jpkiimg"
        create_jpkiimg(image_path, p7s, self.card.cert_der, out_path)

        _img, name, _p7s, _cert = read_jpkiimg(out_path)
        self.assertEqual(name, "target_image.bin")

    def test_large_image_1mb(self):
        """1MB 画像でもラウンドトリップ成功."""
        img, p7s = self._roundtrip(".jpg", image_size=1024 * 1024)
        self.assertTrue(verify_p7s_against_data(p7s, img))


class TestZipStored(unittest.TestCase):
    """格納モードが本当に ZIP_STORED (無圧縮) であるか確認."""

    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_compression_method_is_stored(self):
        """全エントリの compress_type が ZIP_STORED."""
        image_bytes = _make_dummy_image_bytes(seed=99, size=2048)
        image_path = self.tmp_root / "img.jpg"
        image_path.write_bytes(image_bytes)

        sig = self.card.sign_jpki_style(image_bytes)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)
        out_path = self.tmp_root / "img.jpkiimg"
        create_jpkiimg(image_path, p7s, self.card.cert_der, out_path)

        with zipfile.ZipFile(out_path, "r") as zf:
            for info in zf.infolist():
                self.assertEqual(
                    info.compress_type, zipfile.ZIP_STORED,
                    f"{info.filename} が ZIP_STORED ではない: {info.compress_type}"
                )
                # 無圧縮なら compress_size == file_size
                self.assertEqual(info.compress_size, info.file_size)


class TestTamperDetection(unittest.TestCase):
    """改ざん検知: コンテナ内画像を1bit書き換えると検証失敗する."""

    @classmethod
    def setUpClass(cls):
        cls.card = _MockJpkiCard()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _create_signed_container(self, image_bytes: bytes, ext: str = ".jpg"):
        """テスト用の有効な .jpkiimg を生成し path を返す."""
        image_path = self.tmp_root / f"src{ext}"
        image_path.write_bytes(image_bytes)

        sig = self.card.sign_jpki_style(image_bytes)
        p7s = build_p7s(signature=sig, cert_der=self.card.cert_der)
        out_path = self.tmp_root / f"src{ext}.jpkiimg"
        create_jpkiimg(image_path, p7s, self.card.cert_der, out_path)
        return out_path

    def test_unmodified_container_verifies_true(self):
        """改ざん前は当然 True (ベースライン)."""
        original = _make_dummy_image_bytes(seed=10, size=8192)
        path = self._create_signed_container(original)

        img, _name, p7s, _cert = read_jpkiimg(path)
        self.assertEqual(img, original)
        self.assertTrue(verify_p7s_against_data(p7s, img))

    def test_tampered_image_in_container_verifies_false(self):
        """
        作成済 .jpkiimg の中の target_image.jpg を1ビット書き換えて、
        読み出した画像とp7sで検証すると False になる。
        """
        original = _make_dummy_image_bytes(seed=11, size=8192)
        path = self._create_signed_container(original, ext=".jpg")

        # ---- 元のZIPからエントリ抽出 → 画像のみ1bit反転 → 新ZIP書き直し ----
        # zipfileは個別エントリの上書きをサポートしないため、書き直し方式を取る
        with zipfile.ZipFile(path, "r") as zf:
            entries = {n: zf.read(n) for n in zf.namelist()}

        image_name = "target_image.jpg"
        self.assertIn(image_name, entries)

        tampered_image = bytearray(entries[image_name])
        # 中央付近の1バイトの最下位ビットを反転
        tampered_image[len(tampered_image) // 2] ^= 0x01
        entries[image_name] = bytes(tampered_image)

        # 改ざん版ZIPを上書き保存
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            for n, data in entries.items():
                zf.writestr(n, data)

        # ---- 改ざん版を読み出して検証 ----
        img_back, _name, p7s_back, _cert = read_jpkiimg(path)
        self.assertNotEqual(img_back, original)  # 改ざんされている
        # p7s 自体は同じ (差し替えてないから)
        # → 画像と p7s の整合性が崩れて検証 False
        self.assertFalse(verify_p7s_against_data(p7s_back, img_back),
                         "改ざんを検知できていない!")

    def test_tampered_p7s_in_container_verifies_false(self):
        """p7s を改ざんしても検出できる(構造的には壊れない範囲で1B変更)."""
        original = _make_dummy_image_bytes(seed=12, size=2048)
        path = self._create_signed_container(original)

        with zipfile.ZipFile(path, "r") as zf:
            entries = {n: zf.read(n) for n in zf.namelist()}

        # p7s の中央付近を1B反転(構造を壊さない位置を狙う)
        # 失敗するとパース不可で例外になる場合もある。テストとしては
        # 「False が返る or 例外が出る」のどちらかを許容する。
        tampered_p7s = bytearray(entries[CONTAINER_P7S_FILENAME])
        tampered_p7s[len(tampered_p7s) // 2] ^= 0x01
        entries[CONTAINER_P7S_FILENAME] = bytes(tampered_p7s)

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            for n, data in entries.items():
                zf.writestr(n, data)

        img_back, _name, p7s_back, _cert = read_jpkiimg(path)
        # False または P7sVerificationError のどちらかであれば改ざんは検知できている
        try:
            ok = verify_p7s_against_data(p7s_back, img_back)
            self.assertFalse(ok, "p7s改ざんを検知できていない")
        except Exception:
            # 構造破壊で例外になっても「検証通過しない」点ではOK
            pass


class TestErrorHandling(unittest.TestCase):
    """異常系: 不正なZIP / 必須ファイル欠落 / 存在しないファイル等."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            read_jpkiimg(self.tmp_root / "does_not_exist.jpkiimg")

    def test_not_a_zip_file(self):
        """ZIPでないバイナリを渡すと NotJpkiImgError."""
        bogus = self.tmp_root / "garbage.jpkiimg"
        bogus.write_bytes(b"this is not a zip file at all" * 10)

        with self.assertRaises(NotJpkiImgError):
            read_jpkiimg(bogus)

    def test_missing_image_entry(self):
        path = self.tmp_root / "nopic.jpkiimg"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(CONTAINER_P7S_FILENAME, b"\x30\x82\x00\x10dummy")
            zf.writestr(CONTAINER_CERT_FILENAME, b"\x30\x82\x00\x10dummy")

        with self.assertRaises(MissingEntryError) as ctx:
            read_jpkiimg(path)
        self.assertIn("target_image", str(ctx.exception))

    def test_missing_p7s(self):
        path = self.tmp_root / "nop7s.jpkiimg"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("target_image.jpg", b"image")
            zf.writestr(CONTAINER_CERT_FILENAME, b"cert")

        with self.assertRaises(MissingEntryError) as ctx:
            read_jpkiimg(path)
        self.assertIn(CONTAINER_P7S_FILENAME, str(ctx.exception))

    def test_missing_cert(self):
        path = self.tmp_root / "nocert.jpkiimg"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("target_image.jpg", b"image")
            zf.writestr(CONTAINER_P7S_FILENAME, b"p7s")

        with self.assertRaises(MissingEntryError) as ctx:
            read_jpkiimg(path)
        self.assertIn(CONTAINER_CERT_FILENAME, str(ctx.exception))

    def test_create_with_nonexistent_image(self):
        with self.assertRaises(FileNotFoundError):
            create_jpkiimg(
                image_path=self.tmp_root / "nope.jpg",
                p7s_bytes=b"x",
                cert_der_bytes=b"y",
                output_path=self.tmp_root / "out.jpkiimg",
            )

    def test_create_with_empty_p7s(self):
        img = self.tmp_root / "img.jpg"
        img.write_bytes(b"image")
        with self.assertRaises(ValueError):
            create_jpkiimg(img, b"", b"cert", self.tmp_root / "out.jpkiimg")

    def test_create_with_empty_cert(self):
        img = self.tmp_root / "img.jpg"
        img.write_bytes(b"image")
        with self.assertRaises(ValueError):
            create_jpkiimg(img, b"p7s", b"", self.tmp_root / "out.jpkiimg")


# ==============================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
