"""
Phase 1 / Step 3: 署名用PIN認証 + ダミーデータへの署名 + 署名用証明書の読出

==== 安全ポリシー(厳守事項) ====
  1. 2段階実行:
       - --check-only オプションが指定された場合: PIN残回数の確認のみ行い終了
       - デフォルト動作:        残回数を確認後、yes/no確認を経てから本番VERIFYに進む
  2. 安全装置:        残回数 < 3 で自動 sys.exit (ロック防止)
  3. PIN入力の隠蔽:   getpass で画面非表示入力
  4. メモリ上の安全:  PINは bytearray に格納し、APDU送信直後にゼロクリア + del
  5. シングルセッション: VERIFY → 署名 → 署名用証明書読出を 1 接続内で完結

==== 出力ファイル ====
  - signature_dummy.bin : SHA-256("test123") に対するJPKI RSA-2048署名(256B)
  - sign_cert.der       : 署名用電子証明書(DER) ※氏名・住所等を含むため取扱注意

==== 実行例 ====
  py -3.12 test_03_sign.py --check-only   # 残回数確認のみ(消費なし・安全)
  py -3.12 test_03_sign.py                # 本番(PIN入力あり)
"""
import sys
import argparse
import getpass
import hashlib
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from smartcard.System import readers
    from smartcard.util import toHexString
    from smartcard.Exceptions import NoCardException, CardConnectionException
except ImportError:
    print("ERROR: pyscard がインストールされていません。", file=sys.stderr)
    print("       py -3.12 -m pip install pyscard を実行してください。", file=sys.stderr)
    sys.exit(1)


# ============================================================
# APDU 定数
# ============================================================
# JPKI AP (AID: D3 92 F0 00 26 01 00 00 00 01)
SELECT_JPKI_AP = [
    0x00, 0xA4, 0x04, 0x0C, 0x0A,
    0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x01,
]
# 署名用PIN EF       (FID = 0x001B)
SELECT_SIGN_PIN_EF  = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x00, 0x1B]
# 署名用秘密鍵 EF    (FID = 0x001A)
SELECT_SIGN_KEY_EF  = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x00, 0x1A]
# 署名用証明書 EF    (FID = 0x0001)
SELECT_SIGN_CERT_EF = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x00, 0x01]
# VERIFY 残回数確認 APDU バリエーション
# カード/リーダーの APDU 解釈差異を吸収するため複数試す。
# 順に送信して 63Cx (=残x回) または 9000/6983 が返ったらそれを採用。
# 6700 (Wrong length) や 6A86/6A87 (パラメータ不正) は次の variant を試す。
VERIFY_REMAINING_VARIANTS = [
    # ISO 7816 Case 1: ヘッダのみ4バイト(最も標準的)
    ([0x00, 0x20, 0x00, 0x80], "Case1 4-byte"),
    # Case 2/3 相当: 末尾に 0x00 (Lc=0 or Le=0 解釈)
    ([0x00, 0x20, 0x00, 0x80, 0x00], "Case3 Lc=0 5-byte"),
]

# DigestInfo prefix for SHA-256 (PKCS#1 v1.5 構造の固定プレフィックス)
# 全体 = 19 バイト + 32 バイト(SHA-256ダイジェスト) = 51 バイト
DIGEST_INFO_PREFIX_SHA256 = bytes([
    0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01,
    0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20,
])

OUTPUT_SIG  = "signature_dummy.bin"
OUTPUT_CERT = "sign_cert.der"
READ_CHUNK = 0xE0       # 224バイト
MAX_CERT_SIZE = 0x4000  # 16KB安全弁

MIN_SAFE_REMAINING = 3  # この回数未満なら自動中止


