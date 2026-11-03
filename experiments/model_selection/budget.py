"""Time budgets of the PR tier and the nightly from measured rates (T3.1b S5).

Three lanes run in parallel and the slowest one binds (gpu-cluster.md section 2): GPU0 (generation
and query embeddings), GPU1 (judging) and the retrieval lane on the VM CPU (rerank). Pure
arithmetic, no I/O.
"""

from dataclasses import dataclass, replace

PR_BUDGET_MIN = 90.0
NIGHT_BUDGET_MIN = 480.0
RERANK_LANE_MAX_MIN = 20.0
JUDGE_ALLOWANCE = 3072
JUDGE_RESERVE = 1024
GIB = 1024**3


@dataclass(frozen=True)
class Lane:
    """One model lane.

    ``calls`` with ``prompt_tokens``/``out_tokens`` each, measured prefill and per-slot decode
    tok/s.
    """

    calls: int
    prompt_tokens: int
    out_tokens: int
    prefill_tps: float
    decode_tps: float
    slots: int = 4


def with_slots(lane: Lane, slots: int) -> Lane:
    """Return ``lane`` with another ``OLLAMA_NUM_PARALLEL`` (the AI12-09 fallback of 2)."""
    return replace(lane, slots=slots)


def lane_minutes(lane: Lane) -> float:
    """Prefill plus decode time in minutes.

    300 x 3500 tokens at 1200 tok/s = 875 s; 300 x 200 tokens at 4 x 18 tok/s = 833.3 s; together
    28.47 min.

    >>> round(lane_minutes(Lane(300, 3500, 200, 1200, 18, 4)), 2)
    28.47
    """
    prefill = lane.calls * lane.prompt_tokens / lane.prefill_tps
    decode = lane.calls * lane.out_tokens / (lane.slots * lane.decode_tps)
    return (prefill + decode) / 60


@dataclass(frozen=True)
class Estimate:
    """Minutes per lane; ``total_min`` is the maximum, ``binding`` names the slowest lane."""

    gpu0_min: float
    gpu1_min: float
    cpu_min: float
    generations: int
    judge_calls: int
    budget_min: float = PR_BUDGET_MIN

    @property
    def total_min(self) -> float:
        """The slowest of the three lanes."""
        return max(self.gpu0_min, self.gpu1_min, self.cpu_min)

    @property
    def binding(self) -> str:
        """Name of the slowest lane: ``gpu0``, ``gpu1`` or ``cpu``."""
        lanes = {"gpu0": self.gpu0_min, "gpu1": self.gpu1_min, "cpu": self.cpu_min}
        return max(lanes, key=lambda k: lanes[k])

    @property
    def over_budget(self) -> bool:
        """True when the slowest lane exceeds the budget."""
        return self.total_min > self.budget_min


@dataclass(frozen=True)
class PrInputs:
    """Measured inputs of a PR run.

    Case counts, the two LLM lanes, embed and rerank seconds per query.
    """

    smoke: int
    core: int
    robust: int
    gen: Lane
    judge: Lane
    embed_s: float
    rerank_s: float
    rerank_concurrency: float = 1.0
    core_answerable: int = 220
    subset_answerable: int = 110
    subset_other: int = 40


def pr_estimate(inp: PrInputs, *, judged_subset: bool = False) -> Estimate:
    """PR estimate: generations on GPU0, judge calls on GPU1, every query embedded and reranked.

    ``robust_pr`` is retrieve-only: it adds embeddings and rerank queries but no generation and no
    judge call. With ``judged_subset`` the 150-case subset limits generation and judging of the
    answerable core cases.
    """
    queries = inp.smoke + inp.core + inp.robust
    gens = inp.smoke + inp.core
    judge_calls = inp.judge.calls
    if judged_subset:
        gens = inp.smoke + (inp.core - inp.core_answerable) + inp.subset_answerable
        judge_calls = round(inp.judge.calls * (inp.subset_answerable + inp.subset_other) / inp.core)
    gpu0 = lane_minutes(replace(inp.gen, calls=gens)) + queries * inp.embed_s / 60
    gpu1 = lane_minutes(replace(inp.judge, calls=judge_calls))
    cpu = queries * inp.rerank_s / inp.rerank_concurrency / 60
    return Estimate(gpu0, gpu1, cpu, gens, judge_calls)


def nightly_estimate(gen: Lane, judge: Lane) -> Estimate:
    """Nightly (600 generations in parallel to the judging).

    Cause-switches are weekly and not part of it.
    """
    return Estimate(
        lane_minutes(gen), lane_minutes(judge), 0.0, gen.calls, judge.calls, NIGHT_BUDGET_MIN
    )


@dataclass(frozen=True)
class RerankVerdict:
    """Reranker lane minutes and the D222 decision for ``robust_pr``."""

    minutes: float
    robust_pr_reranker: str


