"""
phase2.cli.verify_image: .jpkiimg コンテナの検証.

実行例:
  py -3.12 -m phase2.cli.verify_image docs/sample.jpg.jpkiimg

終了コード:
  0: 検証成功 (有効な署名)
  1: ファイルアクセスエラー
  2: コンテナ構造エラー (NotJpkiImg / MissingEntry)
  3: 署名検証失敗 (改ざん検知)
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phase2.cli._terminal import (
    red, green, yellow, cyan, bold, gray, step, banner, info,
    disable_color,
)
from phase2.container import (
    read_jpkiimg, NotJpkiImgError, MissingEntryError,
)
from phase2.crypto.verify import verify_signed_image


TOTAL_STEPS = 3


def main() -> int:
    parser = argparse.ArgumentParser(
        description=".jpkiimg コンテナを検証して署名者と有効性を表示する",
    )
    parser.add_argument("jpkiimg", help="検証対象の .jpkiimg ファイル")
    parser.add_argument(
        "--no-color", action="store_true",
        help="ANSIカラー出力を無効化",
    )
    args = parser.parse_args()

    if args.no_color:
        disable_color()

    path = Path(args.jpkiimg).resolve()

    print(banner(" JPKI Image Signer - 検証モード"))

    if not path.is_file():
        print(red(f"ERROR: ファイルが存在しません: {path}"))
        return 1

    info(f"検証対象: {cyan(str(path))}")
    info(f"サイズ:   {path.stat().st_size:,} bytes")

    # ============================================================
    # Step 1: コンテナ読み出し
    # ============================================================
    print(step(1, TOTAL_STEPS, "コンテナ読み出し"))
    try:
        image, image_name, p7s, cert = read_jpkiimg(path)
    except NotJpkiImgError as e:
        print()
        print(red(bold("  ❌ 不正なコンテナ: ZIP として開けません")))
        info(f"原因: {e}")
        return 2
    except MissingEntryError as e:
        print()
        print(red(bold("  ❌ 不正なコンテナ: 必須エントリ欠落")))
        info(f"原因: {e}")
        return 2

    info(f"画像:        {image_name}  ({len(image):,} B)")
    info(f"signature:   {len(p7s):,} B")
    info(f"cert:        {len(cert):,} B")

    # ============================================================
    # Step 2: PKCS#7検証
    # ============================================================
    print(step(2, TOTAL_STEPS, "PKCS#7 分離署名を検証"))
    result = verify_signed_image(image, p7s)

    if result.get("error"):
        info(red(f"検証中に構造エラー: {result['error']}"))

    # ============================================================
    # Step 3: 結果表示
    # ============================================================
    print(step(3, TOTAL_STEPS, "結果"))
    print()

    if result["valid"]:
        # ============== 成功表示 (緑) ==============
        print(green(bold("  ✅ 有効な署名です")))
        print()
        signer = result.get("signer_name") or "(取得失敗)"
        source = result.get("signer_name_source", "unknown")

        # 抽出元に応じてマーカーを付与
        if source == "san_directory_name":
            source_label = gray("(SAN内DirectoryNameより取得)")
        elif source == "subject_cn":
            source_label = yellow("(SAN無し→Subject CNフォールバック)")
        else:
            source_label = gray("(取得元不明)")

        print(f"     {bold('署名者:')}        {green(bold(signer))}  {source_label}")

        # 識別符号(Subject CN)が氏名と異なる場合は参考表示
        signer_cn = result.get("signer_cn")
        if signer_cn and signer_cn != signer:
            print(f"     {bold('識別符号:')}      {gray(signer_cn)}")

        nvb = result.get("not_valid_before") or "?"
        nva = result.get("not_valid_after") or "?"
        print(f"     {bold('証明書有効期間:')} {nvb}")
        print(f"     {' ' * 18}  {nva}")
        print(f"     {bold('画像サイズ:')}    {len(image):,} bytes")
        print(f"     {bold('画像エントリ:')}  {image_name}")
        print()
        print(green("  → 画像は署名生成時から1ビットも改変されていません。"))
        print()
        return 0
    else:
        # ============== 失敗表示 (赤) ==============
        print(red(bold("  ❌ 検証エラー: 署名が無効です")))
        print()
        if result.get("error"):
            print(red(f"     原因(構造): {result['error']}"))
        else:
            print(red("     原因: 画像と署名値が整合しません"))
            print(red("           (画像が改ざんされたか、別データで作成された署名の可能性)"))
        signer = result.get("signer_name") or result.get("signer_cn")
        if signer:
            print(f"     {gray(f'証明書上の署名者(参考): {signer}')}")
        print()
        return 3


if __name__ == "__main__":
    sys.exit(main())
