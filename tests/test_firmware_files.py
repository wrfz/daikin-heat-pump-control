"""Consistency of the bridge firmware files (no ESPHome needed)."""

from pathlib import Path
import re

import pytest

import helpers  # noqa: F401  # sets up the import path

ROOT = Path(__file__).resolve().parent.parent
ESPHOME = ROOT / "esphome"
EXAMPLES = sorted(ESPHOME.glob("daikin-*-bridge.yaml"))
REPOSITORY = "https://github.com/wrfz/daikin-heat-pump-control"


def _component_version() -> str:
    text = (ESPHOME / "components" / "daikin_bridge" / "__init__.py").read_text()
    match = re.search(r'^BRIDGE_VERSION = "([^"]+)"$', text, re.MULTILINE)
    assert match
    return match.group(1)


def test_project_version_is_component_version() -> None:
    """The project version of the firmware is the version of the component."""
    text = (ESPHOME / "packages" / "board-esp32.yaml").read_text()
    assert f'version: "{_component_version()}"' in text


def test_examples_present() -> None:
    """There is an example for each bus and for both."""
    assert [path.name for path in EXAMPLES] == [
        "daikin-can-bridge.yaml",
        "daikin-can-uart-bridge.yaml",
        "daikin-uart-bridge.yaml",
    ]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.name)
def test_example_uses_one_version(example: Path) -> None:
    """Component and packages come from the repository at the same ref."""
    text = example.read_text()
    assert re.search(r"^  bridge_ref: \S+$", text, re.MULTILINE)
    assert text.count(f"url: {REPOSITORY}") == 2
    assert text.count("ref: ${bridge_ref}") == 2
    assert "!include" not in text
    files = re.findall(r"^      - (esphome/packages/\S+\.yaml)$", text, re.MULTILINE)
    assert files
    for file in files:
        assert (ROOT / file).is_file(), file
