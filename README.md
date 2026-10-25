# Northstar enterprise agent labs

Python labs follow one invented retail case from a deterministic baseline through typed tools, provenance, memory, approvals, durability, specialist roles and tenant controls. The repository contains companion source, tests and synthetic fixtures. Private source history, execution reports and book assets are excluded.

The required track is offline, deterministic and has no paid keys or third-party Python dependencies. A fixed rule planner is explicitly a simulation. Synthetic reviewer roles demonstrate approval mechanics; they are not real human reviews. No command refunds money, purchases inventory or sends an external message.

Start with [Build start](docs/build-start.md), then the [twelve chapter cards](docs/chapter-cards.md).

## Start with an installed interpreter

Use Python 3.12–3.14. An existing interpreter can run directly, or create a clean environment without downloading packages:

```sh
python3.12 -m venv --without-pip .venv
source .venv/bin/activate
python scripts/check_environment.py
python -m northstar_agents baseline
```

An installed uv can also create the environment with `uv --no-cache venv --offline --python 3.12.13 --no-python-downloads .venv` when that interpreter is already installed. No package installation is required.

## Follow the labs

See [the versioned lab index](docs/lab-index.json) for twelve stages, prerequisites, commands and ownership, and [learning tracks](docs/learning-tracks.md) for concept, implementation and enterprise-design depth.

```sh
python -m northstar_agents glossary
python -m northstar_agents baseline
python -m northstar_agents retrieve --query "returns purchase case"
python -m northstar_agents agent
python -m northstar_agents memory
python -m northstar_agents approvals
python -m northstar_agents teams
python -m northstar_agents platform
python -m northstar_agents operations
python -m northstar_agents capstone --report artifacts/reports/capstone.json
```

For read-only pause/resume:

```sh
python -m northstar_agents workflow --db .state/workflow.sqlite --run-id lab06 --pause-after purchase_checked
python -m northstar_agents workflow --db .state/workflow.sqlite --run-id lab06
python -m northstar_agents trace --db .state/workflow.sqlite
```

For the separate approved synthetic note/outbox and simulated destination:

```sh
python -m northstar_agents durability-lab --report artifacts/reports/durability-lab.json
```

Default labs use new in-memory state or isolated temporary lab databases. Explicit `--db` opts into persistence. The canonical fixture is policy v3 and CASE-SYN-104 / INV-SYN-4817: two blue mugs at GBP 12.50 each, with one red mug reported by the customer. Fulfillment remains unknown. The memory exercise branches a note to v4 without changing the canonical fixture. Report writers require fresh output filenames.

## Validation and boundaries

```sh
python scripts/run_tests.py --report artifacts/reports/tests.json
python scripts/run_offline.py evaluate --output artifacts/reports/evaluation.json
python scripts/verify_labs.py --report artifacts/reports/lab-runs.json
```

The full-lab validation harness and optional model harness currently verify Mac mini hardware before running. Core CLI examples are standard-library Python; use the environment check on your own platform. Baseline evidence is recorded separately from this source snapshot and does not count as a coordinated review round. Re-run checks for the version you use; previous private results are not shipped or claimed as this export's evidence.

- [Architecture](docs/architecture.md), [threat model](docs/threat-model.md), [reliability lab](docs/reliability-lab.md) and [limitations](docs/limitations.md).
- [Data card](docs/data-card.md), [testing strategy](docs/testing-strategy.md), [reproducibility](docs/reproducibility.md) and [operations](docs/deployment.md).
- [Optional schema-constrained model planning](docs/optional-model.md), disabled in default labs; no native model tool-calling claim.
- [MIT license](LICENSE) for original lab software, associated lab documentation and synthetic fixtures, subject to the [upstream exclusions](NOTICE.md). Book manuscripts, covers, illustrations and diagram/build sources are not included in this export or grant.
