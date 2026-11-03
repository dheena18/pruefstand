"""``rag-demo`` command line: ``rag-demo index`` builds or drops a Qdrant collection (T3.4)."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import Settings, load_config
from rag_demo.errors import ConfigError, RagDemoError
from rag_demo.index.indexer import Indexer, IndexReport, IndexTarget
from rag_demo.index.naming import ALIAS
from rag_demo.index.qdrant_admin import QdrantAdmin
from rag_demo.models import RagConfig
from rag_demo.wiring import build_analyzer, build_catalogue, build_dense, resolve_embed_url

app = typer.Typer(help="Tools of the Prüfstand reference RAG app.", add_completion=False)
APP_DIR = Path(__file__).resolve().parents[2]
REPO_CATALOGUE = Path(__file__).resolve().parents[4] / "infra" / "gpu" / "models.yaml"
CONFIG_DIRS = (APP_DIR / "configs", Path("/app/configs"), Path("configs"))


class Encoder(StrEnum):
    """The dense encoder service: TEI CPU (tier 1) or Ollama ``bge-m3`` (tier 2)."""

    TEI = "tei"
    OLLAMA = "ollama"


def default_config(encoder: Encoder | None) -> Path:
    """The config file when ``--config`` is absent: ``RAG_CONFIG``, else the profile of ``encoder``.

    Raises:
        ConfigError: No config file is found.
    """
    if env := os.environ.get("RAG_CONFIG"):
        return Path(env)
    name = "rag.gpu.yaml" if encoder is Encoder.OLLAMA else "rag.yaml"
    for base in CONFIG_DIRS:
        if (base / name).is_file():
            return base / name
    msg = f"cannot find configs/{name}; pass --config"
    raise ConfigError(msg)


def _load(config: Path | None, encoder: Encoder | None, settings: Settings) -> RagConfig:
    path = config or default_config(encoder)
    catalogue = settings.rag_model_catalogue or (
        REPO_CATALOGUE if REPO_CATALOGUE.is_file() else None
    )
    cfg = load_config(path, catalogue)
    if encoder is not None and cfg.embed.engine != encoder.value:
        msg = f"--encoder {encoder.value} but {path.name} has embed.engine {cfg.embed.engine}"
        raise ConfigError(msg)
    return cfg


def _indexer(cfg: RagConfig, settings: Settings, target: IndexTarget) -> Indexer:
    gpu = settings.model_copy(
        update={"rag_model_catalogue": settings.rag_model_catalogue or REPO_CATALOGUE}
    )
    if cfg.embed.engine == "ollama" and settings.embed_tokenizer is None:
        msg = (
            "--encoder ollama needs the model's tokenizer.json to count truncated chunks: set "
            "RAG_EMBED_TOKENIZER (fetch it with `make fetch-tokenizer`)"
        )
        raise ConfigError(msg)
    dense = build_dense(
        cfg,
        resolve_embed_url(cfg, settings),
        catalogue=build_catalogue(cfg, gpu),
        tokenizer=settings.embed_tokenizer,
    )
    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return Indexer(
        settings.qdrant_url,
        dense,
        build_analyzer(cfg),
        SparseEncoder(),
        target=target,
        api_key=key,
    )


def _summary(report: IndexReport) -> str:
    if report.alias is None:
        alias = "alias unchanged"
    elif report.alias_switched:
        alias = f"alias {report.alias} switched"
    else:
        alias = f"alias {report.alias} unchanged"
    cut = f", {report.truncated_chunks} truncated" if report.truncated_chunks else ""
    return f"indexed {report.chunks} chunks into {report.collection}, {alias}{cut}"


def _run(
    corpus: Path | None,
    encoder: Encoder | None,
    config: Path | None,
    collection: str | None,
    *,
    alias: bool,
) -> str:
    settings = Settings()
    if corpus is None:
        msg = "--corpus is required"
        raise ConfigError(msg)
    cfg = _load(config, encoder, settings)
    target = IndexTarget(cfg.embed.model, collection=collection, alias=ALIAS if alias else None)
    indexer = _indexer(cfg, settings, target)
    indexer.index(corpus)
    if indexer.last_report is None:  # pragma: no cover  (index always sets it)
        msg = "indexer produced no report"
        raise ConfigError(msg)
    return _summary(indexer.last_report)


@app.callback()
def main() -> None:
    """Tools of the Prüfstand reference RAG app."""


@app.command("index")
def index(
    *,
    corpus: Annotated[Path | None, typer.Option(help="corpus/<version> directory")] = None,
    encoder: Annotated[Encoder | None, typer.Option(help="tei (tier 1) or ollama (tier 2)")] = None,
    config: Annotated[Path | None, typer.Option(help="rag*.yaml (default by --encoder)")] = None,
    collection: Annotated[
        str | None, typer.Option(help="collection name (PR: pr_<N>_<sha>)")
    ] = None,
    no_alias: Annotated[
        bool, typer.Option("--no-alias", help="do not switch chunks_active")
    ] = False,
    drop: Annotated[str | None, typer.Option(help="delete this collection and exit")] = None,
) -> None:
    """Build a Qdrant collection from a corpus directory, or drop one with --drop."""
    if (corpus is None) == (drop is None):
        raise typer.BadParameter("give exactly one of --corpus and --drop")  # noqa: EM101
    try:
        if drop is not None:
            settings = Settings()
            key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
            QdrantAdmin(settings.qdrant_url, api_key=key).drop(drop, alias=ALIAS)
            typer.echo(f"dropped {drop}")
            return
        typer.echo(_run(corpus, encoder, config, collection, alias=not no_alias))
    except (RagDemoError, ValidationError) as err:
        typer.echo(f"error: {err}", err=True)
        raise typer.Exit(1) from None