# ============================================================
# APDU ヘルパ
# ============================================================
def transmit_strict(conn, apdu, label):
    """SW=9000 を期待。違ったら例外。"""
    data, sw1, sw2 = conn.transmit(apdu)
    extra = " DATA=" + toHexString(data) if data else ""
    print(f"  [{label}] SW={sw1:02X}{sw2:02X}{extra}")
    if (sw1, sw2) != (0x90, 0x00):
        raise RuntimeError(f"{label} 失敗: SW={sw1:02X}{sw2:02X}")
    return data


def check_pin_remaining(conn):
    """
    署名用PIN EF を SELECT し、データ無し VERIFY で残回数を取得する。
    試行回数は消費しない(認証段階に到達していないため)。

    複数のAPDUバリエーションを試して、カード固有の解釈差異を吸収する。

    戻り値:
      int : 残回数(0=ロック、1〜5=残試行)
      None: どのバリアントでも残回数を取得できなかった(カード仕様外の可能性)
    """
    transmit_strict(conn, SELECT_SIGN_PIN_EF, "SELECT 署名用PIN EF")

    last_sw = None
    for apdu, label in VERIFY_REMAINING_VARIANTS:
        data, sw1, sw2 = conn.transmit(apdu)
        print(f"  [VERIFY 残回数確認 / {label}] APDU={toHexString(apdu)}  SW={sw1:02X}{sw2:02X}")
        last_sw = (sw1, sw2)

        # 残回数を含む応答
        if sw1 == 0x63 and (sw2 & 0xF0) == 0xC0:
            return sw2 & 0x0F

        # ロック済み
        if (sw1, sw2) == (0x69, 0x83):
            return 0

        # 既に認証済(通常は新規セッションでは発生しない)
        if (sw1, sw2) == (0x90, 0x00):
            print("  [INFO] 9000 応答(既に認証済?)残回数は取得できません。")
            return None

        # APDU長/パラメータ不正系: 次のバリエーションを試す
        if (sw1, sw2) in [(0x67, 0x00), (0x6A, 0x86), (0x6A, 0x87), (0x6B, 0x00)]:
            print(f"     → このバリエーションは未対応。次を試行します。")
            continue

        # それ以外の想定外SWは安全のため例外
        raise RuntimeError(f"残回数取得 想定外SW: {sw1:02X}{sw2:02X}")

    # 全バリエーション試行後も成立しなかった
    print(f"  [WARN] 全バリエーションで残回数取得失敗(最終SW={last_sw[0]:02X}{last_sw[1]:02X})")
    return None


def verify_pin(conn, pin_bytes):
    """
    PIN認証。pin_bytes は ASCII bytearray/bytes。
    戻り値: (ok: bool, remaining: int|None)
      ok=True  : 認証成功
      ok=False : 認証失敗(remaining=0でロック、>0で残回数)
    """
    apdu = [0x00, 0x20, 0x00, 0x80, len(pin_bytes)] + list(pin_bytes)
    data, sw1, sw2 = conn.transmit(apdu)
    print(f"  [VERIFY PIN] SW={sw1:02X}{sw2:02X}")

    if (sw1, sw2) == (0x90, 0x00):
        return True, None
    if sw1 == 0x63 and (sw2 & 0xF0) == 0xC0:
        return False, sw2 & 0x0F
    if (sw1, sw2) == (0x69, 0x83):
        return False, 0
    raise RuntimeError(f"VERIFY PIN 想定外SW: {sw1:02X}{sw2:02X}")


def compute_digital_signature(conn, digest_info):
    """COMPUTE DIGITAL SIGNATURE (80 2A 00 80) を実行し署名値(256B)を返す。"""
    apdu = ([0x80, 0x2A, 0x00, 0x80, len(digest_info)]
            + list(digest_info) + [0x00])
    data, sw1, sw2 = conn.transmit(apdu)

    # 6Cxx: Le不一致 → sw2の値で再試行(JPKIではほぼ発生しないが防御的に)
    if sw1 == 0x6C:
        apdu[-1] = sw2
        data, sw1, sw2 = conn.transmit(apdu)

    if (sw1, sw2) != (0x90, 0x00):
        raise RuntimeError(f"COMPUTE DIGITAL SIGNATURE 失敗: SW={sw1:02X}{sw2:02X}")
    print(f"  [COMPUTE DIGITAL SIGNATURE] SW=9000  ({len(data)} bytes)")
    return bytes(data)


