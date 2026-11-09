"""Word report: plots, a summary table of significant effects, and detail tables.

Tables follow APA layout: horizontal rules only, header rows that repeat on each page,
rows that never split across pages, and light banding by item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from . import analysis as an
from .plots import footnote_lines
from .results import Results

BLACK, GRAY = (8, "000000"), (4, "BFBFBF")
BAND = "F2F2F2"


# ----------------------------------------------------------------- low-level helpers


def _shade(cell, fill: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _borders(cell, top=None, bottom=None) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcBorders")):
        tcPr.remove(old)
    b = OxmlElement("w:tcBorders")
    for edge, spec in (("top", top), ("left", None), ("bottom", bottom), ("right", None)):
        el = OxmlElement(f"w:{edge}")
        if spec:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(spec[0]))
            el.set(qn("w:color"), spec[1])
        else:
            el.set(qn("w:val"), "nil")
        b.append(el)
    tcPr.append(b)


def _row_flags(row, header: bool = False) -> None:
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))
    if header:
        trPr.append(OxmlElement("w:tblHeader"))


def _mark_size(para, pt: float) -> None:
    """Paragraph-mark size: keeps empty cells the same height as filled ones."""
    pPr = para._p.get_or_add_pPr()
    rPr = pPr.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        pPr.append(rPr)
    for tag in ("w:sz", "w:szCs"):
        el = OxmlElement(tag)
        el.set(qn("w:val"), str(int(pt * 2)))
        rPr.append(el)


def _set_text(cell, text: str, bold: bool = False) -> None:
    para = cell.paragraphs[0]
    for r in list(para.runs):
        r._r.getparent().remove(r._r)
    run = para.add_run(text)
    run.bold = bold


def _fmt(x, nd=2) -> str:
    return "–" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def _short(x: float) -> str:
    """0.05 -> '.05' (no trailing zeros, no leading zero)."""
    return f"{x:g}".replace("0.", ".", 1) if 0 < x < 1 else f"{x:g}"


def _ci(lo, hi) -> str:
    return "–" if not (np.isfinite(lo) and np.isfinite(hi)) else f"[{lo:.2f}, {hi:.2f}]"


# ----------------------------------------------------------------- generic table


@dataclass
class Block:
    """Rows for one item, plus vertical merges (col, first_row, last_row) within it."""

    rows: list[list[tuple[str, bool]]] = field(default_factory=list)
    merges: list[tuple[int, int, int]] = field(default_factory=list)


class Report:
    def __init__(self, res: Results):
        self.res = res
        w = res.cfg["output"]["word"]
        self.doc = Document()
        sec = self.doc.sections[0]
        if w["landscape"]:
            sec.orientation = WD_ORIENT.LANDSCAPE
            sec.page_width, sec.page_height = sec.page_height, sec.page_width
        sec.left_margin = sec.right_margin = Inches(w["margin_in"])
        self.usable = (sec.page_width - sec.left_margin - sec.right_margin) / 914400  # inches
        self.table_no = w["first_table_number"]

    # -- shared table writer
    def table(self, title, header_rows, blocks, widths, note, header_merges=()):
        """header_rows: list of rows of text; header_merges: (row, col_from, col_to) spans."""
        doc = self.doc
        doc.add_page_break()
        cap = doc.add_paragraph()
        cap.add_run(f"Table {self.table_no}").bold = True
        cap.add_run(f"\n{title}").italic = True
        self.table_no += 1

        ncol = len(header_rows[0])
        scale = min(1.0, self.usable / sum(widths))
        widths = [Inches(w * scale) for w in widths]
        tbl = doc.add_table(rows=len(header_rows), cols=ncol)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        nh = len(header_rows)
        for r, texts in enumerate(header_rows):
            row = tbl.rows[r]
            _row_flags(row, header=True)
            for j, text in enumerate(texts):
                _set_text(row.cells[j], text, bold=True)
                _borders(row.cells[j], top=BLACK if r == 0 else None,
                         bottom=BLACK if r == nh - 1 else None)
        for r, c0, c1 in header_merges:
            text = tbl.cell(r, c0).text
            merged = tbl.cell(r, c0).merge(tbl.cell(r, c1))
            for extra in merged.paragraphs[1:]:
                extra._element.getparent().remove(extra._element)
            _set_text(merged, text, bold=True)
            _borders(merged, top=BLACK if r == 0 else None, bottom=BLACK)
        # a header cell spanning all header rows (first column)
        if nh > 1:
            text = tbl.cell(0, 0).text
            merged = tbl.cell(0, 0).merge(tbl.cell(nh - 1, 0))
            for extra in merged.paragraphs[1:]:
                extra._element.getparent().remove(extra._element)
            _set_text(merged, text, bold=True)
            _borders(merged, top=BLACK, bottom=BLACK)

        for b, block in enumerate(blocks):
            start = len(tbl.rows)
            for r, cells in enumerate(block.rows):
                tr = tbl.add_row()
                _row_flags(tr)
                last_in_block = r == len(block.rows) - 1
                last = last_in_block and b == len(blocks) - 1
                for j, (text, bold) in enumerate(cells):
                    c = tr.cells[j]
                    _set_text(c, text, bold)
                    if b % 2 == 1:
                        _shade(c, BAND)
                    _borders(c, bottom=BLACK if last else GRAY if last_in_block else None)
            for col, r0, r1 in block.merges:
                if r1 <= r0:
                    continue
                top = tbl.cell(start + r0, col)
                text = top.text
                bold = any(run.bold for run in top.paragraphs[0].runs)
                merged = top.merge(tbl.cell(start + r1, col))
                for extra in merged.paragraphs[1:]:
                    extra._element.getparent().remove(extra._element)
                _set_text(merged, text, bold)

        for j, col in enumerate(tbl.columns):
            col.width = widths[j]
        for tr in tbl.rows:
            for j, c in enumerate(tr.cells):
                c.width = widths[j]
                c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                for para in c.paragraphs:
                    para.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.CENTER
                    para.paragraph_format.space_after = Pt(0)
                    _mark_size(para, 9)
                    for run in para.runs:
                        run.font.size = Pt(9)
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(6)
        para.add_run("Note. ").italic = True
        para.add_run(note)
        for run in para.runs:
            run.font.size = Pt(8.5)

    # -- content
    def plots(self, images):
        w = self.res.cfg["output"]["word"]
        width = Inches(min(w["plot_width_in"], self.usable))
        for caption, path in images:
            if w["plot_headings"]:
                self.doc.add_paragraph(caption, style="Heading 2")
            self.doc.add_picture(str(path), width=width)
        if w["end_note"] and self.res.prep.factors:
            para = self.doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            lines = footnote_lines(self.res)
            for k, line in enumerate(lines):
                run = para.add_run(line)
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
                if k < len(lines) - 1:
                    run.add_break()

    def _p_header(self) -> str:
        return "p (adj.)" if self.res.cfg["stats"]["p_adjust"] != "none" else "p"

    def _stats_note(self) -> str:
        st = self.res.cfg["stats"]
        t = st["effect_size_thresholds"]
        parts = []
        if st["p_adjust"] != "none":
            parts.append(
                f"p-values are adjusted for multiple comparisons across items within each "
                f"effect ({st['p_adjust']})."
            )
        else:
            parts.append("p-values are not adjusted for multiple comparisons.")
        parts.append(
            f"Effect size labels: small ≥ {_short(t['small'])}, medium ≥ "
            f"{_short(t['medium'])}, large ≥ {_short(t['large'])} (Cohen, 1988)."
        )
        return " ".join(parts)

    def summary_table(self):
        res = self.res
        alpha = res.cfg["stats"]["alpha"]
        thr = res.cfg["stats"]["effect_size_thresholds"]
        names = res.test_names
        top = ["Item"] + [x for n in names for x in (n.replace(" x ", " × "), "")]
        sub = ["Item"] + [x for _ in names for x in (self._p_header(), "Effect size")]
        blocks = []
        for item in res.prep.items:
            row = [(res.prep.item_labels[item], False)]
            for n in names:
                r = res.tests[item][n]
                sig = np.isfinite(r.p_adj) and r.p_adj < alpha
                row += [(an.fmt_p(r.p_adj), False) if sig else ("", False),
                        (an.effect_label(r.eta_sq, thr), False) if sig else ("", False)]
            blocks.append(Block([row]))
        merges = [(0, 1 + 2 * k, 2 + 2 * k) for k in range(len(names))]
        facs = [f.name for f in res.prep.factors]
        desc = f"{', '.join(facs)}: one-way ANOVA main effects (effect size = η²)."
        if len(facs) == 2:
            desc += f" {facs[0]} × {facs[1]}: two-way ANOVA interaction (partial η²)."
        self.table(
            "Significant effects by item",
            [top, sub],
            blocks,
            [2.2] + [0.7, 0.95] * len(names),
            f"Separate between-groups ANOVAs for each item. {desc} Only significant effects "
            f"(p < {_short(alpha)}) are shown; blank cells are non-significant. "
            + self._stats_note(),
            header_merges=merges,
        )

    def overall_table(self):
        res = self.res
        d = res.descriptives[res.descriptives["analysis"] == "Overall"].set_index("item")
        blocks = []
        for item in res.prep.items:
            r = d.loc[item]
            blocks.append(Block([[(res.prep.item_labels[item], False), (str(int(r["n"])), False),
                                  (_fmt(r["mean"]), False), (_fmt(r["sd"]), False),
                                  (_ci(r["ci_low"], r["ci_high"]), False)]]))
        conf = round(res.cfg["stats"]["confidence"] * 100)
        self.table("Descriptive statistics by item",
                   [["Item", "n", "M", "SD", f"{conf}% CI"]], blocks, [3.2, 0.5, 0.6, 0.6, 1.2],
                   f"{conf}% CI = t-based confidence interval for the mean. Non-substantive "
                   "responses (e.g., N/A) are excluded.")

    def oneway_table(self):
        res = self.res
        alpha = res.cfg["stats"]["alpha"]
        conf = round(res.cfg["stats"]["confidence"] * 100)
        letters = any(len(f.levels) > 2 for f in res.prep.factors) and \
            res.cfg["stats"]["posthoc"] == "tukey"
        header = ["Item", "Factor", "Group", "n", "M", "SD", f"{conf}% CI"]
        header += (["Tukey"] if letters else []) + [self._p_header(), "η²"]
        p_col = len(header) - 2
        blocks = []
        for item in res.prep.items:
            d = res.descriptives[res.descriptives["item"] == item]
            blk, r0 = Block(), 0
            for fac in res.prep.factors:
                sub = d[d["analysis"] == fac.name].set_index(fac.name)
                t = res.tests[item][fac.name]
                sig = np.isfinite(t.p_adj) and t.p_adj < alpha
                st = an.stars(t.p_adj, alpha)
                p_text = an.fmt_p(t.p_adj) + (f" {st}" if st else "")
                start = r0
                for lvl in fac.levels:
                    if lvl not in sub.index:
                        continue
                    r = sub.loc[lvl]
                    cells = [(res.prep.item_labels[item], False), (fac.name, False),
                             (lvl, False), (str(int(r["n"])), False), (_fmt(r["mean"]), False),
                             (_fmt(r["sd"]), False), (_ci(r["ci_low"], r["ci_high"]), False)]
                    if letters:
                        show = sig and t.letters
                        cells.append((t.letters.get(lvl, "") if show else "", False))
                    cells += [(p_text, bool(sig)), (an.fmt_eta(t.eta_sq), False)]
                    blk.rows.append(cells)
                    r0 += 1
                if r0 > start:
                    blk.merges += [(1, start, r0 - 1), (p_col, start, r0 - 1),
                                   (p_col + 1, start, r0 - 1)]
            if blk.rows:
                blk.merges.append((0, 0, len(blk.rows) - 1))
                blocks.append(blk)
        widths = [1.4, 0.6, 1.1, 0.4, 0.45, 0.45, 1.0] + ([0.6] if letters else []) + [0.75, 0.5]
        note = (f"Separate one-way between-groups ANOVAs for each factor within each item. "
                f"{conf}% CI = t-based confidence interval for the mean. η² = eta squared. "
                "Bold = significant. * p < .05, ** p < .01, *** p < .001. ")
        if letters:
            note += ("Tukey: groups sharing a letter do not differ significantly (Tukey HSD), "
                     "shown when the ANOVA is significant. ")
        self.table("Descriptive statistics and one-way ANOVA results by item", [header],
                   blocks, widths, note + self._stats_note())

    def twoway_table(self):
        res = self.res
        a, b = res.prep.factors
        name = f"{a.name} x {b.name}"
        alpha = res.cfg["stats"]["alpha"]
        conf = round(res.cfg["stats"]["confidence"] * 100)
        header = ["Item", b.name, a.name, "n", "M", "SD", f"{conf}% CI", self._p_header(),
                  "Partial η²"]
        blocks = []
        for item in res.prep.items:
            d = res.descriptives[(res.descriptives["item"] == item)
                                 & (res.descriptives["analysis"] == name)]
            sub = d.set_index([b.name, a.name])
            t = res.tests[item][name]
            sig = np.isfinite(t.p_adj) and t.p_adj < alpha
            st = an.stars(t.p_adj, alpha)
            p_text = an.fmt_p(t.p_adj) + (f" {st}" if st else "")
            blk = Block()
            for lb in b.levels:
                start = len(blk.rows)
                for la in a.levels:
                    if (lb, la) not in sub.index:
                        continue
                    r = sub.loc[(lb, la)]
                    blk.rows.append([(res.prep.item_labels[item], False), (lb, False),
                                     (la, False), (str(int(r["n"])), False),
                                     (_fmt(r["mean"]), False), (_fmt(r["sd"]), False),
                                     (_ci(r["ci_low"], r["ci_high"]), False),
                                     (p_text, bool(sig)), (an.fmt_eta(t.eta_sq), False)])
                if len(blk.rows) > start:
                    blk.merges.append((1, start, len(blk.rows) - 1))
            if blk.rows:
                last = len(blk.rows) - 1
                blk.merges += [(0, 0, last), (7, 0, last), (8, 0, last)]
                blocks.append(blk)
        self.table(
            "Descriptive statistics and two-way ANOVA interaction results by item",
            [header], blocks, [1.4, 1.3, 0.7, 0.4, 0.45, 0.45, 1.0, 0.7, 0.65],
            f"Separate two-way between-groups ANOVAs ({a.name} × {b.name}) within each item; "
            f"p and partial η² are for the {a.name} × {b.name} interaction effect (Type III "
            f"sums of squares). {conf}% CI = t-based confidence interval for the cell mean. "
            "Bold = significant. * p < .05, ** p < .01, *** p < .001. " + self._stats_note())

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(path))
        return path


def build_report(res: Results, images, path: Path) -> Path:
    w = res.cfg["output"]["word"]
    rep = Report(res)
    if w["include_plots"] and images:
        rep.plots(images)
    facs = res.prep.factors
    if w["summary_table"] and facs:
        rep.summary_table()
    if w["detail_tables"]:
        if not facs:
            rep.overall_table()
        else:
            rep.oneway_table()
            if len(facs) == 2:
                rep.twoway_table()
    if not (w["include_plots"] and images):
        # the first table's page break would leave a blank first page
        body = rep.doc.element.body
        first = body[0] if len(body) else None
        if first is not None and first.xpath(".//w:br[@w:type='page']"):
            body.remove(first)
    return rep.save(path)
