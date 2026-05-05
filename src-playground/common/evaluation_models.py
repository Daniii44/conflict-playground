from pydantic import BaseModel
from datetime import datetime
from common.active_playground_models import Configuration

class Evaluation(BaseModel):
    duration_seconds: float
    incomplete_merge: bool
    perfect_match: bool
    # conflicts_handled_correctly: int
    # conflicts_handled_incorrectly: int
    # missed_uncaught_conflicts: int
    # AI Review Score: Based on 'Metamorphic Testing' or 'LLM-as-a-judge'
    # patterns often found in advanced software testing.
    # ai_review_score: Optional[float] = None 

class ConflictEvaluation(BaseModel):
    """The top-level object to be stored in Redis."""
    configuration: Configuration
    result: Evaluation