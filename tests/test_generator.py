import pytest

from evidenceloop.generator import CandidateGenerator


class StubLLMClient:
    def __init__(self, responses):
        self.responses = responses
        self.prompt = None

    def generate_tests(self, prompt):
        self.prompt = prompt
        return self.responses


def test_generator_strips_code_fences_and_validates_test_functions():
    client = StubLLMClient(["```python\ndef test_regression():\n    assert True\n```"])

    candidates = CandidateGenerator(client).generate(["module.py"], "source", "tests")

    assert candidates == ["def test_regression():\n    assert True"]
    assert "module.py" in client.prompt


@pytest.mark.parametrize("response", ["not Python!", "value = 1"])
def test_generator_rejects_invalid_or_non_test_output(response):
    generator = CandidateGenerator(StubLLMClient([response]))

    with pytest.raises(ValueError):
        generator.generate([], "", "")


def test_refinement_prompt_uses_buggy_feedback_without_fixed_oracle():
    client = StubLLMClient(["def test_refined():\n    assert True"])
    generator = CandidateGenerator(client)

    result = generator.refine(
        candidate="def test_original():\n    assert True",
        changed_files=["module.py"],
        source_context="buggy source only",
        related_tests="existing test context",
        buggy_feedback={"status": "PASS", "stdout": "1 passed", "stderr": ""},
        bug_summary="expected behavior",
    )

    assert result == ["def test_refined():\n    assert True"]
    assert "buggy execution feedback" in client.prompt.lower()
    assert "fixed_status" not in client.prompt.lower()
    assert "fixed output:" not in client.prompt.lower()