def read_binary_all(conn):
    """READ BINARY を offset を進めながら呼び EF全体を取得(test_02 と同等)。"""
    out = bytearray()
    offset = 0
    while True:
        if offset >= MAX_CERT_SIZE:
            raise RuntimeError(f"オフセットが安全上限 {MAX_CERT_SIZE} を超えました。")
        p1 = (offset >> 8) & 0x7F
        p2 = offset & 0xFF
        apdu = [0x00, 0xB0, p1, p2, READ_CHUNK]
        data, sw1, sw2 = conn.transmit(apdu)

        if (sw1, sw2) == (0x90, 0x00):
            out.extend(data)
            print(f"  READ BINARY @offset=0x{offset:04X}  bytes={len(data)}  SW=9000")
            if len(data) < READ_CHUNK:
                break
            offset += len(data)
        elif sw1 == 0x6C:
            apdu[4] = sw2
            data, sw1b, sw2b = conn.transmit(apdu)
            if (sw1b, sw2b) != (0x90, 0x00):
                raise RuntimeError(
                    f"READ BINARY (6C再試行) 失敗: SW={sw1b:02X}{sw2b:02X}"
                )
            out.extend(data)
            print(f"  READ BINARY @offset=0x{offset:04X}  bytes={len(data)}  SW=9000 (6C再試行)")
            break
        elif (sw1, sw2) == (0x6B, 0x00):
            break
        else:
            raise RuntimeError(f"READ BINARY 失敗: SW={sw1:02X}{sw2:02X}")

    return bytes(out)


