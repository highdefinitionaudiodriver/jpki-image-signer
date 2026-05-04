"""
phase3.gui.privacy_warning_dialog: 署名前のプライバシー警告モーダル.

設計意図:
  JPKI署名用電子証明書には署名者の「氏名」「住所」「生年月日」「性別」が
  平文で含まれており、生成される .jpkiimg をインターネット上で公開すると
  個人情報の流出につながる。本ダイアログを「署名を開始」直後に必ず通すことで、
  ユーザーがリスクを認識してから PIN投入に進むようにする。

UX上の安全策:
  - デフォルトボタンを「キャンセル」にして Enter キーでの誤承認を防ぐ
  - 「理解して署名を実行する」ボタンに警告色(赤)を当てる
  - チェックボックス「内容を理解した」をオンにするまで承認ボタンを無効化
  - Windows ダークモード環境でも常にライトテーマで描画(QPalette 強制)
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QFrame,
)


class PrivacyWarningDialog(QDialog):
    """署名処理前のプライバシー警告(モーダル)."""

    def __init__(self, parent: Optional["QDialog"] = None):
        super().__init__(parent)
        self.setWindowTitle("⚠ プライバシーに関する重要な警告")
        self.setModal(True)
        self.setMinimumWidth(560)

        # Windows ダークモード対策: 常にライトテーマで描画
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window,         QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.WindowText,     QColor("#1F2937"))
        pal.setColor(QPalette.ColorRole.Base,           QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.Text,           QColor("#1F2937"))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9CA3AF"))
        pal.setColor(QPalette.ColorRole.ButtonText,     QColor("#1F2937"))
        self.setPalette(pal)

        self._build_ui()

    # ----------------------------------------------------------------
    # UI 構築
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(14)

        # ---- ヘッダ(警告色) ----
        header = QLabel("⚠ プライバシーに関する重要な警告")
        header.setStyleSheet(
            "font-size: 16pt; font-weight: bold;"
            "color: #DC2626;"   # red-600
            "padding: 4px;"
        )
        outer.addWidget(header)

        # ---- 警告本文(赤枠カード) ----
        warn_frame = QFrame()
        warn_frame.setStyleSheet(
            "background-color: #FEF2F2;"   # red-50
            "border: 2px solid #DC2626;"
            "border-radius: 10px;"
        )
        warn_layout = QVBoxLayout(warn_frame)
        warn_layout.setContentsMargins(16, 14, 16, 14)
        warn_layout.setSpacing(10)

        body_html = (
            "<div style='font-size:11pt; color:#1F2937;'>"
            "この署名処理により生成されるファイル "
            "(<b style='color:#DC2626'>.jpkiimg</b>) には、"
            "署名者(あなた)の以下の <b>個人情報</b> が "
            "<b>証明書データの一部として含まれます</b>:"
            "</div>"
            "<div style='margin-top:8px; padding:8px 16px;"
            "            background-color:#FFFFFF; border-radius:6px;'>"
            "<table cellpadding='4'>"
            "<tr><td>🔸 <b>氏名(漢字)</b></td></tr>"
            "<tr><td>🔸 <b>住所</b></td></tr>"
            "<tr><td>🔸 <b>生年月日</b></td></tr>"
            "<tr><td>🔸 <b>性別</b></td></tr>"
            "</table>"
            "</div>"
            "<div style='margin-top:10px; font-size:11pt; color:#7F1D1D;"
            "            font-weight:bold;'>"
            "⚠ インターネット上など不特定多数にこのファイルを公開すると、<br>"
            "&nbsp;&nbsp;&nbsp;個人情報が流出する危険性があります。"
            "</div>"
            "<div style='margin-top:10px; font-size:10pt; color:#374151;'>"
            "特定の取引先への送信や、クローズドな契約・証明目的以外での利用には<br>"
            "十分ご注意ください。"
            "</div>"
        )
        body = QLabel(body_html)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setStyleSheet("background-color: transparent; border: none;")
        warn_layout.addWidget(body)

        outer.addWidget(warn_frame)

        # ---- 確認チェックボックス(承認ボタン解除トリガ) ----
        self.understand_check = QCheckBox(
            "私はこの .jpkiimg に上記の個人情報が含まれることを理解しました"
        )
        self.understand_check.setStyleSheet(
            "QCheckBox { font-size: 10pt; color: #1F2937; padding: 4px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self.understand_check.toggled.connect(self._on_understand_toggled)
        outer.addWidget(self.understand_check)

        # ---- ボタン行 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("キャンセル")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setMinimumWidth(120)
        self.cancel_btn.setStyleSheet(
            "QPushButton { font-size: 11pt; padding: 6px 16px;"
            "             background-color: #FFFFFF; color: #1F2937;"
            "             border: 1px solid #E1E5EB; border-radius: 6px; }"
            "QPushButton:hover { background-color: #F5F7FA;"
            "                    border-color: #3B82F6; color: #3B82F6; }"
        )
        self.cancel_btn.setDefault(True)   # ★ Enter で誤承認を防ぐためキャンセル側を default
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.proceed_btn = QPushButton("⚠ 理解して署名を実行する")
        self.proceed_btn.setMinimumHeight(38)
        self.proceed_btn.setMinimumWidth(220)
        self.proceed_btn.setStyleSheet(
            "QPushButton { font-size: 11pt; font-weight: bold; padding: 6px 16px;"
            "             background-color: #DC2626; color: #FFFFFF;"
            "             border: none; border-radius: 6px; }"
            "QPushButton:hover { background-color: #B91C1C; }"
            "QPushButton:pressed { background-color: #991B1B; }"
            "QPushButton:disabled { background-color: #FCA5A5; color: #FFFFFF; }"
        )
        self.proceed_btn.setEnabled(False)  # 初期は無効
        self.proceed_btn.setDefault(False)
        self.proceed_btn.setAutoDefault(False)
        self.proceed_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.proceed_btn)

        outer.addLayout(btn_row)

    # ----------------------------------------------------------------
    # チェックボックス連動
    # ----------------------------------------------------------------
    def _on_understand_toggled(self, checked: bool) -> None:
        self.proceed_btn.setEnabled(checked)
