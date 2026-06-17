from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FIXTURES_DIR = BACKEND_ROOT / "ai_tests" / "fixtures"
REPORTS_DIR = REPO_ROOT / "reports" / "ai-validation"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class SkipCase(Exception):
    """Raised when an opt-in dependency or credential is not available."""


@dataclass(frozen=True)
class TestCase:
    suite: str
    name: str
    description: str
    func: Callable[[], tuple[list[str], list[str]]]


@dataclass
class CaseResult:
    suite: str
    name: str
    description: str
    status: str
    duration_s: float
    details: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    error: str = ""


@contextmanager
def patched_attr(target, attr: str, value):  # noqa: ANN001
    original = getattr(target, attr)
    setattr(target, attr, value)
    try:
        yield
    finally:
        setattr(target, attr, original)


@contextmanager
def isolated_projects_dir():
    from app import projects

    original = projects.PROJECTS_DIR
    with tempfile.TemporaryDirectory(prefix="narratible_ai_projects_") as tmp:
        projects.PROJECTS_DIR = Path(tmp) / "projects"
        projects.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            yield projects.PROJECTS_DIR
        finally:
            projects.PROJECTS_DIR = original


def load_fixture(filename: str) -> dict:
    with open(FIXTURES_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


def require(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def _live_enabled() -> bool:
    return os.environ.get("NARRATIBLE_AI_TEST_LIVE") == "1"


def case_mock_parse_clean_tts_workflow() -> tuple[list[str], list[str]]:
    from app import main, projects

    fixture = load_fixture("mock_workflow.json")
    project_fixture = fixture["project"]
    pdf_data = fixture["pdf_data"]
    expected = fixture["expected"]
    llm_by_source = {
        chapter["raw_text"]: chapter["llm"]
        for chapter in pdf_data["chapters"]
    }
    tts_calls: list[dict] = []

    def fake_extract_structured_from_pdf(_pdf_path: Path, progress_callback=None):
        if progress_callback:
            progress_callback("Loaded mock PDF fixture.", 1.0)
        return pdf_data

    def fake_llm_clean_text(source_text: str, **kwargs):
        llm = llm_by_source[source_text]
        chunk = {
            "chunk_id": 0,
            "provider": kwargs.get("provider", "mock"),
            "profile": kwargs.get("cleaning_profile", "safe"),
            "status": llm["status"],
            "source_text": source_text,
            "candidate_text": llm["cleaned_text"],
            "accepted_text": llm["cleaned_text"],
            "notes_text": "",
            "integrity_issues": llm["integrity_issues"],
            "metrics": {
                "word_count_ratio": 1.0,
                "anchor_required": 0,
                "anchor_matches": 0
            },
            "risk_level": llm["risk_level"],
            "risk_reasons": llm["integrity_issues"],
            "recommended_action": "review" if llm["risk_level"] == "high" else "accept"
        }
        evaluation = {
            "provider": kwargs.get("provider", "mock"),
            "profile": kwargs.get("cleaning_profile", "safe"),
            "chunk_count": 1,
            "accepted_count": 0 if llm["status"] == "fallback" else 1,
            "fallback_count": llm["fallback_count"],
            "chunks": [chunk]
        }
        return llm["cleaned_text"], evaluation

    async def fake_synthesize_speech(text: str, output_path: Path, **kwargs):
        tts_calls.append({
            "text": text,
            "output_path": str(output_path),
            "engine": kwargs.get("engine"),
            "voice": kwargs.get("voice")
        })
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"FAKE-MP3\n" + text[:160].encode("utf-8", errors="ignore"))

    with isolated_projects_dir():
        main._tasks.clear()
        meta = projects.create_project(project_fixture["title"], project_fixture["author"])
        project_dir = projects._project_path(meta.id)
        (project_dir / "book.pdf").write_bytes(b"%PDF-1.4\n% mock fixture\n")

        with patched_attr(main, "extract_structured_from_pdf", fake_extract_structured_from_pdf):
            with patched_attr(main, "llm_clean_text", fake_llm_clean_text):
                main._run_parse(
                    meta.id,
                    f"parse-{meta.id}",
                    cleaner="llm",
                    modules=[],
                    cleaning_profile="safe",
                )

        parse_task = main._get_task(f"parse-{meta.id}")
        require(parse_task is not None, "parse task status was not recorded")
        require(parse_task["status"] == "done", f"parse task ended as {parse_task['status']}")

        chapters = projects.load_chapters(meta.id)
        require(len(chapters) == expected["chapter_count"], "unexpected parsed chapter count")
        require(chapters[0]["text"] == pdf_data["chapters"][0]["llm"]["cleaned_text"], "accepted LLM text was not saved")
        require("fell back to heuristic text" in " ".join(chapters[1].get("warnings", [])), "fallback warning was not surfaced")

        cleaning_eval = projects.load_cleaning_eval(meta.id)
        require(cleaning_eval is not None, "cleaning evaluation was not saved")
        fallback_count = sum(chapter.get("fallback_count", 0) for chapter in cleaning_eval["chapters"])
        require(fallback_count == expected["fallback_count"], "unexpected cleaning fallback count")

        with patched_attr(main, "synthesize_speech", fake_synthesize_speech):
            asyncio.run(main._run_tts(
                meta.id,
                f"tts-{meta.id}",
                engine="edge-tts",
                voice="en-US-AriaNeural",
                speed=1.0,
                single_file=False,
                read_headings=True,
            ))

        tts_task = main._get_task(f"tts-{meta.id}")
        require(tts_task is not None, "tts task status was not recorded")
        require(tts_task["status"] == "done", f"tts task ended as {tts_task['status']}")
        require(len(tts_calls) == expected["tts_calls"], "unexpected number of TTS calls")
        require(tts_calls[0]["text"].startswith("Chapter One.\n\n"), "chapter heading was not composed for TTS")

        updated_chapters = projects.load_chapters(meta.id)
        audio_paths = [Path(chapter["audio_path"]) for chapter in updated_chapters]
        require(all(path.exists() for path in audio_paths), "mock audio artifacts were not written")

        return [
            f"Parsed {len(chapters)} chapters from mock PDF fixture.",
            f"Stored cleaning evaluation with {fallback_count} fallback chunk(s).",
            f"Synthesized {len(tts_calls)} mocked chapter audio file(s)."
        ], [str(path) for path in audio_paths]


def case_replay_llm_guardrails() -> tuple[list[str], list[str]]:
    from app.cleaner import _evaluate_llm_chunk, _parse_llm_clean_output

    fixture = load_fixture("replay_llm_chunks.json")
    details = []
    for index, item in enumerate(fixture["cases"]):
        source_text = item.get("source_text")
        if source_text is None:
            source_text = " ".join(f"word{i}" for i in range(item.get("source_word_count", 120)))

        response_text = item.get("response_text")
        if response_text is None:
            response_mode = item.get("response_mode")
            if response_mode == "identity_json":
                response_text = json.dumps({"main_text": source_text, "notes_text": ""})
            elif response_mode == "placeholder_summary":
                response_text = "<text>word0 word1. ...(rest of text omitted)</text><notes></notes>"
            else:
                raise AssertionError(f"{item['name']}: unknown response mode {response_mode!r}")

        main_text, notes_text = _parse_llm_clean_output(response_text)
        evaluation = _evaluate_llm_chunk(
            index,
            source_text,
            main_text,
            notes_text,
            item["provider"],
            item["profile"],
        )
        expected = item["expected"]
        require(evaluation.status == expected["status"], f"{item['name']}: unexpected status")
        require(evaluation.risk_level == expected["risk_level"], f"{item['name']}: unexpected risk level")
        require(expected["accepted_contains"] in evaluation.accepted_text, f"{item['name']}: accepted text mismatch")
        for issue in expected["issues_contains"]:
            require(issue in evaluation.integrity_issues, f"{item['name']}: missing issue {issue!r}")
        details.append(f"{item['name']}: {evaluation.status}, {evaluation.risk_level}")
    return details, []


def case_live_edge_tts_smoke() -> tuple[list[str], list[str]]:
    if not _live_enabled():
        raise SkipCase("Set NARRATIBLE_AI_TEST_LIVE=1 to allow network/provider calls.")

    from app.tts import synthesize_speech

    with tempfile.TemporaryDirectory(prefix="narratible_edge_tts_") as tmp:
        output_path = Path(tmp) / "edge-preview.mp3"
        asyncio.run(synthesize_speech(
            "This is a narratible live Edge TTS smoke test.",
            output_path,
            engine="edge-tts",
            voice="en-US-AriaNeural",
        ))
        require(output_path.exists(), "Edge TTS did not create an output file")
        require(output_path.stat().st_size > 0, "Edge TTS output file is empty")
        artifact = REPORTS_DIR / f"edge-preview-{datetime.now().strftime('%Y%m%d-%H%M%S')}.mp3"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(output_path.read_bytes())
    return ["Edge TTS returned non-empty audio."], [str(artifact)]


def case_live_cloud_llm_smoke() -> tuple[list[str], list[str]]:
    if not _live_enabled():
        raise SkipCase("Set NARRATIBLE_AI_TEST_LIVE=1 to allow network/provider calls.")

    from app.cleaner import llm_clean_text
    from app.config import load_config

    cfg = load_config()
    provider = None
    if cfg.llm_provider in ("gemini", "openai"):
        provider = cfg.llm_provider
    elif cfg.gemini_api_key:
        provider = "gemini"
    elif cfg.openai_api_key:
        provider = "openai"

    if provider == "gemini" and not cfg.gemini_api_key:
        raise SkipCase("Gemini provider selected, but no Gemini API key is configured.")
    if provider == "openai" and not cfg.openai_api_key:
        raise SkipCase("OpenAI provider selected, but no OpenAI API key is configured.")
    if provider is None:
        raise SkipCase("Configure a Gemini or OpenAI API key to run cloud LLM smoke tests.")

    source = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu. "
        "This short fixture should be cleaned without summarizing or dropping the closing anchor."
    )
    cleaned, evaluation = llm_clean_text(source, provider=provider, return_evaluation=True)
    require(cleaned.strip(), "cloud LLM returned empty cleaned text")
    require(evaluation.get("chunks"), "cloud LLM did not produce chunk evaluation data")
    return [
        f"Provider {provider} returned {len(cleaned)} character(s).",
        f"Risk levels: {[chunk.get('risk_level') for chunk in evaluation.get('chunks', [])]}"
    ], []


