"""Side-by-side report of an offline A/B run (`bootcamp.py eval --variants A,B`).

Every golden question is asked once per prompt variant (phase2/app/agent/prompt_variants.py), all sessions are
scored by the same batch evaluation, and this module compares the variants: one result table each, then pass rate,
each evaluator's mean score and the mean answer length per variant, with the change of each variant against the
first one (the control). It is the offline counterpart of AgentCore's managed A/B tests, which split live Gateway
traffic between two variants and report p-values; with a handful of golden items there is no significance test, so
read a one-item difference as noise.
"""

from statistics import mean

from bootcamp_cli.evaluate import Report, Result, averages, pass_rate, short_name, spend_lines, table

LABEL_WIDTH = 22
VALUE_WIDTH = 10


def by_variant(report: Report) -> dict[str, list[Result]]:
    """The report's results grouped by variant, in the order the variants were requested."""
    return {variant: [result for result in report.results if result.variant == variant] for variant in report.variants}


def answer_words(results: list[Result]) -> float | None:
    """Mean length of the answers in words (a prompt variant often changes verbosity first)."""
    answers = [len(result.answer.split()) for result in results if result.answer]
    return mean(answers) if answers else None


def metrics(report: Report) -> list[tuple[str, dict[str, float | None]]]:
    """(metric label, variant -> value) rows: pass rate, every evaluator's mean, mean answer words."""
    groups = by_variant(report)
    rows = [("pass rate", {variant: pass_rate(results) for variant, results in groups.items()})]
    means = {variant: averages(results, report.evaluators) for variant, results in groups.items()}
    for evaluator in report.evaluators:
        rows.append((short_name(evaluator), {variant: means[variant].get(evaluator) for variant in groups}))
    rows.append(("answer words (mean)", {variant: answer_words(results) for variant, results in groups.items()}))
    return rows


def cell(value: float | None, percent: bool) -> str:
    """A formatted metric value ("-" when missing)."""
    if value is None:
        return "-"
    return f"{value:.0%}" if percent else f"{value:.2f}" if value <= 1 else f"{value:.0f}"


def delta(value: float | None, control: float | None, percent: bool) -> str:
    """Signed change of a variant against the control ("" when either is missing)."""
    if value is None or control is None:
        return ""
    change = value - control
    return f"{change * 100:+.0f} pts" if percent else f"{change:+.2f}" if abs(control) <= 1 else f"{change:+.0f}"


def comparison(report: Report) -> list[str]:
    """The metric-by-variant table, each non-control variant followed by its change against the control."""
    control, others = report.variants[0], report.variants[1:]
    header = f"{'metric':<{LABEL_WIDTH}}" + "".join(f"{variant:>{VALUE_WIDTH}}" for variant in report.variants)
    header += "".join(f"{f'{v} vs {control}':>{VALUE_WIDTH + 2}}" for v in others)
    lines = [header]
    for label, values in metrics(report):
        percent = label == "pass rate"
        row = f"{label:<{LABEL_WIDTH}}" + "".join(f"{cell(values[v], percent):>{VALUE_WIDTH}}" for v in report.variants)
        row += "".join(f"{delta(values[v], values[control], percent):>{VALUE_WIDTH + 2}}" for v in others)
        lines.append(row)
    return lines


def render(report: Report) -> list[str]:
    """Per-variant result tables, then the comparison and the run's LiteLLM spend."""
    groups = by_variant(report)
    lines = [f"A/B {' vs '.join(report.variants)}: dataset {report.dataset} v{report.version}, "
             f"batch {report.batch_id} ({report.status})"]  # fmt: skip
    for variant, results in groups.items():
        lines += ["", f"variant {variant} ({len(results)} sessions)", *table(results, report.evaluators)]
    return [*lines, "", *comparison(report), *spend_lines(report)]


def lowest_pass_rate(report: Report) -> float:
    """The weakest variant's pass rate (what `eval --min-pass` gates on in an A/B run)."""
    return min((pass_rate(results) for results in by_variant(report).values()), default=0.0)
