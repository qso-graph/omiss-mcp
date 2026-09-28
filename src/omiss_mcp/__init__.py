"""MCP server for OMISS: net schedule, members, check-in history, Statehood, officers and awards."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Final

try:
    _pkg_version = version("omiss-mcp")
except PackageNotFoundError:  # local dev / editable installs without dist metadata
    _pkg_version = "0.0.0-dev"

__version__: Final[str] = _pkg_version

# What this server reads: omiss.net's public pages (the "Facelift" site), as of
# 2026-09. There is no published API or version, so this names the layout.
__spec_version__: Final[str] = "omiss.net-facelift-2026-09"

# Version of the records the tools return (schema/contract.schema.json).
__contract_version__: Final[str] = "0.1"
