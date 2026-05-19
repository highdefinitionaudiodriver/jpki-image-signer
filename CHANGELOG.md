# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- README に「これは何？（30秒で）」「想定ユースケース・価格帯」セクションを追加
- SECURITY.md を追加（脆弱性報告フロー）
- 商用利用・カスタマイズ依頼の連絡先を README 末尾に明記

## [0.1.0] - 2026-05-04

### Added
- マイナンバーカード（JPKI）による画像電子署名・検証機能（CLI + GUI）
- PyQt6 ベースの GUI（ドラッグ&ドロップ対応・PIN 残回数色分け表示）
- `.jpkiimg`（無圧縮 ZIP コンテナ）フォーマット
- PKCS#7 detached SignedData（RSASSA-PKCS1-v1_5 + SHA-256）
- PyInstaller による Windows 単体実行ファイル配布（onedir / onefile）
- 40 件の自動テスト（暗号フロー検証）
