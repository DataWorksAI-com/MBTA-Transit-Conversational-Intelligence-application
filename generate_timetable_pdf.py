"""
Converts 7_Day_Study_Plan.md to a clean, printable PDF.
Run: python generate_timetable_pdf.py
"""

import re
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Preformatted
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

INPUT_MD  = Path(__file__).parent / "7_Day_Study_Plan.md"
OUTPUT_PDF = Path(r"C:\Users\Manikandan\Downloads\Apple_WTE_7Day_Timetable.pdf")

# Palette
DARK   = colors.HexColor("#1d1d1f")
BLUE   = colors.HexColor("#0071e3")
GREEN  = colors.HexColor("#30d158")
ORANGE = colors.HexColor("#ff9f0a")
RED    = colors.HexColor("#ff453a")
GRAY   = colors.HexColor("#6e6e73")
LIGHT  = colors.HexColor("#f5f5f7")
BORDER = colors.HexColor("#d2d2d7")
WHITE  = colors.white
CODE_BG = colors.HexColor("#1e1e2e")
CODE_FG = colors.HexColor("#cdd6f4")

# Day accent colours
DAY_COLORS = {
    "DAY 1": colors.HexColor("#0071e3"),
    "DAY 2": colors.HexColor("#30d158"),
    "DAY 3": colors.HexColor("#ff9f0a"),
    "DAY 4": colors.HexColor("#bf5af2"),
    "DAY 5": colors.HexColor("#ff453a"),
    "DAY 6": colors.HexColor("#64d2ff"),
    "DAY 7": colors.HexColor("#ffd60a"),
}

def build_styles():
    def s(name, **kw):
        return ParagraphStyle(name, **kw)
    return {
        "h1":     s("H1", fontName="Helvetica-Bold", fontSize=20, textColor=DARK,
                    spaceAfter=4, spaceBefore=16, leading=26),
        "h2":     s("H2", fontName="Helvetica-Bold", fontSize=14, textColor=BLUE,
                    spaceAfter=4, spaceBefore=14, leading=20),
        "h3":     s("H3", fontName="Helvetica-Bold", fontSize=11, textColor=DARK,
                    spaceAfter=3, spaceBefore=10, leading=16),
        "h4":     s("H4", fontName="Helvetica-Bold", fontSize=10, textColor=GRAY,
                    spaceAfter=2, spaceBefore=6, leading=14),
        "body":   s("Body", fontName="Helvetica", fontSize=9.5, textColor=DARK,
                    spaceAfter=4, leading=14, alignment=TA_JUSTIFY),
        "bullet": s("Bullet", fontName="Helvetica", fontSize=9.5, textColor=DARK,
                    spaceAfter=2, leading=13, leftIndent=16, bulletIndent=4),
        "bullet2":s("Bullet2", fontName="Helvetica", fontSize=9, textColor=DARK,
                    spaceAfter=2, leading=13, leftIndent=32, bulletIndent=20),
        "code":   s("Code", fontName="Courier", fontSize=8.5, textColor=CODE_FG,
                    spaceAfter=0, spaceBefore=0, leading=12),
        "quote":  s("Quote", fontName="Helvetica-BoldOblique", fontSize=10,
                    textColor=BLUE, spaceAfter=6, spaceBefore=6, leading=15,
                    leftIndent=12),
        "time":   s("Time", fontName="Helvetica-Bold", fontSize=9, textColor=BLUE,
                    spaceAfter=1, spaceBefore=0, leading=13),
    }