def case_live_local_tts_smoke() -> tuple[list[str], list[str]]:
    if not _live_enabled():
        raise SkipCase("Set NARRATIBLE_AI_TEST_LIVE=1 to allow local AI engine calls.")

    engine = os.environ.get("NARRATIBLE_AI_TEST_LOCAL_TTS", "").lower()
    if engine not in ("kokoro", "f5-tts"):
        raise SkipCase("Set NARRATIBLE_AI_TEST_LOCAL_TTS=kokoro or f5-tts.")

    from app.tts import synthesize_speech

    voice_sample_path = None
    voice_reference_text = None
    if engine == "f5-tts":
        sample = os.environ.get("NARRATIBLE_AI_TEST_F5_SAMPLE", "")
        if not sample:
            raise SkipCase("Set NARRATIBLE_AI_TEST_F5_SAMPLE to a WAV/MP3/FLAC reference file.")
        voice_sample_path = Path(sample)
        if not voice_sample_path.exists():
            raise SkipCase(f"F5 reference sample does not exist: {voice_sample_path}")
        voice_reference_text = os.environ.get("NARRATIBLE_AI_TEST_F5_REFERENCE", None)

    with tempfile.TemporaryDirectory(prefix="narratible_local_tts_") as tmp:
        output_path = Path(tmp) / f"{engine}-preview.wav"
        asyncio.run(synthesize_speech(
            "This is a narratible local TTS smoke test.",
            output_path,
            engine=engine,
            voice="af_heart" if engine == "kokoro" else "test",
            voice_sample_path=voice_sample_path,
            voice_reference_text=voice_reference_text,
        ))
        require(output_path.exists(), f"{engine} did not create an output file")
        require(output_path.stat().st_size > 0, f"{engine} output file is empty")
        artifact = REPORTS_DIR / f"{engine}-preview-{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(output_path.read_bytes())
    return [f"{engine} returned non-empty audio."], [str(artifact)]


