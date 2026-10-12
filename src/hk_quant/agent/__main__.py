"""One JSON request on stdin -> one bounded JSON response on stdout.

Use a process timeout in a caller for operations that may fetch large datasets.
The input contains only a tool name and typed arguments, never a file path,
shell command, SQL query, credential, or trading instruction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hk_quant.agent.tools import ResearchTools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded HK Quant research tool protocol")
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument("--registry-dir", default="experiments")
    args = parser.parse_args(argv)

    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError("request exceeds 64 KiB")
        request = json.loads(raw)
        if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
            raise ValueError("request must contain exactly tool and arguments")
        if not isinstance(request["tool"], str) or not isinstance(request["arguments"], dict):
            raise ValueError("tool must be a string and arguments must be an object")
    except (ValueError, json.JSONDecodeError) as exc:
        response = {"ok": False, "error": {"code": "INVALID_INPUT", "message": str(exc)}}
    else:
        try:
            from hk_quant.data.repository import DataRepository
            from hk_quant.experiments.registry import ExperimentRegistry

            registry = ExperimentRegistry(args.registry_dir)
            tools = ResearchTools(DataRepository(args.processed_dir), Path(args.registry_dir) / "artifacts", registry)
            response = tools.call(request["tool"], request["arguments"])
        except ImportError:
            response = {"ok": False, "error": {"code": "DEPENDENCY_UNAVAILABLE", "message": "install project dependencies before running research tools"}}
    print(json.dumps(response, ensure_ascii=False, allow_nan=False, default=str))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
