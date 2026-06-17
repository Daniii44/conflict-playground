import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

from common.config import load_config
from common.evaluation_models import EvaluationInput, MergeSummaryEvaluation
from common.git_util import capture_git
from common.redis_util import setup_redis_connection
from evaluation.analysis.common import (
    EvaluationAnalysis,
    actual_resolution_sha_from_playground_name,
    read_head_commit,
)
from resolution.session import simplified_session_lines


SUMMARY_PROMPT = """You are a technical code-review judge analyzing automated conflict resolution failures.

Analyze the provided data:
1. Original git conflicts
2. Diff (Proposed Resolution vs. Reference Solution)
3. Agent's internal thoughts/chat logs

Task: Describe exactly what went wrong in a single, concise paragraph of 50 words or less. Focus purely on the root cause of the failure mode (e.g., context drift, submodule blindness, rogue syntax injection, or execution slip). Do not include introductory phrases, pleasantries, or broad generalizations. Start directly with the technical explanation."""


@dataclass(frozen=True)
class SummaryJudgeConfig:
    ollama_model: str
    ollama_base_url: str | None = None
    ollama_temperature: float = 0.0


def summary_judge_config(config: dict[str, Any] | None = None) -> SummaryJudgeConfig:
    config = config if config is not None else load_config()
    section = config.get("evaluation_summary", {})
    if not isinstance(section, dict):
        section = {}

    model = (
        os.environ.get("EVALUATION_SUMMARY_OLLAMA_MODEL")
        or section.get("ollama_model")
        or section.get("model")
        or config.get("evaluation_summary_ollama_model")
    )
    if not model:
        raise RuntimeError(
            "Set evaluation_summary_ollama_model in config.yaml "
            "or export EVALUATION_SUMMARY_OLLAMA_MODEL"
        )

    base_url = (
        os.environ.get("EVALUATION_SUMMARY_OLLAMA_BASE_URL")
        or section.get("ollama_base_url")
        or section.get("base_url")
        or config.get("evaluation_summary_ollama_base_url")
    )
    temperature_value = (
        os.environ.get("EVALUATION_SUMMARY_OLLAMA_TEMPERATURE")
        or section.get("ollama_temperature")
        or section.get("temperature")
        or config.get("evaluation_summary_ollama_temperature")
        or 0.0
    )
    try:
        temperature = float(temperature_value)
    except (TypeError, ValueError) as error:
        raise RuntimeError("evaluation_summary.ollama_temperature must be a number") from error

    return SummaryJudgeConfig(
        ollama_model=str(model),
        ollama_base_url=str(base_url) if base_url else None,
        ollama_temperature=temperature,
    )


def build_summary_prompt(original_conflicts: str, proposed_to_actual_diff: str, agent_session: str) -> str:
    return (
        f"{SUMMARY_PROMPT}\n\n"
        "Original git conflicts:\n"
        f"```json\n{original_conflicts}\n```\n\n"
        "Diff (Proposed Resolution vs. Reference Solution):\n"
        f"```diff\n{proposed_to_actual_diff}\n```\n\n"
        "Agent's internal thoughts/chat logs:\n"
        f"```text\n{agent_session}\n```"
    )


def invoke_ollama_judge(prompt: str, config: SummaryJudgeConfig) -> str:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as error:
        raise RuntimeError("Install langchain-ollama to run evaluation summary analysis") from error

    kwargs: dict[str, Any] = {
        "model": config.ollama_model,
        "temperature": config.ollama_temperature,
    }
    if config.ollama_base_url:
        kwargs["base_url"] = config.ollama_base_url

    response = ChatOllama(**kwargs).invoke(prompt)
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text", part)) if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content).strip()


