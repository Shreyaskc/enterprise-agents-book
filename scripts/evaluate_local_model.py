# SPDX-License-Identifier: MIT
"""Three explicit, schema-constrained proposals from an already installed model."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from northstar_agents.model_evidence import metadata, run
from northstar_agents.adapters import OllamaAdapter

def main():
    return run('smoke', metadata_reader=metadata, adapter_type=OllamaAdapter)
if __name__ == '__main__':
    raise SystemExit(main())
