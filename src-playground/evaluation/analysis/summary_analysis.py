import json
import os
import time
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


SUMMARY_PROMPT = """You are a technical code-review judge analyzing an automated conflict resolution failure.

You will be given:
1. Original git conflicts
2. A labeled comparison from the reference solution to the agent's proposed resolution.
3. Labeled comparisons from the original conflicted tree to the agent's proposed resolution and the reference solution.
4. The Agent's internal thoughts/chat logs

CRITICAL COMPARISON READING RULES:
- The comparisons use explicit bracketed labels instead of raw git +/- markers.
- Treat [AGENT INTRODUCED ERROR / DELETE THIS] and [AGENT FORGOT THIS / REQUIRED CODE] as the main error signals.
- Use the conflicted-state comparisons to understand what the agent changed versus what the reference solution changed.
- Compare all labeled comparisons against the Agent's thoughts to identify the exact breakdown in reasoning.

Task: Describe exactly what went wrong in a single, concise paragraph of 50 words or less. Focus purely on the root cause of the failure mode (e.g., context drift, submodule blindness, rogue syntax injection, or execution slip). Do not say "Based on the diff..." or "The agent failed because...". Start directly with the technical explanation."""


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


DIFF_HEADER_PREFIXES = (
    "---",
    "+++",
    "@@",
    "diff --git",
    "index ",
    "new file mode ",
    "deleted file mode ",
    "similarity index ",
    "rename from ",
    "rename to ",
)


def clear_diff_direction(
    diff_text: str,
    *,
    removed_label: str,
    added_label: str,
) -> str:
    cleaned_lines = []
    for line in diff_text.splitlines():
        if line.startswith(DIFF_HEADER_PREFIXES):
            continue

        if line.startswith("-"):
            cleaned_lines.append(f"[{removed_label}]: {line[1:]}")
        elif line.startswith("+"):
            cleaned_lines.append(f"[{added_label}]: {line[1:]}")
        else:
            cleaned_lines.append(f"  {line}")

    return "\n".join(cleaned_lines) or "[NO CONTENT CHANGES]"


