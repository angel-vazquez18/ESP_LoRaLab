"""Generate shared schemas and diagnostic metadata, or detect drift without writes."""

import argparse
import json
from pathlib import Path

from lora_testbed import rf_events_v2, run_protocol_v2
from lora_testbed.experiments_v2 import KnownDataPlan
from lora_testbed.v2 import schema, schema_digest


def outputs(root: Path) -> dict[Path, str]:
    def document(value):
        return json.dumps(value, indent=2) + "\n"

    return {
        root / "contracts/v2/diagnostic.schema.json": document(schema()),
        root / "firmware/diagnostic/main/contract_schema.h": (
            f'#pragma once\n#define CONTRACT_SCHEMA_SHA256 "{schema_digest()}"\n'
        ),
        root / "contracts/v2/known_data.schema.json": document(KnownDataPlan.model_json_schema()),
        root / "contracts/v2/known_data_events.schema.json": document(rf_events_v2.schema()),
        root / "contracts/v2/execution.schema.json": document(run_protocol_v2.schema()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on drift without writing files")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    stale = []
    for path, expected in outputs(root).items():
        if args.check:
            if not path.exists() or path.read_text() != expected:
                stale.append(str(path.relative_to(root)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected)
    if stale:
        print("Generated contract drift: " + ", ".join(stale))
        return 1
    print("Generated contracts match" if args.check else "Generated contracts updated")
    print(f"Diagnostic schema: {schema_digest()}")
    print(f"Execution schema: {run_protocol_v2.schema_digest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