CASES = [
    TestCase(
        "ai-mock",
        "mock-parse-clean-tts-workflow",
        "Runs parse -> mocked LLM cleaning -> mocked TTS artifact generation.",
        case_mock_parse_clean_tts_workflow,
    ),
    TestCase(
        "ai-replay",
        "replay-llm-guardrails",
        "Replays recorded LLM-style responses through cleaner guardrails.",
        case_replay_llm_guardrails,
    ),
    TestCase(
        "ai-live",
        "live-edge-tts-smoke",
        "Calls Edge TTS and verifies non-empty audio.",
        case_live_edge_tts_smoke,
    ),
    TestCase(
        "ai-live",
        "live-cloud-llm-smoke",
        "Calls configured Gemini/OpenAI cleaner and verifies evaluation output.",
        case_live_cloud_llm_smoke,
    ),
    TestCase(
        "ai-live",
        "live-local-tts-smoke",
        "Calls Kokoro or F5-TTS when explicitly enabled.",
        case_live_local_tts_smoke,
    ),
]


SUITE_CHOICES = {
    "fast": ("ai-mock", "ai-replay"),
    "ai-mock": ("ai-mock",),
    "ai-replay": ("ai-replay",),
    "ai-live": ("ai-live",),
    "all": ("ai-mock", "ai-replay", "ai-live"),
}


