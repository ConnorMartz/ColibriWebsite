# This python script will automatically generate occultation events 

import json
from datetime import datetime, timedelta

# Elginfield Observatory coordinates
ELGINFIELD_LAT = 43.0739
ELGINFIELD_LON = -81.3158

# Simulated function that would normally query an API or local data source
def get_occultation_predictions():
    now = datetime.utcnow()
    # Example: simulate 12 future events
    return [
        {
            "name": f"Occultation Candidate {i+1}",
            "datetime_utc": (now + timedelta(days=i*3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "magnitude_drop": round(0.1 + 0.05*i, 2),
            "duration": f"{3+i}s",
            "visible_from_elginfield": True  # Placeholder; in real version you'd calculate this
        }
        for i in range(12)
    ]

def main():
    events = get_occultation_predictions()

    # Filter only events visible from Elginfield
    visible = [e for e in events if e["visible_from_elginfield"]]

    # Keep next 10 upcoming events
    visible = sorted(visible, key=lambda e: e["datetime_utc"])[:10]

    # Save as JSON
    with open("data/occultation_events.json", "w") as f:
        json.dump(visible, f, indent=2)

    print(f"✅ Wrote {len(visible)} events to data/occultation_events.json")

if __name__ == "__main__":
    main()
