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

def fetch_occultations(start_date: str, end_date: str):
    params = {"start_date": start_date, "end_date": end_date}
    r = requests.get(LOPD_API_URL, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    events = data.get("results", data)

    # NEW: write a tiny debug snapshot so we can see the schema
    try:
        snap = events[:3] if isinstance(events, list) else events
        with open("data/_debug_raw_events.json", "w") as f:
            json.dump(snap, f, indent=2)
        print("📝 Wrote data/_debug_raw_events.json (first 3 events)")
    except Exception as e:
        print(f"⚠️ Could not write debug snapshot: {e}")

    return events

# =============================
# Extract datetime string from event
# =============================
def parse_dt_str(ev):
    # Try a wide net of possible keys
    for k in [
        "datetime", "datetime_utc", "time", "utc_time", "event_time",
        "epoch", "epoch_utc", "date_time"
    ]:
        if k in ev and ev[k]:
            return str(ev[k])
    return None

# =============================
# Extract datetime string from event
# =============================
def parse_ra_dec(ev):
    """
    Return (ra_deg, dec_deg) in degrees, or (None, None).
    Try multiple schemas: object coords, star coords, Greek names, underscores, etc.
    """
    candidates = [
        ("ra_deg", "dec_deg"), ("ra", "dec"),
        ("RA_deg", "DEC_deg"), ("RA", "DEC"),
        ("object_ra_deg", "object_dec_deg"),
        ("target_ra_deg", "target_dec_deg"),
        ("alpha", "delta"), ("alpha_deg", "delta_deg"),
        ("star_ra_deg", "star_dec_deg"),
        ("star_ra", "star_dec"),
        ("alpha_star", "delta_star"),
        ("ra_obj", "dec_obj"), ("raStar", "decStar"),
    ]
    for ra_k, dec_k in candidates:
        if ra_k in ev and dec_k in ev:
            try:
                return float(ev[ra_k]), float(ev[dec_k])
            except Exception:
                pass
    return None, None

# =============================
# Visibility filter
# =============================
def filter_visible(events, min_alt_deg=15.0, sun_alt_max_deg=-6.0):
    """
    Keep only events visible from Elginfield Observatory.

    Conditions:
      - Target altitude above min_alt_deg
      - Sun altitude below sun_alt_max_deg (nighttime / twilight cutoff)
      - Event occurs in the future

    Parameters:
        events (list): List of raw event dicts
        min_alt_deg (float): Minimum altitude of target above horizon
        sun_alt_max_deg (float): Maximum Sun altitude (for darkness condition)

    Returns:
        list: Filtered list of visible events
    """
    out = []
    now = datetime.now(timezone.utc)
    for ev in events:
        dt_str = parse_dt_str(ev)
        if not dt_str:
            continue
        try:
            obstime = Time(dt_str)
        except Exception:
            continue
        # reject past events
        try:
            if obstime.to_datetime(timezone.utc) <= now:
                continue
        except Exception:
            pass

        ra_deg, dec_deg = parse_ra_dec(ev)
        if ra_deg is None or dec_deg is None:
            continue

        try:
            target = SkyCoord(ra_deg*u.deg, dec_deg*u.deg)
            altaz = target.transform_to(AltAz(obstime=obstime, location=ELGINFIELD))
            sun_alt = get_sun(obstime).transform_to(AltAz(obstime=obstime, location=ELGINFIELD)).alt
        except Exception:
            continue

        if altaz.alt.deg >= min_alt_deg and sun_alt.deg <= sun_alt_max_deg:
            out.append(ev)
    return out


# =============================
# Sort events by time
# =============================
def sort_by_time(events):
    """
    Sort events chronologically by their UTC datetime.
    If datetime is missing, places them at the end.
    """
    def key(ev):
        return parse_dt_str(ev) or "9999-12-31T00:00:00Z"
    return sorted(events, key=key)
    
# =============================
# Main pipeline
# =============================
def main():
    """
    Master workflow:
      - Query the LIneA API
      - Progressively expand time window (90 → 365 days)
      - Relax visibility thresholds if necessary
      - Ensure at least 5 upcoming visible events
      - Save top 10 to data/occultation_events.json
    """
    now = datetime.now(timezone.utc).date()

    # Progressive search windows (days)
    windows = [90, 180, 270, 365]

    # Visibility thresholds: (min_alt_deg, max_sun_alt_deg)
    thresholds = [
        (15.0, -12.0),
        (12.0, -8.0),
        (10.0, -6.0),
        (8.0, -3.0),
        (5.0, 0.0)
    ]

    collected = []

    # Try progressively larger date windows and looser thresholds
    for days in windows:
        start = now.isoformat()
        end = (now + timedelta(days=days)).isoformat()

        try:
            raw = fetch_occultations(start, end)
        except Exception as e:
            print(f"⚠️ Fetch failed for {start}..{end}: {e}")
            continue

        for min_alt, sun_limit in thresholds:
            visible = filter_visible(raw, min_alt_deg=min_alt, sun_alt_max_deg=sun_limit)
            visible = sort_by_time(visible)

            # De-duplicate by (datetime, name)
            dedup = {}
            for ev in visible:
                dt = parse_dt_str(ev) or "na"
                name = ev.get("name") or ev.get("target") or ev.get("object") or "unknown"
                dedup[(dt, name)] = ev
            visible = list(dedup.values())

            if len(visible) >= 5:
                collected = visible
                print(f"✅ Found {len(visible)} visible events in {days}d window at alt≥{min_alt}°, sun≤{sun_limit}°")
                break  # thresholds loop
        if len(collected) >= 5:
            break  # windows loop

    # Fallback if fewer than 5 events found
    if len(collected) < 5:
        try:
            collected = visible
            print(f"ℹ️ Fewer than 5 events found; returning {len(collected)}")
        except NameError:
            collected = []
            print("ℹ️ No events found at all.")

    # Keep top 10
    final_events = sort_by_time(collected)[:10]

    # Write output JSON
    with open("data/occultation_events.json", "w") as f:
        json.dump(final_events, f, indent=2)

    print(f"✅ Wrote {len(final_events)} events to data/occultation_events.json")


# =============================
# Entrypoint
# =============================
if __name__ == "__main__":
    main()
