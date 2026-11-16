"""Build the in-domain dev set (T3.1b S4): plan, generate, spot-check, assemble.

Public German law text only (GII archives pinned in ``data/sources.yaml``; fetch them with
``python data/download.py --only gii:<law> ...``, the law list is ``indomain_data.LAWS``). The
generator is the pin of ``PRUEFSTAND_DATAGEN_BACKEND`` (``vm``, default: the VM CPU model, D1201;
``github``: GitHub Models, retired); the checker must be another family (``--model``). Every
answer is cached, so any step can be rerun and a quota stop (exit code 3) is resumed later.

    bash scripts/models/vm_llm.sh start   # serves PRUEFSTAND_DATAGEN_BASE_URL (default port 18091)
    python -m model_selection.indomain_cli plan
    python -m model_selection.indomain_cli generate --max-calls 120 --retries 2
    python -m model_selection.indomain_cli check          # second family, first 30 items
    python -m model_selection.indomain_cli assemble
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from model_selection import indomain_data as data
from model_selection import indomain_gen as gen
from model_selection import indomain_retry as retry
from model_selection.bench_cases import prompt_text

RAW_GII = data.REPO / "data" / "raw" / "gii"
SOURCES_YAML = data.REPO / "data" / "sources.yaml"
GITHUB_GEN_MODEL, CHECK_MODEL = "openai/gpt-4.1-mini", "meta/Llama-3.3-70B-Instruct"
VM_GEN_MODEL = "openai_compatible_local/ministral-3-14b-instruct-2512"  # datagen_pins, D1201


def datagen_base_url() -> str:
    """``PRUEFSTAND_DATAGEN_BASE_URL`` (default ``http://127.0.0.1:18091/v1``), not the judge."""
    from pruefstand.core.settings import PruefstandSettings  # noqa: PLC0415  # reason: lazy

    return PruefstandSettings().datagen_base_url


def default_gen_model() -> str:
    """The generator of the configured backend (``PRUEFSTAND_DATAGEN_BACKEND``)."""
    from pruefstand.core.settings import PruefstandSettings  # noqa: PLC0415  # reason: lazy

    return VM_GEN_MODEL if PruefstandSettings().datagen_backend == "vm" else GITHUB_GEN_MODEL


GEN_MODEL = GITHUB_GEN_MODEL  # the GitHub generator of the committed plan and cache keys
EXIT_QUOTA, EXIT_USAGE = 3, 2


def source_ids() -> list[str]:
    """``data/download.py --only`` ids of the laws of the dev set."""
    return [f"gii:{slug}" for slug in data.LAWS]


def load_passages(raw: Path = RAW_GII) -> dict[str, data.Passage]:
    """All norms of the dev-set laws from the pinned GII archives (``data/raw/gii``)."""
    from pruefstand.ingest.gii_xml import GiiXmlLoader  # noqa: PLC0415  # reason: heavy, lazy

    wanted = set(source_ids())
    return {
        d.doc_id: data.Passage(
            d.doc_id, d.law_abbrev or "", str(d.metadata.get("citation_key", "")), d.title, d.text
        )
        for d in GiiXmlLoader().load(raw)
        if d.source in wanted
    }


def pins() -> dict[str, str]:
    """``{gii:<law>: sha256 of xml.zip}`` of the dev-set laws from ``data/sources.yaml``."""
    rows = yaml.safe_load(SOURCES_YAML.read_text(encoding="utf-8"))["sources"]
    wanted = set(source_ids())
    return {r["id"]: r["files"]["xml.zip"] for r in rows if r["id"] in wanted}


def load_plan(path: Path = data.SOURCES_PATH) -> list[str]:
    """The ordered planned passage ids of the committed sources file."""
    plan: list[str] = json.loads(path.read_text(encoding="utf-8"))["plan_order"]
    return plan


def generation(
    p: data.Passage, model: str, retries: int = retry.DEFAULT_RETRIES
) -> tuple[data.Item | None, str]:
    """The first valid cached answer of ``p`` over its attempts: (item, "") or (None, why)."""
    return retry.first_valid(retry.answers(model, p.id, retries), p.text)


def verdict(model: str, pid: str) -> dict[str, Any] | None:
    """The cached spot-check verdict of passage ``pid`` (``None`` when not checked)."""
    text = gen.cached_response(model, data.CHECK_PROMPT, pid)
    if text is None:
        return None
    try:
        return gen.parse_json_object(text)
    except gen.GenError:
        return {"answerable": False, "german": False, "single_passage": False, "reason": "no_json"}


def cmd_plan(_: argparse.Namespace) -> int:
    """Select the passages (items plus reserve) and write the planned exclusion list."""
    passages = load_passages()
    ids = data.plan_passages(
        passages.values(), data.N_ITEMS + data.N_RESERVE, excluded=data.slice_doc_ids()
    )
    meta = {"seed": data.SEED, "plan_order": ids, "pins": pins(), "n_items": data.N_ITEMS}
    doc = data.sources_doc("planned", ids, [], meta)
    data.SOURCES_PATH.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", "utf-8")
    print(f"planned {len(ids)} passages of {len(passages)}")
    return 0


def pending(args: argparse.Namespace, passages: dict[str, data.Passage]) -> list[tuple[str, str]]:
    """(passage id, request text) of the spot-check calls this command still has to make."""
    plan = load_plan()
    out = []
    for pid in plan[: data.N_CHECK]:
        item, _ = generation(passages[pid], args.gen_model, args.retries)
        if item and gen.cached_response(args.model, data.CHECK_PROMPT, pid) is None:
            body = prompt_text(data.CHECK_PROMPT).format(passage=passages[pid].text, **item)
            out.append((pid, body))
    return out


def cmd_generate(args: argparse.Namespace, token: str, base_url: str | None) -> int:
    """Generate with per-item regeneration (``--retries``); every attempt counts as one call."""
    if gen.is_vm(args.model):
        try:  # the answer echoes the alias we send: ask /models once, before anything else
            vm_check(args.model, base_url)
        except gen.GenError as exc:
            print(f"stopped: {exc}", file=sys.stderr)
            return 1
    passages = load_passages()
    tpl = prompt_text(data.GEN_PROMPT)
    tally = retry.Tally()

    def call(key: str, attempt: int, p: data.Passage) -> None:
        if tally.calls and args.pause_s > 0:
            time.sleep(args.pause_s)  # free tier: 15 requests per minute
        body = tpl.format(passage=p.text, law=p.citation, title=p.title)
        gen.ask(token, args.model, data.GEN_PROMPT, key, body, base_url=base_url, attempt=attempt)

    plan = [passages[pid] for pid in load_plan()]
    try:
        retry.run_generate(
            plan,
            lambda pid: retry.answers(args.model, pid, args.retries),
            call,
            retries=args.retries,
            max_calls=args.max_calls,
            tally=tally,
        )
    except gen.QuotaStop as stop:
        print(f"{stop}; {tally.line()}, run again later")
        return EXIT_QUOTA
    except gen.GenError as exc:
        print(f"stopped: {exc}; {tally.line()}", file=sys.stderr)
        return 1
    print(tally.line())
    return 0


def vm_check(model: str, base_url: str | None) -> None:
    """``GenError`` unless the server at ``base_url`` serves the alias of ``model`` (D1201)."""
    from pruefstand.core.errors import ConfigError  # noqa: PLC0415  # reason: lazy, like settings
    from pruefstand.dataset.vm_datagen import check_vm_served  # noqa: PLC0415

    try:
        check_vm_served(model, base_url or "")
    except ConfigError as exc:
        raise gen.GenError(str(exc)) from exc


def cmd_calls(args: argparse.Namespace) -> int:
    """Make up to ``--max-calls`` new calls (generate or check); stop cleanly on quota."""
    if args.cmd == "check" and data.family_of(args.model) == data.family_of(args.gen_model):
        print("the checker must be another provider family than the generator", file=sys.stderr)
        return EXIT_USAGE
    if not gen.is_vm(args.model):
        print("note: GitHub Models is retired (2026-07-30, D1202)", file=sys.stderr)
    token = "" if gen.is_vm(args.model) else gen.read_token(os.environ, args.env_file)
    base_url = datagen_base_url()
    if args.cmd == "generate":
        return cmd_generate(args, token, base_url)
    prompt = data.CHECK_PROMPT
    if gen.is_vm(args.model):
        try:
            vm_check(args.model, base_url)
        except gen.GenError as exc:
            print(f"stopped: {exc}", file=sys.stderr)
            return 1
    done = 0
    for pid, body in pending(args, load_passages())[: args.max_calls]:
        if done and args.pause_s > 0:
            time.sleep(args.pause_s)  # free tier: 15 requests per minute
        try:
            gen.ask(token, args.model, prompt, pid, body, base_url=base_url)
        except gen.QuotaStop as stop:
            print(f"{stop}; {done} new answers cached, run again later")
            return EXIT_QUOTA
        done += 1
    print(f"{done} new answers cached")
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    """Write the dev set, the check verdicts, the final sources list and the data card."""
    passages, plan = load_passages(), load_plan()
    items = {
        p: it for p in plan if (it := generation(passages[p], args.gen_model, args.retries)[0])
    }
    verdicts = {p: v for p in plan[: data.N_CHECK] if (v := verdict(args.model, p))}
    records, stats = data.assemble(plan, passages, items, verdicts)
    for rec in records:
        rec["generator_model"], rec["checker_model"] = args.gen_model, args.model
    if len(records) < data.N_ITEMS:
        print(f"only {len(records)} of {data.N_ITEMS} items; generate more first", file=sys.stderr)
        return 1
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    data.DEV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    checks = [{"gold_passage_id": p, "checker_model": args.model, **v} for p, v in verdicts.items()]
    data.CHECKS_PATH.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in checks) + "\n", encoding="utf-8"
    )
    meta = {"seed": data.SEED, "plan_order": plan, "pins": pins(), "n_items": len(records)}
    used = [r["gold_passage_id"] for r in records]
    doc = data.sources_doc("final", plan, used, meta)
    data.SOURCES_PATH.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", "utf-8")
    data.CARD_PATH.write_text(data.render_card(records, stats, args.gen_model, args.model), "utf-8")
    print(f"assembled {len(records)} items; {stats}")
    return 0


def main(argv: list[str]) -> int:
    """Entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    gen_default = default_gen_model()
    for name, default in (
        ("generate", gen_default),
        ("check", CHECK_MODEL),
        ("assemble", CHECK_MODEL),
    ):
        p = sub.add_parser(name)
        p.add_argument(
            "--model", default=default, help="model of this step (assemble: the checker)"
        )
        p.add_argument("--gen-model", default=gen_default)
        p.add_argument("--max-calls", type=int, default=100)
        p.add_argument(
            "--retries",
            type=int,
            default=retry.DEFAULT_RETRIES,
            help="regenerate an invalid item up to N more times (each one call, D1201)",
        )
        p.add_argument("--pause-s", type=float, default=0.0, help="sleep between two calls")
        p.add_argument("--env-file", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.cmd == "generate":
        args.gen_model = args.model
    try:
        if args.cmd == "plan":
            return cmd_plan(args)
        return cmd_assemble(args) if args.cmd == "assemble" else cmd_calls(args)
    except gen.GenError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
