"""Flight data sources. Both return the same shape, so the rest of the code never
cares where a price came from:

    {"airline": str, "depart": "HH:MM", "arrive": "HH:MM", "overnight": bool,
     "price": int (TWD, total for all passengers), "lcc": bool, "source": str}
"""

import os

import requests

# Low-cost carriers flying TPE-KIX; matched against names (zh/en) and IATA codes.
LCC_NAMES = ("tigerair", "虎航", "peach", "樂桃", "jetstar", "捷星", "scoot", "酷航",
             "zipair", "airasia", "亞洲航空", "亞航", "vietjet", "越捷")
LCC_CODES = {"IT", "MM", "GK", "3K", "TR", "ZG", "D7", "FD", "VJ", "VZ"}


class SourceError(Exception):
    """The source failed or returned nothing usable."""


def is_lcc(name: str, code: str = "") -> bool:
    low = (name or "").lower()
    return code.upper() in LCC_CODES or any(n in low for n in LCC_NAMES)


def _hhmm(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}"


def google_flights(origin: str, dest: str, date: str, adults: int, children: int) -> list[dict]:
    from fast_flights import FlightQuery, Passengers, create_query, get_flights

    q = create_query(
        flights=[FlightQuery(date=date, from_airport=origin, to_airport=dest, max_stops=0)],
        trip="one-way", seat="economy",
        passengers=Passengers(adults=adults, children=children),
        language="zh-TW", currency="TWD",
    )
    try:
        results = get_flights(q)
    except Exception as e:  # blocked, layout change, network...
        raise SourceError(f"fast-flights: {type(e).__name__}: {e}") from e

    out = []
    for r in results:
        if len(r.flights) != 1 or not r.price:
            continue  # direct flights only
        leg = r.flights[0]
        name = "、".join(r.airlines)
        out.append({
            "airline": name,
            "depart": _hhmm(*leg.departure.time),
            "arrive": _hhmm(*leg.arrival.time),
            "overnight": tuple(leg.arrival.date) != tuple(leg.departure.date),
            "price": int(r.price),
            "lcc": is_lcc(name),
            "source": "google",
        })
    if not out:
        raise SourceError("fast-flights: empty result")
    return out


IGNAV_URL = "https://ignav.com/api/fares/one-way"
_rates: dict[str, float] = {}


def to_twd(amount: float, currency: str) -> int:
    """Convert a price to TWD with a free daily exchange-rate feed (cached per run)."""
    if currency in (None, "", "TWD"):
        return int(round(amount))
    if currency not in _rates:
        try:
            r = requests.get(f"https://open.er-api.com/v6/latest/{currency}", timeout=30)
            _rates[currency] = float(r.json()["rates"]["TWD"])
        except (requests.RequestException, KeyError, ValueError) as e:
            raise SourceError(f"ignav: cannot convert {currency} to TWD: {e}") from e
    return int(round(amount * _rates[currency]))


def _name(v) -> str:
    return (v.get("name") or v.get("code") or "") if isinstance(v, dict) else (v or "")


def ignav_raw(origin: str, dest: str, date: str, adults: int, children: int) -> dict:
    key = os.environ.get("IGNAV_API_KEY")
    if not key:
        raise SourceError("ignav: IGNAV_API_KEY not set")
    body = {"origin": origin, "destination": dest, "departure_date": date,
            "adults": adults, "children": children, "cabin_class": "economy",
            "max_stops": 0, "market": "TW"}
    try:
        resp = requests.post(IGNAV_URL, json=body, timeout=60,
                             headers={"X-Api-Key": key, "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise SourceError(f"ignav: {e}") from e
    if resp.status_code != 200:
        raise SourceError(f"ignav: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.json()


def ignav(origin: str, dest: str, date: str, adults: int, children: int) -> list[dict]:
    return parse_ignav(ignav_raw(origin, dest, date, adults, children))


def parse_ignav(data: dict) -> list[dict]:
    out = []
    for it in data.get("itineraries", []):
        price = (it.get("price") or {})
        segs = (it.get("outbound") or {}).get("segments") or []
        if len(segs) != 1 or price.get("amount") is None:
            continue
        s = segs[0]
        dep = s.get("departure_time_local") or ""
        arr = s.get("arrival_time_local") or ""
        code = s.get("marketing_carrier_code") or ""
        name = _name((it.get("outbound") or {}).get("carrier")) or _name(s.get("operating_carrier_name")) or code
        out.append({
            "airline": name,
            "depart": dep[11:16],
            "arrive": arr[11:16],
            "overnight": arr[:10] != dep[:10],
            "price": to_twd(float(price["amount"]), price.get("currency")),
            "lcc": is_lcc(name, code),
            "source": "ignav",
        })
    if not out:
        raise SourceError("ignav: empty result")
    return out


def google_flights_link(origin: str, dest: str, depart: str, ret: str, adults: int, children: int) -> str:
    """Round-trip search page on Google Flights for the booking button."""
    from fast_flights import FlightQuery, Passengers, create_query

    q = create_query(
        flights=[FlightQuery(date=depart, from_airport=origin, to_airport=dest, max_stops=0),
                 FlightQuery(date=ret, from_airport=dest, to_airport=origin, max_stops=0)],
        trip="round-trip", seat="economy",
        passengers=Passengers(adults=adults, children=children),
        language="zh-TW", currency="TWD",
    )
    return q.url()
