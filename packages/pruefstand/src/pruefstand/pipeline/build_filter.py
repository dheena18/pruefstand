"""Stage ``filter`` of ``build_dataset``: the T4.3 QA filters (T4.7a).

Deterministic checks, copy rules, the support check (a model of another family than the datagen
model) and near-duplicates. Without ``models.support`` the support check is skipped and the build
report says so (``support_skipped``).
"""

from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.filters import SupportSetup, filter_candidates
from pruefstand.dataset.sampling import load_chunks
from pruefstand.llm.policy import LOCAL_PROVIDERS, provider_of
from pruefstand.llm.recorder import CallRecorder
from pruefstand.pipeline.build_context import BuildContext, StageResult


def _support(ctx: BuildContext) -> SupportSetup | None:
    models = ctx.cfg.models
    if models is None or models.support is None:
        return None
    ref = models.support
    if provider_of(ref.id) in LOCAL_PROVIDERS:
        llm = ctx.clients.local(ref)
    else:
        llm = ctx.clients.datagen(ref, ctx.cfg.generation.max_requests, CallRecorder())
    return SupportSetup(llm, ref.id, models.datagen.id)


async def filter_stage(ctx: BuildContext) -> StageResult:
    """Run the ``filter`` stage; return the kept candidates and the counters.

    Raises:
        ConfigError: No ``embed`` server configured.
        DatasetError: The support check could not judge every candidate (quota, outage): run the
            stage again.
    """
    if ctx.cfg.embed is None:
        msg = "the filter stage needs an embedding server (embed: url, api, model)"
        raise ConfigError(msg)
    cands = ctx.work.read("generate", QACandidate)
    chunks = {c.chunk_id: c for c in load_chunks(ctx.cfg.corpus_dir)}
    embed = ctx.clients.embed(ctx.cfg.embed)
    outcome = await filter_candidates(cands, chunks, embed, ctx.cfg.filters, support=_support(ctx))
    report = outcome.report
    if report.not_checked or report.reasons.get("judge_error"):
        msg = (
            f"filter: {report.not_checked} candidates not judged and "
            f"{report.reasons.get('judge_error', 0)} judge errors; run the stage again"
        )
        raise DatasetError(msg)
    counters = {"total": report.total, "kept": report.kept, "dropped": report.dropped}
    counters.update({f"drop_{reason}": n for reason, n in sorted(report.reasons.items())})
    counters["support_skipped"] = int(report.support == "skipped")
    return list(outcome.kept), counters
