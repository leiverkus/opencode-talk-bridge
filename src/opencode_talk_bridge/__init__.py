"""opencode-talk-bridge: drive a local OpenCode instance from Nextcloud Talk.

A polling bridge (no webhooks) that forwards allowlisted Talk messages to a
local `opencode serve` HTTP API and posts the agent's replies back into the
conversation. See README.md for the threat model and the status-file contract.
"""

__version__ = "0.2.3"
