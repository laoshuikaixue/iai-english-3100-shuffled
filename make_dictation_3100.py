from __future__ import annotations

import argparse
import hashlib
import html
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
for candidate in (SCRIPT_DIR, SCRIPT_DIR.parent, SCRIPT_DIR.parent.parent):
    if (candidate / "make_shuffled_3100.py").exists():
        sys.path.insert(0, str(candidate))
for candidate in (SCRIPT_DIR, SCRIPT_DIR.parent, SCRIPT_DIR.parent.parent):
    dependency_dir = candidate / "tmp" / "pdf-deps"
    if dependency_dir.is_dir():
        sys.path.insert(0, str(dependency_dir))

from make_shuffled_3100 import (  # noqa: E402
    BODY_BOTTOM,
    BODY_TOP,
    Entry,
    NumberedCanvas,
    extract_entries,
    extract_visual_rows,
    markup_text,
    register_fonts,
)
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


@dataclass(frozen=True)
class Question:
    number: int
    entry: Entry
    direction: str


class DictationCanvas(NumberedCanvas):
    """Page number plus a restrained, formal authorship mark."""

    def _draw_page_number(self, total_pages: int) -> None:
        super()._draw_page_number(total_pages)
        self.saveState()
        width, _ = A4
        self.setFillColor(colors.HexColor("#777777"))
        self.setFont("STKaiti", 8.5)
        self.drawRightString(width - 12 * mm, 8.5 * mm, "编制：LaoShui")
        self.restoreState()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def quiz_headword(entry: Entry) -> str:
    headword = normalize_text(entry.headword)
    headword = re.sub(r"\s+(?:BrE|AmE)$", "", headword)
    headword = re.sub(r"\*+$", "", headword)
    return headword.strip()


def chinese_prompt(entry: Entry) -> str:
    full_text = normalize_text(" ".join(entry.rows))
    raw_headword = normalize_text(entry.headword)
    remainder = full_text[len(raw_headword) :] if full_text.startswith(raw_headword) else full_text

    # Remove pronunciation and English-only labels before retaining the Chinese clue.
    remainder = re.sub(r"(?:BrE|AmE)\s*/[^/]+/", " ", remainder)
    remainder = re.sub(r"/[^/]{1,120}/", " ", remainder)
    remainder = re.sub(r"[A-Za-z]+(?:[.'’-][A-Za-z]+)*", " ", remainder)

    allowed_punctuation = set(
        "，。；：、（）()《》〈〉…“”‘’！!?？-—·/＋+＝=,."
    )
    kept: list[str] = []
    for char in remainder:
        if "\u4e00" <= char <= "\u9fff" or char.isdigit() or char in allowed_punctuation:
            kept.append(char)
        else:
            kept.append(" ")
    prompt = normalize_text("".join(kept))
    prompt = re.sub(r"^[\s，。；：、/()（）.。-]+", "", prompt)
    prompt = re.sub(r"[\s，。；：、/.]+$", "", prompt)
    return prompt or "（请根据词条释义作答）"


def direction_for(entry: Entry) -> str:
    digest = hashlib.sha256(quiz_headword(entry).encode("utf-8")).digest()
    return "en_to_zh" if digest[0] % 2 == 0 else "zh_to_en"


def make_questions(entries: list[Entry], mode: str) -> list[Question]:
    if mode not in {"mixed", "en_to_zh", "zh_to_en"}:
        raise ValueError(f"Unsupported dictation mode: {mode}")
    return [
        Question(
            number=index,
            entry=entry,
            direction=direction_for(entry) if mode == "mixed" else mode,
        )
        for index, entry in enumerate(entries, start=1)
    ]


def answer_text(question: Question) -> str:
    return normalize_text(" ".join(question.entry.rows))


def question_text(
    question: Question, cjk_font, latin_font, show_direction: bool
) -> str:
    if question.direction == "en_to_zh":
        prompt = markup_text(quiz_headword(question.entry), cjk_font, latin_font)
        if show_direction:
            prompt = "<font color='#245A9A'>英</font>　" + prompt
    else:
        prompt = markup_text(chinese_prompt(question.entry), cjk_font, latin_font)
        if show_direction:
            prompt = "<font color='#A05A00'>中</font>　" + prompt
    return (
        f"<b>{question.number}.</b> {prompt}"
        "<br/><font color='#999999'>________________________________</font>"
    )


def answer_cell_text(
    question: Question, cjk_font, latin_font, show_direction: bool
) -> str:
    direction = "英→中" if question.direction == "en_to_zh" else "中→英"
    marker = f"[{direction}] " if show_direction else ""
    text = f"{question.number}. {marker}{answer_text(question)}"
    return markup_text(text, cjk_font, latin_font)


