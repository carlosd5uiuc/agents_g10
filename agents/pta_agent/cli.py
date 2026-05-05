from __future__ import annotations

import argparse
import asyncio
import json
import sys
import unittest
from pathlib import Path

from .models import RunConfig
from .openclaw_baseline import (
    DEFAULT_OPENCLAW_DELAY_SECONDS,
    DEFAULT_OPENCLAW_TIMEOUT_SECONDS,
    OpenClawRunConfig,
    compact_openclaw_model_label,
    current_openclaw_model_id,
    run_openclaw_suite,
    run_openclaw_task,
    setup_openclaw_baseline,
)
from .providers import AnthropicProvider
from .runner import default_output_root, make_session_id, run_suite, run_task, write_grader_bundle, write_session_summary


DEFAULT_PROVIDER = "anthropic"
DEFAULT_TASK_DELAY_SECONDS = 10.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the policy-driven personal task agent.")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{run-all,run-task,test,setup-openclaw,run-openclaw-all,run-openclaw-task}",
    )

    run_task_parser = subparsers.add_parser("run-task", help="Run one task with Anthropic.")
    run_task_parser.add_argument("task_id", help="Task id, e.g. task_04.")
    add_runtime_args(run_task_parser)

    run_all_parser = subparsers.add_parser("run-all", help="Run all tasks with Anthropic, then grade the results.")
    add_runtime_args(run_all_parser)

    test_parser = subparsers.add_parser("test", help="Run PTA unit tests.")
    test_parser.add_argument("--repo-root", default=str(Path.cwd()), help=argparse.SUPPRESS)

    setup_openclaw_parser = subparsers.add_parser("setup-openclaw", help="Install and configure the project-local OpenClaw baseline.")
    setup_openclaw_parser.add_argument("--repo-root", default=str(Path.cwd()), help=argparse.SUPPRESS)

    run_openclaw_task_parser = subparsers.add_parser("run-openclaw-task", help="Run one task with stock OpenClaw.")
    run_openclaw_task_parser.add_argument("task_id", help="Task id, e.g. task_04.")
    add_openclaw_args(run_openclaw_task_parser)

    run_openclaw_all_parser = subparsers.add_parser("run-openclaw-all", help="Run all tasks with stock OpenClaw, then grade the results.")
    add_openclaw_args(run_openclaw_all_parser)

    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()

    if args.command == "test":
        raise SystemExit(run_tests(repo_root))

    if args.command == "setup-openclaw":
        result = setup_openclaw_baseline(repo_root)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["install_returncode"] == 0 and result["mcp_configured"] else 1)

    if args.command == "run-task":
        model_label = current_model_label(DEFAULT_PROVIDER)
        run_one(
            args,
            task_id=args.task_id,
            provider=DEFAULT_PROVIDER,
            task_delay_seconds=DEFAULT_TASK_DELAY_SECONDS,
            model_label=model_label,
        )
        return

    if args.command == "run-openclaw-task":
        run_openclaw_one(args, args.task_id)
        return

    if args.command == "run-openclaw-all":
        run_openclaw_many(args)
        return

    if args.command == "run-all":
        model_label = current_model_label(DEFAULT_PROVIDER)
        run_many(
            args,
            provider=DEFAULT_PROVIDER,
            task_delay_seconds=DEFAULT_TASK_DELAY_SECONDS,
            model_label=model_label,
        )
        return


def run_one(args: argparse.Namespace, task_id: str, provider: str, task_delay_seconds: float, model_label: str | None = None) -> None:
    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else None
    server_script = Path(args.server_script).resolve() if args.server_script else None
    session_id = make_session_id(provider, session_label(task_id, model_label))
    config = RunConfig(
        task_id=task_id,
        provider=provider,
        repo_root=repo_root,
        output_root=output_root,
        max_steps=args.max_steps,
        server_script=server_script,
        task_delay_seconds=task_delay_seconds,
        session_id=session_id,
    )
    summary = asyncio.run(run_task(config))
    session_dir = Path(summary["session_dir"])
    session_summary = write_session_summary([summary], session_dir / "session_summary.json")
    print(json.dumps(session_summary, indent=2))


def run_many(
    args: argparse.Namespace,
    provider: str,
    task_delay_seconds: float,
    model_label: str | None = None,
    task_ids: list[str] | None = None,
    grader_bundle_arg: str | None = None,
) -> None:
    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else None
    server_script = Path(args.server_script).resolve() if args.server_script else None
    session_id = make_session_id(provider, session_label("run-all", model_label))
    config = RunConfig(
        task_id="task_01",
        provider=provider,
        repo_root=repo_root,
        output_root=output_root,
        max_steps=args.max_steps,
        server_script=server_script,
        task_delay_seconds=task_delay_seconds,
        session_id=session_id,
    )
    summaries = asyncio.run(run_suite(config, task_ids=task_ids))
    session_dir = Path(summaries[0]["session_dir"]) if summaries else (output_root or default_output_root(repo_root)) / session_id
    grader_bundle = Path(grader_bundle_arg).resolve() if grader_bundle_arg else session_dir / "grader_bundle.json"
    write_grader_bundle(summaries, grader_bundle)
    grader_results = grade_bundle(repo_root, grader_bundle, session_dir / "grader_results.json")
    session_summary = write_session_summary(
        summaries,
        session_dir / "session_summary.json",
        grader_bundle=grader_bundle,
        grader_results=grader_results,
    )
    print(json.dumps(session_summary, indent=2))


