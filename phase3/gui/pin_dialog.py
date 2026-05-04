"""
phase3.gui.pin_dialog: 署名用PIN入力モーダルダイアログ.

機能:
  - 残回数を色分け表示 (5=緑, 3〜4=黄+警告, 2以下=赤+警告)
  - QLineEdit (Password モード) でPINを画面非表示入力
  - 桁数(6〜16) と ASCII 制約をリアルタイムバリデーション
  - キャンセル / 認証して署名を実行 の2ボタン
  - 閉じる時に入力欄をクリア(メモリ残留対策)
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)


class PinDialog(QDialog):
    """署名用PIN入力モーダル."""

    def __init__(self, remaining: int, parent=None):
        super().__init__(parent)
        self._remaining = remaining
        self._pin_value: Optional[str] = None  # 受理時のみ保持

        self.setWindowTitle("署名用PINの入力")
        self.setModal(True)
        self.setMinimumWidth(480)

        # ---- Windows 11 ダークモード対策 ----
        # システムパレットを無効化し、明示的にライトテーマを適用する。
        # これにより PinDialog 内の QLabel/QLineEdit が常に
        # 「白背景 + 黒文字」で描画される。
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#1F2937"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#1F2937"))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9CA3AF"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1F2937"))
        self.setPalette(pal)

        self._build_ui()

    # ----------------------------------------------------------------
    # UI 構築
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        # ---- タイトル ----
        title = QLabel("🔐 署名用PIN入力")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: bold; color: #1F2937;"
        )
        layout.addWidget(title)

        # ---- 残回数バッジ ----
        if self._remaining >= 5:
            color = "#10B981"   # 緑
            level = "(初期状態)"
            warn = ""
        elif self._remaining >= 3:
            color = "#F59E0B"   # 黄
            level = "(注意)"
            warn = ("<br>⚠️ 過去にPINを間違えた形跡があります。<br>"
                    "確実に正しい署名用PINを入力してください。")
        else:
            color = "#EF4444"   # 赤
            level = "(危険水域)"
            warn = ("<br>⚠️ 残回数が危険水域です! 1回失敗すると "
                    f"あと {max(self._remaining - 1, 0)} 回でロックします。<br>"
                    "PINを完全に把握している自信がない場合はキャンセルしてください。")

        remaining_html = (
            f"<div style='font-size:11pt'>"
            f"PIN残回数:&nbsp;"
            f"<span style='color:{color}; font-weight:bold; font-size:14pt'>"
            f"{self._remaining} 回</span>"
            f"&nbsp;<span style='color:{color}'>{level}</span>"
            f"{warn}"
            f"</div>"
        )
        self.remaining_label = QLabel(remaining_html)
        self.remaining_label.setTextFormat(Qt.TextFormat.RichText)
        self.remaining_label.setWordWrap(True)
        self.remaining_label.setStyleSheet(
            f"background-color: {color}10;"
            f"border: 1px solid {color};"
            f"border-radius: 6px;"
            f"padding: 12px;"
        )
        layout.addWidget(self.remaining_label)

        # ---- 説明 ----
        hint = QLabel(
            "マイナンバーカードの <b>署名用PIN</b> (6〜16桁の英数字) を入力してください。<br>"
            "<span style='color:#6B7280; font-size:9pt'>"
            "※ 入力中の文字は画面に表示されません。<br>"
            "※ 5回連続で間違えるとロックされ、市区町村窓口での解除が必要になります。"
            "</span>"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #374151; padding: 4px;")
        layout.addWidget(hint)

        # ---- PIN入力欄 ----
        self.pin_input = QLineEdit()
        self.pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_input.setMaxLength(16)
        self.pin_input.setMinimumHeight(36)
        self.pin_input.setPlaceholderText("署名用PIN (6〜16桁)")
        self.pin_input.setStyleSheet(
            "font-size: 12pt; padding: 6px 10px;"
            "border: 1px solid #E1E5EB; border-radius: 6px;"
        )
        self.pin_input.textChanged.connect(self._on_text_changed)
        self.pin_input.returnPressed.connect(self._on_accept)
        layout.addWidget(self.pin_input)

        # ---- バリデーション・メッセージ ----
        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet(
            "color: #EF4444; font-size: 9pt; padding: 0px 4px;"
        )
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        # ---- ボタン ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("キャンセル")
        self.cancel_btn.setObjectName("backButton")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.ok_btn = QPushButton("🔐 認証して署名を実行")
        self.ok_btn.setObjectName("primaryButton")
        self.ok_btn.setMinimumHeight(36)
        self.ok_btn.setDefault(True)
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(self.ok_btn)

        layout.addLayout(btn_row)

        # 初回フォーカス
        self.pin_input.setFocus()

    # ----------------------------------------------------------------
    # バリデーション
    # ----------------------------------------------------------------
    def _on_text_changed(self, text: str) -> None:
        msg = self._validate(text)
        self.validation_label.setText(msg or "")
        self.ok_btn.setEnabled(msg is None and 6 <= len(text) <= 16)

    def _validate(self, text: str) -> Optional[str]:
        if len(text) == 0:
            return None  # 空はバリデーションメッセージ表示しない
        if not text.isascii():
            return "PIN は ASCII英数字のみ入力できます"
        if len(text) < 6:
            return f"PIN は 6 桁以上です(現在 {len(text)} 桁)"
        if len(text) > 16:
            return f"PIN は 16 桁以下です(現在 {len(text)} 桁)"
        return None

    # ----------------------------------------------------------------
    # 受理 / キャンセル
    # ----------------------------------------------------------------
    def _on_accept(self) -> None:
        text = self.pin_input.text()
        if self._validate(text) is not None:
            return
        if not (6 <= len(text) <= 16):
            return
        self._pin_value = text
        # 入力欄を即座にクリア(画面残留対策)
        self.pin_input.clear()
        self.accept()

    def reject(self) -> None:  # type: ignore[override]
        self.pin_input.clear()
        self._pin_value = None
        super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.pin_input.clear()
        super().closeEvent(event)

    # ----------------------------------------------------------------
    # 公開API
    # ----------------------------------------------------------------
    def get_pin(self) -> Optional[str]:
        """
        ダイアログを実行してPIN文字列を返す。

        Returns:
            str: 受理時(認証ボタン押下) のPIN文字列
            None: キャンセル時
        """
        result = self.exec()
        if result == QDialog.DialogCode.Accepted:
            return self._pin_value
        return None
