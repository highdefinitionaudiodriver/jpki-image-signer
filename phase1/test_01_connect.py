"""
Phase 1 / Step 1: ICカードリーダー疎通確認

目的:
  - PC/SC 経由で SONY RC-S380 (PaSoRi) を認識できるか確認する
  - マイナンバーカードのATRを取得する
  - 署名用AP(JPKI) への SELECT が成功するか確認する
    (PIN 不要・非破壊。カード状態を一切変更しない)

このテストは PIN を一切扱わないため、PINロックの危険はありません。
"""
import sys

# Windows コンソールでの Unicode 出力対策
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
    print("       次を実行してください: pip install pyscard", file=sys.stderr)
    sys.exit(1)


# --- JPKI 署名用AP の AID ---
# D3 92 F0 00 26 01 00 00 00 01 (10 bytes)
# 出典: OpenSC card-jpki.c
SELECT_SIGN_AP = [
    0x00, 0xA4, 0x04, 0x0C, 0x0A,
    0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x01,
]


def list_and_pick_reader():
    rs = readers()
    if not rs:
        print("ERROR: ICカードリーダーが見つかりません。")
        print("  チェック項目:")
        print("    1. SONY NFCポートソフトウェア がインストール/起動されているか")
        print("    2. PaSoRi (RC-S380) が USB に接続されているか")
        print("    3. デバイスマネージャ上で正常に認識されているか")
        sys.exit(1)

    print(f"検出されたリーダー ({len(rs)}台):")
    for i, r in enumerate(rs):
        print(f"  [{i}] {r}")

    if len(rs) == 1:
        return rs[0]

    while True:
        try:
            idx = int(input("使用するリーダー番号を入力 > ").strip())
            if 0 <= idx < len(rs):
                return rs[idx]
        except ValueError:
            pass
        print("無効な番号です。もう一度入力してください。")


def main():
    print("=" * 60)
    print(" Phase 1 / Step 1 : リーダー疎通確認 (PIN不要・安全)")
    print("=" * 60)

    reader = list_and_pick_reader()
    print(f"\n使用リーダー: {reader}")

    print("\n>>> マイナンバーカードをリーダーにセットしてから Enter を押してください")
    print("    - 接触型: ICチップ面の向きに注意して奥まで差し込む")
    print("    - 非接触(PaSoRi等): リーダー中央に置く")
    print(">>> ", end="")
    input()

    conn = reader.createConnection()
    try:
        conn.connect()
    except NoCardException:
        print("ERROR: カードが検出されません。")
        print("       接触型: IC接点の向きを反転して挿し直してみてください。")
        print("       非接触型: 中央に置き直してください。")
        print("       事前に  certutil -scinfo  でカード認識を確認することを推奨。")
        sys.exit(2)
    except CardConnectionException as e:
        print(f"ERROR: カード接続に失敗しました: {e}")
        sys.exit(2)

    try:
        atr = conn.getATR()
        print("\n[OK] 接続成功")
        print(f"  ATR: {toHexString(atr)}")

        # 非破壊な疎通確認: 署名用AP を SELECT するだけ
        print("\n署名用AP (JPKI) を SELECT します ...")
        data, sw1, sw2 = conn.transmit(SELECT_SIGN_AP)
        print(f"  SW = {sw1:02X}{sw2:02X}")

        sw = (sw1 << 8) | sw2
        if sw == 0x9000:
            print("\n[OK] 署名用AP に到達できました。")
            print("     マイナンバーカード(JPKI) として正常に応答しています。")
            print("\n次のステップ:")
            print("  python test_02_read_cert.py を実行してください (PIN不要)。")
        elif sw == 0x6A82:
            print("\n[NG] 署名用AP が見つかりません (6A82)。")
            print("     - 挿入されたカードがマイナンバーカードでない可能性があります。")
            print("     - 古い住基カード等は対象外です。")
            sys.exit(3)
        else:
            print(f"\n[NG] 想定外の応答: SW={sw1:02X}{sw2:02X}")
            print("     APDU 値の見直しが必要かもしれません。出力を共有してください。")
            sys.exit(3)

    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
