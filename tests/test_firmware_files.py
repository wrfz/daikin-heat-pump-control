"""Consistency of the bridge firmware files (no ESPHome needed)."""

from pathlib import Path
import re

import pytest

import helpers  # noqa: F401  # sets up the import path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((ROOT / "examples").glob("daikin-*-bridge.yaml"))
REPOSITORY = "https://github.com/wrfz/daikin-heat-pump-control"


def test_examples_present() -> None:
    """There is an example for each bus and for both."""
    assert [path.name for path in EXAMPLES] == [
        "daikin-can-bridge.yaml",
        "daikin-can-uart-bridge.yaml",
        "daikin-uart-bridge.yaml",
    ]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.name)
def test_example_is_complete(example: Path) -> None:
    """An example holds the whole node; only the component comes from the repository."""
    text = example.read_text()
    for section in ("esphome", "esp32", "wifi", "api", "ota", "daikin_bridge"):
        assert re.search(rf"^{section}:", text, re.MULTILINE), section
    # The component sets the project name and version itself.
    assert "project:" not in text
    assert f"url: {REPOSITORY}" in text
    assert "packages:" not in text
    assert "!include" not in text
    # The component registers the actions itself.
    assert "actions:" not in text
    buses = {
        "can": "canbus_id: daikin_can" in text,
        "uart": "uart_id: daikin_uart" in text,
    }
    assert buses == {
        "can": "-can-" in example.name,
        "uart": "uart" in example.name,
    }
