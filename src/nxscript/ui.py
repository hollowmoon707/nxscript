"""Terminal banner, stage counters, and bounded error reporting."""

from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from . import __version__

console = Console(highlight=False)
MAX_SHOWN_ERRORS = 12


def banner(command: str) -> None:
    console.print(Panel.fit(
        f"[bold cyan]nxscript[/] [dim]v{__version__}[/]\nNeoX script tools · {command}",
        border_style="cyan",
    ))


def error(message: str) -> None:
    console.print(f"Error: {message}", style="red", markup=False)


class StageProgress(Progress):
    def __init__(self, steps: tuple[str, ...], total: int):
        super().__init__(
            SpinnerColumn(), TextColumn("[cyan]{task.description:<12}"), BarColumn(),
            MofNCompleteColumn(), console=console, disable=not console.is_terminal, transient=True,
        )
        self.tasks_by_step = {step: self.add_task(step, total=total) for step in (*steps, "Processed")}

    def completed(self, step: str) -> None:
        self.advance(self.tasks_by_step[step])


@dataclass
class Summary:
    counts: dict[str, int]
    written: int = 0
    kept: int = 0
    failed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def step_completed(self, step: str) -> None:
        self.counts[step] += 1

    def report_error(self, path: str, message: str) -> None:
        self.failed += 1
        if len(self.errors) < MAX_SHOWN_ERRORS:
            self.errors.append((path, message))

    def show(self, elapsed: float) -> None:
        table = Table(title="nxscript summary", title_style="bold cyan", show_edge=False)
        table.add_column("Stage", style="cyan")
        table.add_column("Files", justify="right")
        for step, count in self.counts.items():
            table.add_row(step, f"{count:,}")
        table.add_section()
        table.add_row("Written", f"{self.written:,}")
        table.add_row("Kept existing", f"{self.kept:,}")
        table.add_row("Failed", f"{self.failed:,}", style="red" if self.failed else None)
        table.add_row("Elapsed", f"{elapsed:.1f}s")
        console.print(table)
        for path, message in self.errors:
            console.print(f"  {path}: {message}", markup=False, style="red")
        if self.failed > len(self.errors):
            console.print(f"  {self.failed - len(self.errors):,} more failures", style="dim")
