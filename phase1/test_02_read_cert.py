"""
Phase 1 / Step 2: 利用者証明用電子証明書(DER) の読み出し

目的:
  - JPKI 利用者証明用AP から 利用者証明用電子証明書(X.509 DER) を
    READ BINARY で読み出し、 auth_cert.der として保存する
  - PIN は一切使用しない (安全)

備考:
  - 当初は「署名用電子証明書(EF=0x0001)」を読み出す予定だったが、
    実機検証の結果、署名用証明書の読み出しには署名用PIN認証が必要(SW=6982)
    であることが判明したため、Phase 1 / Step 2 では
    PIN不要で読める「利用者証明用電子証明書(EF=0x000A)」を読む構成に変更した。
  - 署名用証明書の読み出しは Phase 1 / Step 3(test_03)で
    署名フローと統合して扱う。

成功したら以下のコマンドで内容を確認してください:
  openssl x509 -inform DER -in auth_cert.der -text -noout
  → Subject の CN= に氏名(または符号) が入っていれば正常です。
  → 利用者証明用証明書は氏名/住所/生年月日/性別 を含む(住所はSAN内)。
"""
import sys

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


# --- APDU 定数 ---
# JPKI AP (AID: D3 92 F0 00 26 01 00 00 00 01)
# 注: 署名用APと利用者証明用APは同一AIDで、配下のEFで切り替わる構成。
SELECT_JPKI_AP = [
    0x00, 0xA4, 0x04, 0x0C, 0x0A,
    0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x01,
]
# 利用者証明用電子証明書 EF (FID = 0x000A) ← PIN不要で読める
SELECT_AUTH_CERT_EF = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x00, 0x0A]

OUTPUT_FILE = "auth_cert.der"
READ_CHUNK = 0xE0  # 1 リクエストで読み出す最大バイト数 (224)
MAX_CERT_SIZE = 0x4000  # 安全弁: 16KB を超えたら異常とみなす


def transmit(conn, apdu, label):
    data, sw1, sw2 = conn.transmit(apdu)
    extra = (" DATA=" + toHexString(data)) if data else ""
    print(f"  [{label}] SW={sw1:02X}{sw2:02X}{extra}")
    if (sw1, sw2) != (0x90, 0x00):
        raise RuntimeError(f"{label} 失敗: SW={sw1:02X}{sw2:02X}")
    return data


def read_binary_all(conn):
    """READ BINARY を offset を進めながら呼び出し EF 全体を取得する。"""
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
                break  # 末尾
            offset += len(data)

        elif sw1 == 0x6C:
            # Le 不一致: sw2 が正しい長さ → 再試行
            apdu[4] = sw2
            data, sw1b, sw2b = conn.transmit(apdu)
            if (sw1b, sw2b) != (0x90, 0x00):
                raise RuntimeError(
                    f"READ BINARY (6C 再試行) 失敗: SW={sw1b:02X}{sw2b:02X}"
                )
            out.extend(data)
            print(f"  READ BINARY @offset=0x{offset:04X}  bytes={len(data)}  SW=9000 (6C 再試行)")
            break

        elif (sw1, sw2) == (0x6B, 0x00):
            # オフセット範囲外 = 終端
            break
        else:
            raise RuntimeError(f"READ BINARY 失敗: SW={sw1:02X}{sw2:02X}")

    return bytes(out)


def main():
    print("=" * 60)
    print(" Phase 1 / Step 2 : 署名用電子証明書の読み出し (PIN不要)")
    print("=" * 60)

    rs = readers()
    if not rs:
        print("ERROR: ICカードリーダーが見つかりません。")
        print("       先に test_01_connect.py で疎通を確認してください。")
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
        print(f"ERROR: カード接続に失敗しました: {e}")
        sys.exit(2)

    try:
        print(f"\nATR: {toHexString(conn.getATR())}\n")

        print("[1] JPKI AP を SELECT")
        transmit(conn, SELECT_JPKI_AP, "SELECT JPKI AP")

        print("[2] 利用者証明用証明書 EF (0x000A) を SELECT")
        transmit(conn, SELECT_AUTH_CERT_EF, "SELECT 利用者証明用証明書EF")

        print("[3] READ BINARY ループ開始")
        cert_der = read_binary_all(conn)
        print(f"\n読み出しサイズ: {len(cert_der)} bytes")

        # 簡易 DER 妥当性チェック (ASN.1 SEQUENCE で始まることを確認)
        if len(cert_der) < 4:
            print("[NG] 読み出しサイズが小さすぎます。EF が空か、APDU 値が間違っている可能性があります。")
            sys.exit(4)
        if cert_der[0] != 0x30:
            print("[WARN] 先頭バイトが 0x30 ではありません。DER 構造として不正です。")
            print(f"       先頭16バイト: {cert_der[:16].hex()}")
        else:
            print("[OK] 先頭バイト 0x30 (ASN.1 SEQUENCE) を確認")

        with open(OUTPUT_FILE, "wb") as f:
            f.write(cert_der)
        print(f"\n保存しました: {OUTPUT_FILE}")

        print("\n[次のステップ]")
        print("  以下のコマンドで証明書の中身を確認してください:")
        print(f"    openssl x509 -inform DER -in {OUTPUT_FILE} -text -noout")
        print("  - Subject の CN= に氏名(または符号) が入っていれば成功")
        print("  - これは「利用者証明用」証明書(認証用)です。")
        print("  - 「署名用」証明書(EF=0x0001)はPIN必須のため test_03 で扱います。")
        print("  確認できたら test_03_sign.py に進みます (PIN を扱う最初のステップ)。")

    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
