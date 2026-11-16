from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from app.config import get_settings
from app.doctor import run_checks
from app.media import ffmpeg
from app.pipeline.runner import ASPECTS, Pipeline, Providers
from app.providers.audio_cleaner import create_cleaner
from app.providers.media_ranker import create_ranker
from app.providers.media_search import build_sources, create_search
from app.providers.scene_planner import PlannerError, create_planner
from app.providers.transcriber import create_transcriber

app = typer.Typer(help="AI Video Creator: audio in, captioned video out.", no_args_is_help=True)
console = Console()


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, markup=False)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs full URLs (incl. API keys)


def _run_dir(audio: Path, run_dir: Optional[Path], work_dir: str) -> Path:
    return run_dir or Path(work_dir) / "runs" / audio.stem


@app.command()
def make(
    audio: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Narration audio file")],
    out: Annotated[Optional[Path], typer.Option("--out", "-o")] = None,
    lang: Annotated[Optional[str], typer.Option(help="ur / en. Default: auto-detect")] = None,
    aspect: Annotated[str, typer.Option(help="16:9 or 9:16")] = "16:9",
    vertical: Annotated[bool, typer.Option("--vertical", help="Shortcut for --aspect 9:16")] = False,
    planner: Annotated[Optional[str], typer.Option(help="gemini | heuristic")] = None,
    whisper_model: Annotated[Optional[str], typer.Option(help="tiny/base/small/medium/large-v3")] = None,
    font: Annotated[Optional[str], typer.Option(help="Caption font family, e.g. 'Jameel Noori Nastaleeq'")] = None,
    no_captions: Annotated[bool, typer.Option("--no-captions")] = False,
    force: Annotated[bool, typer.Option(help="Redo all stages, ignore saved results")] = False,
    run_dir: Annotated[Optional[Path], typer.Option()] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Audio file -> transcript -> scenes -> stock visuals -> captioned MP4."""
    _logging(verbose)
    if vertical:
        aspect = "9:16"
    if aspect not in ASPECTS:
        raise typer.BadParameter(f"aspect must be one of {', '.join(ASPECTS)}")
    s = get_settings()
    if planner:
        s.scene_planner = planner
    if whisper_model:
        s.whisper_model = whisper_model
    if font:
        s.caption_font = font
    rd = _run_dir(audio, run_dir, s.work_dir)
    try:
        providers = Providers(
            transcriber=create_transcriber(s),
            planner=create_planner(s),
            search=create_search(s),
            ranker=create_ranker(s, landscape=aspect != "9:16"),
            cleaner=create_cleaner(s),
        )
        result = Pipeline(s, providers, rd).run(
            audio, out or rd / f"{audio.stem}.mp4", lang, aspect, not no_captions, force
        )
    except (PlannerError, ffmpeg.FfmpegError, RuntimeError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    console.print(f"[green]Done:[/green] {result}\nCredits: {rd / 'CREDITS.txt'}")


@app.command()
def transcribe(
    audio: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    lang: Annotated[Optional[str], typer.Option()] = None,
    whisper_model: Annotated[Optional[str], typer.Option()] = None,
    run_dir: Annotated[Optional[Path], typer.Option()] = None,
    force: Annotated[bool, typer.Option()] = False,
) -> None:
    """Only run speech recognition; writes transcript.json into the run dir."""
    _logging(False)
    s = get_settings()
    if whisper_model:
        s.whisper_model = whisper_model
    rd = _run_dir(audio, run_dir, s.work_dir)
    pipe = Pipeline(
        s,
        Providers(create_transcriber(s), None, None, None, create_cleaner(s)),  # type: ignore[arg-type]
        rd,
    )
    try:
        t = pipe.transcribe(audio, lang, force)
    except ffmpeg.FfmpegError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    for seg in t.segments:
        console.print(f"[dim]{seg.start:6.1f}-{seg.end:6.1f}[/dim] {seg.text}")
    console.print(f"\nlanguage={t.language} duration={t.duration:.1f}s -> {rd / 'transcript.json'}")


@app.command()
def doctor(
    offline: Annotated[bool, typer.Option(help="Skip network reachability checks")] = False,
) -> None:
    """Pass/fail list: Python, FFmpeg, .env keys, fonts, and network reachability."""
    s = get_settings()
    marks = {"ok": "[green]PASS[/green]", "warn": "[yellow]WARN[/yellow]", "fail": "[red]FAIL[/red]"}
    checks = run_checks(s, network=not offline)
    for c in checks:
        console.print(f"{marks[c.status]}  {c.name}" + (f"  [dim]{c.detail}[/dim]" if c.detail else ""))
    console.print(f"\nactive media sources: {', '.join(src.name for src in build_sources(s)) or 'none'}")
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
