import importlib.util
from pathlib import Path
from unittest.mock import patch

import playground

from common.evaluation_models import ScheschResolutionResult


SCHESCH_TEST_PATH = Path(playground.__path__[0]) / "schesch" / "test.py"
module_spec = importlib.util.spec_from_file_location("playground_schesch_test", SCHESCH_TEST_PATH)
playground_schesch_test = importlib.util.module_from_spec(module_spec)
assert module_spec.loader is not None
module_spec.loader.exec_module(playground_schesch_test)


class FakeJson:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self, values=None):
        self.json_api = FakeJson(values)

    def json(self):
        return self.json_api


def test_expected_java_home_for_playground_uses_schesch_info_record():
    with patch.dict(playground_schesch_test.os.environ, {"PLAYGROUNDS": "/playgrounds"}):
        redis = FakeRedis(
            {
                "info:conflict:schesch:owner/repo.git:merge-sha": {
                    "human": {"passed": True, "successful_java_home": "/java-17"},
                    "parents": [
                        {"passed": True, "successful_java_home": "/java-17"},
                        {"passed": True, "successful_java_home": "/java-17"},
                    ],
                }
            }
        )

        assert playground_schesch_test.expected_java_home_for_playground(
            redis,
            Path("/playgrounds/owner/repo.git-merge-sha"),
        ) == ("owner/repo.git", "merge-sha", "/java-17")


def test_playground_identifier_preserves_owner_directory():
    with patch.dict(playground_schesch_test.os.environ, {"PLAYGROUNDS": "/playgrounds"}):
        assert playground_schesch_test.playground_identifier(
            Path("/playgrounds/accla/d4m_api_java.git-3d17b93fcaca70344f20d3adcd3bcb71b71ab097")
        ) == "accla/d4m_api_java.git-3d17b93fcaca70344f20d3adcd3bcb71b71ab097"


def test_playground_identifier_rejects_paths_outside_playgrounds():
    with patch.dict(playground_schesch_test.os.environ, {"PLAYGROUNDS": "/playgrounds"}):
        try:
            playground_schesch_test.playground_identifier(Path("/elsewhere/owner/repo.git-merge"))
        except RuntimeError as error:
            assert "not located under PLAYGROUNDS" in str(error)
        else:
            raise AssertionError("Expected PLAYGROUNDS containment error")


def test_run_playground_schesch_test_uses_expected_java_home(monkeypatch):
    redis = FakeRedis(
        {
            "info:conflict:schesch:owner/repo.git:merge-sha": {
                "human": {"passed": True, "successful_java_home": "/java-17"},
                "parents": [
                    {"passed": True, "successful_java_home": "/java-17"},
                    {"passed": True, "successful_java_home": "/java-17"},
                ],
            }
        }
    )

    monkeypatch.setenv("JAVA17_HOME", "/java-17")
    monkeypatch.setenv("PLAYGROUNDS", "/playgrounds")
    with (
        patch.object(
            playground_schesch_test,
            "resolve_playground_root",
            return_value=Path("/playgrounds/owner/repo.git-20260602T120000.000000Z-merge-sha"),
        ),
        patch.object(
            playground_schesch_test,
            "setup_redis_connection",
            return_value=FakeRedis(
                {
                    "info:conflict:schesch:owner/repo.git:merge-sha": {
                        "human": {"passed": True, "successful_java_home": "/java-17"},
                        "parents": [
                            {"passed": True, "successful_java_home": "/java-17"},
                            {"passed": True, "successful_java_home": "/java-17"},
                        ],
                    }
                }
            ),
        ),
        patch.object(playground_schesch_test, "ScheschResolutionRunner", autospec=True) as runner_type,
    ):
        runner_type.return_value.run_tests_in_current_state.return_value = ScheschResolutionResult(
            label="playground",
            passed=True,
            successful_java_home="/java-17",
        )

        assert playground_schesch_test.run_playground_schesch_test() == 0

    runner_type.assert_called_once_with(stream_output=True)
    runner_type.return_value.run_tests_in_current_state.assert_called_once_with(
        Path("/playgrounds/owner/repo.git-20260602T120000.000000Z-merge-sha"),
        "playground",
        java_homes=["/java-17"],
    )
