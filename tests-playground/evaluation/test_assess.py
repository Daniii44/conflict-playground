from evaluation.analysis.common import evaluation_record_key


def test_core_evaluation_record_key_uses_resolution_postfix():
    key = evaluation_record_key(
        "core",
        "resolution:conflict:owner/repo.git-actualsha:20260602T123456.000789Z",
    )

    assert key == "evaluation:merge:core:owner/repo.git-actualsha:20260602T123456.000789Z"
