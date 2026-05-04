"""
phase2.cli.sign_image: 画像 → JPKI署名 → .jpkiimg 生成.

実カード使用の本番フロー:
  1) 画像読み込み
  2) JPKI接続 / SELECT AP / ATR表示
  3) PIN残回数確認 + 安全装置 (assert_safe_to_attempt_pin)
  4) ユーザー続行確認 (yes/no)
  5) PIN入力 (getpass) + VERIFY
  6) DigestInfo構築 + COMPUTE DIGITAL SIGNATURE
  7) 署名用証明書読出 + パディング除去
  8) PKCS#7構築 + .jpkiimg コンテナ作成

実行例:
  py -3.12 -m phase2.cli.sign_image docs/sample.jpg
  py -3.12 -m phase2.cli.sign_image docs/sample.jpg -o docs/signed.jpkiimg

出力:
  デフォルト: <input>.jpkiimg (例: docs/sample.jpg.jpkiimg)
"""
from __future__ import annotations

import sys
import argparse
import getpass
from pathlib import Path

# プロジェクトルートを sys.path に追加(直接実行/モジュール実行両方に対応)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phase2.cli._terminal import (
    red, green, yellow, cyan, bold, gray, step, banner, info, warn,
    disable_color,
)
from phase2.jpki import (
    JpkiSession, build_digest_info_sha256,
    JpkiNoReaderError, JpkiCardError,
    JpkiPinFailedError, JpkiPinLockedError, JpkiPinRiskError,
    JpkiPinNotVerifiedError,
)
from phase2.crypto import build_p7s, trim_der
from phase2.container import create_jpkiimg


TOTAL_STEPS = 8


