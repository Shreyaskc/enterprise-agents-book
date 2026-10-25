# Data card

The required offline fixture in `data/fixtures/northstar_synthetic.json` is invented teaching material, not a UCI sample. Northstar's Service Operations and Inventory Operations share a tenant with distinct permissions; Harbor is a separate invented tenant. All case, policy, tenant, invoice and identity records are synthetic. A checksum manifest is verified by the loader.

CASE-SYN-104 refers to INV-SYN-4817: two blue mugs at GBP 12.50 each. The customer reports one red mug. Purchase records do not prove what was delivered. Synthetic policy v3 requires purchase/case checks and never automatically grants a refund. Approval-gated writes remain local, including the separate simulated note destination. Memory v4 is an isolated branch, not a global policy mutation.

## Optional UCI data

[Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail) is historical transaction data. UCI reports 541,909 rows, dates in 2010–2011, and [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Citation: Chen, D. (2015). Online Retail [Dataset]. UCI Machine Learning Repository. [DOI: 10.24432/C5BW33](https://doi.org/10.24432/C5BW33).

UCI supplies no support tickets, tenant roles, returns policies, inventory on hand or delivery evidence. No real UCI customer identifiers, raw workbook, or derived transaction sample is bundled in this export. Original synthetic fixtures are under MIT; external UCI data and derivatives retain their upstream CC BY 4.0 attribution requirements and are not relicensed by the lab's MIT grant.

Explicit import of independently reviewed local bytes:

```sh
python -m northstar_agents ingest-uci --input /path/to/OnlineRetail.xlsx --expected-sha256 YOUR_REVIEWED_64_HEX_SHA256 --output data/derived/product-aggregates.json
```

The uppercase checksum is a placeholder, not a recorded digest. The importer verifies the exact source bytes before parsing, checks the eight expected columns and records provenance, exclusions and output hashes. To explicitly download from its fixed official URL, add `--download --source-reviewed` and choose a fresh ZIP path as input. This sends no license consent, refuses redirects/oversized inputs, and never runs in default labs/tests.

Schema 2 calculations preserve accepted zero rows:

- `cancellation_or_negative_units`: sum absolute quantity when quantity < 0 OR invoice begins with c/C; not proof of physical returns.
- `nonnegative_non_cancellation_units`: sum quantity >= 0 on other accepted rows.
- `nonnegative_non_cancellation_line_value_gbp`: sum unit price × quantity for that same nonnegative/non-cancellation predicate; not recognized revenue.

Valid rows require a bounded nonempty stock code, integer quantity and finite nonnegative unit price. Valid zero quantities and zero prices are retained. Zero-priced quantities contribute units and zero line value. CustomerID, invoice ID, descriptions, dates and country are omitted from the product aggregate. Keep raw/downloaded data local and ignored; review rights and privacy before redistributing any new derived data.

## Parser and origin boundaries

A caller-supplied SHA-256 verifies bytes against that caller’s expected value; it does not authenticate origin. The importer labels input origin unverified. Associate UCI provenance only with the separately reviewed official URL and recorded archive/workbook identities; synthetic parser workbooks are invented test material. Neither their transaction-shaped schema nor a matching checksum makes them UCI data.

The local parser rejects malformed ZIP/XML/member/cell/shared-string/inline-string structure with stable error codes, including negative shared-string references. Finite numeric values outside the documented magnitude/precision bounds reject the file; invalid quantity, nonfinite/negative price or stock rows retain the existing skip behavior. Quantity uses Python integer lexical parsing (sign/whitespace accepted, fractions rejected). Decimal arithmetic uses precision 128 and aggregate line value rounds to GBP 0.01 with ROUND_HALF_EVEN. Zero quantity and zero price remain retained; cancellation prefix c/C OR negative quantity contributes absolute units to cancellation_or_negative_units. Other accepted rows contribute nonnegative_non_cancellation_units and nonnegative_non_cancellation_line_value_gbp. These are line calculations, not physical returns, recognized revenue or inventory.

Output is written atomically to a fresh reserved path after parsing. An existing file is preserved. The workbook and raw identifiers must stay outside version control and handoff source archives.
