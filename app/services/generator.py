"""Single predefined certificate template rendered to PDF (ReportLab).

A deliberate failure hook: any recipient whose name contains 'FAIL' raises,
so per-certificate failure isolation can be demonstrated and tested.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def generate_certificate_pdf(
    dest: str | Path,
    recipient_name: str,
    course_name: str,
    issuer: str = "Organization",
    certificate_id: str = "",
) -> Path:
    name = (recipient_name or "").strip()
    if not name:
        raise ValueError("recipient name is required")
    if "FAIL" in name.upper():
        raise RuntimeError(f"simulated generation failure for recipient '{recipient_name}'")

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    w, h = landscape(A4)
    c = canvas.Canvas(str(dest), pagesize=landscape(A4))
    # Border
    c.setStrokeColorRGB(0.2, 0.35, 0.6)
    c.setLineWidth(4)
    c.rect(12 * mm, 12 * mm, w - 24 * mm, h - 24 * mm)
    c.setLineWidth(1)
    c.rect(16 * mm, 16 * mm, w - 32 * mm, h - 32 * mm)
    # Title
    c.setFont("Helvetica-Bold", 34)
    c.setFillColorRGB(0.15, 0.25, 0.45)
    c.drawCentredString(w / 2, h - 55 * mm, "Certificate of Completion")
    # Recipient
    c.setFont("Helvetica", 14)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(w / 2, h - 75 * mm, "Proudly presented to")
    c.setFont("Helvetica-Bold", 28)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawCentredString(w / 2, h - 92 * mm, name)
    # Course
    c.setFont("Helvetica", 14)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(w / 2, h - 108 * mm, "for successfully completing")
    c.setFont("Helvetica-Bold", 18)
    c.setFillColorRGB(0.15, 0.25, 0.45)
    c.drawCentredString(w / 2, h - 122 * mm, course_name or "—")
    # Footer: issuer + cert id
    c.setFont("Helvetica", 11)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawCentredString(w / 2, 32 * mm, f"Issued by {issuer}")
    if certificate_id:
        c.setFont("Helvetica", 8)
        c.drawCentredString(w / 2, 25 * mm, f"Certificate ID: {certificate_id}")
    c.showPage()
    c.save()
    return dest
