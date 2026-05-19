# JPKI Image Signer

**Version: v0.1.0** — マイナンバーカード(JPKI)を用いた、画像ファイルへの **電子署名と真正性検証** を行う Windows 向けツールです。

クリエイターが自分の作品(写真・イラスト等の画像)に対して、**「自分が作成したこと」「改ざんされていないこと」** を公的個人認証サービス(JPKI)の署名鍵で証明できるようにすることを目的とします。

---

## 🎯 これは何？（30秒で）

- **誰のため**：イラスト・写真・デザインを公開しているクリエイター／作品の真贋証明をしたい個人
- **何が解決される**：「この作品は本当に自分が作ったものだ」を、AIや盗用が横行する時代に **国の認証局（公的個人認証サービス）** で証明可能にする
- **なぜ既存ツールではダメか**：透かしは外せる。ブロックチェーンNFTは身元を担保しない。本ツールは **国が発行する署名鍵による真正性証明** で、技術的にも法的にも筋が通る
- **使う条件**：Windows 10/11 (x64)、PC/SC 対応 IC カードリーダー、マイナンバーカード（署名用電子証明書が有効なもの）

## 💰 想定ユースケース・価格帯

| 用途 | 形態 |
|---|---|
| 個人利用（自分の作品への署名・他者作品の検証） | 無料（MIT） |
| 検証のみ（受け取った画像が本物か確認したい） | 無料（カード不要・誰でも） |
| 同人・物販での真贋証明、団体導入、カスタマイズ | 応相談 |

---

---

## 📥 ダウンロード / インストール

### エンドユーザー(GUIで使う方)

GitHub の **[Releases](../../releases)** ページから最新版の ZIP をダウンロードしてください。

| 配布物 | 推奨用途 |
|---|---|
| **`JPKI_Image_Signer_Windows_x64_v0.1.0_onedir.zip`** | 通常配布(起動が速い・安定。ZIPを展開して中の `.exe` を起動) |
| `JPKI_Image_Signer_Windows_x64_v0.1.0_onefile.zip` | USB配布等の単一ファイル運用(起動初回 2〜5秒) |

#### 使い方(`onedir.zip`)

