from abc import ABC, abstractmethod
from pydantic import BaseModel

class AnalysisInput(BaseModel):
    git_dir: str
    git_repo_name: str
    merge_commit_oid: str

class Analysis(ABC):
    def __init__(self, analysis_name: str):
        self._analysis_name = analysis_name

    def get_analysis_name(self) -> str:
        return self._analysis_name

    def get_redis_result_prefix(self) -> str:
        return "info:conflict:" + self._analysis_name
    
    @abstractmethod
    def analyse(self, analysisInput: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        pass