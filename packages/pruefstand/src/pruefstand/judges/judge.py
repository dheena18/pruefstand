"""``Judge`` and ``JudgePool``: one versioned German prompt in, one validated verdict out."""

from collections.abc import Mapping

from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.core.models.judge import JudgeTask, JudgeVerdict
from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.core.settings import PruefstandSettings
from pruefstand.judges.escaping import make_nonce, wrap
from pruefstand.judges.output import normalise, output_model, output_schema, spec_of
from pruefstand.judges.tokens import estimate_tokens, input_cap
from pruefstand.llm.client import LLMClient
from pruefstand.llm.prompts import PromptRegistry

JUDGE_MAX_TOKENS = (
    384  # = the catalogue num_predict of the judge; Ollama applies the catalogue value
)


def _nonce_key(given: bytes | None) -> bytes:
    if given is None:
        secret = PruefstandSettings().nonce_key
        given = secret.get_secret_value().encode("utf-8") if secret else b""
        if not given:
            msg = "PRUEFSTAND_NONCE_KEY is not set (HMAC key of the judge-prompt nonces)"
            raise ConfigError(msg)
    if not given:
        msg = "the judge nonce key is empty"
        raise ConfigError(msg)
    return given


class Judge:
    """One judge model behind a versioned prompt registry.

    Args:
        llm: The client of the judge's provider (policy, cache, retries, budget).
        model: The catalogue id (``ollama/<tag>``) or provider id of the judge; it is the
            ``judge_model`` of every verdict. A fallback answer (``LLMResponse.fallback``) reports
            ``resp.model`` instead: the provider-qualified id of the configured fallback model
            (``cfg.llm.fallback_judge``), for example ``github/openai/gpt-4.1-mini``.
        registry: Where the judge prompts are loaded from (``judges/prompts``).
        nonce_key: HMAC key of the block nonces; default ``PRUEFSTAND_NONCE_KEY``.

    Raises:
        ConfigError: No (or an empty) nonce key.
    """

    def __init__(
        self,
        llm: LLMClient,
        model: str,
        registry: PromptRegistry,
        *,
        nonce_key: bytes | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._registry = registry
        self._key = _nonce_key(nonce_key)
        self._cap: int | None = None  # read from the catalogue when first needed (D520)

    @property
    def model(self) -> str:
        """The judge's model id."""
        return self._model

    @property
    def input_cap(self) -> int:
        """Largest rendered prompt in (estimated) tokens: context window minus 1 024 (X3.9)."""
        if self._cap is None:
            self._cap = input_cap(self._model)
        return self._cap

    def prompt_tokens(self, task: JudgeTask) -> int:
        """Estimate the tokens of the prompt ``score`` would send for ``task``.

        Raises:
            ConfigError: Unknown metric or inputs that do not fit the prompt.
            PromptError: The prompt file is missing or malformed.
        """
        return sum(estimate_tokens(m.content) for m in self._render(task))

    def _render(self, task: JudgeTask) -> tuple[Message, ...]:
        spec = spec_of(task.metric)
        if set(task.inputs) != set(spec.variables):
            msg = f"{task.metric}: inputs {sorted(task.inputs)} must be {sorted(spec.variables)}"
            raise ConfigError(msg)
        if task.prompt_id != spec.prompt_id:
            msg = f"{task.metric}: prompt_id '{task.prompt_id}' must be '{spec.prompt_id}'"
            raise ConfigError(msg)
        template = self._registry.get(task.prompt_id, task.prompt_version)
        nonce = make_nonce(self._key, task.prompt_id, task.inputs)
        blocks = {name: wrap(name, text, nonce) for name, text in task.inputs.items()}
        return tuple(template.render(**blocks))

    async def score(self, task: JudgeTask) -> JudgeVerdict:
        """Render the prompt with nonce-wrapped inputs, ask the model and normalise the score.

        Args:
            task: Metric, prompt id and version, and the raw inputs.

        Returns:
            The verdict: normalised ``score``, ``reason``, ``raw_score``, ``judge_model`` and
            whether the answer came from the cache.

        Raises:
            ConfigError: Unknown metric, a prompt id that is not the metric's, or inputs that do not
                fit the prompt (no call is made).
            PromptError: The prompt file is missing or malformed.
            LLMError: The rendered prompt is over the input cap (no call is made; the metrics
                truncate before they ask), or the answer is invalid or out of range after one
                repair.
            PolicyViolation: The provider policy refuses the call.
            QuotaExhausted: The free quota is used up and there is no fallback.
            BudgetExceeded: The call pushed the budget over a limit.
        """
        messages = self._render(task)
        if sum(estimate_tokens(m.content) for m in messages) > self.input_cap:
            msg = f"{task.metric}: the prompt is over the input cap of {self.input_cap} tokens"
            raise LLMError(msg, transient=False)
        request = LLMRequest(
            role=LLMRole.JUDGE,
            model=self._model,
            messages=messages,
            temperature=0.0,
            max_tokens=JUDGE_MAX_TOKENS,
            prompt_id=task.prompt_id,
            prompt_version=task.prompt_version,
            response_format="json",
            json_schema=output_schema(task.metric),
        )
        out, resp = await self._llm.complete_json_meta(request, output_model(task.metric))
        return JudgeVerdict(
            score=normalise(task.metric, out.score),
            reason=out.reason,
            raw_score=out.score,
            judge_model=resp.model if resp.fallback else self._model,
            cached=resp.cached,
        )


class JudgePool:
    """The judges of a run by metric; satisfies ``core.protocols.JudgePoolLike``.

    Args:
        judges: Judge by metric name, plus the default judge under the key ``default``.
        default: The key in ``judges`` of the judge that serves every metric without its own.

    Raises:
        ConfigError: ``default`` is not a key of ``judges``.
    """

    def __init__(self, judges: Mapping[str, Judge], default: str) -> None:
        if default not in judges:
            msg = f"default judge '{default}' is not in the pool ({sorted(judges)})"
            raise ConfigError(msg)
        self._judges = dict(judges)
        self._default = default

    def for_metric(self, metric: str) -> Judge:
        """Return the judge of ``metric``, else the default judge."""
        return self._judges.get(metric, self._judges[self._default])
