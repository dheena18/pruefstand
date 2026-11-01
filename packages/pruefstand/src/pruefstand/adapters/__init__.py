"""Target adapters: talk to the system under test over its public interface."""

from pruefstand.adapters.factory import build_adapter
from pruefstand.adapters.http import HttpTargetAdapter

__all__ = ["HttpTargetAdapter", "build_adapter"]
