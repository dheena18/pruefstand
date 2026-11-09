"""Owner spot-check of the generated dataset (T4.7a). Start: ``make review-app``.

One item per screen. Left: the question, the reference answer and the gold citation. Right: the
source text of the cited provision with the cited Absatz highlighted (and, stronger, the evidence
sentence). The owner answers two yes/no questions (keys ``y`` / ``n``) and may add a note; the
decision goes to ``spotcheck_decisions.jsonl`` in the review work directory. This app never writes
into ``datasets/pruefstand-de/``; only ``apply`` does.

The build config comes from the environment variable ``REVIEW_APP_CONFIG`` (``dataset.yaml``).
"""

import html
import os
from collections.abc import Callable
from pathlib import Path

import streamlit as st
from review_app.logic import (
    ABSATZ,
    EVIDENCE,
    SampleItem,
    SourceView,
    load_sample,
    pending,
    write_decision,
)

from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.config_loader import load_model

CONFIG_ENV = "REVIEW_APP_CONFIG"
_STYLE = {
    ABSATZ: "background:#fff3b0;color:#111",
    EVIDENCE: "background:#ffd24a;color:#111;font-weight:600",
}


def _render(view: SourceView) -> str:
    parts = []
    for seg in view.segments:
        text = html.escape(seg.text).replace("\n", "<br>")
        style = _STYLE.get(seg.level)
        parts.append(f'<span style="{style}">{text}</span>' if style else text)
    return "".join(parts)


def _case_column(entry: SampleItem) -> None:
    case = entry.case
    st.subheader("Question")
    st.write(case.question)
    st.subheader("Reference answer")
    st.write(case.reference_answer or "(none: the system must refuse)")
    st.subheader("Gold citation")
    st.write(", ".join(case.gold_citations) or "(none)")
    if entry.item is not None:
        st.caption(f"Model review: {entry.item.verdict}. {entry.item.reason}")
    st.caption(f"{case.id} - {case.split.value} - {case.category.value} - {case.tenant}")


def _source_column(entry: SampleItem) -> None:
    st.subheader("Source text")
    if not entry.views:
        st.info("No source chunk found for this case.")
    for view in entry.views:
        st.markdown(f"**{view.citation_key or view.chunk_id}**")
        st.markdown(_render(view), unsafe_allow_html=True)


def _first(value: bool) -> None:  # noqa: FBT001  (a callback argument)
    st.session_state["citation"] = value


def _save(cfg: DatasetBuildConfig, case_id: str, plausible: bool) -> None:  # noqa: FBT001
    write_decision(
        cfg,
        case_id,
        citation_ok=bool(st.session_state.get("citation")),
        plausible=plausible,
        note=st.session_state.get("note", ""),
        pseudonym=st.session_state.get("pseudonym", ""),
    )
    st.session_state.pop("citation", None)
    st.session_state["note"] = ""


def _buttons(prefix: str, on_click: Callable[..., None], *args: object) -> None:
    yes, no = st.columns(2)
    yes.button(
        "Yes (y)",
        key=f"{prefix}_yes",
        shortcut="y",
        on_click=on_click,
        args=(*args, True),
        width="stretch",
    )
    no.button(
        "No (n)",
        key=f"{prefix}_no",
        shortcut="n",
        on_click=on_click,
        args=(*args, False),
        width="stretch",
    )


def _questions(cfg: DatasetBuildConfig, entry: SampleItem) -> None:
    if st.session_state.get("citation") is None:
        st.markdown("**1. Does the citation point to the right section and paragraph?**")
        _buttons("c", _first)
        return
    st.markdown(
        "**2. Is the answer plausible given the highlighted text (numbers, dates, durations)?**"
    )
    _buttons("p", _save, cfg, entry.case.id)


def main() -> None:
    """Draw the app."""
    st.set_page_config(page_title="Pruefstand spot-check", layout="wide")
    config = os.environ.get(CONFIG_ENV)
    if not config:
        st.error(f"Set {CONFIG_ENV} to the dataset.yaml of the build (make review-app does).")
        return
    cfg = load_model(Path(config), DatasetBuildConfig)
    sample = load_sample(cfg)
    todo = pending(sample, cfg)
    with st.sidebar:
        st.text_input(
            "Your pseudonym", key="pseudonym", help="Stored as owner-spotcheck:<pseudonym>"
        )
        st.text_area("Optional note for this item", key="note")
        st.progress((len(sample) - len(todo)) / len(sample) if sample else 1.0)
        st.caption(f"{len(sample) - len(todo)} of {len(sample)} checked")
    if not todo:
        st.success("All items are checked. Run `make review-summary` for the verdict.")
        return
    entry = todo[0]
    left, right = st.columns(2)
    with left:
        _case_column(entry)
    with right:
        _source_column(entry)
    if not st.session_state.get("pseudonym", "").strip():
        st.warning("Enter a pseudonym in the sidebar to answer.")
        return
    _questions(cfg, entry)


main()
