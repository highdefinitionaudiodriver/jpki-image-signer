"""
docs/sample.jpg を生成する小さなスクリプト.

Phase 2 / Step 2-4 のテスト用ダミー画像。実署名のテストには
個人情報を含まないこの画像を使うことを推奨する。

実行:
    py -3.12 -m pip install Pillow      # 初回のみ
    py -3.12 docs/make_sample_image.py
"""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit(
        "ERROR: Pillow がインストールされていません。\n"
        "       py -3.12 -m pip install Pillow を実行してください。"
    )


OUT_PATH = Path(__file__).resolve().parent / "sample.jpg"


def _load_font(preferred_paths: list[str], size: int):
    """利用可能な TrueType フォントを試行(全滅したらPIL内蔵フォント)."""
    for p in preferred_paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_sample(out_path: Path = OUT_PATH, size: tuple[int, int] = (800, 600)) -> Path:
    """単色背景に文字を描いたサンプルJPEGを生成して保存."""
    w, h = size
    bg = (70, 130, 180)  # SteelBlue
    img = Image.new("RGB", size, color=bg)
    draw = ImageDraw.Draw(img)

    # フォント(Windows標準のArial→Yu Gothic→PIL内蔵)
    font_l = _load_font(["arial.ttf", "C:/Windows/Fonts/arial.ttf",
                         "C:/Windows/Fonts/YuGothM.ttc"], 64)
    font_m = _load_font(["arial.ttf", "C:/Windows/Fonts/arial.ttf"], 28)
    font_s = _load_font(["arial.ttf", "C:/Windows/Fonts/arial.ttf"], 18)

    title    = "JPKI Test Image"
    subtitle = "Phase 2 / Step 2-4 sample"
    notice   = "Synthetic sample - DO NOT use for any real signature workflow."

    # ---- タイトル(大・中央) ----
    bbox = draw.textbbox((0, 0), title, font=font_l)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((w - tw) // 2, h // 3 - th // 2), title, fill="white", font=font_l)

    # ---- サブタイトル ----
    bbox = draw.textbbox((0, 0), subtitle, font=font_m)
    sw = bbox[2] - bbox[0]
    draw.text(((w - sw) // 2, h // 2 + 10), subtitle, fill=(220, 230, 240), font=font_m)

    # ---- 注意書き(下) ----
    bbox = draw.textbbox((0, 0), notice, font=font_s)
    nw = bbox[2] - bbox[0]
    draw.text(((w - nw) // 2, h - 60), notice, fill=(200, 210, 220), font=font_s)

    # 枠線
    draw.rectangle([(8, 8), (w - 9, h - 9)], outline=(255, 255, 255), width=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=85)
    return out_path


if __name__ == "__main__":
    p = make_sample()
    print(f"[OK] Generated: {p}")
    print(f"     Size: {p.stat().st_size:,} bytes")
