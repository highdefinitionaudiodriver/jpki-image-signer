"""
Phase 1 / Step 4: ダミー署名の数学的妥当性検証

目的:
  test_03_sign.py が生成した signature_dummy.bin と sign_cert.der を用いて、
  「signature_dummy.bin が SHA-256(b'test123') に対する JPKI署名鍵 による
   RSASSA-PKCS1-v1_5 署名」であることを cryptography ライブラリで
   暗号学的に検証する。

検証成功が示すこと:
  - DigestInfo の構築(プレフィックス + SHA-256ダイジェスト)が正しかった
  - カードが RSASSA-PKCS1-v1_5 with SHA-256 を仕様通り実行している
  - 署名値 と 証明書内公開鍵 がペアとして整合している
  - Phase 2 で実装する p7s 生成 / 検証ロジックの土台が固まる

注意:
  sign_cert.der は氏名・住所等の個人情報を含むが、本スクリプトでは
  Subject / Issuer / SAN 等の本文は画面に出力しない設計とする。
  証明書バージョン・シリアル・有効期間・公開鍵長 のみ表示する。

DER長の動的算出:
  EF領域確保サイズ (例: 3808B) には 0xFF/0x00 のパディングが含まれており、
  そのまま load_der_x509_certificate に渡すと
  「Trailing data after sequence」相当のエラーで失敗する。
  本スクリプトは ASN.1 SEQUENCE のヘッダから実DER長を解析して
  正確に切り出してからパースする。
"""
import sys
import hashlib
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.exceptions import InvalidSignature
except ImportError:
    print("ERROR: cryptography がインストールされていません。", file=sys.stderr)
    print("       py -3.12 -m pip install cryptography", file=sys.stderr)
    sys.exit(1)


# ============================================================
# 設定
# ============================================================
CERT_PATH = "sign_cert.der"
SIG_PATH  = "signature_dummy.bin"
DUMMY_DATA = b"test123"   # test_03 と同じダミーデータ


# ============================================================
# ASN.1 DER 長さ解析
# ============================================================
def actual_der_length(data: bytes) -> int:
    """
    ASN.1 SEQUENCE (DER) の先頭バイトから「ヘッダ + 内容」の総バイト数を算出する。

    DER の長さフィールドは:
      - 短形式: 第2バイトが 0x00〜0x7F の場合、そのバイトが内容長
      - 長形式: 第2バイトが 0x81〜0x84 の場合、後続 1〜4 バイトが内容長
                (0x82 = 後続2バイトが内容長、典型的な X.509証明書はこれ)

    Args:
        data: 先頭が 0x30 (SEQUENCE) の DER バイト列

    Returns:
        int: ヘッダ含む総 DER バイト数

    Raises:
        ValueError: DER として不正な構造
    """
    if len(data) < 2:
        raise ValueError("データが短すぎます (2バイト未満)")
    if data[0] != 0x30:
        raise ValueError(f"先頭バイトが 0x30 (SEQUENCE) ではありません: 0x{data[0]:02x}")

    lb = data[1]
    if lb < 0x80:
        # 短形式: 内容長 = lb
        return 2 + lb

    # 長形式
    n = lb & 0x7F
    if n == 0:
        raise ValueError("不定長 (BER) は DER 仕様では禁止されています")
    if n > 4:
        raise ValueError(f"想定外の長さフィールド符号: 0x{lb:02x}")
    if len(data) < 2 + n:
        raise ValueError(f"長さフィールド({n}B)がデータ範囲外")

    length = 0
    for i in range(n):
        length = (length << 8) | data[2 + i]

    return 2 + n + length


# ============================================================
# 互換ヘルパ: 有効期間プロパティ
# ============================================================
def _validity(cert):
    """cryptography 42以降は *_utc プロパティ、古いバージョンは旧プロパティ."""
    try:
        return cert.not_valid_before_utc, cert.not_valid_after_utc
    except AttributeError:
        return cert.not_valid_before, cert.not_valid_after


