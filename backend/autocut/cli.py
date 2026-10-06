import typer
from rich.console import Console
from rich.table import Table

from autocut import doctor as doctor_module

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """AutoCut command line interface."""


@app.command()
def doctor() -> None:
    """Report the status of external dependencies."""
    report = doctor_module.run_checks()
    console = Console()
    console.print(f"Platform: {report.system} {report.machine} | Python {report.python_version}")
    table = Table("Dependency", "Required", "Status", "Version", "Detail")
    for check in report.checks:
        status = (
            "[green]found[/green]"
            if check.found
            else ("[red]missing[/red]" if check.required else "[yellow]missing[/yellow]")
        )
        table.add_row(
            check.name,
            "yes" if check.required else "no",
            status,
            check.version or "-",
            check.detail or "-",
        )
    console.print(table)
    if not report.ok:
        console.print("[red]One or more required dependencies are missing.[/red]")
        raise typer.Exit(code=1)
