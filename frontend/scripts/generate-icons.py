#!/usr/bin/env python3
"""Regenerate Shakambari AI PNG icons from public/logo.svg. Requires cairosvg."""
from pathlib import Path
import cairosvg

PUBLIC = Path(__file__).resolve().parents[1] / "public"
source = PUBLIC / "logo.svg"
for filename, size in (("favicon-32.png", 32), ("apple-touch-icon.png", 180),
                       ("icon-192.png", 192), ("icon-512.png", 512)):
    cairosvg.svg2png(url=str(source), write_to=str(PUBLIC / filename),
                     output_width=size, output_height=size)
print("Generated Shakambari AI icon assets in", PUBLIC)
