"""Shared pytest configuration: Hypothesis profiles (D8-10)."""

import os

from hypothesis import settings

settings.register_profile("ci", max_examples=200, deadline=None)
settings.register_profile("nightly", max_examples=2000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
