"""
診断ツール: .jpkiimg 内の署名用証明書の Subject DN / SAN 拡張を詳細ダンプする.

目的:
  Phase 3 / Step 1 で「漢字氏名は SAN内 DirectoryName の CN属性に
  格納される」と仮定したが、実機 cert で SAN→DirectoryName→CN の抽出が
  失敗している。実際の構造を可視化して extract_signer_name を修正する材料に
  する。

使い方:
  cd C:\\dev\\jpki-image-signer
  py -3.12 docs/inspect_cert_san.py docs/sample.jpg.jpkiimg

⚠️ 個人情報注意:
  出力には署名者の氏名・住所・生年月日等が含まれます。
  共有する場合は必ずマスキング(個人特定可能な値を ●●●●● 等に置換)
  してから貼ってください。
"""
from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートを sys.path に
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Windows console UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from cryptography import x509
from cryptography.x509.oid import ExtensionOID, NameOID

from phase2.container import read_jpkiimg
from phase2.crypto.der_utils import trim_der


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: py -3.12 docs/inspect_cert_san.py <path.jpkiimg>")
        return 1

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"ERROR: ファイルが存在しません: {path}")
        return 1

    print("=" * 70)
    print(f" 証明書 SAN 構造ダンプ: {path}")
    print("=" * 70)

    # ---- コンテナから cert を取り出す ----
    _img, _name, _p7s, cert_raw = read_jpkiimg(path)
    cert_der = trim_der(cert_raw)
    cert = x509.load_der_x509_certificate(cert_der)
    print(f"  cert DER size  : {len(cert_der)} bytes (パディング除去後)")
    print(f"  cert version   : {cert.version.name}")
    print(f"  cert serial    : 0x{cert.serial_number:x}")
    print()

    # ============================================================
    # 1) Subject DN 内の全属性
    # ============================================================
    print("─" * 70)
    print(" [1] Subject DN (Distinguished Name) の属性一覧")
    print("─" * 70)
    for attr in cert.subject:
        print(f"  • {attr.oid._name:30s}  OID={attr.oid.dotted_string:30s}  value={attr.value!r}")
    print()

    # ============================================================
    # 2) SubjectAltName 拡張のフル展開
    # ============================================================
    print("─" * 70)
    print(" [2] SubjectAltName (SAN) 拡張のフル展開")
    print("─" * 70)
    try:
        ext = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
    except x509.ExtensionNotFound:
        print("  ⚠️ SAN 拡張が存在しません。氏名は別の場所(おそらく Subject DN 内)にあります。")
        print()
        return 0

    san = ext.value
    print(f"  critical       : {ext.critical}")
    print(f"  general names  : {len(san)} 個")
    print()

    for i, gn in enumerate(san):
        type_name = type(gn).__name__
        print(f"  ── GeneralName #{i}: {type_name} ─────────────────────────")
        if isinstance(gn, x509.DirectoryName):
            name = gn.value  # x509.Name (DistinguishedName)
            print(f"      DirectoryName 内の属性: {len(list(name))} 個")
            for attr in name:
                print(
                    f"        - {attr.oid._name:30s}  "
                    f"OID={attr.oid.dotted_string:30s}  "
                    f"value={attr.value!r}"
                )
            # 連結フォーマット(参考)
            try:
                print(f"      RFC4514 形式: {name.rfc4514_string()!r}")
            except Exception:
                pass
        elif isinstance(gn, x509.RFC822Name):
            print(f"      email      : {gn.value!r}")
        elif isinstance(gn, x509.DNSName):
            print(f"      dns        : {gn.value!r}")
        elif isinstance(gn, x509.UniformResourceIdentifier):
            print(f"      uri        : {gn.value!r}")
        elif isinstance(gn, x509.IPAddress):
            print(f"      ip         : {gn.value!r}")
        elif isinstance(gn, x509.OtherName):
            print(f"      other OID  : {gn.type_id.dotted_string}")
            print(f"      raw value  : {gn.value!r}  ({len(gn.value)} bytes)")
            try:
                print(f"      hex preview: {gn.value[:32].hex()}...")
            except Exception:
                pass
        else:
            print(f"      raw type   : {gn!r}")
        print()

    # ============================================================
    # 3) すべての拡張のリスト(参考)
    # ============================================================
    print("─" * 70)
    print(" [3] すべての X.509 拡張(参考)")
    print("─" * 70)
    for ext in cert.extensions:
        print(
            f"  • {ext.oid._name or '(unnamed)':40s}  "
            f"OID={ext.oid.dotted_string:30s}  "
            f"critical={ext.critical}"
        )
    print()

    print("=" * 70)
    print(" 共有時は氏名・住所・生年月日等の個人情報を必ずマスクしてください ")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
