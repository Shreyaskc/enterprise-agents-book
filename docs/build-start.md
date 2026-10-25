# Build start

Unpack the reviewed source archive into a new directory, or use a genuine checkout. In a terminal change into the directory containing `pyproject.toml`, `northstar_agents`, `scripts` and `tests`. Do not run inside an unrelated project. No Git initialization, remote, account, key, package install or model is required.

Use an already installed Python 3.12 or 3.14 interpreter. The correction validation exercises 3.12.13 and 3.14.6; compatibility metadata permits 3.13 but no execution claim is made for it. Replace `python3.12` below with your installed supported interpreter if needed.

```sh
python3.12 -m venv --without-pip .venv
source .venv/bin/activate
python scripts/check_environment.py
python scripts/check_repository.py
python -m northstar_agents baseline
```

A venv is optional isolation; the lab has zero third-party packages. An existing uv may select an already installed interpreter offline as described in the README. Do not download software merely to follow this setup.

The baseline should show GBP 25.00 for two blue mugs, a customer report of one red mug, delivery unknown and refund authorization false. Proceed to the [twelve chapter cards](chapter-cards.md). All default business records are invented. The separately reviewed UCI import is optional and its transactions cannot establish delivery or inventory.

Independent labs reset by using new in-memory or temporary stores. The explicit workflow database continues between its two processes only. For reruns choose a new source extraction or new database/run ID and fresh report paths; existing report files are protected. A source archive has no upstream Git history. A local `git init` is a validation bootstrap and must never be represented as recovered release provenance.

For full checks see [reproducibility](reproducibility.md), [testing strategy](testing-strategy.md), and optional [local model planning](optional-model.md). The Mac-specific harness verifies the requested execution hardware; ordinary examples use standard-library Python.
