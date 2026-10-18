"""Shared fixtures for the Allo wT7 tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/allo_wt7 in every test."""
    yield
