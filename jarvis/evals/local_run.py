"""Stage B only: run the migration or memory eval against a local model.

    python -m jarvis.evals.local_run --model qwen3.5-9b-q4km --suite migration [--repeat 3]
    python -m jarvis.evals.local_run --model gemma-4-e4b-q4km --suite memory

Live routing never changes. The local provider is not approved in config/routing.yaml;
this flag builds an in-memory copy of the config, for this eval run only, in which every
route uses the local provider and the given model. Nothing is written back to config.
The llama-server must already be running on the endpoint in config/providers.yaml.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import TextIO

from jarvis.config import Config

PROVIDER = "local"


def local_eval_config(config: Config, model: str) -> Config:
    """Eval-only copy of the config: every route has one candidate, the local model."""
    entry = config.models.get(model) or {}
    if entry.get("provider") != PROVIDER:
        raise SystemExit(f"{model} is not a local model profile in config/models.yaml")
    routes = {
        name: {**spec, "candidates": [{"provider": PROVIDER, "model": model,
                                       "effort": (spec.get("candidates") or [{}])[0].get("effort", "medium")}]}
        for name, spec in config.routing.get("routes", {}).items()
    }
    routing = {**config.routing, "approved_providers": [PROVIDER], "routes": routes}
    return dataclasses.replace(config, routing=routing)


def main(argv: list[str] | None = None, out: TextIO = sys.stdout) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.evals.local_run")
    ap.add_argument("--model", required=True, help="a local model profile in config/models.yaml")
    ap.add_argument("--suite", choices=["migration", "memory"], default="migration")
    ap.add_argument("--category", default=None)
    ap.add_argument("--repeat", type=int, default=1, help="run the suite this many times")
    args = ap.parse_args(argv)

    from jarvis.core.runtime import open_runtime
    from jarvis.providers import make_provider

    rt = open_runtime()
    try:
        rt.config = local_eval_config(rt.config, args.model)
        health = make_provider(PROVIDER, rt.config).health()
        if not health.ok:
            print(f"local server not ready: {health.detail}", file=out)
            return 2
        for _ in range(args.repeat):
            if args.suite == "memory":
                from jarvis.evals.memory_eval import format_live, run_live

                results, path = run_live(rt, PROVIDER, args.category)
                print(format_live(results), file=out)
                print(f"Results: {path}", file=out)
            else:
                from jarvis.evals.runner import run_suite

                report = run_suite(rt, PROVIDER, args.category)
                for r in report.results:
                    print(f"{'PASS' if r.passed else 'FAIL'} {r.task_id} [{r.category}/{r.language}] {r.detail}",
                          file=out)
                print(f"{report.passed}/{len(report.results)} passed. Saved: {report.path}", file=out)
    finally:
        rt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
