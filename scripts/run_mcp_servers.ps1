# Launch the trip-lookup MCP server standalone (for manual testing/inspection
# with an MCP client, e.g. `mcp dev`). Agents normally spawn this themselves
# via mcp_servers/mcp_client.py over stdio — you don't need this running for
# the app itself to work.
#
# Usage: powershell -File scripts/run_mcp_servers.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

python -m trip_planner.mcp_servers.trip_lookup_server