class SummaryEvaluationAnalysis(EvaluationAnalysis):
    def __init__(
        self,
        analysis_name: str = "summary",
        *,
        redis=None,
        judge: Callable[[str, SummaryJudgeConfig], str] = invoke_ollama_judge,
        config: SummaryJudgeConfig | None = None,
    ):
        super().__init__(analysis_name)
        self.redis = redis
        self.judge = judge
        self.config = config

    def failed(
        self,
        evaluation_input: EvaluationInput,
        error: str,
        *,
        actual_resolution_sha: str | None = None,
        proposed_commit_sha: str | None = None,
        info_conflict_key: str | None = None,
        judge_model: str | None = None,
        original_conflicts: str | None = None,
        proposed_to_actual_resolution_patch: str | None = None,
        agent_session: str | None = None,
        prompt: str | None = None,
    ) -> MergeSummaryEvaluation:
        return MergeSummaryEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            info_conflict_key=info_conflict_key,
            judge_model=judge_model,
            original_conflicts=original_conflicts,
            proposed_to_actual_resolution_patch=proposed_to_actual_resolution_patch,
            agent_session=agent_session,
            prompt=prompt,
            error=error,
        )

    def redis_connection(self):
        if self.redis is None:
            self.redis = setup_redis_connection()
        return self.redis

    def repo_and_merge_from_resolution(self, evaluation_input: EvaluationInput) -> tuple[str, str | None]:
        playground_name = evaluation_input.resolution_postfix.rsplit(":", 1)[0]
        if "-" not in playground_name:
            return playground_name, None
        return playground_name.rsplit("-", 1)

    def info_conflict_key(self, evaluation_input: EvaluationInput) -> str | None:
        repo_name, merge_sha = self.repo_and_merge_from_resolution(evaluation_input)
        if merge_sha is None:
            return None
        return f"info:conflict:core:{repo_name}:{merge_sha}"

    def read_info_conflict(self, key: str) -> tuple[str | None, str | None]:
        payload = self.redis_connection().json().get(key)
        if not payload:
            logger.error("No corresponding info:core analysis data at {}", key)
            return None, f"No corresponding info:core analysis data at {key}"
        return json.dumps(payload, sort_keys=True, indent=2), None

    def diff_tree(self, playground_path: str, actual_resolution_sha: str) -> tuple[str | None, str | None]:
        result = capture_git(
            "-C",
            playground_path,
            "diff-tree",
            "-p",
            "HEAD",
            actual_resolution_sha,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout, None

        error = result.stderr.strip() or result.stdout.strip()
        return None, f"Could not diff proposed resolution against actual resolution: {error}"

    def agent_session(self, evaluation_input: EvaluationInput) -> str:
        try:
            lines = simplified_session_lines(evaluation_input.resolution.model_dump(mode="json"))
        except RuntimeError as error:
            return f"[session unavailable: {error}]"
        return "\n".join(lines)

    def analyse(self, evaluation_input: EvaluationInput) -> MergeSummaryEvaluation:
        proposed_resolution = evaluation_input.resolution.proposed_resolution
        if proposed_resolution is None:
            return self.failed(evaluation_input, "Resolution has no proposed_resolution")

        if proposed_resolution.git_archive is None:
            error = proposed_resolution.error or "Resolution has no archived .git repository"
            return self.failed(evaluation_input, error)

        playgrounds = os.environ.get("PLAYGROUNDS")
        if playgrounds is None:
            return self.failed(evaluation_input, "PLAYGROUNDS environment variable is not set")

        playground_name = evaluation_input.restored_playground_name
        playground_path = f"{playgrounds}/{playground_name}"
        actual_resolution_sha = actual_resolution_sha_from_playground_name(playground_name)
        if actual_resolution_sha is None:
            return self.failed(
                evaluation_input,
                f"Could not extract merge SHA from playground name: {playground_name}",
            )

        commit_sha, head_error = read_head_commit(playground_path)
        if head_error is not None:
            return self.failed(
                evaluation_input,
                head_error,
                actual_resolution_sha=actual_resolution_sha,
            )

        info_key = self.info_conflict_key(evaluation_input)
        if info_key is None:
            logger.error("Could not derive info:core key from {}", evaluation_input.resolution_key)
            return self.failed(
                evaluation_input,
                f"Could not derive info:core key from {evaluation_input.resolution_key}",
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
            )

        original_conflicts, info_error = self.read_info_conflict(info_key)
        if info_error is not None:
            return self.failed(
                evaluation_input,
                info_error,
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
            )

        diff, diff_error = self.diff_tree(playground_path, actual_resolution_sha)
        if diff_error is not None:
            return self.failed(
                evaluation_input,
                diff_error,
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
            )

        session = self.agent_session(evaluation_input)
        prompt = build_summary_prompt(original_conflicts or "", diff or "", session)
        try:
            judge_config = self.config or summary_judge_config()
        except RuntimeError as error:
            return self.failed(
                evaluation_input,
                str(error),
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=diff,
                agent_session=session,
                prompt=prompt,
            )

        try:
            summary = self.judge(prompt, judge_config)
        except Exception as error:
            return self.failed(
                evaluation_input,
                str(error),
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
                judge_model=judge_config.ollama_model,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=diff,
                agent_session=session,
                prompt=prompt,
            )

        return MergeSummaryEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            info_conflict_key=info_key,
            judge_model=judge_config.ollama_model,
            original_conflicts=original_conflicts,
            proposed_to_actual_resolution_patch=diff,
            agent_session=session,
            prompt=prompt,
            failure_summary=summary,
        )