def expand_suites(selected: Iterable[str]) -> set[str]:
    suites: set[str] = set()
    for item in selected:
        suites.update(SUITE_CHOICES[item])
    return suites


def list_cases():
    print("Available AI validation cases:")
    for case in CASES:
        print(f"  {case.suite:9} {case.name:32} {case.description}")


def prompt_selection() -> tuple[list[str], list[str]]:
    print("narratible AI validation")
    print("")
    print("1. Fast suite (mock + replay)")
    print("2. Mock workflow only")
    print("3. Replay guardrails only")
    print("4. Live provider smoke tests")
    print("5. Pick individual cases")
    print("6. All suites (live cases remain gated)")
    print("")
    raw = input("Select tests [1]: ").strip() or "1"
    if raw == "1":
        return ["fast"], []
    if raw == "2":
        return ["ai-mock"], []
    if raw == "3":
        return ["ai-replay"], []
    if raw == "4":
        return ["ai-live"], []
    if raw == "6":
        return ["all"], []
    if raw == "5":
        print("")
        for index, case in enumerate(CASES, start=1):
            print(f"{index}. [{case.suite}] {case.name} - {case.description}")
        selected = input("Enter case numbers or names separated by commas: ").strip()
        names = []
        for token in [part.strip() for part in selected.split(",") if part.strip()]:
            if token.isdigit():
                position = int(token)
                if 1 <= position <= len(CASES):
                    names.append(CASES[position - 1].name)
            else:
                names.append(token)
        return ["all"], names
    print(f"Unknown selection {raw!r}; running fast suite.")
    return ["fast"], []


def select_cases(suite_names: list[str], case_names: list[str]) -> list[TestCase]:
    suites = expand_suites(suite_names)
    selected = [case for case in CASES if case.suite in suites]
    if case_names:
        requested = set(case_names)
        selected = [case for case in selected if case.name in requested]
        missing = requested.difference(case.name for case in selected)
        if missing:
            raise SystemExit(f"Unknown AI validation case(s): {', '.join(sorted(missing))}")
    return selected


