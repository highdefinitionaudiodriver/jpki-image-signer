"""
JPKI Image Signer - マルチOS対応ビルドスクリプト.

実行環境のOSを判定して PyInstaller を適切なオプションで起動する。
Windows .exe / macOS .app / Linux バイナリ を生成可能。

機能:
  1. OS判定 (Windows/Darwin/Linux)
  2. assets/icon.png から OSごとに ico/icns を自動変換 (Pillow使用)
  3. アイコン未配置の場合は ダミーアイコン (512x512) を自動生成
  4. PyInstaller で --noconsole / --windowed / --icon を OS別に最適化
  5. デフォルトは --onedir (起動速度・誤検知対策)、--onefile も選択可能

使い方:
  python build.py                      # 通常ビルド (--onedir)
  python build.py --onefile            # 単一実行ファイル
  python build.py --clean              # build/dist をクリアしてから
  python build.py --regenerate-icons   # ico/icns を強制再生成
  python build.py --no-build           # アイコン準備のみ (PyInstaller不要)
  python build.py --skip-deps-check    # 依存パッケージ確認をスキップ
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Windows の cp932 コンソールでも UTF-8 文字を出力できるように
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ==============================================================
# パス定義
# ==============================================================
PROJECT_ROOT = Path(__file__).resolve().parent
ASSETS_DIR   = PROJECT_ROOT / "assets"
DIST_DIR     = PROJECT_ROOT / "dist"
BUILD_DIR    = PROJECT_ROOT / "build"
ENTRY_POINT  = PROJECT_ROOT / "phase3" / "app.py"

# PyInstaller の出力名 (空白を避けると配布時のパス問題が減る)
APP_NAME         = "JPKI_Image_Signer"
APP_DISPLAY_NAME = "JPKI Image Signer"
APP_VERSION      = "0.1.0"   # 配布パッケージ名に埋め込む


# ==============================================================
# OS判定
# ==============================================================
def detect_os() -> str:
    """'windows' / 'macos' / 'linux' のいずれかを返す."""
    s = platform.system()
    if s == "Windows":
        return "windows"
    if s == "Darwin":
        return "macos"
    if s == "Linux":
        return "linux"
    raise RuntimeError(f"未対応のOSです: {s}")


# ==============================================================
# 依存確認
# ==============================================================
def check_dependency(module_name: str, install_hint: str) -> bool:
    """モジュールがインポート可能か確認."""
    try:
        __import__(module_name)
        return True
    except ImportError:
        print(f"  ✗ {module_name} が見つかりません  (pip install {install_hint})")
        return False


def check_all_dependencies(skip: bool = False) -> bool:
    """ビルドに必要な依存を一括確認."""
    if skip:
        print("[依存確認] スキップ (--skip-deps-check)")
        return True

    print("[依存確認]")
    deps = [
        ("PIL",          "Pillow"),
        ("PyQt6.QtCore", "PyQt6"),
        ("smartcard",    "pyscard"),
        ("cryptography", "cryptography"),
        ("asn1crypto",   "asn1crypto"),
        ("PyInstaller",  "PyInstaller"),
    ]
    ok = True
    for mod, hint in deps:
        if check_dependency(mod, hint):
            print(f"  ✓ {mod}")
        else:
            ok = False

    return ok


# ==============================================================
# ダミーアイコン生成 (assets/icon.png が無い場合)
# ==============================================================
def _find_default_font(size: int):
    """OSをまたいで利用可能なフォントを探す."""
    from PIL import ImageFont
    candidates = [
        # Windows
        "arial.ttf", "arialbd.ttf",
        "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate_dummy_icon(out_path: Path, size: int = 512) -> None:
    """『JPKI Signer』と書かれた仮のアイコンを生成する."""
    from PIL import Image, ImageDraw
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 背景: GUIの primary color (#3B82F6 Tailwind blue-500)
    img = Image.new("RGBA", (size, size), (59, 130, 246, 255))
    draw = ImageDraw.Draw(img)

    # 外周の白円(枠アクセント)
    margin = int(size * 0.06)
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        outline=(255, 255, 255, 255),
        width=max(4, size // 64),
    )

    # メインテキスト "JPKI"
    main_font = _find_default_font(int(size * 0.32))
    text = "JPKI"
    bbox = draw.textbbox((0, 0), text, font=main_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) // 2 - bbox[0], (size - th) // 2 - bbox[1] - int(size * 0.05)),
        text,
        fill=(255, 255, 255, 255),
        font=main_font,
    )

    # サブタイトル "Image Signer"
    sub_font = _find_default_font(int(size * 0.10))
    sub = "Image Signer"
    bbox = draw.textbbox((0, 0), sub, font=sub_font)
    sw = bbox[2] - bbox[0]
    draw.text(
        ((size - sw) // 2 - bbox[0], int(size * 0.70)),
        sub,
        fill=(220, 230, 245, 255),
        font=sub_font,
    )

    img.save(out_path, "PNG")
    print(f"  → ダミーアイコン生成: {out_path}  ({size}x{size})")


# ==============================================================
# アイコン変換 PNG → ICO / ICNS
# ==============================================================
def png_to_ico(png_path: Path, ico_path: Path) -> None:
    """PNG → 複数サイズの ICO に変換 (Windows用)."""
    from PIL import Image
    img = Image.open(png_path).convert("RGBA")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    img.save(ico_path, format="ICO", sizes=sizes)
    print(f"  → ICO 生成: {ico_path}  (サイズ: {len(sizes)}解像度)")


def png_to_icns(png_path: Path, icns_path: Path) -> None:
    """PNG → ICNS に変換 (macOS用)."""
    from PIL import Image
    img = Image.open(png_path).convert("RGBA")

    # ICNS は正方形・特定サイズ群を要求する。最大サイズに合わせて
    # 必要なら縮小・拡大しつつ Pillow に渡す。
    # Pillow 9+ は ICNS save に対応(Pillow 自身が必要なサイズを生成)。
    try:
        img.save(icns_path, format="ICNS")
        print(f"  → ICNS 生成: {icns_path}  (Pillow標準)")
    except Exception as e:
        # フォールバック: 一時的に正方形・大きいサイズに変換してから再試行
        print(f"  ⚠️ ICNS 直接保存失敗 ({e})。512x512 リサンプル後に再試行")
        img2 = img.resize((1024, 1024), Image.LANCZOS)
        img2.save(icns_path, format="ICNS")
        print(f"  → ICNS 生成: {icns_path}  (1024x1024 fallback)")


def prepare_icon(os_kind: str, regenerate: bool = False) -> Optional[Path]:
    """
    OSに応じたアイコンを準備する。

    - assets/icon.png が無ければダミー生成
    - Windows: assets/icon.ico を生成
    - macOS:   assets/icon.icns を生成
    - Linux:   icon.png をそのまま返す

    Returns:
        使用するアイコンファイルのパス。失敗時は None。
    """
    src = ASSETS_DIR / "icon.png"
    if not src.is_file():
        print(f"  ⚠️ {src} が見つからないためダミー画像を生成します")
        generate_dummy_icon(src)

    if os_kind == "windows":
        dst = ASSETS_DIR / "icon.ico"
        if regenerate or not dst.is_file() or dst.stat().st_mtime < src.stat().st_mtime:
            png_to_ico(src, dst)
        else:
            print(f"  ✓ 既存ICOを使用: {dst}")
        return dst

    if os_kind == "macos":
        dst = ASSETS_DIR / "icon.icns"
        if regenerate or not dst.is_file() or dst.stat().st_mtime < src.stat().st_mtime:
            png_to_icns(src, dst)
        else:
            print(f"  ✓ 既存ICNSを使用: {dst}")
        return dst

    # Linux: PNG をそのまま使う(ファイルマネージャ表示用)
    print(f"  ✓ Linux: PNG を使用: {src}")
    return src


# ==============================================================
# PyInstaller 引数組み立て
# ==============================================================
def build_pyinstaller_args(
    os_kind: str,
    icon: Optional[Path],
    onefile: bool,
    clean: bool,
) -> list[str]:
    # `pyinstaller` 直叩きは PATH 依存になるため、現在の Python から
    # `python -m PyInstaller` 形式で起動する(環境差を吸収)
    args: list[str] = [sys.executable, "-m", "PyInstaller", "--noconfirm"]

    if clean:
        args.append("--clean")

    # 出力モード
    if onefile:
        args.append("--onefile")
    else:
        args.append("--onedir")

    # GUIモード(コンソールウィンドウを表示しない)
    if os_kind == "windows":
        args.append("--noconsole")
    elif os_kind == "macos":
        args.append("--windowed")
    # Linux は --windowed が無くてもターミナル不要だが念のため
    elif os_kind == "linux":
        args.append("--windowed")

    args.extend(["--name", APP_NAME])

    if icon is not None:
        args.extend(["--icon", str(icon)])

    # ---- Hidden imports (PyInstallerの自動解析が漏れがちなもの) ----
    hidden_imports = [
        "smartcard",
        "smartcard.scard",
        "smartcard.System",
        "smartcard.Exceptions",
        "smartcard.util",
        "smartcard.CardConnection",
    ]
    for h in hidden_imports:
        args.extend(["--hidden-import", h])

    # ---- pyscard の C拡張・データを丸ごと収集 ----
    args.extend(["--collect-all", "smartcard"])

    # ---- アセット (アイコン画像等) をバンドル内 _internal/assets/ に同梱 ----
    # phase3/app.py の _resolve_asset_path() がランタイム時 sys._MEIPASS から
    # assets/<filename> を読み出す。
    # PyInstaller の --add-data 区切り文字: Windows は ';'、それ以外は ':'
    sep = ";" if os_kind == "windows" else ":"
    icon_png = ASSETS_DIR / "icon.png"
    if icon_png.is_file():
        args.extend(["--add-data", f"{icon_png}{sep}assets"])

    # ---- 出力先 ----
    args.extend(["--distpath", str(DIST_DIR)])
    args.extend(["--workpath", str(BUILD_DIR)])

    # ---- エントリポイント ----
    args.append(str(ENTRY_POINT))

    return args


# ==============================================================
# main
# ==============================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="JPKI Image Signer マルチOS ビルドスクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  python build.py                              # --onedir でビルド (推奨)\n"
            "  python build.py --onefile                    # 単一実行ファイルでビルド\n"
            "  python build.py --clean                      # build/dist をクリアしてから\n"
            "  python build.py --no-build                   # アイコン準備のみ\n"
            "  python build.py --package --clean            # --onedir + ZIPパッケージ生成\n"
            "  python build.py --onefile --package --clean  # --onefile + ZIPパッケージ生成\n"
        ),
    )
    parser.add_argument(
        "--onefile", action="store_true",
        help="単一実行ファイルでビルド (default: --onedir)",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="ビルド前に build/ と dist/ をクリア",
    )
    parser.add_argument(
        "--regenerate-icons", action="store_true",
        help="既存の ico/icns を強制再生成",
    )
    parser.add_argument(
        "--no-build", action="store_true",
        help="ビルドはせずアイコン準備のみ実行",
    )
    parser.add_argument(
        "--skip-deps-check", action="store_true",
        help="依存パッケージの存在確認をスキップ",
    )
    parser.add_argument(
        "--package", action="store_true",
        help="ビルド成功後、dist/ に配布用 ZIP を自動生成",
    )
    args = parser.parse_args()

    print("=" * 64)
    print(" JPKI Image Signer - マルチOS ビルドスクリプト")
    print("=" * 64)

    os_kind = detect_os()
    print(f"  OS:           {platform.system()} ({os_kind})")
    print(f"  Python:       {sys.version.split()[0]}")
    print(f"  ENTRY:        {ENTRY_POINT}")
    print(f"  ASSETS:       {ASSETS_DIR}")
    print(f"  DIST:         {DIST_DIR}")
    print(f"  Mode:         {'--onefile' if args.onefile else '--onedir'}")
    print()

    # ---- エントリポイント存在確認 ----
    if not ENTRY_POINT.is_file():
        print(f"ERROR: エントリポイントが見つかりません: {ENTRY_POINT}")
        return 1

    # ---- 依存確認 ----
    if not check_all_dependencies(skip=args.skip_deps_check):
        if args.no_build:
            # アイコン生成だけなら Pillow さえあればOK
            print("\n--no-build モードのため Pillow のみで続行を試みます")
        else:
            print("\nERROR: 必要な依存が不足しています。pip install で追加してください。")
            return 1
    print()

    # ---- アイコン準備 ----
    print("[1/3] アイコン準備...")
    try:
        icon = prepare_icon(os_kind, regenerate=args.regenerate_icons)
    except ImportError as e:
        print(f"ERROR: Pillow が必要です: {e}")
        print("  pip install Pillow")
        return 1
    print()

    if args.no_build:
        print("[完了] アイコン準備のみ実行 (--no-build)")
        return 0

    # ---- 既存出力のクリーンアップ ----
    if args.clean:
        print("[2/3] build/dist クリア...")
        for d in (BUILD_DIR, DIST_DIR):
            if d.is_dir():
                shutil.rmtree(d)
                print(f"  → 削除: {d}")
        print()
    else:
        print("[2/3] (--clean 指定なし、既存出力を上書き)")
        print()

    # ---- PyInstaller 実行 ----
    pyargs = build_pyinstaller_args(os_kind, icon, args.onefile, args.clean)
    print("[3/3] PyInstaller 実行...")
    # ログ用にコマンドの先頭と末尾を表示(全部出すと長すぎる)
    preview_head = " ".join(pyargs[:8])
    print(f"  $ {preview_head} ... {pyargs[-1]}")
    print(f"  ({len(pyargs)} 個の引数)")
    print()

    result = subprocess.run(pyargs, cwd=str(PROJECT_ROOT))

    print()
    print("=" * 64)
    if result.returncode == 0:
        print(" ✅ ビルド成功")
        print("=" * 64)
        _print_build_result(os_kind, args.onefile)

        # ---- 配布用ZIP生成(--package指定時) ----
        if args.package:
            print()
            print("[追加] 配布用ZIPパッケージング...")
            try:
                zip_path = package_distribution(os_kind, args.onefile)
                if zip_path is not None:
                    print()
                    print("=" * 64)
                    print(" 📦 配布パッケージ生成完了")
                    print("=" * 64)
                    print(f"  ZIP: {zip_path}")
            except Exception as e:
                print(f"  ❌ ZIP生成エラー: {e}")
                return 1

        return 0
    else:
        print(f" ❌ ビルド失敗 (exit code: {result.returncode})")
        print("=" * 64)
        return result.returncode


# ==============================================================
# 配布用 ZIP パッケージング
# ==============================================================
def _normalized_arch() -> str:
    """platform.machine() を配布名向けに正規化."""
    raw = platform.machine().lower()
    return {
        "amd64":  "x64",
        "x86_64": "x64",
        "arm64":  "arm64",
        "aarch64": "arm64",
        "i386":   "x86",
        "i686":   "x86",
    }.get(raw, raw or "unknown")


def _os_label(os_kind: str) -> str:
    return {"windows": "Windows", "macos": "macOS", "linux": "Linux"}.get(os_kind, os_kind)


def package_distribution(os_kind: str, onefile: bool) -> Optional[Path]:
    """
    ビルド成果物を配布用ZIPにまとめる。

    Args:
        os_kind: 'windows' / 'macos' / 'linux'
        onefile: True なら単一実行ファイル、False なら --onedir

    Returns:
        生成された .zip のパス。失敗時は None。
    """
    import zipfile

    os_label = _os_label(os_kind)
    arch     = _normalized_arch()
    mode_label = "onefile" if onefile else "onedir"

    zip_basename = f"JPKI_Image_Signer_{os_label}_{arch}_v{APP_VERSION}_{mode_label}"
    zip_path = DIST_DIR / f"{zip_basename}.zip"

    # 既存削除
    if zip_path.is_file():
        zip_path.unlink()

    if onefile:
        # 単一実行ファイル: <APP_NAME>.exe (Win) / <APP_NAME> (Mac/Linux)
        exe_name = f"{APP_NAME}.exe" if os_kind == "windows" else APP_NAME
        src_exe = DIST_DIR / exe_name
        if not src_exe.is_file():
            print(f"  ⚠️ 実行ファイルが見つかりません: {src_exe}")
            return None

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(src_exe, arcname=src_exe.name)
        print(f"  → ZIP生成 (onefile): {zip_path}")
        print(f"     内容: {src_exe.name} のみ")

    else:
        # --onedir: dist/JPKI_Image_Signer/ 配下を丸ごとZIP化
        src_dir = DIST_DIR / APP_NAME
        if not src_dir.is_dir():
            print(f"  ⚠️ 出力ディレクトリが見つかりません: {src_dir}")
            return None

        # ZIP内ルートを APP_NAME/ にする(展開時に汚染されないよう)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            file_count = 0
            for path in src_dir.rglob("*"):
                if path.is_file():
                    arcname = path.relative_to(src_dir.parent)
                    zf.write(path, arcname=str(arcname))
                    file_count += 1
        print(f"  → ZIP生成 (onedir): {zip_path}")
        print(f"     内容: {file_count} ファイル / トップ階層 = {APP_NAME}/")

    # サイズ表示
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"     サイズ: {size_mb:.1f} MB")
    return zip_path


def _print_build_result(os_kind: str, onefile: bool) -> None:
    """成功時の出力先を案内."""
    if onefile:
        if os_kind == "windows":
            exe = DIST_DIR / f"{APP_NAME}.exe"
        else:
            exe = DIST_DIR / APP_NAME
        print(f"  実行ファイル: {exe}")
        if exe.is_file():
            size_mb = exe.stat().st_size / (1024 * 1024)
            print(f"  サイズ:       {size_mb:.1f} MB")
        print()
        print("  ▶ 起動方法:")
        print(f"      {exe}")
    else:
        if os_kind == "macos":
            app_bundle = DIST_DIR / f"{APP_NAME}.app"
            print(f"  .app バンドル: {app_bundle}")
            print()
            print("  ▶ 起動方法:")
            print(f"      open '{app_bundle}'")
        elif os_kind == "windows":
            out_dir = DIST_DIR / APP_NAME
            exe = out_dir / f"{APP_NAME}.exe"
            print(f"  出力フォルダ: {out_dir}")
            print(f"  実行ファイル: {exe}")
            print()
            print("  ▶ 起動方法:")
            print(f"      {exe}")
        else:  # linux
            out_dir = DIST_DIR / APP_NAME
            exe = out_dir / APP_NAME
            print(f"  出力フォルダ: {out_dir}")
            print(f"  実行ファイル: {exe}")
            print()
            print("  ▶ 起動方法:")
            print(f"      ./{exe.relative_to(PROJECT_ROOT)}")

    print()
    print("  ⚠️ 配布時の注意:")
    print("    - PC/SC 対応 ICカードリーダーが受信側PCにも必要です")
    print("    - Windows: SCardSvr サービスが起動していること")
    print("    - 初回起動時は Antivirus に誤検知される場合があります")


if __name__ == "__main__":
    sys.exit(main())
