# EvidenceLoop

**EvidenceLoop generates regression tests from repository changes and evaluates them against buggy and fixed revisions.** It combines change analysis, evidence retrieval, LLM-based test generation, isolated execution, oracle scoring, and structured reporting in one reproducible workflow.

The evaluation uses a frozen set of BugsInPy tasks and compares generated tests with existing tests. Each candidate is scored against the same behavioral oracle: it must fail on the buggy revision and pass on the fixed revision.

<p align="center">
  <a href="https://www.python.org/"><img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="https://opencode.ai/"><img alt="OpenCode" src="https://img.shields.io/badge/LLM-OpenCode%20CLI-F97316?logoColor=white"></a>
  <a href="https://opencode.ai/zen/"><img alt="GLM 5.3" src="https://img.shields.io/badge/Model-GLM%205.3%20Flash-16A34A"></a>
  <a href="https://docs.pytest.org/"><img alt="pytest" src="https://img.shields.io/badge/Tests-pytest-0A9EDC?logo=pytest&logoColor=white"></a>
  <a href="https://www.docker.com/"><img alt="Docker" src="https://img.shields.io/badge/Execution-Docker-2496ED?logo=docker&logoColor=white"></a>
  <a href="https://github.com/soarsmu/BugsInPy"><img alt="BugsInPy" src="https://img.shields.io/badge/Benchmark-BugsInPy-222222"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-3B82F6"></a>
</p>

## 🔎 Research objective

EvidenceLoop investigates how repository evidence and execution feedback affect the generation and prioritization of regression tests. For each benchmark task, the model receives the buggy repository state, changed source, relevant tests, direct callers, and an optional public bug summary. The fixed revision is withheld from generation and used only by the evaluator.

The primary outcome is an **oracle match**: a candidate test fails on the buggy revision and passes on the fixed revision. Collection errors, infrastructure failures, timeouts, and unrelated execution errors are recorded separately and do not constitute detections.

## ⚙️ Workflow

1. Check out the buggy revision and identify changed files.
2. Collect changed-source evidence, related tests, and direct callers.
3. Generate focused pytest code using the configured model (prompt v2).
4. Extract code blocks, validate Python syntax, and make one repair request when output is invalid or truncated.
5. Run the candidate against buggy and fixed revisions in the task's Docker executor (network-isolated, read-only repository copy, resource-limited).
6. Score the result using the behavioral oracle and retain the code, evidence, model diagnostics, token usage, and execution results in JSON.
7. Validate every emitted report against the JSON schemas (`scripts/validate_artifacts.py`).

The comparison runner implements five conditions:

| Condition          | Method                                                           |
| ------------------ | ---------------------------------------------------------------- |
| `existing_tests` | Run the task's baseline test on buggy and fixed revisions.       |
| `one_shot`       | Generate from changed source and the bug summary.                |
| `retrieval`      | Add related tests and collected repository evidence.             |
| `feedback`       | Refine a candidate once using buggy-revision execution feedback. |
| `full`           | Run the EvidenceLoop workflow and evaluate candidate ranking.    |

## 📊 Evaluation results

### Frozen A–E comparison (protocol `evidenceloop-pilot-v1`)

Completed matrix: 3 tasks × 10 repetitions × 5 conditions = **150/150 artifacts** (two transient generation failures counted as non-detections), provider `opencode` / `glm-5.3-flash-free`, seeded bootstrap (10,000 resamples, seed 42).

| Condition         | Detection rate | Detections | Black 021 | FastAPI 012 | PySnooper 001 |
| ----------------- | -------------: | ---------: | --------: | ----------: | ------------: |
| Existing tests    |            33% |    10 / 30 |     10/10 |        0/10 |          0/10 |
| One-shot          |            53% |    16 / 30 |      9/10 |        5/10 |          2/10 |
| Retrieval         |            57% |    17 / 30 |      8/10 |        7/10 |          2/10 |
| Feedback          |            80% |    24 / 30 |      8/10 |       10/10 |          6/10 |
| Full EvidenceLoop |  **83%** |    25 / 30 |      9/10 |       10/10 |          6/10 |

Paired detection-rate difference vs one-shot (mean, 95% CI over 30 paired runs):

| Comparison            |            mean | 95% CI           |
| --------------------- | --------------: | ---------------- |
| Existing − one-shot  |          −0.20 | [−0.37, −0.03] |
| Retrieval − one-shot |           +0.03 | [−0.17, +0.23]  |
| Feedback − one-shot  | **+0.27** | [+0.03, +0.50]   |
| Full − one-shot      | **+0.30** | [+0.10, +0.50]   |