# ============================================================
# main
# ============================================================
def main():
    print("=" * 60)
    print(" Phase 1 / Step 4 : ダミー署名の数学的妥当性検証")
    print("=" * 60)

    # ---- ファイル存在確認 ----
    cert_path = Path(CERT_PATH)
    sig_path  = Path(SIG_PATH)

    if not cert_path.exists():
        print(f"ERROR: {CERT_PATH} が見つかりません。")
        print("       先に test_03_sign.py を実行してください。")
        sys.exit(1)
    if not sig_path.exists():
        print(f"ERROR: {SIG_PATH} が見つかりません。")
        print("       先に test_03_sign.py を実行してください。")
        sys.exit(1)

    cert_raw = cert_path.read_bytes()
    signature = sig_path.read_bytes()

    print(f"\n[1] ファイル読み込み")
    print(f"  {CERT_PATH}: {len(cert_raw)} bytes (EF確保サイズ含む)")
    print(f"  {SIG_PATH}: {len(signature)} bytes")

    if len(signature) != 256:
        print(f"  [WARN] 署名値長が 256B ではありません: {len(signature)}B")

    # ---- DER 実サイズ算出 + トリム ----
    print(f"\n[2] 証明書DERの実サイズ算出 + パディング切り捨て")
    try:
        actual_len = actual_der_length(cert_raw)
    except ValueError as e:
        print(f"ERROR: DERヘッダ解析失敗: {e}")
        sys.exit(2)

    padding_size = len(cert_raw) - actual_len
    print(f"  ASN.1ヘッダから算出した実DER長: {actual_len} bytes")
    print(f"  パディング(切り捨て対象): {padding_size} bytes")

    if padding_size < 0:
        print(f"ERROR: 算出した実DER長 ({actual_len}) が ファイルサイズ ({len(cert_raw)}) を超えています。")
        sys.exit(2)

    cert_der = cert_raw[:actual_len]
    print(f"  トリム後サイズ: {len(cert_der)} bytes")

    # ---- 証明書パース ----
    print(f"\n[3] X.509証明書のパース")
    try:
        cert = x509.load_der_x509_certificate(cert_der)
    except Exception as e:
        print(f"ERROR: 証明書のパースに失敗: {type(e).__name__}: {e}")
        sys.exit(2)

    # 個人情報を出さない構造情報のみ表示
    nvb, nva = _validity(cert)
    print(f"  バージョン: {cert.version.name}")
    print(f"  シリアル番号: 0x{cert.serial_number:x}")
    print(f"  有効期間: {nvb.isoformat()} 〜 {nva.isoformat()}")
    print(f"  署名アルゴリズム: {cert.signature_algorithm_oid._name}")
    print(f"  Subject / Issuer / SAN: (個人情報を含むため画面表示は省略)")

    # ---- 公開鍵抽出 ----
    print(f"\n[4] 公開鍵抽出")
    public_key = cert.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        print(f"ERROR: 公開鍵がRSAではありません: {type(public_key).__name__}")
        sys.exit(2)
    print(f"  鍵種別: RSA")
    print(f"  鍵長:   {public_key.key_size} bit")
    if public_key.key_size != 2048:
        print(f"  [WARN] JPKI仕様では2048bit。実際: {public_key.key_size}")
    pub_numbers = public_key.public_numbers()
    print(f"  公開指数 e: {pub_numbers.e}")

    # ---- 検証対象データ ----
    print(f"\n[5] 検証対象データ")
    print(f"  原文: {DUMMY_DATA!r}")
    sha256 = hashlib.sha256(DUMMY_DATA).digest()
    print(f"  SHA-256: {sha256.hex()}")
    print(f"  署名値先頭16B: {signature[:16].hex()}")

    # ---- 署名検証 ----
    print(f"\n[6] RSASSA-PKCS1-v1_5 with SHA-256 で署名検証")
    print(f"     検証手順 (cryptography が内部で実施):")
    print(f"       1. SHA-256(原文) を計算")
    print(f"       2. DigestInfo(SHA-256, ハッシュ) を構築")
    print(f"       3. PKCS#1 v1.5 パディング を構築")
    print(f"       4. RSA公開鍵で署名値を復号 (sig^e mod n)")
    print(f"       5. 復号結果と 期待値 を定数時間比較")

    try:
        public_key.verify(
            signature,
            DUMMY_DATA,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        print("\n[FAIL] 署名が無効です")
        print("  考えられる原因:")
        print("    - DigestInfoのプレフィックスが誤っている")
        print("    - 署名値とこの証明書の鍵がペアでない")
        print("    - signature_dummy.bin / sign_cert.der が test_03 実行時のものと不一致")
        sys.exit(3)
    except Exception as e:
        print(f"\n[ERROR] 検証中に例外: {type(e).__name__}: {e}")
        sys.exit(3)

    # ---- 成功 ----
    print(f"\n[OK] ✅ 署名は有効です")
    print(f"  証明された事実:")
    print(f"    - SHA-256(b'test123') に対する RSA署名 が正しく生成されている")
    print(f"    - 署名は sign_cert.der 内の公開鍵に対応する秘密鍵 (=JPKI署名鍵) で生成された")
    print(f"    - DigestInfo 構築 / APDU送信 / カード応答 / 結果保存 すべて仕様通り")

    print(f"\n" + "=" * 60)
    print(f" Phase 1 完了 - 全コンポーネントの数学的妥当性が証明されました")
    print(f"=" * 60)
    print(f"\n[次のステップ]")
    print(f"  - 設計書 (design_document.xlsx) 更新")
    print(f"  - Phase 2 着手 (PKCS#7 分離署名 + .jpkiimg コンテナ)")


if __name__ == "__main__":
    main()
