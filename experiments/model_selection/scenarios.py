"""PR time scenarios: measured single-slot generator and the 20 % margin rule (D653, D655)."""

from model_selection.budget import PR_BUDGET_MIN, Estimate, Lane, PrInputs, pr_estimate

# Measured 2026-11-03 on the tier-2 dev stack (D653): the generator prompt is about 1 650 tokens
# (1 404 to 2 226 in the load log), a query embeds in 0.19 s, and the rerank lane is an assumption
# (0.18 s measured for two short passages, 0.5 s assumed for the real top-n).
MEASURED_PROMPT_TOKENS = 1650
MEASURED_EMBED_S = 0.19
ASSUMED_RERANK_S = 0.5
MARGIN_FRACTION = 0.20  # a PR run needs 20 % headroom (D655): anything above 72 min does not fit
PR_LIMIT_MIN = PR_BUDGET_MIN * (1 - MARGIN_FRACTION)


def scenarios(
    out_caps: tuple[int, ...] = (150, 200, 256, 512),
) -> list[tuple[int, Estimate, Estimate]]:
    """PR estimates (full core, 150-case subset) per generator output cap, single-slot generator.

    ``qwen35`` serves one sequence (Ollama: "model architecture does not currently support
    parallel requests"), so the generator lane has one slot whatever ``OLLAMA_NUM_PARALLEL`` says.
    """
    judge = Lane(900, 3000, 150, prefill_tps=1625.0, decode_tps=25.6, slots=4)
    rows = []
    for out in out_caps:
        gen = Lane(350, MEASURED_PROMPT_TOKENS, out, prefill_tps=966.0, decode_tps=19.4, slots=1)
        inp = PrInputs(50, 300, 440, gen, judge, MEASURED_EMBED_S, ASSUMED_RERANK_S)
        rows.append((out, pr_estimate(inp), pr_estimate(inp, judged_subset=True)))
    return rows


def margin_pct(minutes: float, budget_min: float = PR_BUDGET_MIN) -> float:
    """Headroom against ``budget_min`` in percent of the budget (negative = over).

    >>> round(margin_pct(62.1), 1)
    31.0
    """
    return (budget_min - minutes) / budget_min * 100


def scenarios_report() -> str:
    """One line per output cap: full-core and subset PR minutes, margins and the verdict (D655)."""
    lines = []
    for out, full, sub in scenarios():
        verdict = (
            "subset fits" if sub.total_min <= PR_LIMIT_MIN else "does not fit even with the subset"
        )
        full_ok = "fits" if full.total_min <= PR_LIMIT_MIN else "does not fit"
        full_margin, sub_margin = margin_pct(full.total_min), margin_pct(sub.total_min)
        lines.append(
            f"max_tokens {out}: PR full {full.total_min:.1f} min ({full_margin:.1f} % margin,"
            f" {full_ok}), subset {sub.total_min:.1f} min ({sub_margin:.1f} % margin) -> {verdict}"
        )
    return "\n".join(lines)
