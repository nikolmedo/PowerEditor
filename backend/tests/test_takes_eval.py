from typer.testing import CliRunner

from powereditor import cli
from powereditor.eval.takes_eval import evaluate_takes, load_benchmark


def test_synthetic_benchmark_is_labelled_and_sized() -> None:
    benchmark = load_benchmark()

    assert benchmark.synthetic is True
    assert "SYNTHETIC" in benchmark.description
    assert evaluate_takes(benchmark).clusters == 25


def test_heuristic_engine_meets_the_accuracy_floor_on_the_benchmark() -> None:
    report = evaluate_takes(load_benchmark(), threshold=0.6)

    assert report.clustering_accuracy >= 0.9
    assert report.best_take_accuracy >= 0.9
    assert report.off_take_accuracy >= 0.95
    assert 0.0 < report.automatic_share <= 1.0


def test_eval_takes_cli_prints_the_report() -> None:
    result = CliRunner().invoke(cli.app, ["eval-takes", "--threshold", "0.5"])

    assert result.exit_code == 0, result.output
    assert "SYNTHETIC" in result.output
    assert "Best-take accuracy" in result.output
    assert "confidence >= 0.50" in result.output
