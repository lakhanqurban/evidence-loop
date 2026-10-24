from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import json
import subprocess
from typing import Any

from dotenv import load_dotenv

for env_path in (
    Path(__file__).resolve().parents[2] / ".env",
    Path(__file__).resolve().parents[2] / ".env.example",
):
    if env_path.exists():
        load_dotenv(env_path, override=False)


class LLMClient:
    """Provider-agnostic LLM wrapper that surfaces missing credentials and provider errors."""

    def __init__(
        self,
        model: str | None = None,
        provider: str | None = None,
        max_output_tokens: int = 2500,
        max_attempts: int = 2,
    ) -> None:
        self.provider = (provider or os.getenv("EVIDENCELOOP_LLM_PROVIDER") or "gemini").lower()
        provider_model_env = {
            "gemini": "GEMINI_MODEL",
            "openai": "OPENAI_MODEL",
            "opencode": "OPENCODE_MODEL",
        }.get(self.provider)
        self.model = model or (os.getenv(provider_model_env) if provider_model_env else None)
        if not self.model:
            self.model = {
                "gemini": "gemini-3.8-flash",
                "openai": "gpt-4o-mini",
                "opencode": "glm-5.3-flash-free",
            }.get(self.provider, "gemini-3.8-flash")
        if max_output_tokens < 1 or max_attempts < 1:
            raise ValueError("LLM token and attempt limits must be positive.")
        self.max_output_tokens = max_output_tokens
        self.max_attempts = max_attempts
        self.last_usage: dict[str, int] | None = None
        self.total_usage: dict[str, int] = {}
        self.attempt_diagnostics: list[dict[str, object]] = []
        self.last_response_diagnostics: dict[str, object] = {}
        self.response_diagnostics: list[dict[str, object]] = []

    def generate_tests(self, prompt: str, **kwargs: object) -> list[str]:
        self.last_usage = None
        self.last_response_diagnostics = {}
        if self.provider == "gemini":
            if not os.getenv("GEMINI_API_KEY"):
                raise RuntimeError("GEMINI_API_KEY is required for live test generation.")
            return self._call_with_retries("Gemini", self._call_gemini, prompt, kwargs)

        if self.provider == "openai":
            if not os.getenv("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is required for live test generation.")
            return self._call_with_retries("OpenAI", self._call_openai, prompt, kwargs)

        if self.provider == "opencode":
            if not os.getenv("OPENCODE_API_KEY"):
                raise RuntimeError("OPENCODE_API_KEY is required for OpenCode test generation.")
            return self._call_with_retries("OpenCode", self._call_opencode, prompt, kwargs)

        raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _call_with_retries(self, provider: str, call: Any, prompt: str, kwargs: dict[str, object]) -> list[str]:
        last_error: Exception | None = None
        self.attempt_diagnostics = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = call(
                    prompt,
                    max_output_tokens=self.max_output_tokens,
                    **kwargs,
                )
                self.attempt_diagnostics.append({
                    "attempt": attempt,
                    "status": "success",
                    "usage": self.last_usage,
                })
                return result
            except Exception as exc:
                last_error = exc
                diagnostic = _exception_diagnostic(attempt, exc)
                self.attempt_diagnostics.append(diagnostic)
                if not diagnostic.get("retryable", False):
                    break
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 8))
        last_diagnostic = self.attempt_diagnostics[-1] if self.attempt_diagnostics else {}
        detail = str(last_diagnostic.get("message") or "no provider error detail available")
        raise RuntimeError(
            f"{provider} test generation failed after {self.max_attempts} attempt(s); "
            f"last error {last_diagnostic.get('type', 'unknown')}"
            f"{(' HTTP ' + str(last_diagnostic['status_code'])) if last_diagnostic.get('status_code') else ''}: {detail}"
        ) from last_error

    def _call_gemini(self, prompt: str, **kwargs: object) -> list[str]:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-genai is required for Gemini support.") from exc

        from google.genai import types

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=kwargs.get("max_output_tokens", self.max_output_tokens),
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        candidates = getattr(response, "candidates", None) or []
        candidate = candidates[0] if candidates else None
        finish_reason = getattr(candidate, "finish_reason", None)
        prompt_feedback = getattr(response, "prompt_feedback", None)
        diagnostics: dict[str, object] = {
            "provider": "gemini",
            "model": self.model,
            "candidate_count": len(candidates),
            "thinking_level": "low",
        }
        if finish_reason is not None:
            diagnostics["finish_reason"] = getattr(finish_reason, "name", str(finish_reason))
        finish_message = getattr(candidate, "finish_message", None)
        if finish_message:
            diagnostics["finish_message"] = str(finish_message)[:500]
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason is not None:
            diagnostics["prompt_block_reason"] = getattr(block_reason, "name", str(block_reason))
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.last_usage = {
                name: value
                for name in (
                    "prompt_token_count",
                    "candidates_token_count",
                    "thoughts_token_count",
                    "thoughts_token_count",
                    "total_token_count",
                )
                if (value := getattr(usage, name, None)) is not None
            }
            self._accumulate_usage(self.last_usage)

        text = getattr(response, "text", None)
        if not text and candidate is not None:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            text = "".join(str(getattr(part, "text", "")) for part in parts)
        diagnostics["response_chars"] = len(text or "")
        self.last_response_diagnostics = diagnostics
        self.response_diagnostics.append(diagnostics)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")
        return [text]

    def _call_openai(self, prompt: str, **kwargs: object) -> list[str]:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openai is required for OpenAI support.") from exc

        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.responses.create(
            model=self.model,
            input=prompt,
            temperature=0.2,
            max_output_tokens=kwargs.get("max_output_tokens", self.max_output_tokens),
        )
        text = response.output_text
        diagnostics = {"provider": "openai", "model": self.model, "response_chars": len(text or "")}
        status = getattr(response, "status", None)
        if status is not None:
            diagnostics["status"] = str(status)
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete_details, "reason", None)
        if incomplete_reason:
            diagnostics["incomplete_reason"] = str(incomplete_reason)
        self.last_response_diagnostics = diagnostics
        self.response_diagnostics.append(diagnostics)
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage = {
                name: value
                for name in ("input_tokens", "output_tokens", "total_tokens")
                if (value := getattr(usage, name, None)) is not None
            }
            self._accumulate_usage(self.last_usage)
        return [text]

    def _call_opencode(self, prompt: str, **kwargs: object) -> list[str]:
        cli_path = shutil.which("opencode.exe")
        if cli_path is None:
            npm_shim = shutil.which("opencode.cmd")
            if npm_shim:
                cli_path = str(
                    Path(npm_shim).parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
                )
        if cli_path is None:
            appdata = os.getenv("APPDATA")
            if appdata:
                candidate = Path(appdata) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
                if candidate.is_file():
                    cli_path = str(candidate)
        if cli_path is None:
            raise RuntimeError("OpenCode CLI is required for this OpenCode model.")
        command = [
            cli_path, "run", "--model", f"opencode/{self.model}",
            "--variant", "low", "--format", "json",
        ]
        with tempfile.TemporaryDirectory(prefix="evidenceloop-llm-cwd-") as cli_cwd:
            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
                cwd=cli_cwd,
            )

        text_parts: list[str] = []
        token_usage: dict[str, int] = {}
        cli_error: str | None = None
        cli_status_code: int | None = None
        for line in completed.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "text":
                part = event.get("part") or {}
                if isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            elif event.get("type") == "step_finish":
                tokens = (event.get("part") or {}).get("tokens") or {}
                for name in ("input", "output", "reasoning"):
                    if isinstance(tokens.get(name), (int, float)):
                        token_usage[f"{name}_tokens"] = int(tokens[name])
            elif event.get("type") == "error":
                error = event.get("error") or "OpenCode CLI returned an error."
                cli_error = str(error)
                if isinstance(error, dict):
                    error_data = error.get("data") or {}
                    status = error_data.get("statusCode") if isinstance(error_data, dict) else None
                    if isinstance(status, int):
                        cli_status_code = status

        if completed.returncode != 0 or cli_error:
            detail = _redact_diagnostic(cli_error or completed.stderr or "OpenCode CLI failed.")[:1000]
            raise ProviderCLIError(completed.returncode, detail, cli_status_code)
        text = "".join(text_parts)
        if not text.strip():
            raise RuntimeError("OpenCode CLI returned no text completion.")

        self.last_usage = token_usage
        if self.last_usage:
            self._accumulate_usage(self.last_usage)
        diagnostics = {
            "provider": "opencode",
            "model": self.model,
            "response_chars": len(text),
            "transport": "opencode_cli",
        }
        self.last_response_diagnostics = diagnostics
        self.response_diagnostics.append(diagnostics)
        return [text]

    def _accumulate_usage(self, usage: dict[str, int]) -> None:
        for name, value in usage.items():
            self.total_usage[name] = self.total_usage.get(name, 0) + value