def draw_header(canvas, document) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#D8D8D8"))
    canvas.setLineWidth(0.4)
    canvas.line(12 * mm, height - 16 * mm, width - 12 * mm, height - 16 * mm)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.setFont("STKaiti", 8.5)
    canvas.drawString(12 * mm, height - 11.5 * mm, document._dictation_header)
    canvas.restoreState()


def build_pdf(
    questions: list[Question],
    output_path: Path,
    title: str,
    header: str,
    show_direction: bool,
    answer: bool,
) -> None:
    cjk_font, latin_font = register_fonts()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DictationTitle",
        parent=styles["Title"],
        fontName="STSong",
        fontSize=18,
        leading=25,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#171717"),
        spaceAfter=3 * mm,
    )
    question_style = ParagraphStyle(
        "DictationQuestion",
        parent=styles["BodyText"],
        fontName="STKaiti",
        fontSize=9.6,
        leading=12.2,
        alignment=TA_LEFT,
        textColor=colors.black,
        wordWrap="CJK",
    )
    answer_style = ParagraphStyle(
        "DictationAnswer",
        parent=question_style,
        fontSize=8.1,
        leading=10.2,
    )

    usable_width = A4[0] - 24 * mm
    cell_width = usable_width / 2
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=21 * mm,
        bottomMargin=17 * mm,
        title=title,
        author="LaoShui",
        subject="IAI English 3100词默写版",
        creator="LaoShui",
    )
    document._dictation_header = header

    story = [
        Spacer(1, 3 * mm),
        Paragraph(title, title_style),
        Spacer(1, 1.5 * mm),
    ]

    table_rows = []
    for row_start in range(0, len(questions), 2):
        pair = questions[row_start : row_start + 2]
        cells = []
        for question in pair:
            cell_markup = (
                answer_cell_text(question, cjk_font, latin_font, show_direction)
                if answer
                else question_text(question, cjk_font, latin_font, show_direction)
            )
            cells.append(Paragraph(cell_markup, answer_style if answer else question_style))
        if len(cells) == 1:
            cells.append("")
        table_rows.append(cells)

    # One long table lets ReportLab fill each page to the usable bottom edge,
    # while still splitting only between complete question rows.
    table = LongTable(
        table_rows,
        colWidths=[cell_width, cell_width],
        hAlign="LEFT",
        repeatRows=0,
        splitByRow=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3.2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3.2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#E2E2E2")),
                ("LINEAFTER", (0, 0), (0, -1), 0.25, colors.HexColor("#E2E2E2")),
            ]
        )
    )
    story.append(table)

    document.build(
        story,
        onFirstPage=draw_header,
        onLaterPages=draw_header,
        canvasmaker=DictationCanvas,
    )


def make_outputs(input_pdf: Path, output_dir: Path, seed: str) -> list[Path]:
    rows = extract_visual_rows(input_pdf)
    entries = extract_entries(rows)
    if len(entries) < 3000:
        raise RuntimeError(f"Only {len(entries)} entries were detected; extraction is incomplete.")

    shuffled_entries = list(entries)
    random.Random(seed).shuffle(shuffled_entries)

    corrected = "校正版" in input_pdf.name
    edition = "2025校正版" if corrected else "2025版"
    stem = f"高中英语3100词默写版（{edition}）"
    variants = [
        ("混合", "mixed", True),
        ("中文写英文", "zh_to_en", False),
        ("英文写中文", "en_to_zh", False),
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for label, mode, show_direction in variants:
        ordered = make_questions(entries, mode)
        shuffled = make_questions(shuffled_entries, mode)
        ordered_output = output_dir / f"{stem}_{label}_正序.pdf"
        shuffled_output = output_dir / f"{stem}_{label}_乱序.pdf"
        answer_output = output_dir / f"{stem}_{label}_乱序答案.pdf"
        outputs.extend([ordered_output, shuffled_output, answer_output])
        build_pdf(
            ordered,
            ordered_output,
            f"高中英语3100词默写版（{edition}）· {label} · 正序",
            f"{edition} · 默写版 · {label} · 正序",
            show_direction,
            False,
        )
        build_pdf(
            shuffled,
            shuffled_output,
            f"高中英语3100词默写版（{edition}）· {label} · 乱序",
            f"{edition} · 默写版 · {label} · 乱序",
            show_direction,
            False,
        )
        build_pdf(
            shuffled,
            answer_output,
            f"高中英语3100词默写版（{edition}）· {label} · 乱序答案",
            f"{edition} · 默写答案 · {label} · 乱序",
            show_direction,
            True,
        )
    print(f"Detected entries: {len(entries)}")
    print(f"Output directory: {output_dir.resolve()}")
    for output in outputs:
        print(f"Output: {output.resolve()}")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Create ordered and shuffled dictation PDFs.")
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--seed",
        default="LaoShui-IAI-English-3100-dictation-2026-07-20",
        help="Deterministic shuffle seed.",
    )
    args = parser.parse_args()
    make_outputs(args.input_pdf, args.output_dir, args.seed)


if __name__ == "__main__":
    main()
