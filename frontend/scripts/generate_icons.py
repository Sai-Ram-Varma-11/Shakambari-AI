"""
Generates high-resolution raster icons (PNG) and social cards for Shakambari AI
from vector coordinates using Pillow with 4x supersampling for crisp edges.
"""
import os
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

def draw_logo(size: int) -> Image.Image:
    # 4x supersampling for high fidelity anti-aliased curves
    scale = 4
    canvas_size = size * scale
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def s(v):
        return v * canvas_size / 100.0

    # Cream rounded rectangle tile with rx ~ 22%
    rx = s(22)
    tile_rect = [s(2), s(2), canvas_size - s(2), canvas_size - s(2)]
    draw.rounded_rectangle(tile_rect, radius=rx, fill="#FBF7EE", outline="#E4E0D2", width=max(1, int(s(1.5))))

    # Outer shadow under thali
    draw.ellipse([s(50 - 36), s(64 - 17), s(50 + 36), s(64 + 17)], fill=(20, 83, 45, 30))

    # Steel thali rim
    draw.ellipse([s(50 - 36), s(62 - 16), s(50 + 36), s(62 + 16)], fill="#F1EFEA", outline="#14532D", width=max(1, int(s(3))))

    # Turmeric warm inner plate
    draw.ellipse([s(50 - 30), s(61 - 12.5), s(50 + 30), s(61 + 12.5)], fill="#FEF3C7", outline="#F59E0B", width=max(1, int(s(2))))

    # Food katoris / bowls
    draw.ellipse([s(35 - 4.5), s(60 - 4.5), s(35 + 4.5), s(60 + 4.5)], fill="#F59E0B")
    draw.ellipse([s(65 - 4.5), s(60 - 4.5), s(65 + 4.5), s(60 + 4.5)], fill="#166534")
    draw.ellipse([s(50 - 3.5), s(65 - 3.5), s(50 + 3.5), s(65 + 3.5)], fill="#C2410C")

    # Central stem
    stem_w = max(1, int(s(3.5)))
    draw.line([(s(50), s(58)), (s(50), s(32))], fill="#14532D", width=stem_w)

    # Left sprouting leaf polygon approximation
    left_leaf = [
        (s(50), s(38)),
        (s(44), s(38)),
        (s(38), s(35)),
        (s(33), s(28)),
        (s(33), s(21)),
        (s(38), s(22)),
        (s(44), s(26)),
        (s(48), s(32)),
        (s(50), s(38)),
    ]
    draw.polygon(left_leaf, fill="#14532D")

    # Right sprouting leaf polygon approximation
    right_leaf = [
        (s(50), s(34)),
        (s(55), s(33)),
        (s(62), s(29)),
        (s(66), s(22)),
        (s(66), s(15)),
        (s(60), s(17)),
        (s(54), s(22)),
        (s(51), s(28)),
        (s(50), s(34)),
    ]
    draw.polygon(right_leaf, fill="#166534")

    # Turmeric golden bud
    draw.ellipse([s(50 - 2.5), s(30 - 2.5), s(50 + 2.5), s(30 + 2.5)], fill="#F59E0B")

    # Steam curves
    steam_w = max(1, int(s(2.2)))
    # Left steam wisp
    left_steam = [(s(41), s(21)), (s(39), s(17)), (s(43), s(13)), (s(41), s(8))]
    for i in range(len(left_steam) - 1):
        draw.line([left_steam[i], left_steam[i + 1]], fill="#F59E0B", width=steam_w)

    # Right steam wisp
    right_steam = [(s(59), s(18)), (s(62), s(14)), (s(58), s(10)), (s(61), s(6))]
    for i in range(len(right_steam) - 1):
        draw.line([right_steam[i], right_steam[i + 1]], fill="#F59E0B", width=steam_w)

    # Downsample using LANCZOS for high quality
    return img.resize((size, size), Image.Resampling.LANCZOS)


def generate_og_card(w=1200, h=630) -> Image.Image:
    """Creates a 1200x630 Open Graph social preview card."""
    card = Image.new("RGBA", (w, h), "#FBF7EE")
    draw = ImageDraw.Draw(card)

    # Subtle decorative borders & warm sage background section
    draw.rectangle([0, 0, w, 16], fill="#14532D")
    draw.rectangle([0, h - 16, w, h], fill="#F59E0B")

    # Left logo emblem (280x280)
    logo_img = draw_logo(280)
    card.paste(logo_img, (100, 175), logo_img)

    # Title & text
    # Soft sage card container on the right
    card_right = [420, 120, 1100, 510]
    draw.rounded_rectangle(card_right, radius=24, fill="#ECF3E8", outline="#E4E0D2", width=2)

    # Draw text fallback
    # In production/deployment without custom TTF, PIL default or available system fonts
    try:
        font_headline = ImageFont.truetype("arialbd.ttf", 52)
        font_subline = ImageFont.truetype("arial.ttf", 26)
        font_tagline = ImageFont.truetype("arialbd.ttf", 20)
    except Exception:
        font_headline = ImageFont.load_default()
        font_subline = ImageFont.load_default()
        font_tagline = ImageFont.load_default()

    draw.text((460, 170), "Shakambari AI", fill="#14532D", font=font_headline)
    draw.text((460, 245), "Think Smart. Serve Right. Waste Less.", fill="#F59E0B", font=font_tagline)
    draw.text((460, 290), "Food waste intelligence, demand forecasting,", fill="#1C2A1F", font=font_subline)
    draw.text((460, 330), "and verified surplus redistribution for dining halls.", fill="#1C2A1F", font=font_subline)

    draw.rectangle([460, 410, 660, 455], fill="#14532D")
    draw.text((485, 420), "STRICTLY LACTO-VEGETARIAN", fill="#FFFFFF", font=font_tagline)

    return card


def main():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    targets = {
        "favicon-32.png": 32,
        "apple-touch-icon.png": 180,
        "icon-192.png": 192,
        "icon-512.png": 512,
    }

    for name, sz in targets.items():
        out_path = PUBLIC_DIR / name
        img = draw_logo(sz)
        img.save(out_path, format="PNG")
        print(f"Generated {out_path} ({sz}x{sz})")

    og_path = PUBLIC_DIR / "og-card.png"
    og_img = generate_og_card(1200, 630)
    og_img.save(og_path, format="PNG")
    print(f"Generated {og_path} (1200x630)")


if __name__ == "__main__":
    main()
