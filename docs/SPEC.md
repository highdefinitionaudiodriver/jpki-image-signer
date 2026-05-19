# `.jpkiimg` フォーマット仕様 v1.0

本ドキュメントは `.jpkiimg` ファイルの構造を第三者が独立に実装・検証できるよう公開する仕様書です。
**この仕様が公開されていることで、本ツールが廃れた将来でも、署名された画像の真贋検証が可能になります。**

---

## 1. 概要

`.jpkiimg` は、画像ファイル本体に **マイナンバーカード（JPKI）の署名用電子証明書による PKCS#7 分離署名** を付与し、単一のコンテナファイルとして配布できるフォーマットです。

### 設計目標

| 目標 | 実現方法 |
|---|---|
| 元画像を変更しない | サイドカー方式（署名・証明書を別ファイルに分離） |
| 配布の容易さ | 単一ファイル化（無圧縮 ZIP コンテナ） |
| 再エンコード耐性 | バイナリ完全一致で検証（SHA-256） |
| 標準暗号方式 | PKCS#7 CMS SignedData（detached） |
| 検証ツールの独立実装可能性 | OpenSSL 等の汎用ツールでも将来検証可能 |

---

## 2. コンテナ構造

```
sample.jpg.jpkiimg  （無圧縮 ZIP / ZIP_STORED）
├── target_image.<ext>   ← 元画像（無加工バイト列）
├── signature.p7s        ← PKCS#7 分離署名（DER）
└── cert.der             ← JPKI 署名用電子証明書（X.509 DER）
```

### 2.1 ZIP 形式の要件

| 項目 | 値 |
|---|---|
| 圧縮方式 | **ZIP_STORED**（無圧縮）必須 |
| 文字コード（エントリ名） | UTF-8 |
| パスワード保護 | なし |
| 暗号化 | なし |
| エントリ数 | 厳密に 3 |

**無圧縮を強制する理由**：解凍コスト 0、バイナリ完全一致検証の単純化、ファイルサイズの予測可能性、将来の検証ツール実装の容易さ。

### 2.2 エントリ詳細

#### 2.2.1 `target_image.<ext>`

- **内容**：署名対象の元画像。バイト単位で完全に元ファイルと一致しなければならない（再エンコード禁止）
- **拡張子**：`jpg` / `jpeg` / `png` のいずれか（小文字）
- **MIME**：`image/jpeg` または `image/png`

#### 2.2.2 `signature.p7s`

- **内容**：CMS SignedData 構造（RFC 5652、detached / 最小構成）
- **符号化**：DER エンコード
- **署名対象**：`target_image.<ext>` のバイト列の SHA-256 ハッシュ
- **署名アルゴリズム**：RSASSA-PKCS1-v1_5 + SHA-256（OID `1.2.840.113549.1.1.11`）
- **`signedAttrs`**：付加しない（JPKI カードの COMPUTE DIGITAL SIGNATURE と直接対応するため）
- **証明書埋込**：CMS の `certificates` フィールドに `cert.der` と同じ証明書を含めてよい

#### 2.2.3 `cert.der`

- **内容**：JPKI 署名用電子証明書（X.509）
- **符号化**：DER エンコード
- **公開鍵アルゴリズム**：RSA 2048bit
- **発行者 DN**：J-LIS（Japan Agency for Local Authority Information Systems）が発行する署名用認証局
- **個人情報の含有**：氏名（漢字）、住所（漢字）、生年月日、性別、JPKI 識別符号（17 桁の補助番号）が含まれる

> ⚠️ **`cert.der` には個人情報が含まれます**。公開リポジトリ・SNS への投稿・公開チャットへの貼り付けは厳禁です。

---

## 3. 検証手順（参考実装）

任意の言語・ツールで以下の手順を踏めば検証可能です。

```
1. ZIP コンテナを開き、3 エントリを取り出す
   - target_image.<ext>, signature.p7s, cert.der

2. target_image.<ext> のバイト列の SHA-256 を計算
   → H_image

3. signature.p7s（CMS SignedData）から:
   - 署名対象ハッシュアルゴリズム = SHA-256 であることを確認
   - encryptedDigest（署名値）を取り出す
   - certificates から署名者証明書を取り出す（cert.der と一致するはず）

4. cert.der の公開鍵で encryptedDigest を復号 → H_signed

5. H_image == H_signed なら署名は有効、改ざんなし
   不一致なら改ざんあり、または別の画像
```

### OpenSSL での検証例

```bash
# コンテナを展開
unzip -o sample.jpg.jpkiimg -d extracted/

# 検証（PEM 変換が必要）
openssl x509 -inform DER -in extracted/cert.der -out cert.pem
openssl smime -verify -inform DER \
  -in extracted/signature.p7s \
  -content extracted/target_image.jpg \
  -certfile cert.pem \
  -CAfile <J-LIS_CA_chain.pem> \
  -noverify  # 証明書チェーン検証を別途行う場合は外す
```

---

## 4. このバージョンの制限事項

| 項目 | 状態 |
|---|---|
| 証明書チェーン検証 | 仕様外（実装は別途必要） |
| 失効確認（CRL / OCSP） | 仕様外（実装は別途必要） |
| タイムスタンプ（RFC 3161 TST） | 未対応（v2.0 で検討） |
| 画像形式 | JPEG / PNG のみ（v2.0 で WebP / AVIF 追加検討） |
| 動画・音声 | 対象外 |

---

## 5. 互換性ポリシー

- **v1.x の `.jpkiimg`** は、本仕様に準拠する限り、将来も検証可能であり続けます
- **v2.0** で破壊的変更が入る場合、ZIP 内に `manifest.json` を追加してバージョンを明示する予定
- v1.x で生成された `.jpkiimg` を v2.x ツールで検証することは、後方互換として保証されます

---

## 6. ライセンス

本仕様書は **CC0 1.0 Universal (Public Domain Dedication)** で公開します。
誰でも自由に検証ツール・別言語実装・商用利用が可能です。

---

## 7. 参考文献

- RFC 5652: Cryptographic Message Syntax (CMS)
- RFC 5280: Internet X.509 Public Key Infrastructure Certificate
- RFC 8017: PKCS #1 v2.2 (RSA Cryptography)
- ISO/IEC 21320-1: Document Container File
- J-LIS 公的個人認証サービス: https://www.jpki.go.jp/
