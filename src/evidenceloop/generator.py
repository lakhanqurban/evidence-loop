from __future__ import annotations

import ast
import re

from evidenceloop.llm import LLMClient
from evidenceloop.prompts import build_prompt


class CandidateGenerator:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def generate(
        self,
        changed_files: list[str],
        source_context: str,
        related_tests: str,
        bug_summary: str | None = None,
        run_id: str | None = None,
    ) -> list[str]:
        prompt = build_prompt(changed_files, source_context, related_tests, bug_summary)
        if run_id:
            prompt += f"\n\nExperiment repetition id: {run_id}"
        return self._generate_validated(prompt)

    def _generate_validated(self, prompt: str) -> list[str]:
        response = self.llm_client.generate_tests(prompt)
        response_diagnostics = getattr(self.llm_client, "last_response_diagnostics", {})
        truncated = response_diagnostics.get("finish_reason") == "MAX_TOKENS"
        try:
            validated = self._validate_candidates(response)
        except ValueError as exc:
            first_error = exc
            message = str(exc)
            recoverable = any(marker in message for marker in (
                "invalid Python test code",
                "does not contain a pytest test function",
            ))
            if not truncated and not recoverable:
                raise
        else:
            if not truncated:
                return validated
            first_error = ValueError(
                "Gemini stopped at MAX_TOKENS; the syntactically valid response may be incomplete."
            )
        repair_prompt = (
            "Repair or complete this generated pytest test so it is valid Python containing "
            "at least one test_ function. Preserve the intended behavior, return one "
            "focused test function as plain Python source, and do not use Markdown fences "
            "or explanation.\n\n"
            f"Generation diagnostic: {first_error}\n\n"
            f"Generated response:\n{response[0][:8000]}"
        )
        repaired = self.llm_client.generate_tests(repair_prompt)
        try:
            return self._validate_candidates(repaired)
        except ValueError as repair_error:
            raise ValueError(
                f"Initial generation was invalid or truncated and one repair attempt failed: {repair_error}"
            ) from repair_error

    def refine(
        self,
        candidate: str,
        changed_files: list[str],
        source_context: str,
        related_tests: str,
        buggy_feedback: dict[str, str],
        bug_summary: str | None = None,
    ) -> list[str]:
        prompt = build_prompt(changed_files, source_context, related_tests, bug_summary)
        feedback = "\n".join(
            f"{key}: {value[:4000]}" for key, value in buggy_feedback.items()
        )
        prompt += (
            "\n\nRefine this candidate once using only the supplied buggy-revision "
            "execution feedback. The fixed revision and its result are hidden and "
            "must not be requested or inferred. Preserve the intended behavior, "
            "repair collection/runtime issues when present, and strengthen a test "
            "that passes on the buggy revision. Return only Python pytest test code.\n\n"
            f"Candidate to refine:\n{candidate[:12000]}\n\n"
            f"Buggy execution feedback:\n{feedback}"
        )
        return self._generate_validated(prompt)

    @staticmethod
    def _validate_candidates(responses: list[str]) -> list[str]:
        candidates = []
        for response in responses:
            code = _remove_code_fence(response).strip()
            if not code:
                continue
            try:
                tree = ast.parse(code)
            except SyntaxError as exc:
                excerpt = code[:800]
                raise ValueError(
                    f"LLM returned invalid Python test code: {exc.msg} "
                    f"(line {exc.lineno}, column {exc.offset}); response excerpt: {excerpt!r}"
                ) from exc
            if not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
                for node in ast.walk(tree)
            ):
                raise ValueError(
                    "LLM response does not contain a pytest test function; "
                    f"response excerpt: {code[:800]!r}"
                )
            candidates.append(code)
        if not candidates:
            raise ValueError("LLM returned no test candidates.")
        return candidates


def _remove_code_fence(response: str) -> str:
    """Extract a fenced code block even when the model adds surrounding prose."""
    blocks = re.findall(
        r"```\s*([A-Za-z0-9_-]*)\s*\n?(.*?)```",
        response,
        flags=re.DOTALL,
    )
    if blocks:
        python_blocks = [body for language, body in blocks if language.lower() in {"", "python", "py"}]
        if python_blocks:
            return "\n\n".join(python_blocks).strip()
    # Recover the body of an opening fence if the model omitted its closing fence.
    opening_fence = re.search(r"```\s*(?:python|py)?\s*\n", response, flags=re.IGNORECASE)
    if opening_fence:
        return response[opening_fence.end():].strip()
    return response.strip()
