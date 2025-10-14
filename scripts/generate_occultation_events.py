# This python script will automatically generate occultation events 
import json
import requests
from datetime import datetime, timedelta, timezone
from astropy.coordinates import EarthLocation, SkyCoord, AltAz, get_sun
from astropy.time import Time
import astropy.units as u
import numpy as np

# =============================
# Elginfield Observatory coordinates
# =============================
ELGINFIELD_LAT = 43.0739
ELGINFIELD_LON = -81.3158
ELGINFIELD_ALT = 326  # meters
ELGINFIELD = EarthLocation(lat=ELGINFIELD_LAT*u.deg, lon=ELGINFIELD_LON*u.deg, height=ELGINFIELD_ALT*u.m)

# =============================
# API source for occultation predictions
# =============================
LOPD_API_URL = "https://solarsystem.linea.org.br/api/occultations"

def fetch_occultations(start_date, end_date):
    """Fetch occultation predictions from LIneA API."""
    params = {
        "start_date": start_date,
        "end_date": end_date,
        # "magnitude_limit": 18,  # (uncomment if API supports filtering)
    }

    print(f"📡 Fetching occultation data from {start_date} to {end_date}...")
    r = requests.get(LOPD_API_URL, params=params)
    r.raise_for_status()
    data = r.json()

    # The API may return results directly or within 'results'
    events = data.get("results", data)
    print(f"✅ Retrieved {len(events)} total events from API")
    return events

# =============================
# Visibility filter
# =============================
def filter_visible(events):
    """Filter events visible from Elginfield (above horizon & nighttime)."""
    visible = []
    now = datetime.now(timezone.utc)

    for ev in events:
        # Try to read event info
        try:
            dt_str = ev.get("datetime") or ev.get("datetime_utc")
            ra = float(ev.get("ra_deg") or ev.get("ra"))     # degrees
            dec = float(ev.get("dec_deg") or ev.get("dec"))  # degrees
        except Exception as e:
            print(f"⚠️ Skipping malformed event: {e}")
            continue

        # Convert to Astropy Time object
        try:
            obstime = Time(dt_str)
        except Exception:
            continue

        # Convert target to Alt/Az for Elginfield
        target = SkyCoord(ra*u.deg, dec*u.deg)
        altaz = target.transform_to(AltAz(obstime=obstime, location=ELGINFIELD))

        # Compute Sun altitude to exclude daylight events
        sun_alt = get_sun(obstime).transform_to(AltAz(obstime=obstime, location=ELGINFIELD)).alt

        if altaz.alt.deg > 15 and sun_alt.deg < -6:  # >15° altitude and Sun below horizon (civil twilight)
            visible.append(ev)

    print(f"✅ {len(visible)} events visible from Elginfield")
    return visible
    
# =============================
# Main pipeline
# =============================
def main():
    now = datetime.now(timezone.utc)
    start = now.date().isoformat()
    end = (now.date() + timedelta(days=90)).isoformat()

    events = fetch_occultations(start, end)
    visible = filter_visible(events)

    # Sort by datetime
    try:
        visible_sorted = sorted(visible, key=lambda e: e.get("datetime") or e.get("datetime_utc"))
    except Exception:
        visible_sorted = visible

    # Keep next 10
    next10 = visible_sorted[:10]

    with open("data/occultation_events.json", "w") as f:
        json.dump(next10, f, indent=2)

    print(f"✅ Wrote {len(next10)} events to data/occultation_events.json")


if __name__ == "__main__":
    main()
