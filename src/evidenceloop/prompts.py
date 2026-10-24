PROMPT_V2 = """
You are assisting with Python regression testing.

Inputs:
1. Changed source code.
2. Relevant existing tests.
3. Public behavioral requirements, if available.

Generate one complete, focused pytest test function that exercises behavior affected by this change.

Requirements:
- Do not modify production code.
- Do not invent APIs absent from the source.
- Avoid assertions based solely on implementation details.
- Return only valid Python source. Do not use Markdown fences or surrounding explanation.
- Include every line of the test; do not stop mid-statement or leave strings, brackets, or blocks unclosed.
- Prefer a short test with minimal setup and no unnecessary imports.
- If evidence is insufficient, make the best-supported test without adding explanatory prose.
""".strip()


def build_prompt(changed_files: list[str], source_context: str, related_tests: str, bug_summary: str | None = None) -> str:
    context = f"Changed files:\n- {chr(10).join(changed_files)}\n\n"
    context += f"Relevant source context:\n{source_context}\n\n"
    context += f"Relevant existing tests:\n{related_tests}\n\n"
    if bug_summary:
        context += f"Bug summary:\n{bug_summary}\n\n"
    return PROMPT_V2 + "\n\n" + context
