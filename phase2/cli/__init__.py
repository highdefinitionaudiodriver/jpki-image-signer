"""
phase2.cli: 実カードを使うエンドツーエンドCLI.

  - sign_image:   画像 → JPKI署名 → .jpkiimg 出力
  - verify_image: .jpkiimg → 検証結果表示

実行例:
    py -3.12 -m phase2.cli.sign_image docs/sample.jpg
    py -3.12 -m phase2.cli.verify_image docs/sample.jpg.jpkiimg
"""
