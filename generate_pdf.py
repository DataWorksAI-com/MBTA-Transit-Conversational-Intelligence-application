"""
Converts Apple_WTE_Interview_Prep.md to a styled PDF.
Run: python generate_pdf.py
"""

import re
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Preformatted
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

INPUT_MD = Path(__file__).parent / "Apple_WTE_Interview_Prep.md"
OUTPUT_PDF = Path(r"C:\Users\Manikandan\Downloads\Apple_WTE_Interview_Prep.pdf")

# ── Colour palette ────────────────────────────────────────────────────────────
APPLE_DARK   = colors.HexColor("#1d1d1f")
APPLE_BLUE   = colors.HexColor("#0071e3")
APPLE_GRAY   = colors.HexColor("#6e6e73")
APPLE_LIGHT  = colors.HexColor("#f5f5f7")
APPLE_GREEN  = colors.HexColor("#30d158")
APPLE_BORDER = colors.HexColor("#d2d2d7")
CODE_BG      = colors.HexColor("#1e1e2e")   # dark navy
CODE_FG      = colors.HexColor("#cdd6f4")   # light lavender — clearly readable
TABLE_HEADER = colors.HexColor("#0071e3")
TABLE_ALT    = colors.HexColor("#f0f4ff")
WHITE        = colors.white

def build_styles():
    base = getSampleStyleSheet()

    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "h1": style("H1",
            fontName="Helvetica-Bold", fontSize=22, textColor=APPLE_DARK,
            spaceAfter=6, spaceBefore=20, leading=28),
        "h2": style("H2",
            fontName="Helvetica-Bold", fontSize=16, textColor=APPLE_BLUE,
            spaceAfter=4, spaceBefore=16, leading=22,
            borderPad=4),
        "h3": style("H3",
            fontName="Helvetica-Bold", fontSize=13, textColor=APPLE_DARK,
            spaceAfter=4, spaceBefore=12, leading=18),
        "h4": style("H4",
            fontName="Helvetica-Bold", fontSize=11, textColor=APPLE_GRAY,
            spaceAfter=2, spaceBefore=8, leading=15),
        "body": style("Body",
            fontName="Helvetica", fontSize=9.5, textColor=APPLE_DARK,
            spaceAfter=4, spaceBefore=0, leading=14, alignment=TA_JUSTIFY),
        "bullet": style("Bullet",
            fontName="Helvetica", fontSize=9.5, textColor=APPLE_DARK,
            spaceAfter=2, spaceBefore=0, leading=13,
            leftIndent=16, bulletIndent=4),
        "bullet2": style("Bullet2",
            fontName="Helvetica", fontSize=9, textColor=APPLE_DARK,
            spaceAfter=2, spaceBefore=0, leading=13,
            leftIndent=32, bulletIndent=20),
        "code": style("Code",
            fontName="Courier", fontSize=8.5, textColor=CODE_FG,
            spaceAfter=0, spaceBefore=0,
            leading=12, leftIndent=0, rightIndent=0),
        "meta": style("Meta",
            fontName="Helvetica", fontSize=9, textColor=APPLE_GRAY,
            spaceAfter=12, spaceBefore=2, leading=13),
        "callout": style("Callout",
            fontName="Helvetica-Bold", fontSize=10, textColor=APPLE_BLUE,
            spaceAfter=6, spaceBefore=6, leading=14,
            leftIndent=12, borderPad=6),
        "toc_title": style("TOCTitle",
            fontName="Helvetica-Bold", fontSize=18, textColor=APPLE_DARK,
            spaceAfter=12, spaceBefore=8, alignment=TA_CENTER),
        "toc_entry": style("TOCEntry",
            fontName="Helvetica", fontSize=10, textColor=APPLE_DARK,
            spaceAfter=3, spaceBefore=0, leading=14, leftIndent=0),
        "toc_sub": style("TOCSub",
            fontName="Helvetica", fontSize=9, textColor=APPLE_GRAY,
            spaceAfter=2, spaceBefore=0, leading=13, leftIndent=16),
    }


