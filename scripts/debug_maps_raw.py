"""Debug: print raw transit leg details from Google Maps API."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from commute_agent.tools.google_maps_tool import _client, _parse_departure_time

results = _client().directions(
    origin="Colombo Fort",
    destination="University of Ruhuna",
    mode="transit",
    alternatives=True,
    departure_time=_parse_departure_time("08:00"),
)

for ri, route in enumerate(results[:3]):
    print(f"\n=== Route {ri} ===")
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            if step.get("travel_mode") != "TRANSIT":
                continue
            d = step["transit_details"]
            line = d.get("line", {})
            print(f"  line.name       : {line.get('name')}")
            print(f"  line.short_name : {line.get('short_name')}")
            print(f"  vehicle.type    : {line.get('vehicle', {}).get('type')}")
            print(f"  departure_stop  : {d.get('departure_stop', {}).get('name')}")
            print(f"  arrival_stop    : {d.get('arrival_stop', {}).get('name')}")
            print(f"  departure_time  : {d.get('departure_time', {}).get('text')}")
            print(f"  arrival_time    : {d.get('arrival_time', {}).get('text')}")
            print()
