"""
phase3.gui.verify_panel: 検証モード用パネル(Step 2-B 本実装版・v2修正).

修正履歴:
  v1: 結果カード3パターン分岐
  v2: 修正
      - 中央コンテンツ領域を QScrollArea で包んでレイアウト圧縮を解消
        (結果カード追加時に file_label の文字が見切れる問題)
      - ワーカー参照のライフサイクルを安全化(_on_worker_finished で確実に
        参照を切る → ホームボタン押下時クラッシュを解消)
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QFrame, QSizePolicy, QScrollArea,
)

from .workers import VerifyWorker


class VerifyPanel(QWidget):
    """.jpkiimg コンテナを検証する検証モードのパネル(本実装)."""

    back_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("verifyPanel")
        self._file: Optional[Path] = None
        self._worker: Optional[VerifyWorker] = None
        self._result_card: Optional[QFrame] = None
        self._build_ui()

    # ============================================================
    # UI 構築
    # ============================================================
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 24, 40, 32)
        outer.setSpacing(12)

        # ---- ヘッダ(戻るボタン) ----
        header = QHBoxLayout()
        self.back_btn = QPushButton("← ホーム")
        self.back_btn.setObjectName("backButton")
        self.back_btn.clicked.connect(self._on_back_clicked)
        header.addWidget(self.back_btn)
        header.addStretch()
        outer.addLayout(header)

        # ---- タイトル ----
        title = QLabel("🔍 検証モード")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel(".jpkiimg コンテナの真正性(改ざんが無いか)を検証します")
        subtitle.setObjectName("statusLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(subtitle)

        # ---- 中央: スクロール可能エリア ----
        # 結果カードが大きくなっても上部の file_label が圧縮されないように
        # QScrollArea でラップする。
        scroll = QScrollArea(self)
        scroll.setObjectName("verifyScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        inner = QWidget()
        inner.setObjectName("verifyScrollInner")
        self._content_layout = QVBoxLayout(inner)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(12)

        # ファイル表示(中央コンテンツの先頭)
        self.file_label = QLabel("(ファイル未選択)")
        self.file_label.setObjectName("fileLabel")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.file_label.setWordWrap(True)
        self.file_label.setTextFormat(Qt.TextFormat.RichText)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._content_layout.addWidget(self.file_label)

        # 結果カードはここに insertWidget で挿入される(マーカ用 stretch を末尾に置く)
        self._content_layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)

        # ---- ステータス + プログレスバー(画面下部・常時表示) ----
        self.status_label = QLabel("「検証を開始」を押してください")
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

        # ---- 開始ボタン(画面下部・常時表示) ----
        self.start_btn = QPushButton("🔍 検証を開始")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setMinimumHeight(48)
        self.start_btn.clicked.connect(self._start_verification)
        outer.addWidget(self.start_btn)

    # ============================================================
    # 公開API: ファイルセット
    # ============================================================
    def set_file(self, path: Path) -> None:
        self._file = path
        self._stop_running_worker()
        self._clear_result_card()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self.file_label.setText(
            f"<div style='font-size:12pt'>📦 <b>{escape(path.name)}</b></div>"
            f"<div style='color:#6B7280; margin-top:4px'>{escape(str(path))}</div>"
            f"<div style='color:#6B7280; margin-top:4px'>サイズ: {size:,} bytes</div>"
        )
        self.status_label.setText("「検証を開始」を押してください")
        self.progress.hide()
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔍 検証を開始")

    # ============================================================
    # 戻る
    # ============================================================
    def _on_back_clicked(self) -> None:
        self._stop_running_worker()
        self.back_requested.emit()

    # ============================================================
    # 検証開始 / ワーカー管理
    # ============================================================
    def _start_verification(self) -> None:
        if not self._file:
            return

        self._stop_running_worker()
        self._clear_result_card()

        self.start_btn.setEnabled(False)
        self.start_btn.setText("検証中...")
        self.progress.show()
        self.status_label.setText("⏳ 検証中... PKCS#7 を解析しています")

        self._worker = VerifyWorker(self._file, parent=self)
        self._worker.result_ready.connect(self._on_result_ready)
        self._worker.error_occurred.connect(self._on_error_occurred)
        # finished で確実に参照をクリア(deleteLater は finished 経由で行う)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        """
        QThread.run() 終了時に呼ばれる。ここで:
          - シグナルを切断
          - deleteLater で C++ オブジェクト破棄を予約
          - self._worker 参照を None にして以後安全に
        """
        w = self._worker
        if w is None:
            return
        try:
            w.result_ready.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            w.error_occurred.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            w.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        w.deleteLater()
        self._worker = None

    def _stop_running_worker(self) -> None:
        """
        進行中ワーカーがあれば安全に切り離して破棄する。
        - 既に finished 済(self._worker is None)なら何もしない
        - 実行中ならシグナルを切ってから wait()
        """
        w = self._worker
        if w is None:
            return
        # 全シグナル切断 (RuntimeError は破棄済みオブジェクトの場合)
        for sig in (
            getattr(w, "result_ready", None),
            getattr(w, "error_occurred", None),
            getattr(w, "finished", None),
        ):
            if sig is None:
                continue
            try:
                sig.disconnect()
            except (TypeError, RuntimeError):
                pass

        try:
            running = w.isRunning()
        except RuntimeError:
            # 破棄済みオブジェクト
            self._worker = None
            return

        if running:
            w.requestInterruption()
            try:
                w.wait(2000)
            except RuntimeError:
                pass

        try:
            w.deleteLater()
        except RuntimeError:
            pass
        self._worker = None

    # ============================================================
    # 結果ハンドラ
    # ============================================================
    def _on_result_ready(self, result: dict) -> None:
        self.progress.hide()
        self.status_label.setText("")

        if result.get("error"):
            self._show_warning_card(result)
        elif result.get("valid"):
            self._show_success_card(result)
        else:
            self._show_error_card(result)

        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔍 もう一度検証")

    def _on_error_occurred(self, msg: str) -> None:
        self.progress.hide()
        self.status_label.setText("")
        self._show_warning_card({
            "error": msg,
            "error_kind": "unexpected",
            "image_name": None,
            "image_size": 0,
        })
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🔍 もう一度検証")

    # ============================================================
    # 結果カード生成 / 挿入
    # ============================================================
    def _clear_result_card(self) -> None:
        if self._result_card is not None:
            self._content_layout.removeWidget(self._result_card)
            self._result_card.deleteLater()
            self._result_card = None

    def _insert_card(self, card: QFrame) -> None:
        """結果カードを file_label の直後に挿入する."""
        file_index = self._content_layout.indexOf(self.file_label)
        insert_at = (file_index + 1) if file_index >= 0 else 0
        self._content_layout.insertWidget(insert_at, card)
        self._result_card = card

    def _make_card_frame(self, object_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setFrameShape(QFrame.Shape.NoFrame)
        # 縦方向は自然サイズ(コンテンツに合わせて伸びる)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        return frame

    # ---- 成功カード(緑) ----
    def _show_success_card(self, result: dict) -> None:
        card = self._make_card_frame("successCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("✅ 有効な署名です")
        title.setObjectName("cardTitleSuccess")
        layout.addWidget(title)

        signer_name   = result.get("signer_name") or "(取得失敗)"
        signer_source = result.get("signer_name_source", "unknown")
        signer_cn     = result.get("signer_cn")
        nvb = result.get("not_valid_before") or "?"
        nva = result.get("not_valid_after") or "?"
        image_name = result.get("image_name") or "?"
        image_size = result.get("image_size") or 0

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

        signer_cn_html = ""
        if signer_cn and signer_cn != signer_name:
            signer_cn_html = (
                f"<tr><td style='color:#6B7280; padding-right:12px'>識別符号:</td>"
                f"<td style='color:#6B7280'>{escape(signer_cn)}</td></tr>"
            )

        body_html = (
            "<table cellpadding='4'>"
            f"<tr>"
            f"<td style='color:#374151; padding-right:12px'><b>署名者:</b></td>"
            f"<td style='color:#10B981; font-weight:bold; font-size:13pt'>"
            f"{escape(signer_name)}</td>"
            f"</tr>"
            f"<tr><td></td><td>{source_html}</td></tr>"
            f"{signer_cn_html}"
            f"<tr>"
            f"<td style='color:#374151; padding-right:12px'><b>有効期間:</b></td>"
            f"<td>{escape(nvb)}<br>{escape(nva)}</td>"
            f"</tr>"
            f"<tr>"
            f"<td style='color:#374151; padding-right:12px'><b>画像:</b></td>"
            f"<td>{escape(str(image_name))} ({image_size:,} bytes)</td>"
            f"</tr>"
            "</table>"
        )
        body = QLabel(body_html)
        body.setObjectName("cardBody")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(body)

        note = QLabel("🛡️ 画像は署名生成時から1ビットも改変されていません。")
        note.setObjectName("cardSubtle")
        note.setStyleSheet("color: #047857;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._insert_card(card)

    # ---- 改ざん検知カード(赤) ----
    def _show_error_card(self, result: dict) -> None:
        card = self._make_card_frame("errorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("❌ 改ざんを検知しました")
        title.setObjectName("cardTitleError")
        layout.addWidget(title)

        body_html = (
            "<div style='font-size:11pt; color:#7F1D1D;'>"
            "画像と署名値が整合しません。<br>"
            "画像が署名生成時から変更されたか、別データで生成された署名の可能性があります。"
            "<br><br>"
            "<b>このコンテナは信頼できません。</b>"
            "</div>"
        )
        body = QLabel(body_html)
        body.setObjectName("cardBody")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(body)

        signer_name = result.get("signer_name")
        signer_cn   = result.get("signer_cn")
        ref_lines = []
        if signer_name:
            ref_lines.append(f"<b>証明書上の署名者(参考):</b> {escape(signer_name)}")
        if signer_cn and signer_cn != signer_name:
            ref_lines.append(f"<b>識別符号:</b> {escape(signer_cn)}")

        if ref_lines:
            ref_html = (
                "<div style='color:#6B7280; font-size:10pt;'>"
                + "<br>".join(ref_lines) + "</div>"
            )
            ref = QLabel(ref_html)
            ref.setObjectName("cardSubtle")
            ref.setTextFormat(Qt.TextFormat.RichText)
            ref.setWordWrap(True)
            layout.addWidget(ref)

        self._insert_card(card)

    # ---- 警告カード(橙) ----
    def _show_warning_card(self, result: dict) -> None:
        card = self._make_card_frame("warningCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel("⚠ 不正なコンテナです")
        title.setObjectName("cardTitleWarning")
        layout.addWidget(title)

        kind = result.get("error_kind") or "structural"
        kind_label = {
            "not_jpkiimg":    "ZIP として開けない / .jpkiimg として認識できない",
            "missing_entry":  "必須エントリ(target_image / signature.p7s / cert.der)が不足",
            "file_not_found": "ファイルが見つからない",
            "unexpected":     "想定外の例外が発生しました",
            "structural":     "コンテナ構造の異常",
        }.get(kind, "コンテナ構造の異常")

        err_msg = escape(str(result.get("error", "(詳細不明)")))
        body_html = (
            f"<div style='font-size:11pt; color:#78350F;'>"
            f"このファイルは .jpkiimg として正しく構造化されていません。<br><br>"
            f"<b>原因種別:</b> {escape(kind_label)}<br>"
            f"<b>エラー詳細:</b><br>"
            f"<span style='font-family:Consolas,monospace; color:#92400E'>{err_msg}</span>"
            f"</div>"
        )
        body = QLabel(body_html)
        body.setObjectName("cardBody")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(body)

        self._insert_card(card)
