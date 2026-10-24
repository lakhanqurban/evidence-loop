from evidenceloop.executor import ExecutionResult, ExecutionStatus
from evidenceloop.validator import classify_outcome, is_successful_regression


def test_classify_outcome():
    result = ExecutionResult(status=ExecutionStatus.PASS)
    assert classify_outcome(result) == ExecutionStatus.PASS


def test_regression_requires_behavioral_buggy_failure_and_fixed_pass():
    buggy = ExecutionResult(status=ExecutionStatus.ASSERTION_FAILURE)
    fixed = ExecutionResult(status=ExecutionStatus.PASS)

    assert is_successful_regression(buggy, fixed) is True


def test_regression_rejects_buggy_pass_and_environment_failures():
    fixed = ExecutionResult(status=ExecutionStatus.PASS)

    assert is_successful_regression(ExecutionResult(status=ExecutionStatus.PASS), fixed) is False
    assert is_successful_regression(ExecutionResult(status=ExecutionStatus.ENVIRONMENT_FAILURE), fixed) is False