def run_openclaw_one(args: argparse.Namespace, task_id: str) -> None:
    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else None
    model_id = args.model or current_openclaw_model_id()
    session_id = make_session_id("openclaw", session_label(task_id, compact_openclaw_model_label(model_id)))
    summary = asyncio.run(
        run_openclaw_task(
            OpenClawRunConfig(
                repo_root=repo_root,
                task_id=task_id,
                output_root=output_root,
                model_id=model_id,
                timeout_seconds=args.timeout_seconds,
                task_delay_seconds=DEFAULT_OPENCLAW_DELAY_SECONDS,
                session_id=session_id,
            )
        )
    )
    session_dir = Path(summary["session_dir"])
    session_summary = write_session_summary([summary], session_dir / "session_summary.json")
    print(json.dumps(session_summary, indent=2))


def run_openclaw_many(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else None
    model_id = args.model or current_openclaw_model_id()
    session_id = make_session_id("openclaw", session_label("run-all", compact_openclaw_model_label(model_id)))
    summaries = asyncio.run(
        run_openclaw_suite(
            OpenClawRunConfig(
                repo_root=repo_root,
                output_root=output_root,
                model_id=model_id,
                timeout_seconds=args.timeout_seconds,
                task_delay_seconds=DEFAULT_OPENCLAW_DELAY_SECONDS,
                session_id=session_id,
            )
        )
    )
    session_dir = Path(summaries[0]["session_dir"]) if summaries else (output_root or default_output_root(repo_root)) / session_id
    grader_bundle = session_dir / "grader_bundle.json"
    write_grader_bundle(summaries, grader_bundle)
    grader_results = grade_bundle(repo_root, grader_bundle, session_dir / "grader_results.json")
    session_summary = write_session_summary(
        summaries,
        session_dir / "session_summary.json",
        grader_bundle=grader_bundle,
        grader_results=grader_results,
    )
    print(json.dumps(session_summary, indent=2))


def grade_bundle(repo_root: Path, grader_bundle: Path, output_path: Path) -> Path:
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import grader as grader_module

    with grader_bundle.open("r", encoding="utf-8") as handle:
        bundle = json.load(handle)

    results = []
    for task_id, task_output in sorted(bundle.items()):
        grader = getattr(grader_module, f"grade_{task_id}", None)
        if grader is None:
            results.append({"id": task_id, "TSR": 0, "CVC": 1, "PA": 0, "error": "missing grader"})
            continue
        try:
            results.append(grader(task_output))
        except Exception as exc:  # noqa: BLE001 - grader errors should be captured in the artifact
            results.append({"id": task_id, "TSR": 0, "CVC": 1, "PA": 0, "error": repr(exc)})

    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return output_path


def current_model_label(provider: str) -> str | None:
    if provider != "anthropic":
        return provider
    AnthropicProvider.load_environment()
    return compact_model_label(AnthropicProvider.model_id_from_env())


def compact_model_label(model_id: str | None) -> str | None:
    if not model_id:
        return None
    lowered = model_id.lower()
    if "haiku" in lowered:
        return "haiku"
    if "sonnet" in lowered:
        return "sonnet"
    if "opus" in lowered:
        return "opus"
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in lowered)


def session_label(label: str, model_label: str | None) -> str:
    return f"{model_label}-{label}" if model_label else label


def run_tests(repo_root: Path) -> int:
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    tests_dir = repo_root / "agents" / "pta_agent" / "tests"
    suite = unittest.defaultTestLoader.discover(str(tests_dir))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", default=str(Path.cwd()), help=argparse.SUPPRESS)
    parser.add_argument("--output-root", help=argparse.SUPPRESS)
    parser.add_argument("--server-script", help=argparse.SUPPRESS)
    parser.add_argument("--max-steps", type=int, default=30, help=argparse.SUPPRESS)


def add_openclaw_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", default=str(Path.cwd()), help=argparse.SUPPRESS)
    parser.add_argument("--output-root", help=argparse.SUPPRESS)
    parser.add_argument("--model", help="OpenClaw model override. Defaults to ANTHROPIC_MODEL.")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_OPENCLAW_TIMEOUT_SECONDS, help=argparse.SUPPRESS)


if __name__ == "__main__":
    main()
