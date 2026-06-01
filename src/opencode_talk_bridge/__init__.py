"""opencode-talk-bridge: drive a local OpenCode instance from Nextcloud Talk.

A polling bridge (no webhooks) that forwards allowlisted Talk messages to a
local `opencode serve` HTTP API and posts the agent's replies back into the
conversation. See README.md for the threat model and the status-file contract.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    # Single source of truth: the version declared in pyproject.toml.
    __version__ = _version("opencode-talk-bridge")
except PackageNotFoundError:  # running from a raw checkout without an install
    __version__ = "0.0.0+unknown"
