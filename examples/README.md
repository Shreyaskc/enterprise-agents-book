# One case, twelve lab stages

Run `python -m northstar_agents --help` from the root to list commands, then choose a stage. The [lab index](../docs/lab-index.json) and [learning tracks](../docs/learning-tracks.md) provide commands, prerequisites and ownership. All stages share the same strict contracts, service, local store and synthetic fixture.

Independent commands reset state by default. A file-backed workflow explicitly continues one run. The separate reliability lab creates two isolated local stores. Policy v3 remains canonical; only a memory note branches to v4. No default command calls a model or real business service. See the root README and data card for licenses and limitations.