def build_summary_prompt(
    original_conflicts: str,
    proposed_to_actual_diff: str,
    conflicted_to_proposed_diff: str,
    conflicted_to_actual_diff: str,
    agent_session: str,
) -> str:
    proposed_vs_reference = clear_diff_direction(
        proposed_to_actual_diff,
        removed_label="AGENT FORGOT THIS / REQUIRED CODE",
        added_label="AGENT INTRODUCED ERROR / DELETE THIS",
    )
    conflicted_vs_proposed = clear_diff_direction(
        conflicted_to_proposed_diff,
        removed_label="AGENT REMOVED THIS FROM CONFLICTED STATE",
        added_label="AGENT ADDED THIS IN PROPOSED RESOLUTION",
    )
    conflicted_vs_actual = clear_diff_direction(
        conflicted_to_actual_diff,
        removed_label="REFERENCE REMOVED THIS FROM CONFLICTED STATE",
        added_label="REFERENCE ADDED THIS IN CORRECT RESOLUTION",
    )
    return (
        f"{SUMMARY_PROMPT}\n\n"
        "Original git conflicts:\n"
        f"```json\n{original_conflicts}\n```\n\n"
        "Agent's internal thoughts/chat logs:\n"
        f"```text\n{agent_session}\n```\n\n"
        "Comparison Analysis:\n"
        "CRITICAL COMPARISON READING REMINDER:\n"
        "- [AGENT INTRODUCED ERROR / DELETE THIS] means the proposed resolution contains code absent from the reference solution.\n"
        "- [AGENT FORGOT THIS / REQUIRED CODE] means the reference solution contains code missing from the proposed resolution.\n"
        "- Conflicted-state labels describe what each resolution added to or removed from the original conflicted tree.\n\n"
        "Comparison (Reference Solution -> Proposed Resolution):\n"
        f"```text\n{proposed_vs_reference}\n```\n\n"
        "Comparison (Conflicted State -> Proposed Resolution):\n"
        f"```text\n{conflicted_vs_proposed}\n```\n\n"
        "Comparison (Conflicted State -> Reference Solution):\n"
        f"```text\n{conflicted_vs_actual}\n```"
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

    try:
        response = ChatOllama(**kwargs).invoke(prompt)
    except Exception as error:
        location = config.ollama_base_url or "default Ollama base URL"
        raise RuntimeError(
            "Ollama chat completion failed "
            f"for model {config.ollama_model!r} at {location}: "
            f"{type(error).__name__}: {error}"
        ) from error

    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text", part)) if isinstance(part, dict) else str(part)
            for part in content
        )
    summary = str(content).strip()
    if not summary:
        raise RuntimeError(
            f"Ollama chat completion returned an empty response for model {config.ollama_model!r}"
        )
    return summary


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
        conflicted_tree_oid: str | None = None,
        conflicted_to_proposed_resolution_patch: str | None = None,
        conflicted_to_actual_resolution_patch: str | None = None,
        agent_session: str | None = None,
        prompt: str | None = None,
    ) -> MergeSummaryEvaluation:
        return MergeSummaryEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=proposed_commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=conflicted_tree_oid,
            info_conflict_key=info_conflict_key,
            judge_model=judge_model,
            original_conflicts=original_conflicts,
            proposed_to_actual_resolution_patch=proposed_to_actual_resolution_patch,
            conflicted_to_proposed_resolution_patch=conflicted_to_proposed_resolution_patch,
            conflicted_to_actual_resolution_patch=conflicted_to_actual_resolution_patch,
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

    def collect_parents(self, playground_path: str, merge_commit_oid: str) -> tuple[list[str], str | None]:
        result = capture_git(
            "-C",
            playground_path,
            "show",
            "--no-patch",
            "--format=%P",
            merge_commit_oid,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip().split(), None

        error = result.stderr.strip() or result.stdout.strip()
        return [], f"Could not read actual resolution parents: {error}"

    def collect_conflicted_tree_oid(
        self,
        playground_path: str,
        left_parent_oid: str,
        right_parent_oid: str,
    ) -> tuple[str | None, str | None]:
        result = capture_git(
            "-C",
            playground_path,
            "merge-tree",
            "-z",
            left_parent_oid,
            right_parent_oid,
            check=False,
        )
        if result.returncode == 0:
            return None, "Actual resolution parents merge cleanly"

        output = result.stdout + result.stderr
        if "fatal: refusing to merge unrelated histories" in output:
            return None, "Actual resolution parents have unrelated histories"

        conflicted_tree_oid = result.stdout.split("\0", 1)[0].strip()
        if not conflicted_tree_oid:
            return None, "Could not read conflicted tree oid from merge-tree output"

        return conflicted_tree_oid, None

    def diff_tree(
        self,
        playground_path: str,
        base_ref: str,
        target_ref: str,
    ) -> tuple[str | None, str | None]:
        result = capture_git(
            "-C",
            playground_path,
            "diff-tree",
            "-p",
            base_ref,
            target_ref,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout, None

        error = result.stderr.strip() or result.stdout.strip()
        return None, error

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

        proposed_to_actual_diff, diff_error = self.diff_tree(
            playground_path,
            actual_resolution_sha,
            "HEAD",
        )
        if diff_error is not None:
            return self.failed(
                evaluation_input,
                f"Could not diff proposed resolution against actual resolution: {diff_error}",
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
            )

        parents, parents_error = self.collect_parents(playground_path, actual_resolution_sha)
        if parents_error is not None:
            return self.failed(
                evaluation_input,
                parents_error,
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=proposed_to_actual_diff,
            )

        if len(parents) != 2:
            return self.failed(
                evaluation_input,
                f"Actual resolution has {len(parents)} parents; expected 2",
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=proposed_to_actual_diff,
            )

        conflicted_tree_oid, conflicted_tree_error = self.collect_conflicted_tree_oid(
            playground_path,
            parents[0],
            parents[1],
        )
        if conflicted_tree_error is not None:
            return self.failed(
                evaluation_input,
                conflicted_tree_error,
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=proposed_to_actual_diff,
            )

        conflicted_to_proposed_diff, diff_error = self.diff_tree(
            playground_path,
            conflicted_tree_oid,
            "HEAD",
        )
        if diff_error is not None:
            return self.failed(
                evaluation_input,
                f"Could not diff proposed resolution against conflicted tree: {diff_error}",
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                conflicted_tree_oid=conflicted_tree_oid,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=proposed_to_actual_diff,
            )

        conflicted_to_actual_diff, diff_error = self.diff_tree(
            playground_path,
            conflicted_tree_oid,
            actual_resolution_sha,
        )
        if diff_error is not None:
            return self.failed(
                evaluation_input,
                f"Could not diff actual resolution against conflicted tree: {diff_error}",
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                conflicted_tree_oid=conflicted_tree_oid,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=proposed_to_actual_diff,
                conflicted_to_proposed_resolution_patch=conflicted_to_proposed_diff,
            )

        session = self.agent_session(evaluation_input)
        prompt = build_summary_prompt(
            original_conflicts or "",
            proposed_to_actual_diff or "",
            conflicted_to_proposed_diff or "",
            conflicted_to_actual_diff or "",
            session,
        )
        try:
            judge_config = self.config or summary_judge_config()
        except RuntimeError as error:
            logger.error(
                "Cannot run summary judge for {}: {}",
                evaluation_input.resolution_key,
                error,
            )
            return self.failed(
                evaluation_input,
                str(error),
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                conflicted_tree_oid=conflicted_tree_oid,
                info_conflict_key=info_key,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=proposed_to_actual_diff,
                conflicted_to_proposed_resolution_patch=conflicted_to_proposed_diff,
                conflicted_to_actual_resolution_patch=conflicted_to_actual_diff,
                agent_session=session,
                prompt=prompt,
            )

        started = time.monotonic()
        logger.info(
            "Calling Ollama summary judge for {} with model={} base_url={}",
            evaluation_input.resolution_key,
            judge_config.ollama_model,
            judge_config.ollama_base_url or "<default>",
        )
        try:
            summary = self.judge(prompt, judge_config)
        except Exception as error:
            elapsed = time.monotonic() - started
            logger.opt(exception=error).error(
                "Summary judge failed for {} after {:.2f}s with model={} base_url={}: {}",
                evaluation_input.resolution_key,
                elapsed,
                judge_config.ollama_model,
                judge_config.ollama_base_url or "<default>",
                error,
            )
            return self.failed(
                evaluation_input,
                str(error),
                actual_resolution_sha=actual_resolution_sha,
                proposed_commit_sha=commit_sha,
                conflicted_tree_oid=conflicted_tree_oid,
                info_conflict_key=info_key,
                judge_model=judge_config.ollama_model,
                original_conflicts=original_conflicts,
                proposed_to_actual_resolution_patch=proposed_to_actual_diff,
                conflicted_to_proposed_resolution_patch=conflicted_to_proposed_diff,
                conflicted_to_actual_resolution_patch=conflicted_to_actual_diff,
                agent_session=session,
                prompt=prompt,
            )

        elapsed = time.monotonic() - started
        logger.info(
            "Summary judge completed for {} in {:.2f}s with {} characters",
            evaluation_input.resolution_key,
            elapsed,
            len(summary),
        )
        return MergeSummaryEvaluation(
            resolution_key=evaluation_input.resolution_key,
            proposed_commit_sha=commit_sha,
            actual_resolution_sha=actual_resolution_sha,
            conflicted_tree_oid=conflicted_tree_oid,
            info_conflict_key=info_key,
            judge_model=judge_config.ollama_model,
            original_conflicts=original_conflicts,
            proposed_to_actual_resolution_patch=proposed_to_actual_diff,
            conflicted_to_proposed_resolution_patch=conflicted_to_proposed_diff,
            conflicted_to_actual_resolution_patch=conflicted_to_actual_diff,
            agent_session=session,
            prompt=prompt,
            failure_summary=summary,
        )
