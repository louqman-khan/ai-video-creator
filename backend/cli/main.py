from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from app.config import get_settings
from app.doctor import run_checks
from app.media import ffmpeg
from app.pipeline.caption_style import load_style
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
    style_file: Annotated[Optional[Path], typer.Option("--style", exists=True, dir_okay=False, help="TOML caption style file")] = None,
    font_size: Annotated[Optional[float], typer.Option(help="Caption size, % of frame height")] = None,
    color: Annotated[Optional[str], typer.Option(help="Text colour, e.g. #FFFF00")] = None,
    outline_color: Annotated[Optional[str], typer.Option()] = None,
    outline_width: Annotated[Optional[float], typer.Option(help="Outline px at 1080p")] = None,
    position: Annotated[Optional[str], typer.Option(help="bottom | center | top")] = None,
    words_per_line: Annotated[Optional[int], typer.Option(help="Max words per caption")] = None,
    no_captions: Annotated[bool, typer.Option("--no-captions")] = False,
    no_clean: Annotated[bool, typer.Option("--no-clean", help="Skip noise removal")] = False,
    script: Annotated[Optional[Path], typer.Option("--script", exists=True, dir_okay=False, help="Known script text: captions use its exact words, timing comes from the audio")] = None,
    no_normalize: Annotated[bool, typer.Option("--no-normalize", help="Skip loudness normalisation")] = False,
    lufs: Annotated[Optional[float], typer.Option(help="Target loudness in LUFS (default -14)")] = None,
    remove_silence: Annotated[bool, typer.Option("--remove-silence", help="Shorten long pauses")] = False,
    min_gap: Annotated[Optional[float], typer.Option(help="With --remove-silence: pauses >= this many seconds are shortened (default 0.8)")] = None,
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
    if no_clean:
        s.audio_cleaner = "noop"
    try:
        style = load_style(
            style_file, font=font or (s.caption_font or None), size_pct=font_size, color=color,
            outline_color=outline_color, outline_width=outline_width, position=position,
            words_per_line=words_per_line,
        )
    except Exception as e:  # bad TOML / bad colour / out-of-range value
        console.print(f"[red]Caption style error:[/red] {e}")
        raise typer.Exit(1) from None
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
            audio, out or rd / f"{audio.stem}.mp4", lang, aspect, not no_captions, force, style,
            remove_silence, min_gap, not no_normalize, lufs,
            script.read_text("utf-8") if script else None,
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
    script: Annotated[Optional[Path], typer.Option("--script", exists=True, dir_okay=False, help="Align this script to the audio and show the result")] = None,
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
    if script:
        from app.pipeline.align import align_script

        t, stats = align_script(script.read_text("utf-8"), t)
        console.print(f"script words matched exactly: {stats.exact}/{stats.script_words} ({100 * stats.match_ratio:.0f}%)")
    for seg in t.segments:
        console.print(f"[dim]{seg.start:6.1f}-{seg.end:6.1f}[/dim] {seg.text}")
    console.print(f"\nlanguage={t.language} duration={t.duration:.1f}s -> {rd / 'transcript.json'}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address (localhost only by default)")] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8742,
) -> None:
    """Start the web API (upload audio, follow progress, download the video)."""
    import uvicorn

    from app.api.main import create_app

    uvicorn.run(create_app(), host=host, port=port)


