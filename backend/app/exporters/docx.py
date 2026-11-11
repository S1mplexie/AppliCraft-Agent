"""轻量 Markdown -> DOCX 导出器，不引入额外重型依赖。"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
NUMBER_RE = re.compile(r"^\d+[.)]\s+(.*)$")


def _plain(text: str) -> str:
    return text.replace("`", "").replace("*", "").replace("[", "").replace("]", "")


def _add_runs(paragraph, text: str) -> None:
    cursor = 0
    for match in BOLD_RE.finditer(text):
        if match.start() > cursor:
            paragraph.add_run(_plain(text[cursor : match.start()]))
        run = paragraph.add_run(_plain(match.group(1)))
        run.bold = True
        cursor = match.end()
    if cursor < len(text):
        paragraph.add_run(_plain(text[cursor:]))


def markdown_to_docx(markdown: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    try:
        rpr = normal.element.get_or_add_rPr()
        rpr.get_or_add_rFonts().set(qn("w:eastAsia"), "Microsoft YaHei")
    except Exception:  # pragma: no cover - font hint is cosmetic
        pass

    for section in doc.sections:
        section.top_margin = Inches(0.85)
        section.bottom_margin = Inches(0.85)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            paragraph = doc.add_heading(_plain(line[4:]), level=3)
        elif line.startswith("## "):
            paragraph = doc.add_heading(_plain(line[3:]), level=2)
        elif line.startswith("# "):
            paragraph = doc.add_heading(_plain(line[2:]), level=1)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        elif BULLET_RE.match(line):
            paragraph = doc.add_paragraph(style="List Bullet")
            _add_runs(paragraph, BULLET_RE.match(line).group(1))
            continue
        elif NUMBER_RE.match(line):
            paragraph = doc.add_paragraph(style="List Number")
            _add_runs(paragraph, NUMBER_RE.match(line).group(1))
            continue
        elif set(line.strip()) == {"-"}:
            paragraph = doc.add_paragraph("─" * 24)
        else:
            paragraph = doc.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(6)
            _add_runs(paragraph, line)
            continue
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)

    doc.save(str(out_path))
    return out_path
