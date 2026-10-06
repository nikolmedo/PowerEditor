from pathlib import Path

from typer.testing import CliRunner

from powereditor import cli
from powereditor.settings_store import SettingsService


def test_features_lists_every_feature_as_heuristic_by_default() -> None:
    result = CliRunner().invoke(cli.app, ["features"])

    assert result.exit_code == 0
    assert "best_take_choice" in result.output
    assert "heuristic" in result.output
    assert "0.80" in result.output


def test_providers_list_and_features_show_assignments(isolated_environment: Path) -> None:
    service = SettingsService.default()
    service.update(
        {
            "providers": [{"id": "jev", "kind": "typesafe", "transport": "api", "label": "Jev"}],
            "featureModels": {"cta_detection": {"providerId": "jev", "model": "jev-latest"}},
        }
    )
    runner = CliRunner()

    providers = runner.invoke(cli.app, ["providers", "list"])
    features = runner.invoke(cli.app, ["features"])

    assert providers.exit_code == 0
    assert "typesafe" in providers.output
    assert "missing" in providers.output
    assert "jev-latest" in features.output


def test_providers_list_without_providers() -> None:
    result = CliRunner().invoke(cli.app, ["providers", "list"])

    assert result.exit_code == 0
    assert "heuristic" in result.output