def main() -> int:
    parser = argparse.ArgumentParser(
        description="画像をマイナンバーカードのJPKI署名鍵で電子署名し .jpkiimg コンテナを生成する",
    )
    parser.add_argument("image", help="署名対象の画像ファイル(JPEG/PNG等)")
    parser.add_argument(
        "-o", "--output",
        help="出力する .jpkiimg のパス (省略時は <image>.jpkiimg)",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="ANSIカラー出力を無効化",
    )
    args = parser.parse_args()

    if args.no_color:
        disable_color()

    image_path = Path(args.image).resolve()
    if not image_path.is_file():
        print(red(f"ERROR: 画像ファイルが見つかりません: {image_path}"))
        return 1

    output_path = Path(args.output).resolve() if args.output else \
        image_path.with_name(image_path.name + ".jpkiimg")

    print(banner(" JPKI Image Signer - 署名モード"))

    # ============================================================
    # Step 1: 画像読み込み
    # ============================================================
    print(step(1, TOTAL_STEPS, f"画像読み込み: {cyan(str(image_path))}"))
    image_bytes = image_path.read_bytes()
    info(f"サイズ: {len(image_bytes):,} bytes")
    info(f"出力先: {output_path}")

    # ============================================================
    # Step 2-7: カードセッション内で完結
    # ============================================================
    sig: bytes | None = None
    cert_der: bytes | None = None

    try:
        print(step(2, TOTAL_STEPS, "JPKIカードに接続..."))
        with JpkiSession() as s:
            info(f"リーダー: {s.reader_name}")
            info(f"ATR:    {s.atr_hex}")

            # ---- Step 3: 残回数確認 + 安全装置 ----
            print(step(3, TOTAL_STEPS, "署名用PIN残回数を確認 (試行は消費しません)"))
            try:
                remaining = s.assert_safe_to_attempt_pin()
            except JpkiPinLockedError as e:
                print()
                print(red(bold("[FATAL] 署名用PINがロックされています")))
                error(str(e))
                error("市区町村窓口で初期化が必要です。")
                return 3
            except JpkiPinRiskError as e:
                print()
                print(red(bold("[STOP] 安全装置作動")))
                error(f"残回数 {e.remaining} 回 < 安全閾値 {e.threshold} 回")
                error("ロック防止のため処理を中止します。")
                return 3

            if remaining is not None:
                if remaining >= 5:
                    info(f"残回数: {green(str(remaining))} 回 (初期状態)")
                elif remaining >= 3:
                    info(f"残回数: {yellow(str(remaining))} 回")
                else:
                    # ここには到達しないはず(assert_safe_to_attempt_pinで弾かれる)
                    info(f"残回数: {red(str(remaining))} 回")
            else:
                warn("残回数: 不明 (カード/リーダーが標準APDU照会に非対応)")

            # ---- Step 4: 続行確認 ----
            print(step(4, TOTAL_STEPS, "実行確認"))
            print()
            print(f"     {bold('PIN を入力していただきます')}")
            if remaining is not None and remaining > 0:
                info(f"残回数 {remaining} 回。1回失敗すると {remaining - 1} 回になります。")
            info("PINを5回連続で間違えるとロックされます。")
            print()
            ans = input("     続行しますか? [yes/no] > ").strip().lower()
            if ans not in ("yes", "y"):
                print(yellow("\n中止しました。"))
                return 0

            # ---- Step 5: PIN入力 + VERIFY ----
            print(step(5, TOTAL_STEPS, "PIN入力 (画面に表示されません)"))
            pin = getpass.getpass("     署名用PIN > ")
            try:
                try:
                    s.verify_pin(pin)
                finally:
                    # 元の str はimmutableで完全消去不可だが参照を切る
                    del pin
            except JpkiPinFailedError as e:
                print()
                print(red(bold(f"[NG] PIN認証失敗  残回数: {e.remaining} 回")))
                error("本ツールは安全のため再試行を行いません。中止します。")
                return 3
            except JpkiPinLockedError:
                print()
                print(red(bold("[FATAL] PINがロックされました")))
                error("市区町村窓口で初期化が必要です。")
                return 3
            except ValueError as e:
                print(red(f"\n[ERROR] PIN形式不正: {e}"))
                return 3
            info(green("✓ 認証成功"))

            # ---- Step 6: 署名 ----
            print(step(6, TOTAL_STEPS, "DigestInfo構築 → COMPUTE DIGITAL SIGNATURE"))
            di = build_digest_info_sha256(image_bytes)
            info(f"DigestInfo:    {len(di)} B (期待値 51)")
            sig = s.sign_digest_info(di)
            info(f"RSA署名値:      {len(sig)} B (期待値 256)")
            info(f"署名値先頭16B: {gray(sig[:16].hex())}")

            # ---- Step 7: 署名用証明書読出 ----
            print(step(7, TOTAL_STEPS, "署名用電子証明書 EF 読み出し"))
            cert_raw = s.read_sign_certificate()
            cert_der = trim_der(cert_raw)
            padding = len(cert_raw) - len(cert_der)
            info(f"EF生サイズ: {len(cert_raw):,} B  / 実DER: {len(cert_der):,} B")
            info(f"パディング除去: {padding:,} B")

        # session 自動 close (with __exit__)

    except JpkiNoReaderError as e:
        print(red(f"\nERROR: {e}"))
        return 1
    except JpkiCardError as e:
        print(red(f"\nERROR: カード通信失敗: {e}"))
        if e.sw_hex:
            error(f"SW={e.sw_hex}")
        return 2
    except JpkiPinNotVerifiedError as e:
        print(red(f"\nERROR: 内部不整合: {e}"))
        return 3

    # ============================================================
    # Step 8: PKCS#7構築 + コンテナ作成 (カード不要)
    # ============================================================
    assert sig is not None and cert_der is not None
    print(step(8, TOTAL_STEPS, "PKCS#7構築 + .jpkiimg コンテナ作成"))
    p7s = build_p7s(signature=sig, cert_der=cert_der)
    info(f"PKCS#7サイズ:  {len(p7s):,} B")

    create_jpkiimg(
        image_path=image_path,
        p7s_bytes=p7s,
        cert_der_bytes=cert_der,
        output_path=output_path,
    )
    info(f"コンテナサイズ: {output_path.stat().st_size:,} B")

    # ============================================================
    # 完了サマリ
    # ============================================================
    print()
    print(banner(" 完了"))
    print(green(bold(f"  ✅ {output_path} を生成しました")))
    print()
    print(f"  検証コマンド:")
    print(f"    {cyan(f'py -3.12 -m phase2.cli.verify_image {output_path}')}")
    print()
    print(yellow(
        f"  ⚠️  {output_path.name} には署名者の氏名・住所等の個人情報が含まれます。"
    ))
    print(yellow(
        f"      公開リポジトリへのアップロード等は厳禁です。"
    ))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
