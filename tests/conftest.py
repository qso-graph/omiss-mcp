"""Shared pytest configuration for omiss-mcp."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False, help="Run live omiss.net tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: mark test as requiring omiss.net")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip_live = pytest.mark.skip(reason="Live tests disabled (use --live)")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _private_config_dir(tmp_path, monkeypatch):
    """No test touches the real settings folder or the real request spacing."""
    monkeypatch.setenv("OMISS_MCP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("NETLOGGER_MCP_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("NETLOGGER_MCP_CALLSIGN", raising=False)
