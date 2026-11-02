"""Bearer header for the candidate clients (R11 Y2.1, D216)."""

import os
from collections.abc import Mapping


def auth_headers(
    api_key_env: str | None, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return the ``Authorization`` header for the key named by ``api_key_env``, or no header.

    Args:
        api_key_env: Name of the environment variable holding the key; ``None`` disables auth.
        environ: Environment to read (default ``os.environ``).

    Returns:
        ``{"Authorization": "Bearer <key>"}`` when the variable is set and non-empty, else ``{}``.
        The value is never logged by this module.

    Examples:
        >>> auth_headers("K", {"K": "abc"})
        {'Authorization': 'Bearer abc'}
        >>> auth_headers("K", {"K": ""})
        {}
    """
    if api_key_env is None:
        return {}
    value = (os.environ if environ is None else environ).get(api_key_env, "")
    return {"Authorization": f"Bearer {value}"} if value else {}
