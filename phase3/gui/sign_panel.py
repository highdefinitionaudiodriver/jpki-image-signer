"""
phase3.gui.sign_panel: 署名モード用パネル(Step 2-C 本実装版).

責務:
  - 画像ファイルパスを受け取って表示
  - 「署名を開始」ボタンで SignWorker を起動 (QThread)
  - ワーカーからの pin_needed シグナルで PinDialog を開き、PINをワーカーへ返却
  - 結果に応じた緑/赤/橙カードUIを表示
  - 成功時には「出力先フォルダを開く」ボタンを提供
"""
from __future__ import annotations

import os
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QFrame, QSizePolicy, QScrollArea,
)

from .workers import SignWorker
from .pin_dialog import PinDialog
from .privacy_warning_dialog import PrivacyWarningDialog


class SignPanel(QWidget):
    """画像 → JPKI署名 → .jpkiimg を生成する署名モードのパネル(本実装)."""

    back_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("signPanel")
        self._image_path: Optional[Path] = None
        self._output_path: Optional[Path] = None
        self._worker: Optional[SignWorker] = None
        self._result_card: Optional[QFrame] = None
        self._build_ui()

    # ============================================================
    # UI 構築 (verify_panel と同じ ScrollArea 構造)
    # ============================================================
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 24, 40, 32)
        outer.setSpacing(12)

        # ---- ヘッダ ----
        header = QHBoxLayout()
        self.back_btn = QPushButton("← ホーム")
        self.back_btn.setObjectName("backButton")
        self.back_btn.clicked.connect(self._on_back_clicked)
        header.addWidget(self.back_btn)
        header.addStretch()
        outer.addLayout(header)

        # ---- タイトル ----
        title = QLabel("📝 署名モード")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("マイナンバーカードで画像に電子署名し、.jpkiimg を生成します")
        subtitle.setObjectName("statusLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(subtitle)

        # ---- 中央スクロール領域 ----
        scroll = QScrollArea(self)
        scroll.setObjectName("verifyScroll")  # styles.py の同じスタイルを流用
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        inner = QWidget()
        inner.setObjectName("verifyScrollInner")
        self._content_layout = QVBoxLayout(inner)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(12)

        self.file_label = QLabel("(ファイル未選択)")
        self.file_label.setObjectName("fileLabel")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.file_label.setWordWrap(True)
        self.file_label.setTextFormat(Qt.TextFormat.RichText)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._content_layout.addWidget(self.file_label)
        self._content_layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)

        # ---- ステータス + プログレスバー ----
        self.status_label = QLabel("「署名を開始」を押してください")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setObjectName("progressBar")
        self.progress.setRange(0, 0)
        self.progress.setMaximumHeight(8)
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)

        # ---- 開始ボタン ----
        self.start_btn = QPushButton("🔐 署名を開始")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setMinimumHeight(48)
        self.start_btn.clicked.connect(self._start_signing)
        outer.addWidget(self.start_btn)

    # ============================================================
    # 公開API: ファイルセット
    # ============================================================
    def set_file(self, path: Path) -> None:
        self._image_path = path
        # 出力先: 同じディレクトリ・元ファイル名 + .jpkiimg
        self._output_path = path.with_name(path.name + ".jpkiimg")
        self._stop_running_worker()
        self._clear_result_card()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self.file_label.setText(
            f"<div style='font-size:12pt'>📄 <b>{escape(path.name)}</b></div>"
            f"<div style='color:#6B7280; margin-top:4px'>{escape(str(path))}</div>"
            f"<div style='color:#6B7280; margin-top:4px'>サイズ: {size:,} bytes&nbsp;&nbsp;|&nbsp;&nbsp;拡張子: {path.suffix}</div>"
            f"<div style='color:#6B7280; margin-top:8px'>"
            f"出力先(予定): <span style='color:#3B82F6'>{escape(str(self._output_path))}</span>"
            f"</div>"
        )
        self.status_label.setText("「署名を開始」を押してください")
        self.progress.hide()
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔐 署名を開始")

    # ============================================================
    # ホームに戻る
    # ============================================================
    def _on_back_clicked(self) -> None:
        self._stop_running_worker()
        self.back_requested.emit()

    # ============================================================
    # 署名開始 / ワーカー管理
    # ============================================================
    def _start_signing(self) -> None:
        if self._image_path is None or self._output_path is None:
            return

        # ★ 署名処理開始の前に必ず プライバシー警告 を通す ★
        # 生成される .jpkiimg は氏名・住所・生年月日・性別を含むため、
        # ユーザーがこの事実を認識した上で進むことを保証する。
        from PyQt6.QtWidgets import QDialog
        warning = PrivacyWarningDialog(parent=self)
        if warning.exec() != QDialog.DialogCode.Accepted:
            self.status_label.setText(
                "<span style='color:#6B7280'>"
                "プライバシー警告でキャンセルされました(個人情報保護のため処理を中断)"
                "</span>"
            )
            return

        self._stop_running_worker()
        self._clear_result_card()

        self.start_btn.setEnabled(False)
        self.start_btn.setText("処理中...")
        self.progress.show()
        self.status_label.setText("⏳ 開始しています...")

        self._worker = SignWorker(
            self._image_path, self._output_path, parent=self
        )
        self._worker.stage_started.connect(self._on_stage_started)
        self._worker.pin_needed.connect(self._on_pin_needed)
        self._worker.result_ready.connect(self._on_result_ready)
        self._worker.error_occurred.connect(self._on_error_occurred)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        w = self._worker
        if w is None:
            return
        for sig_name in ("stage_started", "pin_needed", "result_ready",
                         "error_occurred", "finished"):
            sig = getattr(w, sig_name, None)
            if sig is None:
                continue
            try:
                sig.disconnect()
            except (TypeError, RuntimeError):
                pass
        try:
            w.deleteLater()
        except RuntimeError:
            pass
        self._worker = None

    def _stop_running_worker(self) -> None:
        w = self._worker
        if w is None:
            return
        for sig_name in ("stage_started", "pin_needed", "result_ready",
                         "error_occurred", "finished"):
            sig = getattr(w, sig_name, None)
            if sig is None:
                continue
            try:
                sig.disconnect()
            except (TypeError, RuntimeError):
                pass

        try:
            running = w.isRunning()
        except RuntimeError:
            self._worker = None
            return

        if running:
            try:
                w.cancel()  # PIN待ち中なら即解除
                w.wait(5000)
            except RuntimeError:
                pass

        try:
            w.deleteLater()
        except RuntimeError:
            pass
        self._worker = None

    # ============================================================
    # ステージ進捗
    # ============================================================
    def _on_stage_started(self, msg: str) -> None:
        self.status_label.setText(f"⏳ {escape(msg)}")

    # ============================================================
    # PIN要求 → PinDialog → ワーカーへ返却
    # ============================================================
    def _on_pin_needed(self, remaining: int) -> None:
        self.status_label.setText("🔐 PIN入力ダイアログを表示しています...")

        dlg = PinDialog(remaining, parent=self)
        pin_str = dlg.get_pin()  # キャンセル時は None
        # ダイアログオブジェクトはここでスコープ外、内部のpin_input.clear() は実行済

        if self._worker is None:
            # ホーム遷移等で worker が消えていた場合
            return
        # ワーカーへ受け渡す(provide_pin が PIN を bytearray化して保持)
        try:
            self._worker.provide_pin(pin_str)
        except RuntimeError:
            # worker が破棄されていた場合
            pass
        finally:
            # PIN文字列の参照を切る
            del pin_str

    # ============================================================
    # 結果ハンドラ
    # ============================================================
    def _on_result_ready(self, result: dict) -> None:
        self.progress.hide()
        self.status_label.setText("")
        self._show_success_card(result)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔐 もう一度署名する")

    def _on_error_occurred(self, kind: str, msg: str) -> None:
        self.progress.hide()
        self.status_label.setText("")

        if kind == "cancelled":
            # キャンセルは控えめに表示
            self.status_label.setText(
                "<span style='color:#6B7280'>キャンセルされました</span>"
            )
            self.start_btn.setEnabled(True)
            self.start_btn.setText("🔐 署名を開始")
            return

        if kind in ("pin_locked", "pin_failed"):
            severity = "error"   # 赤
        elif kind in ("pin_risk", "no_reader", "card_error"):
            severity = "warning"  # 橙
        else:
            severity = "warning"  # 想定外も橙

        self._show_failure_card(kind, msg, severity)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔐 もう一度署名する")

    # ============================================================
    # 結果カード生成
    # ============================================================
    def _clear_result_card(self) -> None:
        if self._result_card is not None:
            self._content_layout.removeWidget(self._result_card)
            self._result_card.deleteLater()
            self._result_card = None

    def _insert_card(self, card: QFrame) -> None:
        file_index = self._content_layout.indexOf(self.file_label)
        insert_at = (file_index + 1) if file_index >= 0 else 0
        self._content_layout.insertWidget(insert_at, card)
        self._result_card = card

    def _make_card_frame(self, object_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        return frame

    # ---- 成功カード(緑) ----
    def _show_success_card(self, result: dict) -> None:
        card = self._make_card_frame("successCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("✅ 署名完了")
        title.setObjectName("cardTitleSuccess")
        layout.addWidget(title)

        signer_name   = result.get("signer_name") or "(取得失敗)"
        signer_source = result.get("signer_name_source", "unknown")
        out_path      = result.get("output_path") or "?"
        container_size = result.get("container_size") or 0
        image_size    = result.get("image_size") or 0
        signature_size = result.get("signature_size") or 0
        cert_size     = result.get("cert_der_size") or 0
        p7s_size      = result.get("p7s_size") or 0

        if signer_source == "san_jpki_other_name":
            source_html = (
                "<span style='color:#10B981'>"
                "(JPKI規格 SAN OtherName より取得)</span>"
            )
        elif signer_source == "san_directory_name":
            source_html = (
                "<span style='color:#6B7280'>"
                "(SAN内 DirectoryName より取得)</span>"
            )
        elif signer_source == "subject_cn":
            source_html = (
                "<span style='color:#F59E0B'>"
                "(SAN氏名OID未検出 → Subject CN フォールバック)</span>"
            )
        else:
            source_html = "<span style='color:#6B7280'>(取得元不明)</span>"

        body_html = (
            "<table cellpadding='4'>"
            f"<tr>"
            f"<td style='color:#374151; padding-right:12px'><b>署名者:</b></td>"
            f"<td style='color:#10B981; font-weight:bold; font-size:13pt'>{escape(signer_name)}</td>"
            f"</tr>"
            f"<tr><td></td><td>{source_html}</td></tr>"
            f"<tr>"
            f"<td style='color:#374151; padding-right:12px'><b>出力ファイル:</b></td>"
            f"<td style='color:#3B82F6'>{escape(out_path)}</td>"
            f"</tr>"
            f"<tr>"
            f"<td style='color:#374151; padding-right:12px'><b>コンテナサイズ:</b></td>"
            f"<td>{container_size:,} bytes</td>"
            f"</tr>"
            f"<tr>"
            f"<td style='color:#6B7280; padding-right:12px; font-size:9pt'>内訳(参考):</td>"
            f"<td style='color:#6B7280; font-size:9pt'>"
            f"画像 {image_size:,}B / 署名 {signature_size}B / 証明書 {cert_size:,}B / PKCS#7 {p7s_size:,}B"
            f"</td>"
            f"</tr>"
            "</table>"
        )
        body = QLabel(body_html)
        body.setObjectName("cardBody")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(body)

        # 注意書き
        notice = QLabel(
            "🛡️ 出力ファイルには署名者の氏名・住所・生年月日等の個人情報が含まれます。"
            "公開リポジトリへのアップロード等にご注意ください。"
        )
        notice.setObjectName("cardSubtle")
        notice.setStyleSheet("color: #047857; font-size: 9pt;")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        # 出力先フォルダを開くボタン
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        open_btn = QPushButton("📂 出力先フォルダを開く")
        open_btn.setObjectName("backButton")
        open_btn.setMinimumHeight(36)
        open_btn.clicked.connect(self._open_output_folder)
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

        self._insert_card(card)

    # ---- 失敗カード(赤 or 橙) ----
    def _show_failure_card(self, kind: str, msg: str, severity: str) -> None:
        if severity == "error":
            object_name = "errorCard"
            title_object_name = "cardTitleError"
            title_text = self._title_for_error_kind(kind)
            text_color = "#7F1D1D"
        else:  # warning
            object_name = "warningCard"
            title_object_name = "cardTitleWarning"
            title_text = self._title_for_error_kind(kind)
            text_color = "#78350F"

        card = self._make_card_frame(object_name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel(title_text)
        title.setObjectName(title_object_name)
        layout.addWidget(title)

        body_html = (
            f"<div style='font-size:11pt; color:{text_color};'>"
            f"<b>原因種別:</b> {escape(kind)}<br><br>"
            f"<b>詳細メッセージ:</b><br>"
            f"<span style='font-family:Consolas,monospace'>{escape(msg)}</span>"
            f"</div>"
        )
        body = QLabel(body_html)
        body.setObjectName("cardBody")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(body)

        # 種別ごとの追加ガイダンス
        guidance = self._guidance_for_error_kind(kind)
        if guidance:
            g = QLabel(f"<div style='color:{text_color}; font-size:10pt;'>{guidance}</div>")
            g.setObjectName("cardSubtle")
            g.setTextFormat(Qt.TextFormat.RichText)
            g.setWordWrap(True)
            layout.addWidget(g)

        self._insert_card(card)

    def _title_for_error_kind(self, kind: str) -> str:
        return {
            "no_reader":   "⚠ ICカードリーダーが見つかりません",
            "card_error":  "⚠ カード通信エラー",
            "pin_locked":  "❌ 署名用PINがロックされています",
            "pin_failed":  "❌ PIN認証失敗",
            "pin_risk":    "⚠ 安全装置作動 (PIN残回数<3)",
            "unexpected":  "⚠ 想定外のエラー",
        }.get(kind, "⚠ エラー")

    def _guidance_for_error_kind(self, kind: str) -> str:
        return {
            "pin_locked":
                "<b>市区町村窓口での初期化が必要です。</b> "
                "本人確認書類を持参のうえ、住民登録の自治体へお問い合わせください。",
            "pin_failed":
                "PINを正確に入力してから「もう一度署名する」を押してください。"
                "失敗が続くとロックされます。",
            "pin_risk":
                "残回数が安全閾値を下回っています。"
                "PINを完全に把握しているか確認してから再実行してください。",
            "no_reader":
                "リーダーをUSB接続し、SCardSvrサービスが起動しているか確認してください。",
            "card_error":
                "カードを抜き差しする / リーダーを再接続する / アプリを再起動するなどお試しください。",
        }.get(kind, "")

    # ============================================================
    # 出力先フォルダを開く (Windows: explorer /select)
    # ============================================================
    def _open_output_folder(self) -> None:
        if self._output_path is None or not Path(self._output_path).exists():
            return

        path = Path(self._output_path)
        try:
            if sys.platform == "win32":
                # ファイル選択した状態でエクスプローラを開く
                subprocess.run(
                    ["explorer", "/select,", str(path)],
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                # フォールバック: 親フォルダを開く
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
