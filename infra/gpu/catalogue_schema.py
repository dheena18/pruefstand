"""Validator for ``models.yaml`` and ``endpoints.yaml`` (T3.1a; script-only, not in the package).

The catalogue is the single machine-readable list of servable models (interfaces 1.5,
gpu-cluster.md section 2). The rules are the ones the T3.1a prompt and ADR-0018/0019 fix: four
roles, one judge, the standard set fits the cluster disk and each card, ``options`` and
``option_bounds`` are complete and consistent, chat entries carry a tokenizer hash.
``gpu_catalogue.py`` (what the shell scripts call) reads the same file with PyYAML only; this
module is what tests and CI use to check it.
"""

import re
from pathlib import Path
from typing import Literal, NoReturn, Self

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

NUM_PARALLEL = 4
MAX_LOADED_MODELS = 3
VRAM_CARD_BUDGET_GB = 44.0
DISK_FREE_BUDGET_GB = 14.0
DISK_RESERVE_GB = 2.0
JUDGE_CTX_ALLOWANCE = 4096
JUDGE_MAX_PREDICT = 384
LICENSE_ALLOWLIST = frozenset({"Apache-2.0", "MIT", "Gemma", "CC-BY-4.0", "BSD-3-Clause"})
URL_SETTINGS = frozenset({"OLLAMA_GPU0_URL", "OLLAMA_GPU1_URL", "RERANK_URL"})
GB = 1_000_000_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _bad(message: str) -> NoReturn:
    raise ValueError(message)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Options(_Frozen):
    """The per-model Ollama options sent on every preload and every trusted request."""

    num_ctx: int
    num_predict: int
    temperature: float
    seed: int
    top_p: float


class OptionBounds(_Frozen):
    """Min/max the ``llm-proxy`` lets a candidate pass through (round 12 N2)."""

    temperature: tuple[float, float]
    top_p: tuple[float, float]
    num_predict: tuple[int, int]


class Tokenizer(_Frozen):
    """Where the prompt-token counter comes from and the hash that pins it (AI13-05)."""

    source: str
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not HEX64.match(value):
            _bad("tokenizer.sha256 must be 64 lowercase hex characters")
        return value


class Entry(_Frozen):
    """One servable model."""

    id: str
    engine: Literal["ollama", "cpu"]
    tag: str
    digest: str | None = None
    revision: str | None = None
    quantization: str
    family: str
    ollama_family: str | None = None
    role: Literal["generator", "judge", "embed", "rerank"]
    server: Literal["gpu0", "gpu1", "vm"]
    standard: bool
    think: bool | None = None
    capabilities: tuple[str, ...] = ()
    license: str
    provisional: bool
    disk_bytes: int | None = None
    keep_alive: str | None = None
    kv_bytes_per_token: int | None = None
    swa_window: int | None = None
    options: Options | None = None
    option_bounds: OptionBounds | None = None
    tokenizer: Tokenizer | None = None
    query_prefix: str | None = None
    doc_prefix: str | None = None
    max_input_tokens: int | None = None
    request_timeout_s: float | None = (
        None  # rerank entries: client timeout sized for the CPU (T3.5)
    )

    @model_validator(mode="after")
    def _entry_rules(self) -> Self:
        if self.license not in LICENSE_ALLOWLIST:
            _bad(f"{self.id}: licence {self.license!r} is not on the allowlist")
        if self.engine == "ollama":
            self._ollama_rules()
        elif not (self.revision and HEX40.match(self.revision)):
            _bad(f"{self.id}: a cpu entry needs a 40-hex revision")
        if self.role in {"generator", "judge", "embed"}:
            self._options_rules()
        return self

    def _ollama_rules(self) -> None:
        if self.id != f"ollama/{self.tag}":
            _bad(f"{self.id}: an ollama id must be 'ollama/' + tag")
        if not (self.digest and HEX64.match(self.digest)):
            _bad(f"{self.id}: digest must be 64 lowercase hex characters")
        if self.disk_bytes is None or self.keep_alive is None or self.kv_bytes_per_token is None:
            _bad(f"{self.id}: disk_bytes, keep_alive and kv_bytes_per_token are required")
        if "thinking" in self.capabilities and self.think is not False:
            _bad(f"{self.id}: capability 'thinking' requires think: false (D95)")

    def _options_rules(self) -> None:
        opts = self.options
        if opts is None:
            _bad(f"{self.id}: options are required")
        if self.role == "embed":
            if opts.num_ctx != self.max_input_tokens:
                _bad(f"{self.id}: embed num_ctx must equal max_input_tokens (AI12-08)")
            return
        bounds = self.option_bounds
        if bounds is None or self.tokenizer is None:
            _bad(f"{self.id}: chat entries need option_bounds and tokenizer")
        inside = (
            bounds.temperature[0] <= opts.temperature <= bounds.temperature[1]
            and bounds.top_p[0] <= opts.top_p <= bounds.top_p[1]
            and bounds.num_predict[0] <= opts.num_predict <= bounds.num_predict[1]
        )
        if not inside:
            _bad(f"{self.id}: a default option lies outside its option_bounds (N2)")
        if self.role == "judge" and opts.num_predict > JUDGE_MAX_PREDICT:
            _bad(f"{self.id}: judge num_predict must be <= {JUDGE_MAX_PREDICT}")


