from abc import ABC, abstractmethod

from pydantic import BaseModel

from common.evaluation_models import EvaluationInput
from common.git_util import capture_git
from common.redis_util import EVALUATION_MERGE_PREFIX, RESOLUTION_CONFLICT_PREFIX


class EvaluationAnalysis(ABC):
    def __init__(self, analysis_name: str):
        self._analysis_name = analysis_name

    def get_analysis_name(self) -> str:
        return self._analysis_name

    def get_redis_result_prefix(self) -> str:
        return f"{EVALUATION_MERGE_PREFIX}{self._analysis_name}"

    @abstractmethod
    def analyse(self, evaluation_input: EvaluationInput) -> BaseModel | None:
        pass


def resolution_postfix(resolution_key: str) -> str:
    return resolution_key.removeprefix(RESOLUTION_CONFLICT_PREFIX)


def evaluation_record_key(analysis: EvaluationAnalysis | str, resolution_key: str) -> str:
    analysis_name = analysis.get_analysis_name() if isinstance(analysis, EvaluationAnalysis) else analysis
    return f"{EVALUATION_MERGE_PREFIX}{analysis_name}:{resolution_postfix(resolution_key)}"


def actual_resolution_sha_from_playground_name(playground_name: str) -> str | None:
    if "-" not in playground_name:
        return None
    return playground_name.rsplit("-", 1)[1]


def read_head_commit(playground_path: str) -> tuple[str | None, str | None]:
    head_result = capture_git("-C", playground_path, "rev-parse", "HEAD", check=False)
    if head_result.returncode == 0:
        return head_result.stdout.strip(), None

    error = head_result.stderr.strip() or head_result.stdout.strip()
    return None, f"Could not read resolved HEAD: {error}"
