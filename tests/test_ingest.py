# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from northstar_agents.contracts import Rejected
from northstar_agents.ingest import download_source, ingest


def workbook(rows):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = ET.Element(f"{{{ns}}}worksheet")
    data = ET.SubElement(root, f"{{{ns}}}sheetData")
    for index, values in enumerate(rows, 1):
        row = ET.SubElement(data, f"{{{ns}}}row", r=str(index))
        for column, value in zip("ABCDEFGH", values):
            cell = ET.SubElement(row, f"{{{ns}}}c", r=f"{column}{index}", t="inlineStr")
            inline = ET.SubElement(cell, f"{{{ns}}}is")
            ET.SubElement(inline, f"{{{ns}}}t").text = str(value)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(root))
    return out.getvalue()


HEADER = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID", "Country"]


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.source = self.path / "synthetic-parser-test.xlsx"
        self.source.write_bytes(workbook([HEADER,
            ["1", "TEST", "invented parser fixture", "2", "40000", "12.50", "PRIVATE_CUSTOMER_CANARY", "UK"],
            ["C2", "TEST", "invented parser fixture", "-1", "40001", "12.50", "PRIVATE_CUSTOMER_CANARY", "UK"],
            ["3", "INVALID", "invented parser fixture", "oops", "40001", "NaN", "PRIVATE_CUSTOMER_CANARY", "UK"]]))
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.output = self.path / "aggregate.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_transforms_synthetic_workbook_without_redistributing_identifiers(self):
        report = ingest(self.source, self.sha, self.output)
        raw = self.output.read_text()
        self.assertNotIn("PRIVATE_CUSTOMER_CANARY", raw)
        data = json.loads(raw)
        self.assertEqual(data["rows_read"], 3)
        self.assertEqual(data["rows_skipped_invalid_quantity_price_or_stock"], 1)
        self.assertEqual(data["products"], [{"stock_code": "TEST", "nonnegative_non_cancellation_units": 2,
                                           "cancellation_or_negative_units": 1, "nonnegative_non_cancellation_line_value_gbp": "25.00"}])
        self.assertEqual(data["schema_version"], 2)
        self.assertIn("not recognized revenue", data["predicates"]["nonnegative_non_cancellation_line_value_gbp"])
        self.assertEqual(data["input_sha256"], self.sha)
        self.assertEqual(report["output_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertIn("10.24432/C5BW33", data["citation"])

    def test_checksum_mismatch_and_missing_expected_checksum_fail_closed(self):
        for checksum in ["0" * 64, "", "unknown"]:
            with self.assertRaises(Rejected):
                ingest(self.source, checksum, self.output)
        self.assertFalse(self.output.exists())

    def test_operational_predicates_do_not_infer_physical_returns_or_revenue(self):
        self.source.write_bytes(workbook([HEADER,
            ["1", "TEST", "invented", "2", "40000", "12.50", "X", "UK"],
            ["C2", "TEST", "invented", "3", "40000", "12.50", "X", "UK"],
            ["3", "TEST", "invented", "-4", "40000", "12.50", "X", "UK"],
            ["4", "TEST", "invented", "0", "40000", "12.50", "X", "UK"],
            ["5", "TEST", "invented", "1", "40000", "-1", "X", "UK"],
            ["6", "TEST", "invented", "5", "40000", "0", "X", "UK"]]))
        sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        ingest(self.source, sha, self.output)
        data = json.loads(self.output.read_text())
        self.assertEqual(data["products"], [{"stock_code": "TEST", "nonnegative_non_cancellation_units": 7,
                                           "cancellation_or_negative_units": 7,
                                           "nonnegative_non_cancellation_line_value_gbp": "25.00"}])
        self.assertEqual(data["rows_skipped_invalid_quantity_price_or_stock"], 1)
        self.assertIn("not proof of physical return", data["predicates"]["cancellation_or_negative_units"])
        self.assertIn("zero unit price are retained", data["predicates"]["zero_retention"])

    def test_existing_output_not_overwritten(self):
        self.output.write_text("preserve existing work")
        with self.assertRaises(FileExistsError):
            ingest(self.source, self.sha, self.output)
        self.assertEqual(self.output.read_text(), "preserve existing work")

    def test_official_zip_shape_supported_without_extracting_paths(self):
        source = self.path / "uci-shape-synthetic.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("Online Retail.xlsx", self.source.read_bytes())
            archive.writestr("../unrelated.txt", "must never be extracted")
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(ingest(source, sha, self.output)["rows_read"], 3)
        self.assertFalse((self.path.parent / "unrelated.txt").exists())

    def test_download_requires_explicit_source_review_before_network(self):
        with self.assertRaisesRegex(Rejected, "source_review_required"):
            download_source(self.path / "download.zip", source_reviewed=False)

    def test_unexpected_schema_rejected(self):
        self.source.write_bytes(workbook([["unexpected"]]))
        sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with self.assertRaisesRegex(Rejected, "unexpected_workbook_schema"):
            ingest(self.source, sha, self.output)
