"""Reporting - PDF report generator (concept: REPORTING, PDF flavor).

A small, dependency-free PDF writer (A4, Helvetica base-14 fonts - no font
embedding needed). Produces the "FlyRank Weekly Deal Briefing" report:
title block, summary stats, and a ranked deals table, multi-page capable.
Served by GET /api/reports/weekly as a real downloadable PDF.
"""

from __future__ import annotations

from datetime import datetime, timezone

PAGE_W, PAGE_H = 595.28, 841.89
MARGIN = 56.0
_TITLE = "FlyRank Weekly Deal Briefing"

_HELPERS = None  # placeholder, kept for symmetry


def _sanitize(text: str) -> str:
    """PDF Helvetica uses WinAnsi; drop anything we cannot encode."""
    return text.encode("latin-1", "replace").decode("latin-1")


def _escape(text: str) -> str:
    return _sanitize(text).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class PDFReport:
    def __init__(self, title: str = _TITLE, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self.pages: list[bytearray] = []  # finished content streams
        self._cur = bytearray()
        self._y = MARGIN  # y measured from the TOP of the page

    # ---------- low-level helpers ----------
    def _ensure_space(self, needed: float) -> None:
        if self._y + needed > PAGE_H - MARGIN:
            self.new_page()

    def new_page(self) -> None:
        if self._cur:
            self.pages.append(self._cur)
        self._cur = bytearray()
        self._y = MARGIN
        self.text("F2", 9, PAGE_W - MARGIN, MARGIN - 14, "", align="right")

    def _line(self, x1, y1, x2, y2) -> None:
        pdf_y1, pdf_y2 = PAGE_H - y1, PAGE_H - y2
        self._cur += f"{x1:.2f} {pdf_y1:.2f} m {x2:.2f} {pdf_y2:.2f} l S\n".encode()

    def text(self, font: str, size: float, x: float, y: float, s: str, align: str = "left") -> None:
        width = len(s) * size * 0.5
        if align == "right":
            x -= width
        elif align == "center":
            x -= width / 2
        self._cur += (
            f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {PAGE_H - y:.2f} Tm "
            f"({_escape(s)}) Tj ET\n"
        ).encode()

    def paragraph(self, s: str, x: float, y: float, width: float, size: float = 11, gap: float = 16) -> None:
        words, line, lines = s.split(), "", []
        for w in words:
            trial = f"{line} {w}".strip()
            if len(trial) * size * 0.5 <= width:
                line = trial
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        for ln in lines:
            self._ensure_space(gap)
            self.text("F1", size, x, self._y, ln)
            self._y += gap

    # ---------- public API ----------
    def title_block(self, subtitle: str = "") -> None:
        self._ensure_space(120)
        self.text("F2", 22, MARGIN, self._y, self.title)
        self._y += 30
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.text("F1", 11, MARGIN, self._y, f"Generated {stamp}")
        self._y += 18
        subtitle = subtitle or self.subtitle
        if subtitle:
            self.text("F1", 11, MARGIN, self._y, subtitle)
            self._y += 18
        self._line(MARGIN, self._y, PAGE_W - MARGIN, self._y)
        self._y += 16

    def stats_row(self, label: str, value: str) -> None:
        self._ensure_space(20)
        self.text("F1", 11, MARGIN, self._y, label)
        self.text("F2", 11, PAGE_W - MARGIN, self._y, value, align="right")
        self._y += 18

    def deals_table(self, deals: list[dict]) -> None:
        headers = ["Rank", "Airline", "Route", "Departure", "Price", "Value", "vs Avg"]
        widths = [40, 130, 95, 75, 65, 55, 60]
        x0 = MARGIN
        table_w = sum(widths)
        row_h = 22

        def draw_row(cells: list[str], bold: bool = False) -> None:
            font = "F2" if bold else "F1"
            self._ensure_space(row_h + 4)
            x = x0
            for cell, w in zip(cells, widths):
                self.text(font, 9.5 if not bold else 9.5, x + 4, self._y + 14, cell[: int(w / 5.5)])
                x += w
            self._line(x0, self._y + row_h, x0 + table_w, self._y + row_h)
            self._y += row_h

        self._ensure_space(30)
        self.text("F2", 13, x0, self._y, "Top ranked deals")
        self._y += 24
        self._line(x0, self._y, x0 + table_w, self._y)
        draw_row(headers, bold=True)
        if not deals:
            draw_row(["", "No deals match the current filters", "", "", "", "", ""])
        for d in deals[:20]:
            route = f"{d['origin']} -> {d['destination']}"
            draw_row(
                [
                    str(d.get("rank", "")),
                    d["airline"],
                    route,
                    d.get("departure_date", ""),
                    f"${d['price']:.0f}",
                    f"{d.get('value_score', 0):.0f}",
                    f"{d.get('vs_route_avg', 0):+.0f}%",
                ]
            )

    def footer(self, page_no: int, total: int) -> None:
        self.text(
            "F1", 8, PAGE_W - MARGIN, PAGE_H - MARGIN + 10,
            f"Page {page_no} of {total}", align="right",
        )

    # ---------- build ----------
    def build(self) -> bytes:
        if self._cur:
            self.pages.append(self._cur)
        total = len(self.pages)
        for i in range(total):
            self.pages[i] = self.pages[i]  # already final

        objects: list[bytes] = []
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
        kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(total))
        objects.append(
            f"<< /Type /Pages /Kids [{kids}] /Count {total} >>".encode()
        )  # 2
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3
        objects.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
        )  # 4

        for i, content in enumerate(self.pages):
            # page object
            objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                    f"/Contents {6 + 2 * i} 0 R >>"
                ).encode()
            )
            # content stream object (footer line added per page)
            stream = bytearray(content)
            footer_text = f"FlyRank - {self.title}"
            page_no = f"Page {i + 1} of {total}"
            stream += (
                f"BT /F1 8 Tf 1 0 0 1 {MARGIN} {MARGIN - 14:.2f} Tm "
                f"({_escape(footer_text)}) Tj ET\n"
                f"BT /F1 8 Tf 1 0 0 1 {PAGE_W - MARGIN} {MARGIN - 14:.2f} Tm "
                f"({_escape(page_no)}) Tj ET\n"
            ).encode()
            objects.append(
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                + bytes(stream)
                + b"\nendstream"
            )

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for idx, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"

        xref_pos = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode()
        return bytes(out)


def build_weekly_report(user: dict, deals: list[dict]) -> bytes:
    doc = PDFReport(subtitle=f"Prepared for {user['email']}")
    doc.title_block()
    if deals:
        avg = sum(d["price"] for d in deals) / len(deals)
        doc.stats_row("Deals analyzed", str(len(deals)))
        doc.stats_row("Price range", f"${min(d['price'] for d in deals):.0f} - ${max(d['price'] for d in deals):.0f}")
        doc.stats_row("Average price", f"${avg:.0f}")
        best = deals[0]
        doc.stats_row("Top pick", f"{best['airline']} {best['origin']}->{best['destination']} ${best['price']:.0f} (score {best.get('value_score', 0):.0f})")
        doc.stats_row("Cheapest", f"{min(deals, key=lambda d: d['price'])['airline']} ${min(d['price'] for d in deals):.0f}")
        doc._y += 8
    doc.deals_table(deals)
    return doc.build()