def _exception_diagnostic(attempt: int, exc: Exception) -> dict[str, object]:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    message = str(exc)
    if response is not None:
        body = getattr(response, "text", None)
        if body:
            message = f"{message}; response={body}"
    message = _redact_diagnostic(message)[:2000]
    diagnostic: dict[str, object] = {
        "attempt": attempt,
        "status": "error",
        "type": type(exc).__name__,
        "message": message,
        "retryable": _is_retryable(status_code, message, exc),
    }
    if status_code is not None:
        diagnostic["status_code"] = status_code
    return diagnostic


class ProviderCLIError(RuntimeError):
    def __init__(self, exit_code: int, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.status_code = status_code


def _is_retryable(status_code: object, message: str, exc: Exception) -> bool:
    text = message.lower()
    if any(marker in text for marker in (
        "requestsperday",
        "daily quota",
        "you exceeded your current quota",
        "quota exceeded for metric",
    )):
        return False
    try:
        code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        code = None
    if code in {408, 429, 500, 502, 503, 504}:
        return True
    if code is not None:
        return False
    return isinstance(exc, (TimeoutError, ConnectionError))


def _redact_diagnostic(value: str) -> str:
    redacted = value
    for secret_name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "OPENCODE_API_KEY"):
        secret = os.getenv(secret_name)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_API_KEY]", redacted)

def build_llm_client(model: str | None = None, provider: str | None = None) -> LLMClient:
    return LLMClient(model=model, provider=provider)
