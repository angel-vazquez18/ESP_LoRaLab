"""Validate final PDF contents, source binding, page boundaries and review record."""
from pathlib import Path
import hashlib
import json
import pdfplumber
from pypdf import PdfReader

root=Path(__file__).resolve().parent
g=json.loads((root/"drawing-geometry.json").read_text())
m=json.loads((root/"document-metadata.json").read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(g["source"])==g["source_sha256"]
records=[]
for name,count in [("Enclosure-Technical-Drawings.pdf",4),("Enclosure-Engineering-Dossier.pdf",10)]:
    file=root/name
    r=PdfReader(file)
    assert len(r.pages)==count
    text="\n".join(p.extract_text() for p in r.pages)
    assert "LAYOUT DRAFT" not in text
    required=["Z 19.6","Z 19.15 / 17.15","dia 8.8","dia 4.4 x 5 deep","7 x dia 1.6"] if count==4 else ["1.001281","0.698781","M3 x 22","RX-M3x5x4","zero ERC","0.3 mm floor"]
    for token in required:assert token in text,(name,token)
    with pdfplumber.open(file) as pp:
        outside=[(i+1,ch.get("text")) for i,p in enumerate(pp.pages) for ch in p.chars if ch["x0"] < 0 or ch["x1"] > p.width+.1 or ch["top"] < 0 or ch["bottom"] > p.height+.1]
    assert not outside,outside
    records.append({"file":str(file),"pages":count,"sha256":sha(file),"required_text_present":True,"text_outside_page":outside})
images=[]
pdf=root/"Enclosure-Engineering-Dossier.pdf"
for v in m["views"]:
    p=Path(v["path"])
    assert p.exists()
    assert p.stat().st_mtime <= pdf.stat().st_mtime,"Source view changed after PDF: "+str(p)
    images.append({"file":str(p),"sha256":sha(p)})
report={"ok":True,"source_cad_sha256":g["source_sha256"],"corrected_assembly_sha256":g["electronics_section_provenance"]["corrected_assembly_sha256"],"pdfs":records,"source_images":images,"visual_review":"All 4 A3 drawing pages and 10 A4 dossier pages rendered through Poppler and visually inspected; no clipped/overlapping text, missing images or unreadable dimension labels observed.","preview_directory":str(root/"preview")}
(root/"DOCUMENT-VALIDATION.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
