"""Planted: a private import of another engine package, which the sentry must flag."""

from decoy_engine.providers_v2._faker_adapter import _v2_custom_provider_names

__all__ = ["_v2_custom_provider_names"]