# ============================================================
# main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Phase 1 / Step 3: 署名用PIN認証 + ダミー署名 + 署名用証明書読出"
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="PIN残回数の確認のみ実行する(VERIFY/署名は行わない、最も安全)",
    )
    args = parser.parse_args()

    print("=" * 60)
    if args.check_only:
        print(" Phase 1 / Step 3 : PIN残回数確認のみ (消費なし・安全)")
    else:
        print(" Phase 1 / Step 3 : 署名用PIN認証 → ダミー署名 → 証明書読出")
    print("=" * 60)

    # ---- リーダー検出 & 接続 ----
    rs = readers()
    if not rs:
        print("ERROR: ICカードリーダーが見つかりません。")
        sys.exit(1)
    reader = rs[0]
    print(f"使用リーダー: {reader}")

    print("\n>>> マイナンバーカードをリーダーにセットしてから Enter を押してください")
    print("    - 接触型: ICチップ面を正しい向きで奥まで差し込む")
    print("    - 非接触(PaSoRi等): リーダー中央に置く")
    print(">>> ", end="")
    input()

    conn = reader.createConnection()
    try:
        conn.connect()
    except NoCardException:
        print("ERROR: カードが検出されません。")
        sys.exit(2)
    except CardConnectionException as e:
        print(f"ERROR: カード接続失敗: {e}")
        sys.exit(2)

    try:
        # ============================================================
        # 同一セッション内で全処理を実施(再認証不要にするため)
        # ============================================================
        print(f"\nATR: {toHexString(conn.getATR())}\n")

        # [1] JPKI AP SELECT
        print("[1] JPKI AP を SELECT")
        transmit_strict(conn, SELECT_JPKI_AP, "SELECT JPKI AP")

        # [2] PIN残回数確認(消費しない)
        print("\n[2] 署名用PIN残回数を確認 (試行は消費しません)")
        remaining = check_pin_remaining(conn)

        if remaining == 0:
            print("\n[FATAL] 署名用PINがロックされています(残0回)。")
            print("        市区町村の窓口で初期化が必要です。アプリは即時中断します。")
            sys.exit(3)

        if remaining is not None:
            print(f"\n  → PIN残回数: {remaining} 回")

            if remaining < MIN_SAFE_REMAINING:
                print(f"\n[STOP] 安全装置: 残回数 < {MIN_SAFE_REMAINING} のため処理を継続しません。")
                print("       通常は初期状態 5 回 のはずです。過去に間違いがあった可能性があります。")
                sys.exit(3)
        else:
            # ---- 残回数が取得できないケース ----
            # 6700 等で応答するカード/リーダーの組合せが存在する。
            # この場合 PIN試行は消費されていないが、残回数の事前確認はできない。
            print("\n[WARN] PIN残回数を事前取得できませんでした。")
            print("       原因: お使いのカード/リーダーが標準の 残回数照会APDU に")
            print("             非対応の可能性があります(PIN試行は消費されていません)。")
            print("       影響: 1回失敗時のリスクが見えない状態で実行することになります。")
            print("       推奨: PINを完全に把握している自信がある場合のみ続行してください。")

            if args.check_only:
                print("\n[完了] --check-only モードのためここで終了します。残回数は不明のままです。")
                sys.exit(0)

            ans = input("残回数不明のまま続行しますか? [yes/no] > ").strip().lower()
            if ans not in ("yes", "y"):
                print("中止しました。")
                sys.exit(0)
            print("[警告] 残回数不明状態で続行します。1回でも間違えるとロックに近づきます。")
            remaining = -1  # マーカー: 不明

        # --check-only: ここで終了
        if args.check_only:
            print("\n[完了] --check-only モードのためここで終了します。")
            print("       本番実行は: py -3.12 test_03_sign.py")
            sys.exit(0)

        # [3] 続行確認(yes/no)
        print("\n" + "-" * 56)
        print(" これから 署名用PIN を入力していただきます。")
        print(" 入力されたPINでVERIFYを実行し、ダミーデータに署名します。")
        if remaining > 0:
            print(f" 残回数: {remaining} 回。1回失敗すると {remaining - 1} 回になります。")
        else:
            print(" 残回数: 不明 (取得失敗のため明示できません)")
        print("-" * 56)
        ans = input("続行しますか? [yes/no] > ").strip().lower()
        if ans not in ("yes", "y"):
            print("中止しました。")
            sys.exit(0)

        # [4] PIN入力(getpassで隠蔽)
        pin_str = getpass.getpass(
            "署名用PIN(6〜16桁・画面に表示されません) > "
        )
        if not (6 <= len(pin_str) <= 16):
            print("ERROR: PIN桁数が不正です(6〜16桁の範囲外)。中止します。")
            del pin_str  # 念のため
            sys.exit(3)
        if not pin_str.isascii():
            print("ERROR: PINはASCII英数字のみ受付。中止します。")
            del pin_str
            sys.exit(3)

        # PIN を bytearray に変換 (mutable にすることで後続のゼロクリアを可能にする)
        # str はimmutableなのでメモリ上から確実に消すことはPython仕様上不可能。
        # 早期に bytearray へ移行 + 元の str を del することで参照を切る。
        pin_bytes = bytearray(pin_str.encode("ascii"))
        del pin_str  # 元のPIN文字列の参照を切る(GC候補化)

        # [5] VERIFY PIN
        print("\n[5] VERIFY PIN を実行")
        try:
            ok, rem = verify_pin(conn, pin_bytes)
        finally:
            # APDU送信直後に PIN bytes をゼロクリア(同一bytearray上で破壊的に上書き)
            for i in range(len(pin_bytes)):
                pin_bytes[i] = 0
            del pin_bytes  # 参照を切る

        if not ok:
            if rem == 0:
                print("\n[FATAL] PINがロックされました(残0回)。")
                print("        市区町村窓口で初期化が必要です。")
            else:
                print(f"\n[NG] PIN認証失敗。残回数: {rem} 回。")
                print("     本ツールは安全のため再試行を行いません。中止します。")
            sys.exit(3)
        print("  → 認証成功")

        # [6] ダミーデータの SHA-256 → DigestInfo 構築
        print("\n[6] ダミーデータ b\"test123\" のSHA-256 → DigestInfo 構築")
        dummy = b"test123"
        sha256 = hashlib.sha256(dummy).digest()
        print(f"  SHA-256: {sha256.hex()}")

        digest_info = DIGEST_INFO_PREFIX_SHA256 + sha256
        print(f"  DigestInfo: {len(digest_info)} bytes (期待値: 51)")
        if len(digest_info) != 51:
            raise RuntimeError(f"DigestInfo長さ異常: {len(digest_info)}")
        print(f"  DigestInfo(hex): {digest_info.hex()}")

        # [7] 署名用秘密鍵 EF SELECT
        print("\n[7] 署名用秘密鍵 EF を SELECT")
        transmit_strict(conn, SELECT_SIGN_KEY_EF, "SELECT 署名用秘密鍵EF")

        # [8] COMPUTE DIGITAL SIGNATURE
        print("\n[8] COMPUTE DIGITAL SIGNATURE 実行")
        signature = compute_digital_signature(conn, digest_info)
        print(f"  → 署名値長: {len(signature)} bytes (期待値: 256)")
        if len(signature) != 256:
            print(f"  [WARN] RSA-2048の標準長は256B。実際: {len(signature)}B")
        Path(OUTPUT_SIG).write_bytes(signature)
        print(f"  保存: {OUTPUT_SIG}")
        print(f"  署名値先頭16B: {signature[:16].hex()}")

        # [9] 署名用証明書読出(同一セッションなのでPIN認証は再不要)
        print("\n[9] 署名用証明書 EF (0x0001) を SELECT")
        transmit_strict(conn, SELECT_SIGN_CERT_EF, "SELECT 署名用証明書EF")

        print("\n[10] READ BINARY ループ開始")
        cert_der = read_binary_all(conn)
        print(f"\n読み出しサイズ: {len(cert_der)} bytes")
        if len(cert_der) < 4 or cert_der[0] != 0x30:
            print("[WARN] DER構造として不正な可能性があります。")
            print(f"       先頭16B: {cert_der[:16].hex()}")
        else:
            print("[OK] 先頭バイト 0x30 (ASN.1 SEQUENCE) を確認")
            # 実DER長を表示(参考)
            if cert_der[1] == 0x82:
                actual_len = 4 + (cert_der[2] << 8 | cert_der[3])
                print(f"     実DER長(ヘッダから算出): {actual_len} bytes")
                print(f"     EF確保サイズ - 実DER長 = パディング {len(cert_der) - actual_len} B")

        Path(OUTPUT_CERT).write_bytes(cert_der)
        print(f"  保存: {OUTPUT_CERT}")

        # ---- 完了サマリ ----
        print("\n" + "=" * 60)
        print(" Phase 1 / Step 3 完了")
        print("=" * 60)
        print(f"  - 署名値:        {OUTPUT_SIG} ({len(signature)} bytes)")
        print(f"  - 署名用証明書:  {OUTPUT_CERT} ({len(cert_der)} bytes)")
        print()
        print("[次のステップ]")
        print("  1) 証明書の中身確認:")
        print(f"       certutil -dump {OUTPUT_CERT}")
        print("       → Subject に氏名、SAN(代替名)に住所/生年月日/性別 が見えるはず")
        print()
        print("  2) 署名値の事前検証(任意):")
        print("       py -3.12 -m pip install cryptography")
        print("       後でPhase 2の検証ロジックを実装します。")
        print()
        print("  ⚠️ sign_cert.der は氏名・住所・生年月日・性別を含みます。")
        print("     共有・GitHubアップロード等にご注意ください。")

    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
