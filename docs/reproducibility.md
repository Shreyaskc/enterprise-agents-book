# Reproduce a lab run

Use an already installed Python 3.12–3.14 interpreter and record its exact patch version plus SQLite version. `requirements.lock` records zero third-party Python runtime/test packages. Keep `.venv`, raw data, state, caches and generated reports out of source exports.

```sh
python scripts/check_environment.py
python scripts/run_tests.py --report artifacts/reports/tests.json
python scripts/run_offline.py evaluate --output artifacts/reports/evaluation.json
python scripts/verify_labs.py --report artifacts/reports/lab-runs.json
python scripts/run_offline.py durability-lab --report artifacts/reports/durability-lab.json
```

The full-lab harness checks Mac mini hardware. Record expected and observed outcomes separately. Use isolated temporary databases for independent labs; only an explicit file-backed workflow run continues prior state. Policy v3 is canonical; the memory lab's v4 note is a branch. Use fresh report filenames and fresh run IDs when repeating a persistent lab.

No old validation logs, private repository commits, personal machine paths or prior model results are included. Reports generated here must include source and fixture/rubric hashes. Git metadata is optional: archives have null revision with a reason, and an ancestor repository never supplies provenance. A genuine local checkout revision is labeled as local metadata, not upstream attestation. Redact host/user paths and private references before approving any generated output for public release.

Optional UCI ingestion requires explicit source and checksum review. Its field predicates and upstream license are in the data card. Optional local inference requires an existing reviewed model, explicit approval and separate recorded results. No benchmark, broad quality or production-readiness claim follows from a small smoke test.

## Source-only validation

`python scripts/check_repository.py` scans the script’s exact lab root without Git. Required project markers, a nonempty sorted file list, count, byte bound and SHA-256 are reported. The limit is 300 files, one million bytes per file and five million total; Git, caches, state, generated reports and raw/derived data are excluded. Python syntax, JSON, relative documentation links, fixture hash and coverage contracts are checked. The reported file set is local validation evidence, not hosted CI or recovered history. A canary in a disposable enclosing repository must not enter that set.

The versioned regression contract requires the 13 ordered unique case IDs; the versioned lab contract requires twelve stages, explicit workflow resume and separate durability command (14 invocations). Empty, duplicate, incomplete or malformed contracts persist structured failure before scenario execution. `verify_labs.py` checks business semantics and preserves earlier results on per-command timeout, malformed JSON or nonzero exit. Child process groups have a 60-second per-command bound; diagnostic records do not echo arbitrary failing output. Relative canonical commands identify each step.

## Optional finite HTTP fixture

The default test process denies socket connections. A separate finite loopback HTTP double is opt-in and contains no model or external calls:

```sh
NORTHSTAR_TEST_LOOPBACK=1 python -m unittest -v tests.test_round1_models.SocketTimeoutEvidenceTests
```

Its no-response and delayed-header cases exercise an inactivity timeout; a finite slowly delivered body demonstrates why that timeout is not an absolute deadline. Use explicit opt-in when collecting comprehensive correction evidence. Restricted environments may forbid opening a loopback listener; record that failure rather than claiming a pass. No server-side cancellation guarantee follows.