def rerank_verdict(
    queries: int, seconds_per_query: float, concurrency: float = 1.0
) -> RerankVerdict:
    """Reranker lane = queries x seconds / concurrency; above 20 min the reranker goes off (D222).

    >>> rerank_verdict(790, 2.0).robust_pr_reranker
    'off'
    """
    minutes = queries * seconds_per_query / concurrency / 60
    return RerankVerdict(minutes, "on" if minutes <= RERANK_LANE_MAX_MIN else "off")


@dataclass(frozen=True)
class Remedies:
    """Binding lane, the ordered remedy list (AI13-03) and the PR time with the 150-case subset."""

    binding: str
    steps: list[str]
    subset_min: float
    fits_with_subset: bool


def remedies(
    est: Estimate,
    budget_min: float = PR_BUDGET_MIN,
    subset_gen_share: float = 240 / 350,
    subset_judge_share: float = 0.5,
) -> Remedies:
    """Name the binding lane and the remedies in order.

    The subset scales generations and judge calls by share.
    """
    subset = max(est.gpu0_min * subset_gen_share, est.gpu1_min * subset_judge_share, est.cpu_min)
    by_lane = {
        "gpu0": [
            "pin generation.max_tokens + prompt budget (before the first baseline)",
            "150-case judged subset",
        ],
        "gpu1": ["150-case judged subset", "smaller judge or lower num_ctx"],
        "cpu": [
            "robust_pr with the reranker off (D222)",
            "rerank passages truncated to 256 tokens",
        ],
    }
    steps = by_lane[est.binding] + ["smaller judge or lower num_ctx"]
    return Remedies(est.binding, steps, subset, subset <= budget_min)


def required_judge_ctx(gen_ctx: int, allowance: int = JUDGE_ALLOWANCE) -> int:
    """Judge ``num_ctx`` = generator ``num_ctx`` + allowance + 1 024 reserve (D306).

    8192 -> 12288.
    """
    return gen_ctx + allowance + JUDGE_RESERVE


def judge_ctx_problems(
    pins: dict[str, int], gen_ctx: int, allowance: int, vram_failed: set[str]
) -> list[str]:
    """Violations of the judge context rule, each naming the judge.

    A measured allowance above 3 072 fails every judge; a pin below the required value fails
    unless the
    VRAM measurement of that judge is recorded as failed.
    """
    problems: list[str] = []
    need = required_judge_ctx(gen_ctx)
    for name, num_ctx in pins.items():
        if allowance > JUDGE_ALLOWANCE:
            problems.append(f"{name}: measured allowance {allowance} > {JUDGE_ALLOWANCE}")
        elif num_ctx < need and name not in vram_failed:
            problems.append(f"{name}: num_ctx {num_ctx} < {need} without a failed VRAM measurement")
    return problems


def total_gib(
    num_ctx: int, slots: int, kv_bytes_per_token: float, weights_gib: float, overhead_gib: float
) -> float:
    """Card use in GiB.

    KV for ``num_ctx`` x ``slots`` tokens plus weights plus overhead (vision tower, compute
    buffer).
    """
    return num_ctx * slots * kv_bytes_per_token / GIB + weights_gib + overhead_gib


def fits(
    *,
    num_ctx: int,
    slots: int,
    kv_bytes_per_token: float,
    weights_gib: float,
    overhead_gib: float,
    card_gib: float,
) -> bool:
    """True when ``total_gib`` is within the card budget (lower slots first, then ``num_ctx``)."""
    return total_gib(num_ctx, slots, kv_bytes_per_token, weights_gib, overhead_gib) <= card_gib


def report() -> str:
    """Budgets from the rates measured on 2026-11-03: the generator serialises (1 stream)."""
    gen = Lane(350, 3500, 200, prefill_tps=966.0, decode_tps=19.4, slots=1)
    judge = Lane(900, 3000, 150, prefill_tps=1625.0, decode_tps=25.6, slots=4)
    inp = PrInputs(50, 300, 440, gen, judge, embed_s=0.05, rerank_s=1.2)
    lines = []
    for label, sub in (("PR full core", False), ("PR 150-case subset", True)):
        e = pr_estimate(inp, judged_subset=sub)
        lines.append(
            f"{label}: gpu0 {e.gpu0_min:.1f} gpu1 {e.gpu1_min:.1f} cpu {e.cpu_min:.1f}"
            f" min -> {e.binding}"
        )
    night = nightly_estimate(replace(gen, calls=600), replace(judge, calls=1800))
    lines.append(
        f"nightly 600: gpu0 {night.gpu0_min:.1f} gpu1 {night.gpu1_min:.1f} min (budget 480)"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    from model_selection.scenarios import scenarios_report

    print(report())
    print(scenarios_report())
