"""Smoke test: the dashboard script runs for every scenario without raising."""
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.scenarios import SCENARIO_NAMES  # noqa: E402


@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
def test_app_renders(scenario):
    at = AppTest.from_file("../app.py", default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value(scenario).run()
    assert not at.exception, at.exception
    assert any("SIMULATION" in w.value for w in at.warning)
