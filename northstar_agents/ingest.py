# SPDX-License-Identifier: MIT
"""Explicit, checksum-checked UCI ingestion; exports product aggregates, no CustomerID."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from .contracts import Rejected
from .reporting import write_report

UCI_URL = "https://archive.ics.uci.edu/static/public/352/online+retail.zip"
UCI_PAGE = "https://archive.ics.uci.edu/dataset/352/online+retail"
CITATION = "Chen, D. (2015). Online Retail [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5BW33."
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
MAX_ARCHIVE = 40_000_000
MAX_XML = 200_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: object, **__: object) -> None:
        raise Rejected("source_redirect_denied")


def download_source(destination: Path, *, source_reviewed: bool) -> None:
    if not source_reviewed:
        raise Rejected("source_review_required")
    # Only an explicit CLI subcommand reaches this function. No license consent is sent.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(UCI_URL, timeout=30) as response:
        content = response.read(MAX_ARCHIVE + 1)
    if len(content) > MAX_ARCHIVE:
        raise Rejected("source_too_large")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(content)


def _member(archive: zipfile.ZipFile, name: str, maximum: int = MAX_XML) -> bytes:
    if archive.namelist().count(name) != 1:
        raise Rejected("archive_member_unavailable")
    info = archive.getinfo(name)
    if info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise Rejected("unsupported_archive_member")
    if info.file_size > maximum:
        raise Rejected("archive_member_too_large")
    return archive.read(name)


def _string(node: ET.Element | None) -> str:
    if node is None:
        raise Rejected("malformed_string_node")
    # Rich strings are the concatenation of text runs, excluding formatting whitespace.
    texts = list(node.iter(NS + "t"))
    if not texts:
        raise Rejected("malformed_string_node")
    return "".join(t.text or "" for t in texts)


def _rows(workbook: bytes):
    with zipfile.ZipFile(io.BytesIO(workbook)) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(_member(archive, "xl/sharedStrings.xml", 30_000_000))
            if root.tag != NS + "sst":
                raise Rejected("malformed_shared_strings")
            strings = [_string(node) for node in root.findall(NS + "si")]
        sheet = _member(archive, "xl/worksheets/sheet1.xml")
        # Streaming rows keeps the full UCI workbook's XML tree out of memory.
        seen_root = False
        sheet_data = False
        for event, row in ET.iterparse(io.BytesIO(sheet), events=("start", "end")):
            if not seen_root:
                if row.tag != NS + "worksheet":
                    raise Rejected("malformed_worksheet")
                seen_root = True
            if row.tag == NS + "sheetData":
                sheet_data = True
            if event != "end" or row.tag != NS + "row":
                continue
            if not sheet_data:
                raise Rejected("malformed_worksheet")
            cells = {}
            for cell in row.findall(NS + "c"):
                reference = cell.attrib.get("r", "")
                match = re.fullmatch(r"([A-H])([1-9][0-9]*)", reference)
                if not match or match[1] in cells:
                    raise Rejected("invalid_cell_reference")
                column = match[1]
                value_node = cell.find(NS + "v")
                value = value_node.text or "" if value_node is not None else ""
                kind = cell.attrib.get("t")
                if kind == "s":
                    if not re.fullmatch(r"[0-9]+", value) or len(value) > 9 or int(value) >= len(strings):
                        raise Rejected("invalid_shared_string_reference")
                    value = strings[int(value)]
                elif kind == "inlineStr":
                    value = _string(cell.find(NS + "is"))
                elif kind not in {None, "n"}:
                    raise Rejected("unsupported_cell_type")
                cells[column] = value
            yield cells
            row.clear()
        if not sheet_data:
            raise Rejected("malformed_worksheet")


def ingest(source: Path, expected_sha256: str, destination: Path) -> dict:
    try:
        with localcontext() as context:
            context.prec = 128
            return _ingest(source, expected_sha256, destination)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError) as exc:
        raise Rejected("malformed_workbook_container_or_xml") from exc


def _ingest(source: Path, expected_sha256: str, destination: Path) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise Rejected("expected_checksum_required")
    if source.stat().st_size > MAX_ARCHIVE:
        raise Rejected("source_too_large")
    raw = source.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected_sha256:
        raise Rejected("source_checksum_mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if "xl/worksheets/sheet1.xml" in archive.namelist():
            workbook = raw
        else:
            # Read a named member into memory; never extract arbitrary paths.
            candidates = [n for n in archive.namelist() if n.rsplit("/", 1)[-1] == "Online Retail.xlsx"]
            if len(candidates) != 1:
                raise Rejected("workbook_unavailable")
            workbook = _member(archive, candidates[0], MAX_ARCHIVE)
    aggregates = defaultdict(lambda: {"nonnegative_non_cancellation_units": 0, "cancellation_or_negative_units": 0,
                                      "nonnegative_non_cancellation_line_value_gbp": Decimal(0)})
    rows_read = skipped = 0
    rows = iter(_rows(workbook))
    header = next(rows, {})
    expected = {"A": "InvoiceNo", "B": "StockCode", "C": "Description", "D": "Quantity",
                "E": "InvoiceDate", "F": "UnitPrice", "G": "CustomerID", "H": "Country"}
    if header != expected:
        raise Rejected("unexpected_workbook_schema")
    for row in rows:
        rows_read += 1
        try:
            quantity = int(row.get("D", ""))
            price = Decimal(row.get("F", ""))
            if abs(quantity) > 10**12 or (price.is_finite() and (price.adjusted() > 12 or price.as_tuple().exponent < -64 or len(price.as_tuple().digits) > 64)):
                raise Rejected("numeric_range_exceeded")
            stock = row.get("B", "")
            if not stock or len(stock) > 40 or not price.is_finite() or price < 0:
                raise ValueError
        except Rejected:
            raise
        except (ValueError, InvalidOperation):
            skipped += 1
            continue
        group = aggregates[stock]
        if quantity < 0 or row.get("A", "").lower().startswith("c"):
            group["cancellation_or_negative_units"] += abs(quantity)
        else:
            group["nonnegative_non_cancellation_units"] += quantity
            group["nonnegative_non_cancellation_line_value_gbp"] += price * quantity
    products = [{"stock_code": code, **{k: str(v.quantize(Decimal("0.01"))) if isinstance(v, Decimal) else v
                                               for k, v in values.items()}}
                for code, values in sorted(aggregates.items())]
    output = {"schema_version": 2, "source_kind": "caller_supplied_workbook_origin_unverified",
              "origin_authentication": "SHA-256 verifies supplied bytes, not their origin; UCI attribution applies only to separately reviewed UCI input.",
              "source_url": UCI_PAGE, "doi": "10.24432/C5BW33", "citation": CITATION,
              "license_reported_by_source": "CC BY 4.0", "input_sha256": observed,
              "workbook_sha256": hashlib.sha256(workbook).hexdigest(), "rows_read": rows_read,
              "observed_columns": list(header.values()), "observed_column_count": len(header),
              "rows_skipped_invalid_quantity_price_or_stock": skipped,
              "removed_fields": ["CustomerID", "InvoiceNo", "Description", "InvoiceDate", "Country"],
              "transformation": "Product transaction-line aggregates; no physical-return or recognized-revenue inference.",
              "numeric_rules": "Quantity parsed by Python int (integer lexical form, whitespace/sign allowed). Decimal arithmetic precision 128; aggregate line values rounded to 0.01 with ROUND_HALF_EVEN. Zero quantities and prices retained.",
              "predicates": {
                  "valid_row": "Nonempty stock code (<=40 characters), integer quantity with abs <= 10^12, finite nonnegative unit price with adjusted exponent <= 12, fractional exponent >= -64 and <=64 coefficient digits. Out-of-range finite values reject the file. Non-numeric/nonfinite/negative-price rows are skipped.",
                  "cancellation_or_negative_units": "Sum abs(Quantity) where Quantity < 0 OR InvoiceNo starts with c/C; not proof of physical return.",
                  "nonnegative_non_cancellation_units": "Sum Quantity where Quantity >= 0 AND InvoiceNo does not start with c/C.",
                  "nonnegative_non_cancellation_line_value_gbp": "Sum UnitPrice * Quantity under the same nonnegative/non-cancellation predicate; not recognized revenue.",
                  "zero_retention": "Otherwise valid rows with zero quantity or zero unit price are retained. Zero quantity contributes zero; zero-priced quantities still contribute units but zero line value."
              },
              "limitations": "No verified physical returns, recognized revenue, ticket, delivery, policy, tenant or inventory-on-hand facts.", "products": products}
    write_report(destination, output)
    return {"output": str(destination), "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "rows_read": rows_read, "products": len(products), "source_sha256": observed}