def header_footer(canvas, doc):
    canvas.saveState()
    w, h = letter
    # Header bar
    canvas.setFillColor(APPLE_DARK)
    canvas.rect(0, h - 28, w, 28, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(36, h - 18, "Apple WTE — Wireless Systems AI/ML Engineer Interview Prep")
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(w - 36, h - 18, "Manikandan Meenakshi Sundaram")
    # Footer
    canvas.setFillColor(APPLE_BORDER)
    canvas.rect(0, 0, w, 24, fill=1, stroke=0)
    canvas.setFillColor(APPLE_GRAY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(36, 8, "Confidential — Interview Preparation Material")
    canvas.drawRightString(w - 36, 8, f"Page {doc.page}")
    canvas.restoreState()


def escape(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def inline_format(text: str) -> str:
    """Convert inline markdown (**bold**, `code`, *italic*) to ReportLab tags."""
    # Bold-italic
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # Inline code
    text = re.sub(
        r"`([^`]+)`",
        r'<font name="Courier" size="8.5" color="#c0392b"><b>\1</b></font>',
        text,
    )
    return text


def parse_md(md_text: str, styles: dict):
    """Parse markdown into ReportLab flowables."""
    story = []
    lines = md_text.split("\n")
    i = 0
    in_code = False
    code_buf = []

    def flush_code():
        nonlocal code_buf
        if not code_buf:
            return

        MAX_LINES = 38   # max lines per code block before splitting to new table
        col_w = letter[0] - 2 * 0.85 * inch - 12

        def make_code_table(text: str):
            pre = Preformatted(text, styles["code"], maxLineLength=88)
            t = Table([[pre]], colWidths=[col_w])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), CODE_BG),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#45475a")),
            ]))
            return t

        # Split into chunks of MAX_LINES so no single table overflows a page
        chunks = [code_buf[i:i + MAX_LINES] for i in range(0, len(code_buf), MAX_LINES)]
        story.append(Spacer(1, 6))
        for chunk in chunks:
            story.append(make_code_table("\n".join(chunk)))
            story.append(Spacer(1, 3))
        story.append(Spacer(1, 3))
        code_buf = []

    def add_hr():
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=1,
                                color=APPLE_BORDER, spaceAfter=6))

    # ── table accumulator ────────────────────────────────────────────────────
    table_buf = []
    in_table = False

    def flush_table():
        nonlocal table_buf
        if not table_buf:
            return
        rows = []
        for row in table_buf:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            rows.append(cells)
        if not rows:
            table_buf = []
            return

        # Remove separator row (---|---)
        rows = [r for r in rows if not all(re.match(r"[-:]+$", c) for c in r)]

        if not rows:
            table_buf = []
            return

        col_count = max(len(r) for r in rows)
        # Pad rows
        padded = [r + [""] * (col_count - len(r)) for r in rows]

        col_width = (letter[0] - 2 * inch) / col_count

        tbl_data = []
        for ri, row in enumerate(padded):
            tbl_row = []
            for ci, cell in enumerate(row):
                cell_escaped = escape(cell)
                cell_fmt = inline_format(cell_escaped)
                if ri == 0:
                    p = Paragraph(f"<b>{cell_fmt}</b>",
                                  ParagraphStyle("TH",
                                      fontName="Helvetica-Bold",
                                      fontSize=8.5,
                                      textColor=WHITE,
                                      leading=12,
                                      alignment=TA_CENTER))
                else:
                    p = Paragraph(cell_fmt,
                                  ParagraphStyle("TD",
                                      fontName="Helvetica",
                                      fontSize=8.5,
                                      textColor=APPLE_DARK,
                                      leading=12))
                tbl_row.append(p)
            tbl_data.append(tbl_row)

        t = Table(tbl_data, colWidths=[col_width] * col_count,
                  repeatRows=1)
        tbl_style = [
            ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER),
            ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 8.5),
            ("ALIGN",      (0, 0), (-1, 0), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, TABLE_ALT]),
            ("GRID",       (0, 0), (-1, -1), 0.5, APPLE_BORDER),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ]
        t.setStyle(TableStyle(tbl_style))
        story.append(Spacer(1, 6))
        story.append(t)
        story.append(Spacer(1, 8))
        table_buf = []

    while i < len(lines):
        line = lines[i]

        # ── code fence ───────────────────────────────────────────────────────
        if line.startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_table()
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # ── table row ────────────────────────────────────────────────────────
        stripped = line.strip()
        if stripped.startswith("|"):
            in_table = True
            table_buf.append(line)
            i += 1
            continue
        elif in_table:
            flush_table()
            in_table = False

        # ── horizontal rule ──────────────────────────────────────────────────
        if re.match(r"^-{3,}$", stripped):
            add_hr()
            i += 1
            continue

        # ── headings ─────────────────────────────────────────────────────────
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = escape(m.group(2).strip())
            text = inline_format(text)
            skey = {1: "h1", 2: "h2", 3: "h3", 4: "h4"}.get(level, "h4")

            if level == 1:
                story.append(PageBreak())
                story.append(Paragraph(text, styles["h1"]))
                story.append(HRFlowable(width="100%", thickness=2,
                                        color=APPLE_BLUE, spaceAfter=8))
            elif level == 2:
                story.append(Spacer(1, 4))
                story.append(Paragraph(text, styles["h2"]))
                story.append(HRFlowable(width="100%", thickness=0.5,
                                        color=APPLE_BORDER, spaceAfter=4))
            else:
                story.append(Paragraph(text, styles[skey]))
            i += 1
            continue

        # ── bullets ──────────────────────────────────────────────────────────
        m2 = re.match(r"^(\s*)[-*]\s+(.+)$", line)
        if m2:
            indent = len(m2.group(1))
            text = escape(m2.group(2))
            text = inline_format(text)
            bstyle = styles["bullet2"] if indent >= 4 else styles["bullet"]
            bullet_char = "◦" if indent >= 4 else "•"
            story.append(Paragraph(
                f'<bullet>{bullet_char}</bullet>{text}', bstyle))
            i += 1
            continue

        # ── blank line ───────────────────────────────────────────────────────
        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        # ── block quote / callout (lines starting with >) ────────────────────
        if stripped.startswith(">"):
            text = escape(stripped.lstrip("> ").strip())
            text = inline_format(text)
            story.append(Paragraph(text, styles["callout"]))
            i += 1
            continue

        # ── regular paragraph ────────────────────────────────────────────────
        # Accumulate consecutive body lines
        para_lines = [stripped]
        while i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if (not nxt or nxt.startswith("#") or nxt.startswith("-")
                    or nxt.startswith("*") or nxt.startswith("|")
                    or nxt.startswith("```") or nxt.startswith(">")
                    or re.match(r"^-{3,}$", nxt)):
                break
            para_lines.append(nxt)
            i += 1
        text = escape(" ".join(para_lines))
        text = inline_format(text)
        story.append(Paragraph(text, styles["body"]))
        i += 1

    if in_code:
        flush_code()
    if in_table:
        flush_table()

    return story


