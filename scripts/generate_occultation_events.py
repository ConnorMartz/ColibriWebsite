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
HEADERS = {
    # Some APIs reject Python's default UA; pretend to be a browser
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ColibriBot/1.0"
}

def fetch_occultations(start_date: str, end_date: str):
    """
    Query LIneA Occultation API for a given date range.
    Returns a list of event dicts. Also writes a tiny debug snapshot.
    """
    params = {"start_date": start_date, "end_date": end_date}
    print(f"📡 GET {LOPD_API_URL} {params}")
    r = requests.get(LOPD_API_URL, params=params, headers=HEADERS, timeout=60)
    print(f"🔗 status={r.status_code}")
    r.raise_for_status()
    data = r.json()

    # API shape: {"count": ..., "results": [ ... ]}
    events = data.get("results", data if isinstance(data, list) else [])
    if not isinstance(events, list):
        events = []

    # Write a small debug snapshot (first 3 items) so we can see actual keys in the repo
    try:
        with open("data/_debug_raw_events.json", "w") as f:
            json.dump(events[:3], f, indent=2)
        print("📝 Wrote data/_debug_raw_events.json")
    except Exception as e:
        print(f"⚠️ Could not write debug snapshot: {e}")

    print(f"✅ API returned {len(events)} items")
    return events

# =============================
# Extract datetime string from event
# =============================
def parse_dt_str(ev):
    """
    Extract a UTC datetime string. LIneA uses 'date_time'.
    """
    for k in [
        "date_time",  # LIneA
        "datetime", "datetime_utc", "time", "utc_time", "event_time",
        "epoch", "epoch_utc", "dateTime"
    ]:
        v = ev.get(k)
        if v:
            return str(v)
    return None

# =============================
# Extract datetime string from event
# =============================
def parse_ra_dec(ev):
    """
    Prefer star coordinates for pointing; fall back to target coords.
    """
    # LIneA preferred keys:
    if "ra_star_deg" in ev and "dec_star_deg" in ev:
        try:
            return float(ev["ra_star_deg"]), float(ev["dec_star_deg"])
        except Exception:
            pass
    if "ra_target_deg" in ev and "dec_target_deg" in ev:
        try:
            return float(ev["ra_target_deg"]), float(ev["dec_target_deg"])
        except Exception:
            pass

    # Generic fallbacks
    candidates = [
        ("ra_deg", "dec_deg"), ("ra", "dec"),
        ("RA_deg", "DEC_deg"), ("RA", "DEC"),
        ("alpha", "delta"), ("alpha_deg", "delta_deg"),
        ("star_ra", "star_dec"), ("raStar", "decStar"),
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
    Keep events visible from Elginfield (altitude & sun constraints; future only).
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

        # future only
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

    print(f"🔭 Visible after cuts (alt≥{min_alt_deg}°, sun≤{sun_alt_max_deg}°): {len(out)}")
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
# Normalize to a stable output schema
# =============================
def normalize(ev):
    """
    Return a dict with stable keys used by the website:
      name, datetime_utc, magnitude_drop, duration, ra_deg, dec_deg
    """
    name = ev.get("name") or ev.get("principal_designation") or ev.get("alias") or "Occultation"
    when = parse_dt_str(ev)
    ra_deg, dec_deg = parse_ra_dec(ev)
    return {
        "name": name,
        "datetime_utc": when,
        "magnitude_drop": ev.get("magnitude_drop"),
        "duration": ev.get("event_duration"),
        "ra_deg": ra_deg,
        "dec_deg": dec_deg
    }
    
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
    windows = [90, 180, 270, 365]  # progressively larger ranges
    thresholds = [(15.0, -12.0), (12.0, -8.0), (10.0, -6.0), (8.0, -3.0), (5.0, 0.0)]

    collected = []
    fallback_any = []

    for days in windows:
        start = now.isoformat()
        end = (now + timedelta(days=days)).isoformat()

        try:
            raw = fetch_occultations(start, end)
        except Exception as e:
            print(f"❌ fetch failed for {start}..{end}: {e}")
            continue

        # Keep a sorted copy without visibility filtering (for a graceful fallback)
        fallback_any = sort_by_time(raw)[:10] if isinstance(raw, list) else []

        for min_alt, sun_limit in thresholds:
            visible = filter_visible(raw, min_alt_deg=min_alt, sun_alt_max_deg=sun_limit)
            visible = sort_by_time(visible)

            # de-dup by (datetime, name)
            dedup = {}
            for ev in visible:
                dt = parse_dt_str(ev) or "na"
                nm = ev.get("name") or ev.get("principal_designation") or ev.get("alias") or "Occultation"
                dedup[(dt, nm)] = ev
            visible = list(dedup.values())

            if len(visible) >= 5:
                collected = visible
                print(f"✅ Using {len(visible)} visible events from {days}d window @ alt≥{min_alt}°, sun≤{sun_limit}°")
                break
        if len(collected) >= 5:
            break

    # If still <5, fall back so the site isn't empty while we tune filters
    if len(collected) < 5:
        if fallback_any:
            print(f"ℹ️ Falling back to unfiltered events: {len(fallback_any)}")
            collected = fallback_any
        else:
            collected = []
            print("ℹ️ No events found at all.")

    # Normalize and keep top 10
    final_events = [normalize(ev) for ev in sort_by_time(collected)[:10]]

    with open("data/occultation_events.json", "w") as f:
        json.dump(final_events, f, indent=2)

    print(f"✅ Wrote {len(final_events)} events to data/occultation_events.json")

# =============================
# Entrypoint
# =============================
if __name__ == "__main__":
    main()
