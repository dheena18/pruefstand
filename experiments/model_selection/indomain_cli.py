"""Build the in-domain dev set (T3.1b S4): plan, generate, spot-check, assemble.

Public German law text only (GII archives pinned in ``data/sources.yaml``; fetch them with
``python data/download.py --only gii:<law> ...``, the law list is ``indomain_data.LAWS``). Needs
GitHub Models (``indomain_gen.py``); every answer is cached, so any step can be rerun and a
quota stop (exit code 3) is resumed the next day.

    python -m model_selection.indomain_cli plan
    python -m model_selection.indomain_cli generate --max-calls 120
    python -m model_selection.indomain_cli check          # second family, first 30 items
    python -m model_selection.indomain_cli assemble
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from model_selection import indomain_data as data
from model_selection import indomain_gen as gen
from model_selection.bench_cases import prompt_text

RAW_GII = data.REPO / "data" / "raw" / "gii"
SOURCES_YAML = data.REPO / "data" / "sources.yaml"
GEN_MODEL, CHECK_MODEL = "openai/gpt-4.1-mini", "meta/Llama-3.3-70B-Instruct"
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


def generation(p: data.Passage, model: str) -> tuple[data.Item | None, str]:
    """The validated cached generation of passage ``p``: (item, "") or (None, reason)."""
    text = gen.cached_response(model, data.GEN_PROMPT, p.id)
    if text is None:
        return None, "not_generated"
    try:
        raw = gen.parse_json_object(text)
    except gen.GenError:
        return None, "no_json"
    return data.validate_item(raw, p.text)


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
    """(passage id, request text) of the calls this command still has to make."""
    plan = load_plan()
    if args.cmd == "generate":
        todo = [p for p in plan if gen.cached_response(args.model, data.GEN_PROMPT, p) is None]
        tpl = prompt_text(data.GEN_PROMPT)
        return [
            (
                p,
                tpl.format(
                    passage=passages[p].text, law=passages[p].citation, title=passages[p].title
                ),
            )
            for p in todo
        ]
    out = []
    for pid in plan[: data.N_CHECK]:
        item, _ = generation(passages[pid], args.gen_model)
        if item and gen.cached_response(args.model, data.CHECK_PROMPT, pid) is None:
            body = prompt_text(data.CHECK_PROMPT).format(passage=passages[pid].text, **item)
            out.append((pid, body))
    return out


def cmd_calls(args: argparse.Namespace) -> int:
    """Make up to ``--max-calls`` new calls (generate or check); stop cleanly on quota."""
    if args.cmd == "check" and data.family_of(args.model) == data.family_of(args.gen_model):
        print("the checker must be another provider family than the generator", file=sys.stderr)
        return EXIT_USAGE
    token = gen.read_token(os.environ, args.env_file)
    prompt = data.GEN_PROMPT if args.cmd == "generate" else data.CHECK_PROMPT
    done = 0
    for pid, body in pending(args, load_passages())[: args.max_calls]:
        try:
            gen.ask(token, args.model, prompt, pid, body)
        except gen.QuotaStop as stop:
            print(f"{stop}; {done} new answers cached, run again later")
            return EXIT_QUOTA
        done += 1
    print(f"{done} new answers cached")
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    """Write the dev set, the check verdicts, the final sources list and the data card."""
    passages, plan = load_passages(), load_plan()
    items = {p: it for p in plan if (it := generation(passages[p], args.gen_model)[0])}
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
    for name, default in (
        ("generate", GEN_MODEL),
        ("check", CHECK_MODEL),
        ("assemble", CHECK_MODEL),
    ):
        p = sub.add_parser(name)
        p.add_argument(
            "--model", default=default, help="model of this step (assemble: the checker)"
        )
        p.add_argument("--gen-model", default=GEN_MODEL)
        p.add_argument("--max-calls", type=int, default=100)
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
