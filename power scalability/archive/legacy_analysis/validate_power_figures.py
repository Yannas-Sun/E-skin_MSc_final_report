"""Validate generated figure files without modifying the data or artwork."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image
from pypdf import PdfReader


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def embedded_font(font) -> bool:
    font = font.get_object()
    descendants = font.get("/DescendantFonts")
    if descendants:
        return all(embedded_font(item) for item in descendants)
    descriptor = font.get("/FontDescriptor")
    return bool(descriptor and any(
        name in descriptor.get_object()
        for name in ("/FontFile", "/FontFile2", "/FontFile3")
    ))


def validate(figure_dir: Path) -> dict:
    manifest = json.loads((figure_dir / "figure_manifest.json").read_text(encoding="utf-8"))
    source = Path(manifest["source_csv"])
    if not source.is_absolute():
        # The legacy manifest stores paths relative to Final; resolve them
        # independently of the caller's current working directory.
        source = Path(__file__).resolve().parents[3] / source
    check(digest(source) == manifest["source_sha256"], "Source CSV changed since generation")
    script_dir = Path(__file__).resolve().parent
    for name, field in (("power_figures.py", "plot_script_sha256"),
                        ("power_report.mplstyle", "style_sha256")):
        check(digest(script_dir / name) == manifest[field], f"Regenerate after changing {name}")
    check(len(manifest["figures"]) == 7, "Expected seven figures")

    results = []
    for entry in manifest["figures"]:
        stem = entry["stem"]
        expected_mm = entry["dimensions_mm"]
        check(not entry["text_outside_canvas"], f"Text is clipped in {stem}")
        check({Path(item["name"]).suffix for item in entry["formats"]} ==
              {".png", ".pdf", ".svg"}, f"Incomplete exports for {stem}")
        for item in entry["formats"]:
            check(digest(figure_dir / item["name"]) == item["sha256"],
                  f"Export hash mismatch: {item['name']}")

        with Image.open(figure_dir / f"{stem}.png") as png:
            dpi = png.info.get("dpi", (0, 0))
            check(all(abs(value - 300) < 0.1 for value in dpi), f"Wrong PNG DPI: {stem}")
            expected_pixels = [value / 25.4 * 300 for value in expected_mm]
            check(all(abs(a - b) <= 1 for a, b in zip(png.size, expected_pixels)),
                  f"Wrong PNG canvas: {stem}")
            check(png.convert("RGBA").getchannel("A").getextrema() == (255, 255),
                  f"Transparent PNG: {stem}")
            dimensions_px = list(png.size)

        pdf = PdfReader(figure_dir / f"{stem}.pdf")
        check(len(pdf.pages) == 1, f"Wrong PDF page count: {stem}")
        page = pdf.pages[0]
        page_mm = [float(page.mediabox.width) * 25.4 / 72,
                   float(page.mediabox.height) * 25.4 / 72]
        check(all(abs(a - b) < 0.02 for a, b in zip(page_mm, expected_mm)),
              f"Wrong PDF canvas: {stem}")
        fonts = page["/Resources"].get_object()["/Font"].get_object()
        check(bool(fonts) and all(embedded_font(font) for font in fonts.values()),
              f"Unembedded PDF font: {stem}")

        svg = ET.parse(figure_dir / f"{stem}.svg").getroot()
        text_nodes = svg.findall(".//{http://www.w3.org/2000/svg}text")
        check(bool(text_nodes), f"SVG does not retain editable text: {stem}")
        label_text = " ".join("".join(node.itertext()) for node in text_nodes)
        check(not any("\u4e00" <= char <= "\u9fff" for char in label_text),
              f"Non-English chart label: {stem}")
        results.append({"stem": stem, "status": "PASS", "png_pixels": dimensions_px,
                        "png_dpi": list(dpi), "png_opaque": True,
                        "pdf_mm": [round(v, 3) for v in page_mm],
                        "pdf_fonts_embedded": True, "svg_text_elements": len(text_nodes),
                        "export_hashes_match": True, "text_inside_canvas": True})
    return {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "PASS", "source_sha256": digest(source),
            "scope": "File integrity, canvas, DPI, opacity, embedded PDF fonts and SVG text; not a scientific-validity or journal-compliance certification.",
            "figures": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure-dir", type=Path,
                        default=Path(__file__).resolve().parent / "DATA_analysis/figures")
    args = parser.parse_args()
    report = validate(args.figure_dir)
    target = args.figure_dir / "figure_validation.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(report['figures'])} figures / 21 exports. {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
