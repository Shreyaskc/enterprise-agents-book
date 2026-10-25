# SPDX-License-Identifier: MIT
import hashlib, io, json, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from northstar_agents.data import ROOT
from tests.test_ingest import HEADER, workbook
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
ROWS = [HEADER, ['1', 'TEST', 'invented parser fixture', '2', '40000', '12.50', 'PRIVATE_CUSTOMER_CANARY', 'UK']]

def zip_members(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    return out.getvalue()

def sheet_bytes(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return z.read('xl/worksheets/sheet1.xml')

def shared_workbook(reference=None, malformed_node=False):
    root = ET.fromstring(sheet_bytes(workbook(ROWS)))
    strings = []
    for cell in root.iter(NS + 'c'):
        strings.append(''.join(cell.find(NS + 'is').itertext()))
        cell.remove(cell.find(NS + 'is'))
        cell.set('t', 's')
        ET.SubElement(cell, NS + 'v').text = str(len(strings) - 1)
    sst = ET.Element(NS + 'sst')
    for value in strings:
        si = ET.SubElement(sst, NS + 'si')
        if value == 'invented parser fixture':
            ET.SubElement(ET.SubElement(si, NS + 'r'), NS + 't').text = 'invented '
            ET.SubElement(ET.SubElement(si, NS + 'r'), NS + 't').text = 'parser fixture'
        else:
            ET.SubElement(si, NS + 't').text = value
    target = root.find('.//' + NS + 'c[@r="B2"]/' + NS + 'v')
    if reference == 'missing':
        target.getparent() if hasattr(target, 'getparent') else root.find('.//' + NS + 'c[@r="B2"]').remove(target)
    elif reference is not None:
        target.text = reference
    if malformed_node:
        sst.remove(sst[0])
        ET.SubElement(sst, NS + 'si')
    return zip_members({'xl/worksheets/sheet1.xml': ET.tostring(root), 'xl/sharedStrings.xml': ET.tostring(sst)})

class MalformedIngestionTests(unittest.TestCase):

    def invoke(self, p, raw, name, occupied=False):
        source = p / f'{name}-PATH_CANARY.xlsx'
        source.write_bytes(raw)
        output = p / f'{name}.json'
        if occupied:
            output.write_text('KEEP_EXISTING')
        result = subprocess.run([sys.executable, '-m', 'northstar_agents', 'ingest-uci', '--input', str(source), '--expected-sha256', hashlib.sha256(raw).hexdigest(), '--output', str(output)], cwd=ROOT, capture_output=True, text=True, timeout=15)
        return (result, output)

    def test_malformed_containers_xml_strings_and_numeric_range_have_stable_cli_failures(self):
        inline = ET.fromstring(sheet_bytes(workbook(ROWS)))
        cell = inline.find('.//' + NS + 'c[@r="B2"]')
        cell.remove(cell.find(NS + 'is'))
        cases = {'nonzip': b'not zip', 'truncated': workbook(ROWS)[:25], 'xml': zip_members({'xl/worksheets/sheet1.xml': b'<oops'}), 'missing-member': zip_members({'xl/sharedStrings.xml': b'<sst/>'}), 'missing-inline': zip_members({'xl/worksheets/sheet1.xml': ET.tostring(inline)}), 'huge-price': workbook([HEADER, ['1', 'TEST', 'invented', '2', '40000', '1e999', 'CANARY', 'UK']])}
        for ref in ['-1', '9999', '1.5', 'oops', 'missing', '']:
            cases['shared-' + str(ref)] = shared_workbook(ref)
        cases['malformed-node'] = shared_workbook(malformed_node=True)
        with tempfile.TemporaryDirectory() as tmp:
            for name, raw in cases.items():
                with self.subTest(name=name):
                    result, out = self.invoke(Path(tmp), raw, name)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(json.loads(result.stderr)['status'], 'rejected')
                    self.assertFalse(out.exists())
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertNotIn('PATH_CANARY', result.stderr)

    def test_shared_and_inline_valid_fixtures_produce_equivalent_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            products = []
            for i, raw in enumerate([workbook(ROWS), shared_workbook()]):
                run, path = self.invoke(Path(tmp), raw, str(i))
                self.assertEqual(run.returncode, 0, run.stderr)
                data = json.loads(path.read_text())
                products.append(data['products'])
                self.assertEqual(data['source_kind'], 'caller_supplied_workbook_origin_unverified')
                self.assertNotIn('PRIVATE_CUSTOMER_CANARY', path.read_text())
            self.assertEqual(products[0], products[1])
            self.assertEqual(products[0][0]['nonnegative_non_cancellation_line_value_gbp'], '25.00')

    def test_malformed_input_preserves_occupied_output_and_no_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, path = self.invoke(Path(tmp), b'broken', 'bad', occupied=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(path.read_text(), 'KEEP_EXISTING')

    def test_nonfinite_missing_cells_rounding_and_zero_predicates_remain_explicit(self):
        rows = [HEADER, ['1', 'TEST', 'invented', '1', '40000', '.005', 'X', 'UK'], ['2', 'TEST', 'invented', '0', '40000', '1', 'X', 'UK'], ['C3', 'TEST', 'invented', '3', '40000', '0', 'X', 'UK'], ['4', 'TEST', 'invented', '2', '40000', 'NaN', 'X', 'UK'], ['5', 'TEST', 'invented', '2', '40000', 'Infinity', 'X', 'UK'], ['6', 'TEST', 'invented', '1.5', '40000', '1', 'X', 'UK']]
        with tempfile.TemporaryDirectory() as tmp:
            run, path = self.invoke(Path(tmp), workbook(rows), 'edge')
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads(path.read_text())
            self.assertEqual(data['rows_skipped_invalid_quantity_price_or_stock'], 3)
            self.assertEqual(data['products'][0]['nonnegative_non_cancellation_line_value_gbp'], '0.00')
            self.assertEqual(data['products'][0]['cancellation_or_negative_units'], 3)

    def test_excel_serialized_fractional_price_precision_is_accepted(self):
        rows = [HEADER, ['1', 'TEST', 'invented parser fixture', '2', '40000', '0.28999999999999998', 'CANARY', 'UK']]
        with tempfile.TemporaryDirectory() as tmp:
            run, path = self.invoke(Path(tmp), workbook(rows), 'excel-precision')
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads(path.read_text())
            self.assertEqual(data['rows_skipped_invalid_quantity_price_or_stock'], 0)
            self.assertEqual(data['products'][0]['nonnegative_non_cancellation_line_value_gbp'], '0.58')

    def test_declared_size_limits_and_missing_numeric_cell_are_explicit(self):
        from unittest.mock import patch
        from northstar_agents.ingest import ingest, _member
        from northstar_agents.contracts import Rejected
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic.xlsx'
            raw = workbook(ROWS)
            path.write_bytes(raw)
            with patch('northstar_agents.ingest.MAX_ARCHIVE', 10), self.assertRaisesRegex(Rejected, 'source_too_large'):
                ingest(path, hashlib.sha256(raw).hexdigest(), Path(tmp) / 'out.json')
            self.assertFalse((Path(tmp) / 'out.json').exists())
            with zipfile.ZipFile(io.BytesIO(raw)) as archive, self.assertRaisesRegex(Rejected, 'archive_member_too_large'):
                _member(archive, 'xl/worksheets/sheet1.xml', maximum=10)
            run, output = self.invoke(Path(tmp), workbook([HEADER, ['1', 'TEST', 'invented', '1', '40000']]), 'missing-price')
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(output.read_text())['rows_skipped_invalid_quantity_price_or_stock'], 1)
