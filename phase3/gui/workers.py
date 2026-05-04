"""
phase3.gui.workers: GUI からの非同期処理を担う QThread ワーカー群.

PyQt6 でブロッキング処理(検証・カード通信)を UI スレッドで動かすと
画面がフリーズするため、QThread + pyqtSignal で別スレッド化する。

Step 2-B: VerifyWorker (カード不要・検証専用)
Step 2-C: SignWorker (カード必要・PIN+署名+コンテナ作成) を追加予定
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QThread, QMutex, QWaitCondition, pyqtSignal


# ==============================================================
# VerifyWorker
# ==============================================================

class VerifyWorker(QThread):
    """
    .jpkiimg コンテナを別スレッドで検証する QThread.

    シグナル:
      result_ready(dict):
          検証完了(成功・改ざん・構造異常を含む)。
          辞書は phase2.crypto.verify.verify_signed_image の戻り値に
          image_name / image_size を追加した拡張版。
      error_occurred(str):
          想定外の例外発生時のみ。文字列は型名 + メッセージ。

    使い方:
        worker = VerifyWorker(Path("xxx.jpkiimg"))
        worker.result_ready.connect(on_result)
        worker.error_occurred.connect(on_error)
        worker.finished.connect(worker.deleteLater)  # 自動破棄
        worker.start()
    """

    result_ready    = pyqtSignal(dict)
    error_occurred  = pyqtSignal(str)

    def __init__(self, jpkiimg_path: Path, parent: Any = None):
        super().__init__(parent)
        self._path = Path(jpkiimg_path)

    # ---------------------------------------------------------------- run
    def run(self) -> None:
        # 遅延 import: ワーカースレッドで初回実行時にロード
        try:
            from phase2.container import (
                read_jpkiimg, NotJpkiImgError, MissingEntryError,
            )
            from phase2.crypto.verify import verify_signed_image
        except ImportError as e:
            self.error_occurred.emit(f"ImportError: {e}")
            return

        # ---- 1) ファイル存在 / コンテナ展開 ----
        try:
            image, image_name, p7s, cert = read_jpkiimg(self._path)
        except FileNotFoundError as e:
            self.result_ready.emit(self._error_result(
                error=f"FileNotFoundError: {e}",
                error_kind="file_not_found",
            ))
            return
        except NotJpkiImgError as e:
            self.result_ready.emit(self._error_result(
                error=f"NotJpkiImgError: {e}",
                error_kind="not_jpkiimg",
            ))
            return
        except MissingEntryError as e:
            self.result_ready.emit(self._error_result(
                error=f"MissingEntryError: {e}",
                error_kind="missing_entry",
            ))
            return
        except Exception as e:
            # 想定外: error_occurred 経由で通知
            self.error_occurred.emit(
                f"{type(e).__name__}: {e}  (read_jpkiimg)"
            )
            return

        # ---- 2) PKCS#7 検証 + 署名者抽出 ----
        try:
            result = verify_signed_image(image, p7s)
        except Exception as e:
            self.error_occurred.emit(
                f"{type(e).__name__}: {e}  (verify_signed_image)"
            )
            return

        # ---- 3) 補助情報を結果に追加 ----
        # GUI 側で表示しやすいよう、画像メタも詰めて返す
        result_dict: dict = dict(result)
        result_dict["image_name"] = image_name
        result_dict["image_size"] = len(image)
        result_dict["jpkiimg_path"] = str(self._path)
        result_dict["error_kind"]  = "structural" if result_dict.get("error") else None

        self.result_ready.emit(result_dict)

    # ---------------------------------------------------------------- 内部ヘルパ
    def _error_result(self, error: str, error_kind: str) -> dict:
        """構造異常時の戻り値辞書を組み立てる(verify_signed_imageと互換形式)."""
        return {
            "valid": False,
            "signer_name": None,
            "signer_name_source": "unknown",
            "signer_cn": None,
            "not_valid_before": None,
            "not_valid_after": None,
            "error": error,
            "error_kind": error_kind,
            "image_name": None,
            "image_size": 0,
            "jpkiimg_path": str(self._path),
        }


# ==============================================================
# SignWorker
# ==============================================================

class SignWorker(QThread):
    """
    画像 → JPKI署名 → .jpkiimg 出力 を別スレッドで実行する QThread.

    シグナル:
      stage_started(str):
          各処理ステップの開始を通知。UIは status_label を更新する。
      pin_needed(int):
          PIN入力が必要になった。引数は残回数。
          UIスレッドで PinDialog を開き、provide_pin() を呼ぶ責務がある。
      result_ready(dict):
          署名完了。output_path / signer_name / 各種サイズ等を含む。
      error_occurred(str, str):
          エラー発生。第1引数=種別キー、第2引数=詳細メッセージ。
          種別: 'no_reader' / 'card_error' / 'pin_locked' / 'pin_failed' /
                'pin_risk' / 'cancelled' / 'unexpected'

    PIN同期(QMutex + QWaitCondition):
        run() は pin_needed を発火した後、_pin_condition で待機する。
        UIから provide_pin(str|None) が呼ばれると wakeAll される。
        None は「キャンセル」を意味する。
    """

    stage_started   = pyqtSignal(str)
    pin_needed      = pyqtSignal(int)
    result_ready    = pyqtSignal(dict)
    error_occurred  = pyqtSignal(str, str)

    def __init__(
        self,
        image_path: Path,
        output_path: Path,
        parent: Any = None,
    ):
        super().__init__(parent)
        self._image_path  = Path(image_path)
        self._output_path = Path(output_path)

        # PIN exchange synchronization
        self._pin_mutex     = QMutex()
        self._pin_condition = QWaitCondition()
        self._pin_bytes:     Optional[bytearray] = None  # PIN as bytearray
        self._pin_provided:  bool = False
        self._pin_cancelled: bool = False

    # ============================================================
    # UIスレッドから呼ばれる API
    # ============================================================
    def provide_pin(self, pin_str: Optional[str]) -> None:
        """
        PIN入力結果をワーカースレッドへ受け渡す。

        Args:
            pin_str: 入力されたPIN文字列。None なら「キャンセル」。
        """
        self._pin_mutex.lock()
        try:
            if pin_str is None:
                self._pin_cancelled = True
                self._pin_bytes = None
            else:
                # 即座に bytearray に変換(後でゼロクリア可能にするため)
                self._pin_bytes = bytearray(pin_str.encode("ascii"))
            self._pin_provided = True
            self._pin_condition.wakeAll()
        finally:
            self._pin_mutex.unlock()

    def cancel(self) -> None:
        """
        ホーム遷移等のために、ワーカーを安全にキャンセルする。
        - PIN待ち中なら即座に解除
        - 進行中なら interruption を要求(APDU途中ならそこまでは続行)
        """
        self.requestInterruption()
        self._pin_mutex.lock()
        try:
            self._pin_cancelled = True
            self._pin_provided  = True
            self._pin_bytes     = None
            self._pin_condition.wakeAll()
        finally:
            self._pin_mutex.unlock()

    # ============================================================
    # run(): ワーカースレッド本体
    # ============================================================
    def run(self) -> None:
        # 遅延 import (ワーカースレッド初回起動時にロード)
        try:
            from phase2.jpki import (
                JpkiSession, build_digest_info_sha256,
                JpkiNoReaderError, JpkiCardError,
                JpkiPinLockedError, JpkiPinFailedError, JpkiPinRiskError,
                JpkiPinNotVerifiedError,
            )
            from phase2.crypto import build_p7s, trim_der
            from phase2.crypto.verify import extract_signer_name
            from phase2.container import create_jpkiimg
            from cryptography import x509
        except ImportError as e:
            self.error_occurred.emit("unexpected", f"ImportError: {e}")
            return

        # ============== Stage 1: 画像読み込み ==============
        try:
            self.stage_started.emit("[1/8] 画像を読み込み中...")
            image_bytes = self._image_path.read_bytes()
        except FileNotFoundError as e:
            self.error_occurred.emit("unexpected", f"画像ファイルが見つかりません: {e}")
            return
        except OSError as e:
            self.error_occurred.emit("unexpected", f"画像読み込み失敗: {e}")
            return

        if self.isInterruptionRequested():
            self.error_occurred.emit("cancelled", "キャンセルされました")
            return

        # ============== Stage 2〜8: JPKIセッション内で実行 ==============
        try:
            self.stage_started.emit("[2/8] JPKIカードに接続中...")
            with JpkiSession() as session:
                if self.isInterruptionRequested():
                    self.error_occurred.emit("cancelled", "キャンセルされました")
                    return

                # ---- Stage 3: PIN残回数確認 + 安全装置 ----
                self.stage_started.emit("[3/8] PIN残回数を確認中...")
                try:
                    remaining = session.assert_safe_to_attempt_pin()
                except JpkiPinLockedError as e:
                    self.error_occurred.emit("pin_locked", str(e))
                    return
                except JpkiPinRiskError as e:
                    self.error_occurred.emit("pin_risk", str(e))
                    return

                if self.isInterruptionRequested():
                    self.error_occurred.emit("cancelled", "キャンセルされました")
                    return

                # ---- Stage 4: PIN入力要求 (UIスレッドへ) ----
                self.stage_started.emit("[4/8] PIN入力をお待ちしています...")
                self.pin_needed.emit(remaining if remaining is not None else 0)

                # PIN受領まで待機
                self._pin_mutex.lock()
                try:
                    while not self._pin_provided:
                        self._pin_condition.wait(self._pin_mutex)
                    pin_bytes  = self._pin_bytes
                    cancelled  = self._pin_cancelled
                    # ローカル変数にコピー後、共有領域はクリア
                    self._pin_bytes = None
                    self._pin_provided = False
                finally:
                    self._pin_mutex.unlock()

                if cancelled or pin_bytes is None:
                    if pin_bytes is not None:
                        # 念のためゼロクリア
                        for i in range(len(pin_bytes)):
                            pin_bytes[i] = 0
                    self.error_occurred.emit("cancelled", "ユーザーによりキャンセルされました")
                    return

                # ---- Stage 5: VERIFY PIN ----
                self.stage_started.emit("[5/8] PIN認証中...")
                try:
                    # JpkiSession.verify_pin は str を受け取るため、
                    # bytearray から一時的に str を作って渡す。
                    # JpkiSession 内部でも bytearray化+ゼロクリアが行われる。
                    pin_str_tmp = bytes(pin_bytes).decode("ascii")
                    try:
                        session.verify_pin(pin_str_tmp)
                    finally:
                        # 一時 str はimmutableで完全消去不可だが
                        # 参照を切ることで GC 候補化
                        del pin_str_tmp
                except JpkiPinFailedError as e:
                    self.error_occurred.emit(
                        "pin_failed",
                        f"PIN認証失敗。残回数 {e.remaining} 回。本ツールは安全のため再試行しません。"
                    )
                    return
                except JpkiPinLockedError as e:
                    self.error_occurred.emit("pin_locked", str(e))
                    return
                except ValueError as e:
                    self.error_occurred.emit("unexpected", f"PIN形式エラー: {e}")
                    return
                finally:
                    # bytearray ゼロクリア (常時)
                    if pin_bytes is not None:
                        for i in range(len(pin_bytes)):
                            pin_bytes[i] = 0
                    pin_bytes = None  # type: ignore

                if self.isInterruptionRequested():
                    self.error_occurred.emit("cancelled", "キャンセルされました")
                    return

                # ---- Stage 6: DigestInfo + 署名取得 ----
                self.stage_started.emit("[6/8] 署名値を計算中... (SHA-256 → DigestInfo → COMPUTE DIGITAL SIGNATURE)")
                digest_info = build_digest_info_sha256(image_bytes)
                signature = session.sign_digest_info(digest_info)

                if self.isInterruptionRequested():
                    self.error_occurred.emit("cancelled", "キャンセルされました")
                    return

                # ---- Stage 7: 署名用証明書 読み出し ----
                self.stage_started.emit("[7/8] 署名用電子証明書を読み出し中...")
                cert_raw = session.read_sign_certificate()
                cert_der = trim_der(cert_raw)

                if self.isInterruptionRequested():
                    self.error_occurred.emit("cancelled", "キャンセルされました")
                    return

                # ---- Stage 8: PKCS#7 + コンテナ作成 ----
                self.stage_started.emit("[8/8] PKCS#7 構築 + .jpkiimg コンテナ作成中...")
                p7s = build_p7s(signature=signature, cert_der=cert_der)
                create_jpkiimg(
                    image_path=self._image_path,
                    p7s_bytes=p7s,
                    cert_der_bytes=cert_der,
                    output_path=self._output_path,
                )

                # ---- 成功: 結果を組み立て ----
                cert_obj = x509.load_der_x509_certificate(cert_der)
                signer_name, signer_source = extract_signer_name(cert_obj)

                result_dict = {
                    "output_path":           str(self._output_path),
                    "image_path":            str(self._image_path),
                    "image_size":            len(image_bytes),
                    "signature_size":        len(signature),
                    "cert_der_size":         len(cert_der),
                    "p7s_size":              len(p7s),
                    "container_size":        self._output_path.stat().st_size,
                    "signer_name":           signer_name,
                    "signer_name_source":    signer_source,
                    "remaining_pin_attempts_before": remaining,
                }
                self.result_ready.emit(result_dict)

        except JpkiNoReaderError as e:
            self.error_occurred.emit(
                "no_reader",
                f"ICカードリーダーが見つかりません。\nUSB接続とリーダー認識を確認してください。\n\n詳細: {e}"
            )
        except JpkiCardError as e:
            sw = f" (SW={e.sw_hex})" if getattr(e, "sw_hex", None) else ""
            self.error_occurred.emit(
                "card_error",
                f"カード通信エラー: {e}{sw}"
            )
        except JpkiPinNotVerifiedError as e:
            self.error_occurred.emit("unexpected", f"内部不整合: {e}")
        except Exception as e:
            self.error_occurred.emit("unexpected", f"{type(e).__name__}: {e}")