The matrix doubles as a nested component ablation: each lift isolates one component (LLM one-shot over the baseline, retrieval, the execution-feedback loop, and ranking/selection). With the third task, both the feedback-loop and full-pipeline lifts are nonzero at the 95% level; retrieval alone is within noise of one-shot. PySnooper 001 is the hardest configuration — the existing suite detects nothing and retrieval has little to exploit — and it is there that the execution-feedback loop triples the rate (0.20 → 0.60). Rates are descriptive (3 tasks, n=30 per condition), generation failures count as non-detections (intention to treat), and per-task tables are unweighted means. Full details and validity notes live in the [run report](experiments/results/glm-5.3-flash-free-20261018-v3/REPORT.md).

### Benchmark scope

Three BugsInPy defects are measured end-to-end in the frozen matrix: [Black bug 21](experiments/results/glm-5.3-flash-free-20261018-v3/bugsinpy-black-021), [FastAPI bug 12](experiments/results/glm-5.3-flash-free-20261018-v3/bugsinpy-fastapi-012), and [PySnooper bug 1](experiments/results/glm-5.3-flash-free-20261018-v3/bugsinpy-pysnooper-001) — the hardest configuration, where the pre-existing suite cannot discriminate the bug and the existing-tests arm scores 0 by construction. Earlier protocol runs (prompt v1, provider diagnostics, a partial quota-interrupted matrix) are retained under `experiments/results/` for provenance; pre-freeze runs are excluded from the current schema gate.

### Benchmark repositories

The benchmark repositories are not included. Download them into `.benchmark_repos/`:

