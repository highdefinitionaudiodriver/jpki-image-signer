"""
phase3.app: GUI アプリケーション エントリポイント.

実行:
  py -3.12 -m phase3.app
  または
  py -3.12 phase3/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加(直接実行/モジュール実行両方に対応)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from phase3.gui.main_window import MainWindow
from phase3.gui.styles import APP_STYLESHEET


def _resolve_asset_path(filename: str) -> Path:
    """
    アセット(アイコン等) のパスを解決する。

    開発時:    <PROJECT_ROOT>/assets/<filename>
    PyInstaller バンドル時:
       --add-data によってバンドル内 _internal/assets/<filename> に
       展開されるため sys._MEIPASS を起点に解決する。
    """
    # PyInstaller がランタイム時のみ設定する属性
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        return Path(base) / "assets" / filename
    # 開発時: phase3/app.py から見て ../assets/
    return Path(__file__).resolve().parent.parent / "assets" / filename


def main() -> int:
    # High DPI 対応(Qt 6では既定で有効、保険として明示)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)

    app = QApplication(sys.argv)
    app.setApplicationName("JPKI Image Signer")
    app.setApplicationDisplayName("JPKI Image Signer")
    app.setOrganizationName("JPKI Image Signer Project")

    # 既定フォント(Windows: Yu Gothic UI / Segoe UI)
    default_font = QFont("Yu Gothic UI", 10)
    app.setFont(default_font)

    # ---- ウィンドウ・タスクバーアイコン ----
    # .exe ファイル自体のアイコン(Explorer 上で見えるもの)は PyInstaller の
    # --icon フラグで設定されるが、起動後のウィンドウ・タスクバーのアイコンは
    # QApplication.setWindowIcon() で明示設定する必要がある。
    # PNG (透過対応) を優先し、無ければ ICO/ICNS の順でフォールバック。
    for cand in ("icon.png", "icon.ico", "icon.icns"):
        icon_path = _resolve_asset_path(cand)
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    # スタイルシート適用(モダンフラット)
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
