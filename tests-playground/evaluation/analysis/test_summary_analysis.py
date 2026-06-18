from datetime import datetime
from subprocess import CompletedProcess
from unittest.mock import patch

from common.active_playground_models import Configuration
from common.evaluation_models import EvaluationInput
from common.resolution_models import ConflictResolution, ProposedResolution
from evaluation.analysis.summary_analysis import (
    SummaryEvaluationAnalysis,
    SummaryJudgeConfig,
    summary_judge_config,
)


class FakeRedisJson:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self, values=None):
        self.json_api = FakeRedisJson(values)

    def json(self):
        return self.json_api


def evaluation_input():
    resolution_key = "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    return EvaluationInput(
        resolution_key=resolution_key,
        resolution_postfix="owner/repo.git-actualsha:20260602T120000.000000Z",
        restored_playground_name="owner/repo.git-20260602T120000.000000Z-actualsha",
        resolution=ConflictResolution(
            configuration=Configuration(
                hook_type="opencode",
                playground_version="test",
                volume_type="bind-mount",
                resolution_start=datetime(2026, 6, 2, 12, 0, 0),
            ),
            resolution_end=datetime(2026, 6, 2, 12, 0, 5),
            hook_result={
                "opencode_session_export": {
                    "data": {
                        "messages": [
                            {
                                "info": {"role": "assistant"},
                                "parts": [
                                    {"type": "text", "text": "I inspected the conflict."},
                                    {
                                        "type": "tool",
                                        "state": {
                                            "title": "Run tests",
                                            "input": {"command": "pytest"},
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                }
            },
            proposed_resolution=ProposedResolution(git_archive="archive"),
        ),
    )


def test_summary_analysis_builds_prompt_from_info_diff_and_session(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    info_key = "info:conflict:core:owner/repo.git:actualsha"
    redis = FakeRedis(
        {
            info_key: {
                "repo": "owner/repo.git",
                "merge_commit_oid": "actualsha",
                "merge_result": {"logical_conflicts": [{"type": "CONFLICT (content)", "paths": ["file.txt"]}]},
            }
        }
    )
    judge_calls = []

    def judge(prompt, config):
        judge_calls.append((prompt, config))
        return "The agent resolved the wrong side of file.txt after losing conflict context."

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.summary_analysis.capture_git") as summary_capture_git,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        summary_capture_git.side_effect = [
            CompletedProcess(
                args=[],
                returncode=0,
                stdout="diff --git a/file.txt b/file.txt\n+bad\n-required\n",
                stderr="",
            ),
            CompletedProcess(args=[], returncode=0, stdout="left-parent right-parent\n", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="conflicted-tree\0metadata", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="diff --git a/file.txt b/file.txt\n+proposed\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="diff --git a/file.txt b/file.txt\n+actual\n", stderr=""),
        ]

        record = SummaryEvaluationAnalysis(
            redis=redis,
            judge=judge,
            config=SummaryJudgeConfig(ollama_model="llama-test"),
        ).analyse(evaluation_input())

    assert record.resolution_key == "resolution:conflict:owner/repo.git-actualsha:20260602T120000.000000Z"
    assert record.proposed_commit_sha == "proposed-sha"
    assert record.actual_resolution_sha == "actualsha"
    assert record.info_conflict_key == info_key
    assert record.judge_model == "llama-test"
    assert record.conflicted_tree_oid == "conflicted-tree"
    assert record.proposed_to_actual_resolution_patch == "diff --git a/file.txt b/file.txt\n+bad\n-required\n"
    assert record.conflicted_to_proposed_resolution_patch == "diff --git a/file.txt b/file.txt\n+proposed\n"
    assert record.conflicted_to_actual_resolution_patch == "diff --git a/file.txt b/file.txt\n+actual\n"
    assert "CONFLICT (content)" in record.original_conflicts
    assert "I inspected the conflict." in record.agent_session
    assert "Run tests | Command: pytest" in record.agent_session
    assert record.failure_summary == "The agent resolved the wrong side of file.txt after losing conflict context."
    assert record.error is None

    prompt, config = judge_calls[0]
    assert config.ollama_model == "llama-test"
    assert "Original git conflicts:" in prompt
    assert "Diff (Reference Solution -> Proposed Resolution):" in prompt
    assert "Diff (Conflicted State vs. Proposed Resolution):" in prompt
    assert "Diff (Conflicted State vs. Reference Solution):" in prompt
    assert "In Reference -> Proposed only" in prompt
    assert "Agent's internal thoughts/chat logs:" in prompt
    assert "50 words or less" in prompt
    assert [call.args for call in summary_capture_git.call_args_list] == [
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "-p",
            "actualsha",
            "HEAD",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "show",
            "--no-patch",
            "--format=%P",
            "actualsha",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "merge-tree",
            "-z",
            "left-parent",
            "right-parent",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "-p",
            "conflicted-tree",
            "HEAD",
        ),
        (
            "-C",
            "/playgrounds/owner/repo.git-20260602T120000.000000Z-actualsha",
            "diff-tree",
            "-p",
            "conflicted-tree",
            "actualsha",
        )
    ]


def test_summary_analysis_logs_error_when_info_core_is_missing(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.summary_analysis.logger.error") as log_error,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")

        record = SummaryEvaluationAnalysis(
            redis=FakeRedis(),
            judge=lambda prompt, config: "unused",
            config=SummaryJudgeConfig(ollama_model="llama-test"),
        ).analyse(evaluation_input())

    assert record.error == "No corresponding info:core analysis data at info:conflict:core:owner/repo.git:actualsha"
    log_error.assert_called_once_with(
        "No corresponding info:core analysis data at {}",
        "info:conflict:core:owner/repo.git:actualsha",
    )


def test_summary_judge_config_reads_top_level_config_keys(monkeypatch):
    monkeypatch.delenv("EVALUATION_SUMMARY_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("EVALUATION_SUMMARY_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("EVALUATION_SUMMARY_OLLAMA_TEMPERATURE", raising=False)

    config = summary_judge_config(
        {
            "evaluation_summary_ollama_model": "qwen-test",
            "evaluation_summary_ollama_base_url": "http://ollama:11434",
            "evaluation_summary_ollama_temperature": "0.2",
        }
    )

    assert config.ollama_model == "qwen-test"
    assert config.ollama_base_url == "http://ollama:11434"
    assert config.ollama_temperature == 0.2


def test_summary_analysis_records_missing_model_config(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    monkeypatch.delenv("EVALUATION_SUMMARY_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("EVALUATION_SUMMARY_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("EVALUATION_SUMMARY_OLLAMA_TEMPERATURE", raising=False)
    info_key = "info:conflict:core:owner/repo.git:actualsha"
    redis = FakeRedis({info_key: {"merge_result": {"logical_conflicts": []}}})

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.summary_analysis.capture_git") as summary_capture_git,
        patch("evaluation.analysis.summary_analysis.load_config", return_value={}),
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        summary_capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="diff\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="left-parent right-parent\n", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="conflicted-tree\0metadata", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="conflicted to proposed diff\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="conflicted to actual diff\n", stderr=""),
        ]

        record = SummaryEvaluationAnalysis(
            redis=redis,
            judge=lambda prompt, config: "unused",
        ).analyse(evaluation_input())

    assert record.error == (
        "Set evaluation_summary_ollama_model in config.yaml or export EVALUATION_SUMMARY_OLLAMA_MODEL"
    )
    assert record.prompt is not None
    assert record.failure_summary is None


def test_summary_analysis_logs_judge_exception(monkeypatch):
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    info_key = "info:conflict:core:owner/repo.git:actualsha"
    redis = FakeRedis({info_key: {"merge_result": {"logical_conflicts": []}}})

    def failing_judge(prompt, config):
        raise RuntimeError("Ollama chat completion failed for model 'missing': 404 model not found")

    with (
        patch("evaluation.analysis.common.capture_git") as head_capture_git,
        patch("evaluation.analysis.summary_analysis.capture_git") as summary_capture_git,
        patch("evaluation.analysis.summary_analysis.logger") as logger,
    ):
        head_capture_git.return_value = CompletedProcess(args=[], returncode=0, stdout="proposed-sha\n", stderr="")
        summary_capture_git.side_effect = [
            CompletedProcess(args=[], returncode=0, stdout="diff\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="left-parent right-parent\n", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="conflicted-tree\0metadata", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="conflicted to proposed diff\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="conflicted to actual diff\n", stderr=""),
        ]

        record = SummaryEvaluationAnalysis(
            redis=redis,
            judge=failing_judge,
            config=SummaryJudgeConfig(ollama_model="missing", ollama_base_url="http://ollama:11434"),
        ).analyse(evaluation_input())

    assert record.failure_summary is None
    assert record.error == "Ollama chat completion failed for model 'missing': 404 model not found"
    logger.info.assert_called_once()
    logger.opt.assert_called_once()
    logger.opt.return_value.error.assert_called_once()


def test_invoke_ollama_judge_rejects_empty_response(monkeypatch):
    class EmptyResponse:
        content = ""

    class FakeChatOllama:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke(self, prompt):
            return EmptyResponse()

    import types
    import sys

    fake_module = types.SimpleNamespace(ChatOllama=FakeChatOllama)
    monkeypatch.setitem(sys.modules, "langchain_ollama", fake_module)

    from evaluation.analysis.summary_analysis import invoke_ollama_judge

    try:
        invoke_ollama_judge("prompt", SummaryJudgeConfig(ollama_model="llama-test"))
    except RuntimeError as error:
        assert str(error) == "Ollama chat completion returned an empty response for model 'llama-test'"
    else:
        raise AssertionError("Expected empty response error")