@app.command()
def clean(
    days: Annotated[float, typer.Option(help="Remove things nothing has used for this many days")] = 7.0,
    segments: Annotated[bool, typer.Option("--segments", help="Also remove old render caches inside projects (they are made again when needed)")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Only show what would be removed")] = False,
) -> None:
    """Free disk space: unused stock media, orphaned editing proxies, stale caches. Your uploads and exports are never touched."""
    from app.maintenance import clean as do_clean
    from app.maintenance import survey

    s = get_settings()
    mb = lambda n: f"{n / 1e6:,.1f} MB"  # noqa: E731
    for item in survey(s, days, segments):
        console.print(f"{item.label:42} {mb(item.bytes):>12}   removable {mb(item.reclaimable):>10}")
    r = do_clean(s, days, segments, dry_run)
    console.print(f"\n{'Would free' if dry_run else 'Freed'} [bold]{mb(r['freed'])}[/bold] ({r['removed']} items)")


@app.command()
def speak(
    out: Annotated[Path, typer.Argument(help="Where to write the narration (a .wav file)")],
    text: Annotated[Optional[str], typer.Option("--text", help="The text to speak")] = None,
    file: Annotated[Optional[Path], typer.Option("--file", help="Or a text file to speak")] = None,
    lang: Annotated[str, typer.Option("--lang", help="en or ur")] = "en",
) -> None:
    """Speak a script with a synthetic voice (then use the result like any recording: `avc make narration.wav --script script.txt`)."""
    from app.providers.tts import TTSUnavailable, create_tts

    body = text if text is not None else (file.read_text("utf-8") if file else None)
    if not body or not body.strip():
        console.print("[red]Give the text with --text or --file.[/red]")
        raise typer.Exit(1)
    tts = create_tts(get_settings())
    try:
        tts.synthesize(body, lang, out)
    except TTSUnavailable as e:
        console.print(f"[red]{e}[/red] (voices installed now: {', '.join(tts.languages()) or 'none'})")
        raise typer.Exit(1) from None
    console.print(f"[green]Saved[/green] {out}")


@app.command("app")
def app_command(
    port: Annotated[int, typer.Option(help="Port of the local server")] = 8742,
    host: Annotated[str, typer.Option(help="Address to listen on (127.0.0.1 = this computer only; 0.0.0.0 inside a container behind a reverse proxy)")] = "127.0.0.1",
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Do not open the browser")] = False,
) -> None:
    """Run the whole app in one process (server + built web editor) and open it in the browser."""
    import threading
    import webbrowser

    import uvicorn

    from app.api.main import create_app

    s = get_settings()
    if not (Path(s.frontend_dist) / "index.html").is_file():
        console.print(f"[red]The web app is not built yet.[/red] Run `npm install && npm run build` in the frontend folder (expected {s.frontend_dist}).")
        raise typer.Exit(1)
    url = f"http://127.0.0.1:{port}/"
    if not no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    console.print(f"AI Video Creator: [bold]{url}[/bold]  (Ctrl+C to stop)")
    server = uvicorn.Server(uvicorn.Config(create_app(s), host=host, port=port, proxy_headers=s.trusted_proxy, forwarded_allow_ips="*" if s.trusted_proxy else None, log_level=os.environ.get("AVC_LOG_LEVEL", "warning")))
    parent = int(os.environ.get("AVC_PARENT_PID", "0") or 0)
    if parent:  # started by the desktop app: stop when it is gone, even if it was killed instead of closed
        from app.procutil import pid_alive

        def watch() -> None:
            import time

            while not server.should_exit:
                time.sleep(2)
                if not pid_alive(parent):
                    server.should_exit = True

        threading.Thread(target=watch, daemon=True).start()
    server.run()


@app.command("fetch-ffmpeg")
def fetch_ffmpeg() -> None:
    """Download a static ffmpeg + ffprobe into tools/bin (Windows and Linux; on macOS use `brew install ffmpeg`)."""
    from app.media.fetch_ffmpeg import FetchError, fetch

    try:
        files = fetch(progress=lambda m: console.print(f"[dim]{m}[/dim]"))
    except FetchError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    for f in files:
        console.print(f"[green]Saved[/green] {f}")
    console.print("[dim]Builds by BtbN (github.com/BtbN/FFmpeg-Builds), GPL licence: fine for personal use; read the licence before distributing a product that ships it.[/dim]")


@app.command("fetch-models")
def fetch_models(
    clip: Annotated[bool, typer.Option("--clip", help="Also download the CLIP picture-ranking model (about 155 MB)")] = False,
    faces: Annotated[bool, typer.Option("--faces", help="Also download the small face-finding model (1 MB) used by smart crop")] = False,
    whisper: Annotated[bool, typer.Option("--whisper", help="Also download the speech-recognition model chosen by WHISPER_MODEL")] = False,
) -> None:
    """Download the RNNoise speech-denoise model (used by the audio cleaner); with --clip the picture ranker, with --whisper the speech recognition model."""
    from app.media import models

    s = get_settings()
    say = lambda m: console.print(f"[dim]{m}[/dim]")  # noqa: E731
    try:
        console.print(f"[green]Saved[/green] {models.fetch_rnnoise(s, say)}")
        console.print("[dim]Source: github.com/GregorR/rnnoise-models (author states the models are not subject to copyright). Check this is acceptable for your product before shipping it.[/dim]")
        if clip:
            for f in models.fetch_clip(s, say):
                console.print(f"[green]Saved[/green] {f}")
            console.print("[dim]CLIP ViT-B/32 (OpenAI, MIT licence), ONNX int8 files by Xenova (Hugging Face).[/dim]")
        if faces:
            console.print(f"[green]Saved[/green] {models.fetch_face(s, say)}")
            console.print("[dim]Ultra-Light-Fast-Generic-Face-Detector RFB-320 (MIT licence).[/dim]")
        if whisper:
            models.fetch_whisper(s.whisper_model, say)
            console.print(f"[green]Ready[/green] speech model '{s.whisper_model}'")
    except models.ModelError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


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
