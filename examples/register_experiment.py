"""Offline experiment registry demo (writes to a temporary directory).

Run from the repository root: python examples/register_experiment.py
"""

from __future__ import annotations

from tempfile import TemporaryDirectory

from hk_quant.experiments import ExperimentRegistry


def main() -> None:
    with TemporaryDirectory(prefix="hk-quant-registry-") as temporary:
        registry = ExperimentRegistry(temporary)
        config = {"question": "Can a fixed rule beat its baseline?", "seed": 7}
        run = registry.create_experiment("validation", config, seed=7)
        registry.update_experiment_status(run.experiment_id, "RUNNING")
        registry.save_artifact(run.experiment_id, "summary.json", {"status": "synthetic demonstration"})
        completed = registry.update_experiment_status(
            run.experiment_id, "COMPLETED", conclusion="demonstration only",
        )
        print(f"Run: {completed.experiment_id}")
        print(f"Config hash: {completed.config_hash}")
        print(f"Summary: {registry.load_experiment_artifacts(completed.experiment_id)['summary.json']}")


if __name__ == "__main__":
    main()
