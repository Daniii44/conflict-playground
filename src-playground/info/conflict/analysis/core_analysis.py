import signal
import subprocess
import sys
from pydantic import BaseModel
from common.redis_util import setup_redis_connection
from common.merge_tree import MergeResult, parse_merge_result, prune_auto_merged
from loguru import logger
from info.conflict.analysis.common import Analysis, AnalysisInput

class InfoConflict(BaseModel):
    repo: str
    merge_commit_oid: str
    parent_count: int

    merge_result: MergeResult

class CoreAnalysis(Analysis):

    def collect_parents(self, analysisInput: AnalysisInput) -> list[str]:
        show_cmd = ["git", f"--git-dir={analysisInput.git_dir}", "show", "--no-patch", "--format=%P", analysisInput.merge_commit_oid]
        try:
            parents = subprocess.check_output(show_cmd, text=True).strip().split()
        except subprocess.CalledProcessError as e:
            if e.returncode == -signal.SIGINT:
                global exiting
                exiting = True
                sys.exit(0)
            logger.error(f"Error running git show for {analysisInput.merge_commit_oid}: {e}")
            return []
        return parents

    def process_merge_tree_output(self, git_dir: str, main_oid: str, feature_oid: str) -> MergeResult | None:
        merge_tree_cmd = ["git", f"--git-dir={git_dir}", "merge-tree", "-z", main_oid, feature_oid]
        
        try:
            subprocess.check_output(merge_tree_cmd, text=True, stderr=subprocess.STDOUT)
            logger.debug(f"No conflict for merge {main_oid} and {feature_oid}")
        except subprocess.CalledProcessError as e:
            if e.returncode == -signal.SIGINT:
                global exiting
                exiting = True
                sys.exit(0)
            if b'fatal: refusing to merge unrelated histories' in e.output.encode():
                return None

            return prune_auto_merged(parse_merge_result(e.output.encode()))
    
    def analyse(self, analysisInput: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        parents = self.collect_parents(analysisInput)
        if len(parents) < 2:
            logger.error(f"Merge commit {analysisInput.merge_commit_oid} has less than 2 parents, skipping")
            return None
        elif len(parents) > 2:
            # Not supporting octopus merges for now, since git doesn't even allow to perform non trivial octopus merges directly.
            # TODO: Take a look whether there are complex octoopus merges nonetheless
            logger.info(f"Merge commit {analysisInput.merge_commit_oid} has more than 2 parents, skipping")
            return None
        
        mergeResult = self.process_merge_tree_output(analysisInput.git_dir, parents[0], parents[1])
        if mergeResult is None:
            return None
        
        return (analysisInput, InfoConflict(
            repo=analysisInput.git_repo_name,
            merge_commit_oid=analysisInput.merge_commit_oid,
            parent_count=len(parents),
            merge_result=mergeResult,
        ))