def run_case(case: TestCase) -> CaseResult:
    started = time.perf_counter()
    try:
        details, artifacts = case.func()
        status = "pass"
        error = ""
    except SkipCase as exc:
        details = [str(exc)]
        artifacts = []
        status = "skip"
        error = ""
    except AssertionError as exc:
        details = []
        artifacts = []
        status = "fail"
        error = str(exc)
    except Exception:
        details = []
        artifacts = []
        status = "fail"
        error = traceback.format_exc()

    return CaseResult(
        suite=case.suite,
        name=case.name,
        description=case.description,
        status=status,
        duration_s=time.perf_counter() - started,
        details=details,
        artifacts=artifacts,
        error=error,
    )


def write_report(results: list[CaseResult], report_path: Path, selected_suites: list[str]) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    overall = "FAIL" if any(result.status == "fail" for result in results) else "PASS"
    lines = [
        "# AI Validation Report",
        "",
        f"- Timestamp: {datetime.now().isoformat(timespec='seconds')}",
        f"- Suites: {', '.join(selected_suites)}",
        f"- Overall: {overall}",
        f"- Live gate: NARRATIBLE_AI_TEST_LIVE={os.environ.get('NARRATIBLE_AI_TEST_LIVE', '')!r}",
        "",
        "## Results",
        "",
        "| Suite | Case | Status | Seconds |",
        "|---|---|---|---|",
    ]
    for result in results:
        lines.append(f"| {result.suite} | {result.name} | {result.status.upper()} | {result.duration_s:.2f} |")

    lines.extend(["", "## Details", ""])
    for result in results:
        lines.extend([
            f"### {result.suite} / {result.name}",
            "",
            result.description,
            "",
            f"- Status: {result.status.upper()}",
            f"- Duration: {result.duration_s:.2f}s",
        ])
        for detail in result.details:
            lines.append(f"- Detail: {detail}")
        for artifact in result.artifacts:
            lines.append(f"- Artifact: {artifact}")
        if result.error:
            lines.extend(["", "```text", result.error, "```"])
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run opt-in narratible AI workflow validations.")
    parser.add_argument(
        "--suite",
        action="append",
        choices=sorted(SUITE_CHOICES),
        help="Suite to run. Repeatable. Defaults to an interactive menu in a TTY, otherwise fast.",
    )
    parser.add_argument("--case", action="append", default=[], help="Run one case by name. Repeatable.")
    parser.add_argument("--list", action="store_true", help="List available cases and exit.")
    parser.add_argument("--report-path", default="", help="Custom markdown report path.")
    parser.add_argument("--no-report", action="store_true", help="Do not write a markdown report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.list:
        list_cases()
        return 0

    if args.suite:
        selected_suites = args.suite
        selected_cases = args.case
    elif sys.stdin.isatty():
        selected_suites, selected_cases = prompt_selection()
    else:
        selected_suites = ["fast"]
        selected_cases = args.case

    cases = select_cases(selected_suites, selected_cases)
    if not cases:
        print("No AI validation cases selected.")
        return 1

    print(f"Running {len(cases)} AI validation case(s)...")
    results = []
    for case in cases:
        result = run_case(case)
        results.append(result)
        print(f"[{result.status.upper():4}] {result.suite} / {result.name} ({result.duration_s:.2f}s)")
        if result.error:
            print(f"       {result.error.splitlines()[0] if result.error.splitlines() else result.error}")
        for detail in result.details:
            print(f"       {detail}")

    if not args.no_report:
        report_path = Path(args.report_path) if args.report_path else REPORTS_DIR / f"ai-validation-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        written = write_report(results, report_path, selected_suites)
        print(f"Report written: {written}")

    return 1 if any(result.status == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