1. ZIPをダウンロード
2. 任意のフォルダに展開(例: `C:\Tools\JPKI_Image_Signer\`)
3. 展開先の `JPKI_Image_Signer\JPKI_Image_Signer.exe` をダブルクリック
4. 画像ファイル(JPEG/PNG)または `.jpkiimg` をウィンドウにドラッグ&ドロップ

> Python のインストール **不要**(`.exe` に Python ランタイム同梱)。
> ICカードリーダー(PC/SC対応)とマイナンバーカードのみご準備ください。

### 開発者(ソースから動かす方)

```powershell
git clone <このリポジトリのURL> jpki-image-signer
cd jpki-image-signer
py -3.12 -m pip install pyscard cryptography asn1crypto PyQt6 Pillow openpyxl
py -3.12 -m phase3.app
```

詳細は [クイックスタート](#クイックスタート) を参照してください。

---

## 主な特徴

| 特徴 | 説明 |
|---|---|
| 🔐 **公的電子認証ベース** | マイナンバーカードの **署名用電子証明書(RSA-2048)** で署名。第三者(役所発行)が身元保証する。 |
| 📦 **サイドカー方式 + ZIPコンテナ** | 元画像を一切加工せず、署名/証明書を別ファイルで持ち、`.jpkiimg`(無圧縮ZIP)に同梱。 |
| 🖼 **画像の再エンコード無し** | JPEG/PNG等のメタデータ剥がれ・再圧縮によるハッシュ不一致を回避。 |
| 🛡 **PINロック対策の安全装置** | 残回数事前確認 / 閾値未満で自動中止 / メモリ上のPINゼロクリア。 |
| ✅ **数学的に検証済の暗号フロー** | RSASSA-PKCS1-v1\_5 + SHA-256 の検証ロジックを 40件の自動テストでカバー。 |

---

## システムアーキテクチャ

### 1. 採用方針: サイドカー方式 + ZIPコンテナ

電子署名を画像に直接埋め込む方式(EXIF/XMPやステガノグラフィ)には次の弱点があります:

- メタデータが**SNS等のアップロードで剥がされる**
- 再圧縮で**バイナリが変わってハッシュ不一致**

本ツールはこれを回避するため、**画像を一切加工せず**、署名と証明書を分離した上で **無圧縮ZIPコンテナ** に同梱します。

### 2. `.jpkiimg` コンテナの中身

```
sample.jpg.jpkiimg (無圧縮ZIP / ZIP_STORED)
├── target_image.jpg     ← 元画像(無加工)
├── signature.p7s        ← PKCS#7 分離署名(detached SignedData)
└── cert.der             ← 署名用電子証明書(X.509 DER)
```

検証側は コンテナを開く → `target_image.*` のSHA-256を計算 → `signature.p7s` を `cert.der` の公開鍵で検証 → **改ざんが無ければ「有効」、1ビットでも変われば「無効」** と判定します。

### 3. メリット

| 項目 | 効果 |
|---|---|
| 元画像非加工 | 既存の画像ビューア・印刷・Exif読み取り等が問題無く動作 |
| ZIP化 | 単一ファイルとして配布・保管が容易 |
| 無圧縮(STORED) | アクセス時の解凍コストゼロ。元画像のサイズ感も維持 |
| PKCS#7 標準 | OpenSSL等の汎用ツールでも将来的な検証可能性を確保 |

---

## 現在の機能 (Phase 3 完了時点)

**GUI(PyQt6) と CLI の両方** で動作します。エンドユーザーには GUI を、自動化や CI 用途には CLI を、それぞれ用途に応じて使い分けられます。

### 🖱️ GUI モード(推奨・エンドユーザー向け)

```powershell
py -3.12 -m phase3.app
```

**ドラッグ&ドロップで直感的に操作**できます:

- **画像ファイル(JPEG/PNG)をD&D** → 自動的に **署名モード** に切替
- **`.jpkiimg` をD&D** → 自動的に **検証モード** に切替
- ホバー中のウィンドウは背景・点線枠が変色して受付状態を視覚フィードバック
- 非対応のファイル形式は警告ダイアログで明示的に拒否

#### 署名モード の特徴

- 画像情報・出力先パスを自動表示
- 「🔐 署名を開始」 → カード接続 → **PIN残回数を確認** → **PinDialog** が開く
- PinDialog は残回数を **色分け** (5=緑/3〜4=黄+警告/2以下=赤+警告)
- 入力中は `Password` モードで非表示、桁数バリデーションをリアルタイム実行
- 認証成功時は緑カードに **署名者氏名(漢字)** ・コンテナサイズ・内訳サイズを表示
- 「📂 出力先フォルダを開く」ボタンで Explorer を起動

#### 検証モード の特徴

- 結果に応じて **3 パターン**のカードUI:
  - ✅ **緑カード**: 「有効な署名です」+ 署名者氏名 + 抽出元ラベル + 識別符号 + 有効期間
  - ❌ **赤カード**: 「改ざんを検知しました」+ 詳細メッセージ + 参考情報
  - ⚠ **橙カード**: 「不正なコンテナです」+ 原因種別(NotJpkiImg/MissingEntry等) + エラー詳細

#### 内部設計

- **QThread** ベースのバックグラウンドワーカー(`SignWorker` / `VerifyWorker`) でカード操作を別スレッド化 → GUIフリーズ防止
- **QMutex + QWaitCondition** で UIスレッド ⇄ ワーカースレッド間の **PIN同期**(双方向シグナル)
- PIN は受け取り後即 `bytearray` 化 → APDU送信直後にゼロクリア → 参照を `del`

(GUI スクリーンショットは将来 `docs/images/` に配置予定)

```
![Welcome](docs/images/welcome.png)
![Sign Mode](docs/images/sign_mode.png)
![Pin Dialog](docs/images/pin_dialog.png)
![Verify Success](docs/images/verify_success.png)
![Verify Tampered](docs/images/verify_tampered.png)
```

### ⌨️ CLI モード(自動化向け)

#### 署名 (`phase2.cli.sign_image`)

```powershell
py -3.12 -m phase2.cli.sign_image docs/sample.jpg
```

- 8ステップの進捗表示(ANSIカラー)
- ICカードリーダー自動検出 / ATR表示
- **PIN残回数事前確認(消費なし)** + 残3回未満で自動中止
- `getpass` による画面非表示PIN入力
- カードでRSA署名生成 → 署名用証明書取得 → `.jpkiimg` 出力

#### 検証 (`phase2.cli.verify_image`)

```powershell
py -3.12 -m phase2.cli.verify_image docs/sample.jpg.jpkiimg
```

- コンテナ展開
- PKCS#7 検証 (RSASSA-PKCS1-v1\_5 + SHA-256)
- 結果表示 (✅ 緑 / ❌ 赤)
- 終了コード: 0=有効, 2=構造異常, 3=改ざん検知

---

## 動作要件

| 項目 | バージョン/条件 |
|---|---|
| OS | Windows 10 / 11 (64-bit 推奨) |
| Python | **3.10 以上**(3.12 で動作確認済) |
| ICカードリーダー | **PC/SC 対応**(マイナンバーカード対応のもの。例: Sony PaSoRi RC-S380、ACR39U、Alcor AU9540系等) |
| Windowsサービス | `SCardSvr` (Smart Card) が起動中であること |

### 必須Pythonパッケージ

```powershell
py -3.12 -m pip install pyscard cryptography asn1crypto PyQt6 Pillow openpyxl
```

| パッケージ | 用途 | 必須/任意 |
|---|---|---|
| `pyscard`      | PC/SC経由でICカードと通信 | **必須** |
| `cryptography` | RSA/SHA-256/X.509処理 | **必須** |
| `asn1crypto`   | PKCS#7(CMS) DER構築 | **必須** |
| `PyQt6`        | GUI フレームワーク | **必須(GUI使用時)** |
| `Pillow`       | サンプル画像の生成 | 任意 |
| `openpyxl`     | 設計書(.xlsx)の再生成 | 任意 |

> **CLI のみ運用なら** PyQt6 と Pillow は不要(`pyscard cryptography asn1crypto` の3つだけ)。

---

## クイックスタート

### 共通の準備

```powershell
# 1) リポジトリ取得 / 配置
cd C:\dev\jpki-image-signer

# 2) 依存インストール (GUI使う場合)
py -3.12 -m pip install pyscard cryptography asn1crypto PyQt6 Pillow

# 3) サンプル画像を生成 (任意)
py -3.12 docs/make_sample_image.py

# 4) リーダーにマイナンバーカードを挿入

# 5) 残回数確認(安全)
py -3.12 phase1/test_03_sign.py --check-only
```

### 🖱️ GUI で署名・検証(推奨)

```powershell
py -3.12 -m phase3.app
```

ウィンドウが開いたら **画像ファイルを D&D** → 「🔐 署名を開始」 → PIN入力 → 完了!
出来上がった `.jpkiimg` を **D&D し直す** だけで検証モードに切り替わります。

### ⌨️ CLI で署名・検証

```powershell
# 署名 (PIN入力1回)
py -3.12 -m phase2.cli.sign_image docs/sample.jpg

# 検証
py -3.12 -m phase2.cli.verify_image docs/sample.jpg.jpkiimg
```

---

## 📦 リリース版(配布物)の使い方

エンドユーザー向けに **PyInstaller でビルドした実行ファイル** を配布できます。Python 環境が無いPCでも `.exe` ひとつで起動できます。

### ビルド方法

```powershell
# 推奨: --onedir + ZIPパッケージ生成
py -3.12 build.py --package --clean

# 軽量配布: --onefile + ZIPパッケージ生成
py -3.12 build.py --onefile --package --clean
```

成果物は `dist/` 配下に出力されます:

| 出力 | 内容 |
|---|---|
| `dist/JPKI_Image_Signer/` | --onedir モードの展開フォルダ(実行ファイル + 依存DLL) |
| `dist/JPKI_Image_Signer.exe` | --onefile モードの単一実行ファイル |
| `dist/JPKI_Image_Signer_Windows_x64_v0.1.0_onedir.zip` | --onedir 配布用 ZIP |
| `dist/JPKI_Image_Signer_Windows_x64_v0.1.0_onefile.zip` | --onefile 配布用 ZIP |

### `--onedir` 版 と `--onefile` 版 の違い

| 項目 | `--onedir`(推奨) | `--onefile` |
|---|---|---|
| **ファイル構成** | フォルダ配下に `.exe` + 依存DLL多数 | 単一の `.exe` のみ |
| **配布の手軽さ** | フォルダ全体を ZIP で渡す必要あり | `.exe` ひとつをそのまま渡せる |
| **起動速度** | 即時(数百ms) | 初回 2〜5秒(`%TEMP%`に展開するため) |
| **ファイルサイズ** | 展開済 80〜130MB / ZIP 50〜80MB | 単一 60〜100MB |
| **Antivirus 誤検知率** | 低い | 高い(自己解凍系として認識されやすい) |
| **おすすめ用途** | 通常の配布・社内利用・常用 | USB配布・1回限りの送付 |

### 配布物の動作要件(受信側PC)

| 項目 | 要件 |
|---|---|
| OS | Windows 10 / 11 (64-bit) |
| ランタイム | 不要(`.exe` に Python 同梱) |
| ICカードリーダー | **PC/SC 対応**(マイナンバーカード対応のもの) |
| Windowsサービス | **`SCardSvr` (Smart Card)** が起動中であること |
| マイナンバーカード | 署名用PIN(6〜16桁英数字)を把握していること |

### ⚠️ Antivirus 誤検知について

PyInstaller でビルドした `.exe` は、その性質上(Pythonランタイム+依存をまとめたブートローダ起動)、**Windows Defender や一部のセキュリティソフトに誤検知される場合があります**。これは PyInstaller 製のあらゆるアプリで起こり得る既知の挙動で、本ツール固有の問題ではありません。

#### 警告が表示された場合の対処

1. **「PCを保護しました」(SmartScreen)** ダイアログが出た場合:
   - 「**詳細情報**」をクリック → 「**実行**」ボタンが現れる → クリック
2. **Windows Defender が削除/隔離した場合**:
   - 「ウイルスと脅威の防止」 → 「保護の履歴」 → 該当項目で「許可」
   - もしくは Defender の「除外」設定で **配布フォルダ/exe** を除外リストに追加
3. **そもそも信頼できないと判断する場合**:
   - 配布元(本ツールの作者)に **VirusTotal でのスキャン結果** を確認してもらう
   - もしくは Python 環境で **ソースから直接実行**(README 上部のクイックスタート参照)

#### 開発者側で対策する場合(将来課題)

- **コード署名証明書** (Authenticode / EV) を取得して `.exe` に署名すると誤検知率が大幅に下がります(取得費用は年額1〜10万円程度)。
- リリース前に [VirusTotal](https://www.virustotal.com/) で事前スキャンし、結果URLを README に記載する運用も有効です。

---

## ⚠️ セキュリティ上の注意

### PINロックの重大性

マイナンバーカードの **署名用PIN(6〜16桁英数字)を5回連続で間違えると、カードがロック**されます。
解除には**市区町村窓口での手続き(本人確認書類持参)** が必要で、簡単には復旧できません。

### 本ツールの安全装置

PINロックを防ぐため、以下の多重安全機構を実装しています:

1. **残回数事前確認(`assert_safe_to_attempt_pin`)**
   VERIFY APDU を空データで送出し、`SW=63CX` から残回数を取得します。
   この操作では**試行カウンタは消費されません**(認証段階に到達していないため)。
   複数の APDU バリエーション(Case1 4-byte / Case3 Lc=0 5-byte)を自動試行してカード差異も吸収します。

2. **閾値未満で自動中止**
   残回数が **3 未満** の場合、本ツールは PIN VERIFY を**実行しません**。
   `JpkiPinRiskError` を投げて即座に停止します(変更可能)。

3. **PIN入力の隠蔽**
   `getpass.getpass()` でターミナル上で**マスク入力**(画面に何も表示されない)。

4. **メモリ上のPINゼロクリア**
   入力されたPIN文字列は即座に `bytearray` に変換され、APDU送信直後に**1バイトずつ 0 で上書き**されます。
   元の `str` オブジェクトは Python の仕様上完全消去できませんが、参照を `del` で切ることで GC を促します。

5. **再試行の禁止**
   PIN認証に1回失敗した時点で本ツールは**処理を中止**します。
   ユーザーは別途 `--check-only` で残回数を確認してから、慎重に再実行する運用です。

### 個人情報の取扱(★最重要)

`.jpkiimg` には **署名用電子証明書** (`cert.der`) が含まれ、これには以下の個人情報が **平文** で格納されています:

- 氏名(漢字)
- 住所
- 生年月日
- 性別

⚠️ **公開リポジトリ・SNS・パブリックな共有領域に `.jpkiimg` をアップロードしないでください**。
真正性検証目的で第三者に渡す場合は、相手が信頼できる個人/組織であることを確認してください。

#### プライバシー警告ダイアログ(GUI)

GUI モードでは「🔐 署名を開始」をクリックした直後に、必ず **プライバシー警告ダイアログ** が表示されます:

- 警告本文に含まれる個人情報の内訳(氏名/住所/生年月日/性別)を明示
- ユーザーが「内容を理解した」チェックボックスをONにするまで実行ボタンは無効
- 既定ボタンは「キャンセル」(Enter キーでの誤承認を防止)
- 実行ボタンは赤色の警告スタイル

これによりリスクを認識した上での操作のみ許可されます。

#### 推奨される運用

- ✅ クローズドな取引先・契約先への限定送信
- ✅ 真正性確認のために身元保証された個人へ手渡し的に共有
- ❌ 一般公開の Web サイト・SNS・GitHub Public リポジトリへのアップロード
- ❌ クラウドストレージの「リンクで共有」(URL知っていれば誰でもアクセス可)機能でのばらまき

---

## プロジェクト構成

```
jpki-image-signer/
├── phase1/                          # 実機検証用CLI(Phase 1)
│   ├── test_01_connect.py           # リーダー疎通
│   ├── test_02_read_cert.py         # 利用者証明用cert読出
│   ├── test_03_sign.py              # PIN+署名+署名用cert読出
│   └── test_04_verify_dummy.py      # 数学的検証
│
├── phase2/                          # 再利用モジュール(Phase 2)
│   ├── jpki/                        # JPKIカード操作
│   │   ├── apdu.py                  #   APDU定数・ビルダ・SW解析
│   │   ├── digest.py                #   SHA-256 + DigestInfo
│   │   └── session.py               #   JpkiSession + 例外階層
│   ├── crypto/                      # 暗号処理
│   │   ├── der_utils.py             #   ASN.1 DER長解析
│   │   ├── p7s.py                   #   PKCS#7構築・検証
│   │   └── verify.py                #   高レベル検証 + SAN OtherName 氏名抽出
│   ├── container/                   # .jpkiimg コンテナ
│   │   ├── writer.py                #   create_jpkiimg
│   │   └── reader.py                #   read_jpkiimg
│   ├── cli/                         # CLI
│   │   ├── sign_image.py            #   実カード署名フロー
│   │   ├── verify_image.py          #   検証フロー
│   │   └── _terminal.py             #   ANSIカラー+UTF-8ヘルパ
│   └── tests/                       # ユニットテスト(50件Pass)
│       ├── test_p7s.py              #   27件: DER/p7s/改ざん検知/SAN氏名抽出
│       └── test_container.py        #   18件: ZIP/ラウンドトリップ/異常系
│
├── phase3/                          # GUI アプリ(Phase 3) ★新
│   ├── app.py                       # エントリポイント (QApplication)
│   └── gui/
│       ├── main_window.py           #   QMainWindow + D&D + 自動モード判別
│       ├── sign_panel.py            #   署名モードパネル + 結果カード
│       ├── verify_panel.py          #   検証モードパネル + 3パターンカード
│       ├── pin_dialog.py            #   PIN入力モーダル(色分け / バリデーション)
│       ├── workers.py               #   QThread: SignWorker / VerifyWorker
│       └── styles.py                #   モダンフラット QSS
│
├── docs/                            # ドキュメント
│   ├── design_document.xlsx         # 設計書(機能/API/データ/エラー/Mermaid)
│   ├── generate_design_document.py  # 設計書ジェネレータ
│   ├── make_sample_image.py         # ダミー画像生成
│   ├── inspect_cert_san.py          # 診断ツール: cert SAN構造ダンプ
│   ├── sample.jpg                   # テスト用サンプル
│   └── images/                      # GUIスクリーンショット(将来)
│
└── README.md                        # 本ファイル
```

---

## ロードマップ

| Phase | 内容 | 状態 |
|---|---|---|
| **Phase 1** | JPKIカード通信の実機検証(CLIスクリプト) | ✅ 完了 |
| **Phase 2** | 再利用モジュール化 + PKCS#7 + コンテナ + CLI統合 | ✅ 完了 |
| **Phase 3** | PyQt6 GUI 実装 + SAN OtherName 氏名抽出 + プライバシー警告ダイアログ | ✅ 完了 |
| **Phase 4** | マルチOS対応ビルドスクリプト + PyInstaller化 + 配布ZIP化 | ✅ 完了 |
| 将来課題 | コード署名証明書取得 / macOS/Linux 実機検証 / GitHub Actions による自動ビルド | 未着手 |

### Phase 3 完了時点の主な達成事項

- **GUI**: 単一ウィンドウで D&D による自動モード切替(画像→署名 / `.jpkiimg`→検証)
- **非同期処理**: QThread + QMutex/QWaitCondition による UIスレッド ⇄ ワーカースレッド間の PIN同期
- **PIN入力モーダル**: 残回数色分け + Password入力 + リアルタイムバリデーション
- **結果UI**: 3パターン(緑成功 / 赤改ざん検知 / 橙構造異常)のカード表示
- **SAN氏名抽出**: 実機検証で判明した JPKI独自 OID `1.2.392.200149.8.5.5.1` からの漢字氏名抽出を実装(設計書 MEM-007 参照)
- **テスト**: 50件のユニットテスト(`phase2/tests/`) + 実機 End-to-End 動作確認

---

## ライセンスと免責

### 免責事項

本ソフトウェアは **個人開発のプロトタイプ** です。MIT ライセンス相当の自由な使用を想定していますが、以下を強く認識した上でご利用ください。

#### 一般免責

> 本ツールは「現状のまま(AS IS)」提供されます。明示・黙示を問わず、商品性、特定目的への適合性、第三者の権利侵害が無いこと等、いかなる種類の保証も行いません。
>
> **本ツールを利用したことに起因または関連して生じたいかなる損害(直接・間接・特別・偶発・結果的損害、データ消失、業務中断、金銭的損害を含む)についても、作者は一切の責任を負いません。** 利用者は自己責任のもとで本ツールを使用するものとします。

#### 特に重要なリスクとユーザー責任

| リスク | ユーザー側で取るべき対応 |
|---|---|
| **マイナンバーカードのPINロック** | 5回連続でPIN入力を間違えるとロックされ、市区町村窓口での解除手続が必要。本ツールには残回数事前確認機能があるが、最終的な入力責任はユーザーにあります。 |
| **個人情報の流出** | `.jpkiimg` には署名者の **氏名・住所・生年月日・性別** が証明書として平文で含まれます。公開リポジトリ・SNS・URL共有への投稿は厳禁です。 |
| **法的有効性** | 本ツールが生成する電子署名の業務・契約・公的手続きにおける法的扱いは別途確認が必要です。e-文書法・電子署名法等の適用可否は管轄や用途によります。 |
| **検証側の信頼** | 本ツールの検証結果(「✅ 有効な署名です」)は暗号学的整合性の保証であり、署名者の意思や契約の成立は別途担保する必要があります。 |
| **JPKI仕様の変更** | 公的個人認証サービス側の仕様変更(証明書フォーマット・OID等)により本ツールが動作しなくなる可能性があります。 |
| **Antivirus 誤検知** | PyInstaller 製バイナリの性質上、Windows Defender 等で誤検知される場合があります(詳細は本READMEの該当セクション参照)。 |

#### 推奨される利用形態

- ✅ クローズドな取引先・契約先への限定的な真正性証明
- ✅ 個人作品の真正性を**信頼できる相手**にだけ証明する用途
- ❌ 一般公開ウェブサイト・SNS・GitHub Public 等へのアップロード
- ❌ 不特定多数への配布・販売

### 第三者ライブラリのライセンス

本ツールは以下のオープンソースライブラリを使用しています:

| ライブラリ | ライセンス |
|---|---|
| pyscard | LGPL |
| cryptography | Apache 2.0 / BSD |
| asn1crypto | MIT |
| PyQt6 | GPL v3 / Commercial |
| Pillow | HPND |
| openpyxl | MIT |
| PyInstaller | GPL (ただし生成バイナリには影響しない例外条項あり) |

PyQt6 は GPL v3 のため、本ツールも同等のライセンスでの公開が望ましいです。商用利用の場合は PyQt6 の商用ライセンスを別途取得するか、PySide6 (LGPL) への移行をご検討ください。

### バージョン履歴

| バージョン | 日付 | 主な変更 |
|---|---|---|
| **v0.1.0** | 初回リリース | Phase 1〜4 完成 / Windows GUI / CLI / 配布ZIP |

---

## 関連ドキュメント

- [`docs/design_document.xlsx`](docs/design_document.xlsx) — 機能一覧・API仕様・データ仕様・エラー定義・Mermaidアーキテクチャ図
- 各モジュールのソースコードに記載の docstring(主要関数すべてに型情報・例外・使用例を記載)

---

## 🤝 商用利用・カスタマイズ依頼

- 個人利用は無料（MIT ライセンス）
- 検証側ツールの組み込み（団体・物販イベント等）、カスタムフォーマット対応、運用支援は応相談
- 連絡先：highdefinitionaudiodriver@gmail.com
