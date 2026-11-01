"""Target configs: the system under test is always a real HTTP service (ADR-0008)."""

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TargetConfig(BaseModel):
    """How to reach the system under test.

    Attributes:
        type: Adapter type; only ``http`` exists (there is no simulated target, ADR-0008).
        url: Base URL of the target API v1.
        auth_env: *Name* of the env var that holds a bearer token, never the token itself.
        timeout_s: Per-request timeout in seconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["http"] = "http"
    url: str = Field(min_length=1)
    auth_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    timeout_s: float = Field(default=60, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _http_url(self) -> Self:
        parts = urlsplit(self.url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            msg = "url must be an http:// or https:// URL with a host"
            raise ValueError(msg)
        return self


class HttpTargetConfig(TargetConfig):
    """The ``type == "http"`` specialisation: ``type`` and ``url`` are both required."""

    type: Literal["http"]
    url: str = Field(min_length=1)
