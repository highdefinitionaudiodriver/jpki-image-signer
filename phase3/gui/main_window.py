"""
phase3.gui.main_window: アプリのメインウィンドウ.

機能:
  - ウィンドウ全体で D&D を受付
  - ドロップされたファイルの拡張子を判定:
      * .jpg / .jpeg / .png    → SignPanel に切替
      * .jpkiimg               → VerifyPanel に切替
      * その他                  → エラーダイアログ + StatusBar 通知で拒否
  - D&D ホバー時に背景・枠線を変色(視覚フィードバック)
  - Welcome → 各モード → 戻る で Welcome に戻る画面遷移
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QWidget, QVBoxLayout, QLabel,
    QStatusBar, QMessageBox,
)

from .sign_panel import SignPanel
from .verify_panel import VerifyPanel


# ファイル拡張子→モード のマッピング
SIGN_EXTS:   set[str] = {".jpg", ".jpeg", ".png"}
VERIFY_EXTS: set[str] = {".jpkiimg"}
ALL_EXTS:    set[str] = SIGN_EXTS | VERIFY_EXTS


# ==============================================================
# Welcome パネル
# ==============================================================

class WelcomePanel(QWidget):
    """初期画面: D&D を促すプロンプト."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("welcomePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("📥")
        icon.setObjectName("welcomeIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("JPKI Image Signer")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("画像ファイル または .jpkiimg をドラッグ&ドロップしてください")
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        hint = QLabel(
            "🖼  JPEG / PNG  →  署名モード(マイナンバーカードで電子署名)<br>"
            "📦  .jpkiimg     →  検証モード(改ざんされていないか検証)"
        )
        hint.setObjectName("welcomeHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setTextFormat(Qt.TextFormat.RichText)

        layout.addStretch()
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(hint)
        layout.addStretch()


# ==============================================================
# MainWindow
# ==============================================================

class MainWindow(QMainWindow):
    """JPKI Image Signer メインウィンドウ."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JPKI Image Signer")
        self.resize(800, 600)
        self.setMinimumSize(640, 480)
        self.setAcceptDrops(True)

        # ---- 中央ウィジェット: QStackedWidget ----
        self.stack = QStackedWidget(self)
        self.stack.setObjectName("centralStack")
        # D&D ハイライト用の動的プロパティ初期化
        self.stack.setProperty("dragging", "false")
        self.setCentralWidget(self.stack)

        self.welcome_panel = WelcomePanel()
        self.sign_panel    = SignPanel()
        self.verify_panel  = VerifyPanel()

        self.stack.addWidget(self.welcome_panel)
        self.stack.addWidget(self.sign_panel)
        self.stack.addWidget(self.verify_panel)
        self.stack.setCurrentWidget(self.welcome_panel)

        # 戻るシグナル接続
        self.sign_panel.back_requested.connect(self._on_back)
        self.verify_panel.back_requested.connect(self._on_back)

        # ステータスバー
        self.setStatusBar(QStatusBar())
        self._set_default_status()

    # ============================================================
    # D&D
    # ============================================================

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if self._is_acceptable_drag(event):
            event.acceptProposedAction()
            self._set_dragging(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        if self._is_acceptable_drag(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # type: ignore[override]
        self._set_dragging(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        self._set_dragging(False)
        urls = event.mimeData().urls() if event.mimeData() else []
        if not urls:
            event.ignore()
            return

        # 1ファイルのみを対象にする(複数同時ドロップは先頭のみ)
        local = urls[0].toLocalFile()
        if not local:
            self._show_error("URL ではなくローカルファイルをドロップしてください。")
            event.ignore()
            return

        path = Path(local)
        if not path.is_file():
            self._show_error(f"ファイルが見つかりません:\n{path}")
            event.ignore()
            return

        ext = path.suffix.lower()
        if ext in SIGN_EXTS:
            self._enter_sign_mode(path)
            event.acceptProposedAction()
        elif ext in VERIFY_EXTS:
            self._enter_verify_mode(path)
            event.acceptProposedAction()
        else:
            self._show_error(
                f"非対応のファイル形式です: <b>{ext or '(拡張子無し)'}</b><br><br>"
                f"対応形式:<br>"
                f"・ 署名モード: {', '.join(sorted(SIGN_EXTS))}<br>"
                f"・ 検証モード: {', '.join(sorted(VERIFY_EXTS))}"
            )
            event.ignore()

    # ============================================================
    # 内部ヘルパ
    # ============================================================

    def _is_acceptable_drag(self, event) -> bool:
        """単一ファイル かつ 対応拡張子なら True."""
        md = event.mimeData()
        if md is None or not md.hasUrls():
            return False
        urls = md.urls()
        if len(urls) != 1:
            return False
        local = urls[0].toLocalFile()
        if not local:
            return False
        ext = Path(local).suffix.lower()
        return ext in ALL_EXTS

    def _set_dragging(self, dragging: bool) -> None:
        """D&D 中の視覚フィードバックを切替."""
        self.stack.setProperty("dragging", "true" if dragging else "false")
        # QSS の動的プロパティセレクタを再適用するために unpolish/polish が必要
        style = self.stack.style()
        if style is not None:
            style.unpolish(self.stack)
            style.polish(self.stack)
        self.stack.update()

    def _enter_sign_mode(self, path: Path) -> None:
        self.sign_panel.set_file(path)
        self.stack.setCurrentWidget(self.sign_panel)
        self.statusBar().showMessage(f"署名モード: {path.name}")

    def _enter_verify_mode(self, path: Path) -> None:
        self.verify_panel.set_file(path)
        self.stack.setCurrentWidget(self.verify_panel)
        self.statusBar().showMessage(f"検証モード: {path.name}")

    def _on_back(self) -> None:
        self.stack.setCurrentWidget(self.welcome_panel)
        self._set_default_status()

    def _set_default_status(self) -> None:
        self.statusBar().showMessage(
            "ファイルをドラッグ&ドロップしてください  |  "
            "JPEG/PNG → 署名,  .jpkiimg → 検証"
        )

    def _show_error(self, html_msg: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("ファイル形式エラー")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(html_msg)
        box.exec()
        self.statusBar().showMessage("非対応のファイルが拒否されました", 5000)
