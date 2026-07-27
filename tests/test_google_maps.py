"""
Quick smoke test for the Google Maps transit tool.

Usage:
  uv run python scripts/test_google_maps.py <origin> <destination> [HH:MM]

Examples:
  uv run python scripts/test_google_maps.py "Colombo Fort" "Kandy"
  uv run python scripts/test_google_maps.py "Colombo Fort" "Galle" "07:00"
  uv run python scripts/test_google_maps.py "Maradana" "Kandy" "09:30"
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from commute_agent.tools.google_maps_tool import get_transit_routes
from commute_agent.core.exceptions import RouteNotFoundError

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

origin      = sys.argv[1]
destination = sys.argv[2]
time        = sys.argv[3] if len(sys.argv) > 3 else None

print(f"\n{'='*60}")
print(f"  {origin} -> {destination}" + (f" at {time}" if time else ""))
print(f"{'='*60}")

try:
    routes = get_transit_routes(origin, destination, time)
    for r in routes:
        print(f"  [{r.transit_mode.upper()}] route_id: {r.route_id}")
        for line in r.description.splitlines():
            print(f"    {line}")
        print()
except RouteNotFoundError as e:
    print(f"  [NO ROUTES] {e}")
except Exception as e:
    print(f"  [ERROR] {type(e).__name__}: {e}")