class Catalogue(_Frozen):
    """The whole ``models.yaml`` with the cross-entry rules of ADR-0018/0019."""

    models: tuple[Entry, ...]

    def by_id(self, model_id: str) -> Entry:
        """Return the entry with this id; raises ``KeyError`` if unknown."""
        for entry in self.models:
            if entry.id == model_id:
                return entry
        raise KeyError(model_id)

    def standard(self, role: str) -> Entry:
        """The one standard (day/night) entry of a role."""
        found = [e for e in self.models if e.role == role and e.standard]
        if len(found) != 1:
            _bad(f"exactly one standard {role} entry is required")
        return found[0]

    @model_validator(mode="after")
    def _set_rules(self) -> Self:
        ids = [e.id for e in self.models]
        if len(set(ids)) != len(ids):
            _bad("duplicate catalogue ids")
        judges = [e for e in self.models if e.role == "judge"]
        if len(judges) != 1 or judges[0].family == "qwen":
            _bad("exactly one judge entry, and its family is not qwen (ADR-0019)")
        if any(e.family != "qwen" for e in self.models if e.role == "generator"):
            _bad("every generator is family qwen (ADR-0019)")
        for role in ("generator", "embed", "judge", "rerank"):
            self.standard(role)
        self._fit_rules()
        return self

    def _fit_rules(self) -> None:
        gen_opts = self.standard("generator").options
        judge_opts = self.standard("judge").options
        if gen_opts is None or judge_opts is None:
            _bad("generator and judge need options")
        if judge_opts.num_ctx < gen_opts.num_ctx + JUDGE_CTX_ALLOWANCE:
            _bad("judge num_ctx must be >= generator num_ctx + 4096 (D306)")
        if disk_total_gb(self, include_generator=False) > DISK_FREE_BUDGET_GB - DISK_RESERVE_GB:
            _bad("the standard set does not leave 2 GB free on the cluster disk")
        for mode in ("day", "night"):
            if len(mode_models(self, mode)) > MAX_LOADED_MODELS:
                _bad(f"{mode}: more than OLLAMA_MAX_LOADED_MODELS models")
            for card, gb in planned_vram_gb(self, mode).items():
                if gb > VRAM_CARD_BUDGET_GB:
                    _bad(f"{mode}: planned VRAM of the {card} card is {gb:.1f} GB > 44")


def mode_models(cat: Catalogue, mode: str) -> list[Entry]:
    """The models resident in a mode, generator first (ADR-0019: day and night are the same set)."""
    if mode not in {"day", "night"}:
        _bad(f"no {mode} mode (ADR-0019)")
    order = {"generator": 0, "embed": 1, "judge": 2}
    chosen = [e for e in cat.models if e.standard and e.role in order]
    return sorted(chosen, key=lambda e: order[e.role])


def planned_vram_gb(cat: Catalogue, mode: str) -> dict[str, float]:
    """Planned VRAM per card: weights + ``num_ctx * NUM_PARALLEL * kv_bytes_per_token``."""
    cards = {"generator": 0.0, "judge": 0.0}
    for e in mode_models(cat, mode):
        if e.options is None or e.disk_bytes is None:
            _bad(f"{e.id}: options and disk_bytes are required")
        kv = e.options.num_ctx * NUM_PARALLEL * (e.kv_bytes_per_token or 0)
        cards["judge" if e.role == "judge" else "generator"] += (e.disk_bytes + kv) / GB
    return cards


def disk_total_gb(cat: Catalogue, *, include_generator: bool) -> float:
    """Disk of the standard Ollama set in GB (decimal), optionally without the present generator."""
    total = sum(
        (e.disk_bytes or 0)
        for e in cat.models
        if e.standard and e.engine == "ollama" and (include_generator or e.role != "generator")
    )
    return total / GB


class Endpoint(_Frozen):
    """One service of ``endpoints.yaml``."""

    base_url_env: str
    model_id: str
    family: str
    kind: Literal["chat", "embed", "rerank"]

    @field_validator("base_url_env")
    @classmethod
    def _setting(cls, value: str) -> str:
        if value not in URL_SETTINGS:
            _bad(f"base_url_env must be one of {sorted(URL_SETTINGS)}")
        return value


class Endpoints(_Frozen):
    """The whole ``endpoints.yaml``."""

    endpoints: dict[str, Endpoint]

    def check_against(self, cat: Catalogue) -> None:
        """Raise ``ValueError`` when an endpoint names a model that is not in the catalogue."""
        for name, endpoint in self.endpoints.items():
            try:
                cat.by_id(endpoint.model_id)
            except KeyError:
                _bad(f"endpoint {name}: unknown model_id {endpoint.model_id}")


def load_catalogue(path: Path) -> Catalogue:
    """Parse and validate ``models.yaml``."""
    return Catalogue.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_endpoints(path: Path, cat: Catalogue) -> Endpoints:
    """Parse ``endpoints.yaml`` and check every ``model_id`` against the catalogue."""
    endpoints = Endpoints.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    endpoints.check_against(cat)
    return endpoints