- Black — [https://github.com/psf/black](https://github.com/psf/black)
- FastAPI — [https://github.com/tiangolo/fastapi](https://github.com/tiangolo/fastapi)
- PySnooper — [https://github.com/cool-RR/PySnooper](https://github.com/cool-RR/PySnooper)

### Result artifacts

- [Frozen comparison summary](experiments/results/glm-5.3-flash-free-20261018-v3/comparison-summary.json)
- [Frozen comparison analysis](experiments/results/glm-5.3-flash-free-20261018-v3/analysis.json)
- [Run report (ablation reading + validity notes)](experiments/results/glm-5.3-flash-free-20261018-v3/REPORT.md)
- [Benchmark manifest](benchmarks/manifest.csv)

## 🚀 Requirements and installation

- Python 3.11 or newer for the EvidenceLoop package.
- Git and Docker Desktop / Docker Engine with Linux containers enabled.
- A supported LLM provider and API credentials for generation commands.
- Local checkouts for the benchmark repositories referenced by the manifest.

The task-specific executor images use Python 3.8 to match the benchmark repositories. The general runner image uses Python 3.11.

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the package and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
evidenceloop --help
```

Build the Docker images from the repository root:

```bash
docker build -f docker/Dockerfile -t evidenceloop-runner:local .
docker build -f docker/black-bug21.Dockerfile -t evidenceloop-black-bug21:local .
docker build -f docker/fastapi-bug12.Dockerfile -t evidenceloop-fastapi-bug12:local .
docker build -f docker/pysnooper-bug01.Dockerfile -t evidenceloop-pysnooper-bug01:local .
```

Each benchmark task also needs a local interpreter for baseline reproduction; the `repo_path`, `setup_command`, and `baseline_test_command` columns in [benchmarks/manifest.csv](benchmarks/manifest.csv) reference a per-task environment (e.g. `.benchmark_repos/pysnooper-venv`).

## 🔐 Configure model access

Generation runs through one of three provider adapters (`src/evidenceloop/llm.py`); the default for the frozen run was the **OpenCode CLI** with `glm-5.3-flash-free`, configured in `experiments/configs/default.yaml`.

Copy `.env.example` to `.env` and provide a key locally:

```dotenv
EVIDENCELOOP_LLM_PROVIDER=opencode
OPENCODE_API_KEY=your_key_here
OPENCODE_MODEL=glm-5.3-flash-free
```

- **OpenCode (default):** prompts are piped to the `opencode` CLI over stdin in a disposable working directory; 5-minute per-call timeout with error-aware retries.
- **Gemini:** requires the `google-genai` SDK and `GEMINI_API_KEY` (low thinking setting on `gemini-3.8-flash`).
- **OpenAI:** requires the `openai` SDK and `OPENAI_API_KEY` / `OPENAI_MODEL`.

Never commit API keys. Diagnostics are redacted automatically before being written to artifacts.

## 💻 CLI usage

Inspect changes between two revisions:

```bash
evidenceloop analyze --repo /path/to/project --base BASE_REV --target TARGET_REV
```

Generate candidate tests and save the JSON record:

```bash
evidenceloop generate /path/to/project BASE_REV TARGET_REV \
  --bug-summary "Describe the public behavior that should be covered" \
  --output generated-tests.json
```

List benchmark tasks or reproduce a task's existing test:

```bash
evidenceloop benchmark --manifest benchmarks/manifest.csv
evidenceloop benchmark --manifest benchmarks/manifest.csv \
  --task-id bugsinpy-black-021 --reproduce \
  --output benchmark-reproduction.json
```

Run a single generation and scoring experiment:

```bash
evidenceloop experiment bugsinpy-fastapi-012 \
  --manifest benchmarks/manifest.csv \
  --output experiments/results/fastapi-012.json \
  --bug-summary "A non-Bearer scheme is absent when authentication is optional."
```

## 🧪 Run the comparison matrix

The frozen comparison command runs selected tasks for 10 repetitions:

```bash
python experiments/run_comparison.py \
  --manifest benchmarks/manifest.csv \
  --output-dir experiments/results/comparison-run \
  --task-id bugsinpy-black-021 \
  --task-id bugsinpy-fastapi-012 \
  --task-id bugsinpy-pysnooper-001 \
  --repetitions 10 \
  --max-total-cost-usd 24.00 \
  --bug-summary "bugsinpy-black-021=Writing Unicode source to a temporary file should work regardless of the process default encoding." \
  --bug-summary "bugsinpy-fastapi-012=A non-Bearer scheme is absent when authentication is optional." \
  --bug-summary "bugsinpy-pysnooper-001=Tracing code with non-ASCII source files or emitting trace output to a file must use UTF-8 encoding instead of assuming ASCII."
```

The runner calculates its preflight estimate from repetitions, tasks, four LLM conditions, and the configured per-condition allowance, without subtracting artifacts it will reuse:

```text
10 repetitions × 3 tasks × 4 LLM conditions × $0.20 = $24.00
```

`--max-total-cost-usd` is a required preflight value, not a provider-side spending cap; actual spend scales with newly generated artifacts (resuming with `--task-id` filters skips stored ones). Syntax repair and provider retries may add calls beyond the estimate. The runner resumes from saved artifacts, so interrupted runs can be completed by deleting failed artifacts and rerunning with the same output directory.

Analyze the resulting summary:

```bash
python experiments/analyze_comparison.py \
  --input experiments/results/comparison-run/comparison-summary.json \
  --output experiments/results/comparison-run/analysis.json
```

Validate all emitted reports against the JSON schemas (696 JSON reports currently: 595 valid post-freeze artifacts plus 101 excluded pre-freeze legacy files):

```bash
python scripts/validate_artifacts.py
# optionally exclude legacy pre-freeze runs:
python scripts/validate_artifacts.py --exclude frozen-comparison-v1
```

Baseline benchmark reproduction and analysis do not call an LLM:

```bash
python experiments/run_experiment.py \
  --manifest benchmarks/manifest.csv \
  --output experiments/results/benchmark-reproduction.json

python experiments/analyze_results.py \
  --input experiments/results/benchmark-reproduction.json \
  --output experiments/results/benchmark-summary.json
```

## 🛡️ Execution and data handling

- Generated tests run in Docker, never directly on the host.
- The executor disables container networking, uses a read-only sanitized repository copy, drops Linux capabilities, and applies CPU, memory, process, and time limits.
- Task executor images reproduce the locale conditions their bug depends on (e.g. C locale with PEP 538 coercion disabled for the Black and PySnooper encoding defects).
- The OpenCode CLI adapter runs in a disposable temporary working directory so provider-side file writes never touch the host repository or benchmark clones.
- Benchmark reproduction commands from the manifest run on the host; use a manifest you trust.
- Repository source, related tests, bug summaries, and execution feedback are sent to the configured model provider when generation is enabled.
- Keep API credentials in environment variables or a local `.env` file.

## 📚 Evaluation scope and reproducibility

The frozen study evaluates BugsInPy defects Black 21, FastAPI 12, and PySnooper 1. Reported findings characterize these tasks (rates are unweighted task means); broader cross-project evaluation is planned.

The manifest's repository paths are local to the development environment. Before running on another machine, update each `repo_path` to the corresponding local checkout. Task image definitions and pinned requirements are in `docker/` and `benchmarks/requirements/`; oracle candidates ship in `benchmarks/candidate_tests/`.

`experiments/configs/default.yaml` pins the current protocol settings (model `glm-5.3-flash-free`, prompt v2, temperature 0.2, 2 attempts, 2,500 output tokens, seeded ranking). `experiments/configs/protocol-v1.yaml` describes the earlier prompt-v1 protocol; treat them as separate protocol versions when comparing results.

## 📄 License

Distributed under the [MIT License](LICENSE).