def cover_page(styles):
    """Return flowables for a cover page."""
    elems = []
    elems.append(Spacer(1, 1.2 * inch))

    # Apple-style logo block
    elems.append(Paragraph("", ParagraphStyle("Logo",
        fontName="Helvetica-Bold", fontSize=48,
        textColor=APPLE_DARK, alignment=TA_CENTER, spaceAfter=0)))

    elems.append(Spacer(1, 0.2 * inch))
    elems.append(HRFlowable(width="60%", thickness=3, color=APPLE_BLUE,
                             hAlign="CENTER", spaceAfter=20))

    elems.append(Paragraph(
        "Apple Wireless Systems AI/ML Engineer",
        ParagraphStyle("CoverTitle",
            fontName="Helvetica-Bold", fontSize=26,
            textColor=APPLE_DARK, alignment=TA_CENTER, leading=32,
            spaceAfter=4)
    ))
    elems.append(Paragraph(
        "Complete Interview Preparation Guide",
        ParagraphStyle("CoverSub",
            fontName="Helvetica", fontSize=16,
            textColor=APPLE_GRAY, alignment=TA_CENTER, leading=22,
            spaceAfter=20)
    ))

    elems.append(HRFlowable(width="60%", thickness=1, color=APPLE_BORDER,
                             hAlign="CENTER", spaceAfter=24))

    # Candidate info box
    info_data = [
        [Paragraph("<b>Candidate</b>",
                   ParagraphStyle("IK", fontName="Helvetica-Bold", fontSize=10,
                                  textColor=APPLE_GRAY, alignment=TA_CENTER)),
         Paragraph("<b>Role</b>",
                   ParagraphStyle("IK", fontName="Helvetica-Bold", fontSize=10,
                                  textColor=APPLE_GRAY, alignment=TA_CENTER)),
         Paragraph("<b>Organization</b>",
                   ParagraphStyle("IK", fontName="Helvetica-Bold", fontSize=10,
                                  textColor=APPLE_GRAY, alignment=TA_CENTER))],
        [Paragraph("Manikandan Meenakshi Sundaram",
                   ParagraphStyle("IV", fontName="Helvetica-Bold", fontSize=11,
                                  textColor=APPLE_DARK, alignment=TA_CENTER)),
         Paragraph("Wireless Systems AI/ML Engineer",
                   ParagraphStyle("IV", fontName="Helvetica", fontSize=11,
                                  textColor=APPLE_DARK, alignment=TA_CENTER)),
         Paragraph("Wireless Technologies &amp; Ecosystems (WTE)",
                   ParagraphStyle("IV", fontName="Helvetica", fontSize=11,
                                  textColor=APPLE_DARK, alignment=TA_CENTER))],
    ]
    info_table = Table(info_data, colWidths=[2.0*inch, 2.5*inch, 2.5*inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), APPLE_LIGHT),
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, APPLE_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elems.append(info_table)
    elems.append(Spacer(1, 0.3 * inch))

    # Round overview
    rounds = [
        ["Round", "Focus", "Your Edge"],
        ["Phone Screen", "Intro + high-level ML/wireless", "MBTA CI Cisco feature, Crewasis RAG"],
        ["Technical 1", "AI/ML deep dive (LLMs, RAG, agents)", "Production RAG, LangGraph, LoRA/DPO"],
        ["Technical 2", "Wireless protocols (WiFi, BT, Thread)", "Study Section 3 hardest — gap area"],
        ["Technical 3", "Python coding + data analysis", "Strong — Spark, Pandas, PyTorch"],
        ["System Design", "End-to-end AI agent architecture", "MBTA CI distributed architecture"],
        ["Behavioral", "Ownership, impact, collaboration", "MBTA CI featured, $72K contract"],
    ]
    r_table = Table(rounds, colWidths=[1.3*inch, 2.5*inch, 3.2*inch])
    r_style = [
        ("BACKGROUND", (0, 0), (-1, 0), APPLE_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, TABLE_ALT]),
        ("GRID", (0, 0), (-1, -1), 0.5, APPLE_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#fff3cd")),  # highlight wireless gap
    ]
    r_table.setStyle(TableStyle(r_style))
    elems.append(r_table)

    elems.append(Spacer(1, 0.3 * inch))
    elems.append(Paragraph(
        "May 2026 | Northeastern University MS Applied Machine Intelligence",
        ParagraphStyle("Footer2",
            fontName="Helvetica", fontSize=9,
            textColor=APPLE_GRAY, alignment=TA_CENTER)
    ))
    elems.append(PageBreak())
    return elems


def main():
    print(f"Reading: {INPUT_MD}")
    md_text = INPUT_MD.read_text(encoding="utf-8")

    styles = build_styles()

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.7 * inch,
        title="Apple WTE Interview Prep — Manikandan Meenakshi Sundaram",
        author="Manikandan Meenakshi Sundaram",
        subject="Apple Wireless Systems AI/ML Engineer Interview Preparation",
    )

    story = []
    story += cover_page(styles)
    story += parse_md(md_text, styles)

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(f"PDF saved: {OUTPUT_PDF}")
    print(f"File size: {OUTPUT_PDF.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