def header_footer(canvas, doc):
    canvas.saveState()
    w, h = letter
    canvas.setFillColor(DARK)
    canvas.rect(0, h - 28, w, 28, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(36, h - 18, "Apple WTE — 7-Day Interview Prep Timetable")
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(w - 36, h - 18, f"Page {doc.page}")
    canvas.setFillColor(BORDER)
    canvas.rect(0, 0, w, 22, fill=1, stroke=0)
    canvas.setFillColor(GRAY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(36, 6, "Manikandan Meenakshi Sundaram  |  Northeastern University")
    canvas.drawRightString(w - 36, 6, "Apple WTE Interview Prep  |  May 2026")
    canvas.restoreState()

def escape(t):
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def inline_fmt(t):
    t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", t)
    t = re.sub(r"\*\*(.+?)\*\*",     r"<b>\1</b>", t)
    t = re.sub(r"\*(.+?)\*",         r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`",
               r'<font name="Courier" size="8.5" color="#c0392b"><b>\1</b></font>', t)
    return t

def make_code_table(lines, col_w):
    text = "\n".join(lines)
    pre  = Preformatted(text, ParagraphStyle(
        "CP", fontName="Courier", fontSize=8.5, textColor=CODE_FG, leading=12))
    t = Table([[pre]], colWidths=[col_w])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), CODE_BG),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("BOX",           (0,0),(-1,-1), 0.5, colors.HexColor("#45475a")),
    ]))
    return t

def parse_md(text, styles):
    story  = []
    lines  = text.split("\n")
    i      = 0
    in_code = False
    code_buf = []
    table_buf = []
    in_table  = False
    col_w = letter[0] - 2*0.85*inch - 12
    MAX_CODE = 35

    def flush_code():
        nonlocal code_buf
        if not code_buf: return
        chunks = [code_buf[j:j+MAX_CODE] for j in range(0, len(code_buf), MAX_CODE)]
        story.append(Spacer(1, 6))
        for ch in chunks:
            story.append(make_code_table(ch, col_w))
            story.append(Spacer(1, 3))
        story.append(Spacer(1, 3))
        code_buf.clear()

    def flush_table():
        nonlocal table_buf
        if not table_buf: return
        rows = []
        for row in table_buf:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            rows.append(cells)
        rows = [r for r in rows if not all(re.match(r"[-:]+$", c) for c in r)]
        if not rows: table_buf.clear(); return
        cc = max(len(r) for r in rows)
        padded = [r + [""]*(cc-len(r)) for r in rows]
        cw = (letter[0] - 2*inch) / cc

        tdata = []
        for ri, row in enumerate(padded):
            tr = []
            for cell in row:
                cf = inline_fmt(escape(cell))
                if ri == 0:
                    p = Paragraph(f"<b>{cf}</b>", ParagraphStyle("TH",
                        fontName="Helvetica-Bold", fontSize=8.5,
                        textColor=WHITE, leading=12, alignment=TA_CENTER))
                else:
                    p = Paragraph(cf, ParagraphStyle("TD",
                        fontName="Helvetica", fontSize=8.5,
                        textColor=DARK, leading=12))
                tr.append(p)
            tdata.append(tr)

        t = Table(tdata, colWidths=[cw]*cc, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  BLUE),
            ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, colors.HexColor("#f0f4ff")]),
            ("GRID",          (0,0),(-1,-1), 0.5, BORDER),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
            ("RIGHTPADDING",  (0,0),(-1,-1), 6),
            ("TOPPADDING",    (0,0),(-1,-1), 4),
            ("BOTTOMPADDING", (0,0),(-1,-1), 4),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ]))
        story.append(Spacer(1,6))
        story.append(t)
        story.append(Spacer(1,8))
        table_buf.clear()

    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            if in_code: flush_code(); in_code = False
            else:       flush_table(); in_code = True
            i += 1; continue

        if in_code:
            code_buf.append(line); i += 1; continue

        s = line.strip()

        if s.startswith("|"):
            in_table = True; table_buf.append(line); i += 1; continue
        elif in_table:
            flush_table(); in_table = False

        if re.match(r"^-{3,}$", s):
            story.append(Spacer(1,4))
            story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=4))
            i += 1; continue

        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            lvl  = len(m.group(1))
            text = inline_fmt(escape(m.group(2).strip()))

            # Detect day header for colour
            day_color = BLUE
            for dk, dc in DAY_COLORS.items():
                if dk in m.group(2).upper():
                    day_color = dc; break

            if lvl == 1:
                story.append(PageBreak())
                story.append(Paragraph(text, ParagraphStyle("DH",
                    fontName="Helvetica-Bold", fontSize=20, textColor=DARK,
                    spaceAfter=4, spaceBefore=8, leading=26)))
                story.append(HRFlowable(width="100%", thickness=3,
                                        color=day_color, spaceAfter=8))
            elif lvl == 2:
                story.append(Spacer(1,4))
                story.append(Paragraph(text, ParagraphStyle("SH",
                    fontName="Helvetica-Bold", fontSize=14, textColor=day_color,
                    spaceAfter=3, spaceBefore=12, leading=20)))
                story.append(HRFlowable(width="100%", thickness=0.5,
                                        color=BORDER, spaceAfter=4))
            elif lvl == 3:
                story.append(Paragraph(text, styles["h3"]))
            else:
                # Session time headers (e.g. "08:15 – 10:15 | Session 1")
                story.append(Paragraph(text, ParagraphStyle("STime",
                    fontName="Helvetica-Bold", fontSize=10, textColor=ORANGE,
                    spaceAfter=2, spaceBefore=8, leading=14)))
            i += 1; continue

        m2 = re.match(r"^(\s*)[-*]\s+(.+)$", line)
        if m2:
            ind   = len(m2.group(1))
            text  = inline_fmt(escape(m2.group(2)))
            bstyle = styles["bullet2"] if ind >= 4 else styles["bullet"]
            bchar  = "◦" if ind >= 4 else "•"
            story.append(Paragraph(f'<bullet>{bchar}</bullet>{text}', bstyle))
            i += 1; continue

        if not s:
            story.append(Spacer(1,4)); i += 1; continue

        if s.startswith(">"):
            text = inline_fmt(escape(s.lstrip("> ").strip()))
            story.append(Paragraph(text, styles["quote"]))
            i += 1; continue

        # numbered list
        nm = re.match(r"^\d+\.\s+(.+)$", s)
        if nm:
            text = inline_fmt(escape(nm.group(1)))
            story.append(Paragraph(f'<bullet>•</bullet>{text}', styles["bullet"]))
            i += 1; continue

        para_lines = [s]
        while i + 1 < len(lines):
            nxt = lines[i+1].strip()
            if (not nxt or nxt.startswith("#") or nxt.startswith("-")
                    or nxt.startswith("*") or nxt.startswith("|")
                    or nxt.startswith("```") or nxt.startswith(">")
                    or re.match(r"^-{3,}$", nxt) or re.match(r"^\d+\.", nxt)):
                break
            para_lines.append(nxt); i += 1
        text = inline_fmt(escape(" ".join(para_lines)))
        story.append(Paragraph(text, styles["body"]))
        i += 1

    if in_code:  flush_code()
    if in_table: flush_table()
    return story


def cover(styles):
    elems = []
    elems.append(Spacer(1, 0.8*inch))
    elems.append(Paragraph("7-Day Interview Prep",
        ParagraphStyle("CT", fontName="Helvetica-Bold", fontSize=28,
                       textColor=DARK, alignment=TA_CENTER, spaceAfter=4, leading=34)))
    elems.append(Paragraph("Complete Daily Timetable",
        ParagraphStyle("CS", fontName="Helvetica", fontSize=16,
                       textColor=GRAY, alignment=TA_CENTER, spaceAfter=20, leading=22)))
    elems.append(HRFlowable(width="60%", thickness=3, color=BLUE,
                             hAlign="CENTER", spaceAfter=24))

    # Day grid
    days = [
        ("DAY 1", "Python Basics\n+ LeetCode Easy", "#0071e3"),
        ("DAY 2", "ML Fundamentals\n+ From Scratch", "#30d158"),
        ("DAY 3", "RAG Deep Dive\n+ LLM Fine-tuning", "#ff9f0a"),
        ("DAY 4", "Agents\n+ System Design", "#bf5af2"),
        ("DAY 5", "Wireless Protocols\n+ Hard Coding", "#ff453a"),
        ("DAY 6", "Behavioral\n+ Code Review", "#64d2ff"),
        ("DAY 7", "Full Mock\nInterview Day", "#ffd60a"),
    ]

    day_cells = []
    for label, topic, col in days:
        c = colors.HexColor(col)
        cell = [
            Paragraph(f"<b>{label}</b>", ParagraphStyle("DL",
                fontName="Helvetica-Bold", fontSize=13, textColor=WHITE,
                alignment=TA_CENTER, leading=17, spaceAfter=4)),
            Paragraph(topic.replace("\n","<br/>"), ParagraphStyle("DT",
                fontName="Helvetica", fontSize=8.5, textColor=WHITE,
                alignment=TA_CENTER, leading=12))
        ]
        day_cells.append((cell, c))

    # 4 + 3 layout
    row1 = [[dc[0]] for dc in day_cells[:4]]
    row2 = [[dc[0]] for dc in day_cells[4:]]

    def make_row(cells_data, day_data):
        t = Table([cells_data], colWidths=[1.6*inch]*len(cells_data))
        style = [
            ("TOPPADDING",    (0,0),(-1,-1), 12),
            ("BOTTOMPADDING", (0,0),(-1,-1), 12),
            ("LEFTPADDING",   (0,0),(-1,-1), 4),
            ("RIGHTPADDING",  (0,0),(-1,-1), 4),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ]
        for ci, (_, c) in enumerate(day_data):
            style.append(("BACKGROUND", (ci,0),(ci,0), c))
        t.setStyle(TableStyle(style))
        return t

    elems.append(make_row(row1, day_cells[:4]))
    elems.append(Spacer(1,6))
    row2_padded = row2 + [[Paragraph("", ParagraphStyle("e"))]]  # pad to 4
    elems.append(make_row(row2_padded, day_cells[4:] + [(None, LIGHT)]))
    elems.append(Spacer(1, 0.3*inch))

    # Key stats
    stats = [
        ["20 LeetCode Problems", "10 ML Implementations", "5 STAR Stories"],
        ["2 System Designs", "1 Working RAG System", "1 Working Agent"],
    ]
    st = Table(stats, colWidths=[2.1*inch]*3)
    st.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), LIGHT),
        ("FONTNAME",      (0,0),(-1,-1), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,-1), 9),
        ("TEXTCOLOR",     (0,0),(-1,-1), DARK),
        ("GRID",          (0,0),(-1,-1), 0.5, BORDER),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ]))
    elems.append(st)
    elems.append(Spacer(1, 0.25*inch))

    elems.append(Paragraph(
        "8–9 focused hours/day  |  Read → Write from memory → Speak out loud",
        ParagraphStyle("Rule", fontName="Helvetica-Bold", fontSize=10,
                       textColor=BLUE, alignment=TA_CENTER, spaceAfter=4)))
    elems.append(Paragraph(
        "Manikandan Meenakshi Sundaram  |  Northeastern University  |  Apple WTE  |  May 2026",
        ParagraphStyle("Sub", fontName="Helvetica", fontSize=9,
                       textColor=GRAY, alignment=TA_CENTER)))
    elems.append(PageBreak())
    return elems


def main():
    print(f"Reading: {INPUT_MD}")
    md = INPUT_MD.read_text(encoding="utf-8")
    styles = build_styles()

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF), pagesize=letter,
        leftMargin=0.85*inch, rightMargin=0.85*inch,
        topMargin=0.9*inch,   bottomMargin=0.7*inch,
        title="Apple WTE 7-Day Interview Timetable",
        author="Manikandan Meenakshi Sundaram",
    )

    story = cover(styles) + parse_md(md, styles)
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    size = OUTPUT_PDF.stat().st_size / 1024
    print(f"Saved: {OUTPUT_PDF}  ({size:.1f} KB)")


if __name__ == "__main__":
    main()
