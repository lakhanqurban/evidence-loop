from __future__ import annotations

from evidenceloop.executor import ExecutionResult, ExecutionStatus


def classify_outcome(result: ExecutionResult) -> ExecutionStatus:
    return result.status


def is_successful_regression(buggy_result: ExecutionResult, fixed_result: ExecutionResult) -> bool:
    return (
        buggy_result.status in {ExecutionStatus.ASSERTION_FAILURE, ExecutionStatus.EXECUTION_ERROR}
        and fixed_result.status == ExecutionStatus.PASS
    )
