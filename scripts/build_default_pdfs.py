"""Convert the bundled default A-Z documents to PDF (run once after changing backend/assets/defaults)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services import file_converter, file_detector, pdf_merger  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "backend" / "assets" / "defaults"
OUT = SRC / "pdf"
OUT.mkdir(exist_ok=True)
for f in sorted(SRC.iterdir()):
    if not f.is_file():
        continue
    kind = file_detector.detect(f.name, None)
    dest = OUT / (f.stem + ".pdf")
    if kind.category == "pdf":
        dest.write_bytes(f.read_bytes())
    else:
        file_converter.convert_to_pdf(f, kind, dest, f.name)
    pdf_merger.validate_pdf(dest, f.name)
    print("ok", f.name, "->", dest.name, dest.stat().st_size)
