"""Tools for the World Cup 2026 fan-logistics agent.

Curated, keyless data so runs are deterministic. Each function is a tool the
ADK agent can call; rich return values make for readable Phoenix traces.
"""
from __future__ import annotations

# Real 2026 World Cup host venues with plausible transit notes.
_VENUES = {
    "MetLife Stadium": {
        "city": "East Rutherford, NJ",
        "transit": "NJ Transit rail to Secaucus Junction, transfer to the Meadowlands line; "
                   "or coach bus 351 from Port Authority, NYC.",
        "gate_buffer_min": 75,
    },
    "SoFi Stadium": {
        "city": "Inglewood, CA",
        "transit": "Metro K Line to Downtown Inglewood station, then the free stadium shuttle "
                   "(~12 min). Rideshare drop-off lots fill early.",
        "gate_buffer_min": 90,
    },
    "AT&T Stadium": {
        "city": "Arlington, TX",
        "transit": "Trinity Railway Express to CentrePort, transfer to the Arlington "
                   "Entertainment District shuttle. No direct rail to the stadium.",
        "gate_buffer_min": 75,
    },
    "Mercedes-Benz Stadium": {
        "city": "Atlanta, GA",
        "transit": "MARTA rail to GWCC/CNN Center (W1) or Vine City (W2), ~6 min walk.",
        "gate_buffer_min": 75,
    },
    "Lumen Field": {
        "city": "Seattle, WA",
        "transit": "Link light rail to Stadium station, ~3 min walk. Sounder rail on event days.",
        "gate_buffer_min": 60,
    },
}

# Curated food options keyed by city: (name, cuisine, price_per_person_usd).
_FOOD = {
    "East Rutherford, NJ": [("Redd's", "American", 25), ("El Mariachi", "Mexican", 18)],
    "Inglewood, CA": [("Stevie's Creole Cafe", "Creole", 30), ("Dulan's Soul Food", "Soul food", 16)],
    "Arlington, TX": [("Cane Rosso", "Pizza", 22), ("Prince Lebanese Grill", "Lebanese", 15)],
    "Atlanta, GA": [("Antico Pizza", "Pizza", 20), ("Busy Bee Cafe", "Soul food", 19)],
    "Seattle, WA": [("Mioposto", "Pizza", 21), ("Tat's Deli", "Sandwiches", 14)],
}


def get_match_logistics(venue: str) -> dict:
    """Look up the city, public-transit route, and recommended gate-arrival buffer for a
    2026 World Cup venue.

    Args:
        venue: Stadium name, e.g. 'SoFi Stadium'.

    Returns:
        A dict with city, transit, and gate_buffer_min, or an error listing known venues.
    """
    info = _VENUES.get(venue)
    if not info:
        return {"error": f"Unknown venue '{venue}'.", "known_venues": list(_VENUES)}
    return {"venue": venue, **info}


def find_food_near(city: str, max_price_per_person: int) -> dict:
    """Find food options in a host city at or under a per-person budget.

    Args:
        city: City string exactly as returned by get_match_logistics, e.g. 'Inglewood, CA'.
        max_price_per_person: Maximum per-person spend in USD.

    Returns:
        A dict with the city and a list of matching options (name, cuisine, price).
    """
    options = [
        {"name": n, "cuisine": c, "price_per_person": p}
        for (n, c, p) in _FOOD.get(city, [])
        if p <= max_price_per_person
    ]
    return {"city": city, "max_price_per_person": max_price_per_person, "options": options}


def build_day_plan(venue: str, kickoff: str, food_choice: str,
                   transit_cost: int, food_cost: int) -> dict:
    """Assemble the final structured match-day plan after the other tools have been called.

    Args:
        venue: Stadium name.
        kickoff: Kickoff time, e.g. '16:00'.
        food_choice: The restaurant the user/agent selected.
        transit_cost: Estimated per-person transit cost in USD.
        food_cost: Estimated per-person food cost in USD.

    Returns:
        A structured plan dict including a total per-person cost estimate.
    """
    return {
        "venue": venue,
        "kickoff": kickoff,
        "food_choice": food_choice,
        "estimated_cost_per_person": transit_cost + food_cost,
        "cost_breakdown": {"transit": transit_cost, "food": food_cost},
        "status": "ready",
    }
