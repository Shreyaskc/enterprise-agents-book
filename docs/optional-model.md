# Optional local schema-constrained planning

`northstar_agents/adapters.py` uses the standard library to send nonstreaming JSON-schema-constrained requests to the loopback Ollama `/api/chat` endpoint. It returns a read-only action proposal, not a native `tools` payload. Application schema and permissions remain authoritative; the model never grants approval or executes a write.

Primary references: [chat API](https://docs.ollama.com/api/chat), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs). Inspect the local schema without inference with `python -m northstar_agents adapter-schema`.

The default path is disabled. Trusted code must provide a scoped expiring `LocalModelApproval` and explicitly enable local inference. The harness checks installed model name/digest, Mac mini hardware and current server version. No download or startup setting change occurs. The request budget is three at most in the smoke/loop harness, output is capped at 128 tokens, context option is 4096, socket inactivity timeout is 30 seconds, thinking is disabled and `keep_alive: 0` requests unloading. These settings do not establish a monetary cap or general model correctness.

After reviewing a suitable existing installation and its terms, replace these placeholders:

```sh
python scripts/evaluate_local_model.py --model YOUR_LOCAL_MODEL --expected-digest YOUR_INSTALLED_MODEL_SHA256 --approve-local-inference --output artifacts/reports/model-smoke.json
python scripts/run_local_agent.py --model YOUR_LOCAL_MODEL --expected-digest YOUR_INSTALLED_MODEL_SHA256 --approve-local-inference --output artifacts/reports/model-agent.json
```

The smoke executes no tools. The guided loop permits only synthetic case/invoice/policy reads, at most three model requests and three tool steps. It does not grant the case-create approval. Record final actions, evidence, actual usage/timing and model/server versions separately from deterministic results, without hidden reasoning.

No model weights or runtime binaries are bundled or covered by the original-code MIT license. Review upstream notices, verify local routing and deny external model-server egress as appropriate. A loopback URL/name check alone is not attestation. Paid APIs and cloud models are outside this track. Record fresh results for the reviewed snapshot separately from this source archive; no previous private smoke is presented as its evidence.

The 60-second elapsed check happens before dispatch, not as a hard overall deadline. Slow-drip responses can exceed an inactivity timeout. Report measured elapsed time without implying server cancellation. Existing installed model/digest/server checks are metadata checks, not whole-supply-chain attestation.

Both harnesses reserve the output before work, persist partial evidence before each attempt/reservation and after each observation, and retain a separate SQLite budget sidecar next to the report. Do not ship that local state in a public source export. An interrupted or uncertain request remains reserved and is never automatically retried. A failed final `/api/ps` read leaves primary observations intact and records loaded models as unknown (`null`) with an error type. It must not be reported as an empty service. Prior environment state is restored. A busy service causes a safe stop; coordinate another run separately instead of retrying inference automatically.

Offline robustness tests use clearly labeled doubles to cover postflight failure, interruption, malformed payloads, usage, schema constraints, budget persistence and expiry. They do not establish live-model quality. Record actual 3-proposal smoke and 3-read guided-loop results separately for the reviewed source revision. The small optional live observations do not constitute held-out evaluation or a benchmark.

Report schema version 2 preserves source, per-attempt prompt and schema hashes, durable reservation/observation states and the measured 90-second elapsed flag. That flag affects acceptance but does not enforce cancellation or a hard deadline.
