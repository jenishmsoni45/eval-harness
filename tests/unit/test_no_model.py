"""No AI model is called anywhere (phases.md P1-4; requirements.md non-goals).

- No hosted-model SDK or local model runtime is in the locked environment, so none can run.
- No source file imports one or reads a provider API key.
- Scripted agents are Inspect `mockllm` models with no API key.
- An actual scripted run uses only `mockllm`, imports no SDK, and never fetches a tokenizer file.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from inspect_ai.event import ModelEvent
from inspect_ai.model._providers.mockllm import MockLLM

from harness.agents.oracle import oracle_model
from harness.tasks import REPO_ROOT

if TYPE_CHECKING:
    from tests.conftest import OracleRun

# Distribution names (uv.lock) and import names of hosted-model SDKs and local model runtimes.
FORBIDDEN_DISTRIBUTIONS = frozenset(
    {
        "anthropic", "openai", "google-genai", "google-generativeai", "google-cloud-aiplatform",
        "mistralai", "groq", "cohere", "together", "litellm", "ollama", "azure-ai-inference",
        "transformers", "torch", "vllm", "llama-cpp-python", "huggingface-hub",
        "sentence-transformers", "replicate", "fireworks-ai", "openrouter",
    }
)  # fmt: skip
FORBIDDEN_MODULES = frozenset(
    {
        "anthropic", "openai", "google.genai", "google.generativeai", "vertexai", "mistralai",
        "groq", "cohere", "together", "litellm", "ollama", "azure.ai.inference", "transformers",
        "torch", "vllm", "llama_cpp", "huggingface_hub",
    }
)  # fmt: skip
API_KEY = re.compile(r"[A-Z][A-Z0-9_]*_API_KEY")
SOURCE_DIRS = ("harness", "scripts", "tests")


def source_files() -> list[Path]:
    this = Path(__file__).resolve()
    return sorted(
        p for d in SOURCE_DIRS for p in (REPO_ROOT / d).rglob("*.py") if p.resolve() != this
    )


def imported_modules(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def is_forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f"{f}.") for f in FORBIDDEN_MODULES)


def test_the_lockfile_has_no_model_sdk_or_runtime() -> None:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    names = {package["name"] for package in lock["package"]}
    assert names, "uv.lock lists no packages"
    assert not names & FORBIDDEN_DISTRIBUTIONS


def test_no_source_file_imports_a_model_sdk() -> None:
    offenders = {
        str(p.relative_to(REPO_ROOT)): sorted(
            m for m in imported_modules(p.read_text()) if is_forbidden(m)
        )
        for p in source_files()
    }
    assert {path: mods for path, mods in offenders.items() if mods} == {}


def test_no_source_file_reads_a_provider_api_key() -> None:
    offenders = [
        str(p.relative_to(REPO_ROOT)) for p in source_files() if API_KEY.search(p.read_text())
    ]
    assert offenders == []


def test_the_checks_above_catch_what_they_look_for() -> None:
    assert is_forbidden("openai")
    assert is_forbidden("google.genai.types")
    assert not is_forbidden("inspect_ai.model")
    assert imported_modules("import anthropic\nfrom openai import OpenAI\n") == {
        "anthropic",
        "openai",
    }
    assert API_KEY.search('os.environ["ANTHROPIC_API_KEY"]')


def test_scripted_agents_are_mockllm_models_without_an_api_key() -> None:
    model = oracle_model()
    assert str(model).startswith("mockllm/")
    assert isinstance(model.api, MockLLM)
    assert model.api.api_key is None


@pytest.mark.docker
def test_a_scripted_run_uses_only_mockllm(oracle_run: OracleRun) -> None:
    log = oracle_run.log
    assert log.status == "success"
    assert log.eval.model == "mockllm/oracle"
    assert log.samples
    models = {e.model for s in log.samples for e in s.events if isinstance(e, ModelEvent)}
    assert models == {"mockllm/oracle"}


@pytest.mark.docker
def test_a_scripted_run_imports_no_sdk_and_fetches_no_tokenizer(oracle_run: OracleRun) -> None:
    assert sorted(m for m in oracle_run.modules if is_forbidden(m)) == []
    assert oracle_run.tokenizer_calls == []
