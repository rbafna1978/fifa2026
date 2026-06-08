"""Tools for the World Cup 2026 fan-logistics agent.

Curated, keyless data so runs are deterministic. Each function is a tool the
ADK agent can call; rich return values make for readable Phoenix traces.

Data provenance:
- `transit` / `gate_buffer_min`: plausible curated values for planning.
- `post_event_egress_min` / `egress_note`: HISTORICAL ESTIMATES of how long it
  realistically takes to clear the venue area after a large event, grounded in
  comparable past NFL games / concerts at each venue. These are NOT live
  match-day traffic and are labelled as estimates everywhere they surface.
- `accessibility`: REAL, sourced details from each venue's official
  accessibility page (source URL recorded per venue). Do not fabricate; if a
  fact is unknown for a venue it is left out / null and the agent should say so.
- `dietary` tags on food options are curated/approximate (planning hints), NOT a
  live menu guarantee.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Football time structure, encoded once (pure arithmetic, no lookups).
_NORMAL_END_MIN = 113   # 90 regulation + ~8 stoppage + 15 half-time
# Knockout extra-time tail: ~5 break + 30 extra time + ~7 ET stoppage + ~15 penalties/walk-up.
_KNOCKOUT_TAIL_MIN = 57  # -> latest end ~+170 min after kickoff

# Real 2026 World Cup host venues with plausible transit notes + sourced accessibility.
_VENUES = {
    "MetLife Stadium": {
        "city": "East Rutherford, NJ",
        "transit": "NJ Transit rail to Secaucus Junction, transfer to the Meadowlands line; "
                   "or coach bus 351 from Port Authority, NYC.",
        "gate_buffer_min": 75,
        # Egress estimate: official guidance notes post-event pickup runs ~25-45 min after a
        # sellout and advises waiting 20-30 min before heading out; rail back via Secaucus
        # adds crowding. Historical estimate from comparable Giants/Jets games, not live traffic.
        # Source: https://www.metlifestadium.com/plan-your-visit/a-z-guide (parking/egress)
        "post_event_egress_min": 60,
        "egress_note": "Historical estimate from comparable NFL sellouts (not live traffic): "
                       "~60 min to clear; staff advise waiting 20-30 min before leaving.",
        # Source: https://www.metlifestadium.com/plan-your-visit/accessibility
        "accessibility": {
            "parking": "Accessible parking in Lots E, F and G (parking pass + valid disability "
                       "license plate/placard required).",
            "entrances": "Elevators for guests with disabilities at the HCLTech, Verizon and "
                         "Moody's corners of the stadium.",
            "transit_dropoff": "Dedicated accessible drop-off in Lot C (between the Verizon Gate "
                               "and the HCLTech Gate); traffic staff direct guests there.",
            "companion_seating": "Wheelchair/low-mobility and companion seating on all levels. "
                                 "ADA info: (201) 559-1515 / adainfo@metlifestadium.com.",
            "source": "https://www.metlifestadium.com/plan-your-visit/accessibility",
        },
    },
    "SoFi Stadium": {
        "city": "Inglewood, CA",
        "transit": "Metro K Line to Downtown Inglewood station, then the free stadium shuttle "
                   "(~12 min). Rideshare drop-off lots fill early.",
        "gate_buffer_min": 90,
        # Egress estimate: Chargers/Rams guidance notes parking lots close ~1 hr after the game
        # and the Metro K Line + shuttle crowd heavily post-event. Historical estimate, not live.
        # Source: https://www.chargers.com/sofi-stadium/parking/
        "post_event_egress_min": 60,
        "egress_note": "Historical estimate from comparable NFL games/concerts (not live traffic): "
                       "~60 min; lots close ~1 hr after the game and the Metro shuttle queues.",
        # Source: https://www.sofistadium.com/plan-your-visit/accessibility (+ /accessible-parking)
        "accessibility": {
            "parking": "Licensed ADA parking in every parking zone (valid state ADA placard/"
                       "plate required).",
            "entrances": "All entries are accessible; accessibility podiums with waiting chairs "
                         "inside Entry 4, 8 and 10.",
            "transit_dropoff": "ADA drop-off/pick-up north of the stadium on Kareem Court "
                               "(suggested address 3178 Pincay Dr, Inglewood, CA 90305).",
            "companion_seating": "Wheelchair + companion seating with enhanced sight lines on "
                                 "every level and price point; up to 3 companions.",
            "source": "https://www.sofistadium.com/plan-your-visit/accessibility",
        },
    },
    "AT&T Stadium": {
        "city": "Arlington, TX",
        "transit": "Trinity Railway Express to CentrePort, transfer to the Arlington "
                   "Entertainment District shuttle. No direct rail to the stadium.",
        "gate_buffer_min": 75,
        # Egress estimate: no direct rail; departure depends on lot egress + the Entertainment
        # District shuttle / TRE, with ADA shuttles also running after events. Historical estimate
        # from comparable Cowboys games, not live traffic.
        # Source: https://attstadium.com/stadium-info/parking/
        "post_event_egress_min": 60,
        "egress_note": "Historical estimate from comparable NFL games (not live traffic): ~60 min; "
                       "no direct rail, so allow time for lot egress + shuttle/TRE back.",
        # Source: https://attstadium.com/stadium-info/accessibility/
        "accessibility": {
            "parking": "ADA parking (state placard/plate required, first-come) in Blue Lots "
                       "1/7/10/11/15 and Silver Lots 4/5/12/13/14; ADA shuttles run from Cowboys "
                       "lots to the stadium and after events.",
            "entrances": "All stadium entrances are flat/step-free with power-assisted entry doors.",
            "transit_dropoff": "Designated vehicle drop-off and pick-up zones (no direct rail; "
                               "TRE to CentrePort + Entertainment District shuttle).",
            "companion_seating": "Wheelchair + companion seating on all levels; folding companion "
                                 "chairs provided. Guest Services: (817) 892-4161.",
            "source": "https://attstadium.com/stadium-info/accessibility/",
        },
    },
    "Mercedes-Benz Stadium": {
        "city": "Atlanta, GA",
        "transit": "MARTA rail to GWCC/CNN Center (W1) or Vine City (W2), ~6 min walk.",
        "gate_buffer_min": 75,
        # Egress estimate: MARTA from Vine City / GWCC is relatively efficient but crowds heavily
        # right after the event. Historical estimate from comparable Falcons/Atlanta United games
        # and concerts, not live traffic.
        # Source: https://www.mercedesbenzstadium.com/accessibility (transit) + parking site
        "post_event_egress_min": 45,
        "egress_note": "Historical estimate from comparable events (not live traffic): ~45 min; "
                       "MARTA from Vine City/GWCC is efficient but queues right after the final whistle.",
        # Source: https://www.mercedesbenzstadium.com/accessibility
        "accessibility": {
            "parking": "ADA parking (first-come) in all decks/lots; nearest: HDBY, Silver Deck, "
                       "Red Deck, Orange Deck. Complimentary ADA shuttles from the Blue and Yellow Lots.",
            "entrances": "Gate 1, Gate 2 and the Silver Deck Bridge entrances are ADA accessible; "
                         "Guest Services Office (ADA accommodations) at Gate 1.",
            "transit_dropoff": "ADA drop-off/pick-up on Northside Dr. (between the pedestrian bridge "
                               "and Home Depot Backyard); ADA shuttle drops at Vine City MARTA (Gate 1).",
            "companion_seating": "Wheelchair + companion seating with enhanced sight lines on every "
                                 "level; Mobility Ambassadors provide wheelchair escorts.",
            "source": "https://www.mercedesbenzstadium.com/accessibility",
        },
    },
    "Lumen Field": {
        "city": "Seattle, WA",
        "transit": "Link light rail to Stadium station, ~3 min walk. Sounder rail on event days.",
        "gate_buffer_min": 60,
        # Egress estimate: Link light rail (Stadium / ID-Chinatown) in downtown Seattle clears
        # crowds reasonably quickly. Historical estimate from comparable Seahawks/Sounders games
        # and concerts, not live traffic.
        # Source: https://www.lumenfield.com/plan-your-visit/parking-transportation
        "post_event_egress_min": 45,
        "egress_note": "Historical estimate from comparable events (not live traffic): ~45 min; "
                       "Link light rail at Stadium/ID-Chinatown stations clears crowds steadily.",
        # Source: https://www.lumenfield.com/plan-your-visit-stadium-guide/accessibility-services-guide
        "accessibility": {
            "parking": "Accessible parking in the North Lot and Lumen Field Parking Garage; "
                       "additional ADA parking at the Union Station Garage (first-come).",
            "entrances": "Accessible Entrance on Level 2; all public gates are ADA-compliant "
                         "(incl. Northwest and Southwest gates) with elevators, ramps, wide concourses.",
            "transit_dropoff": "ADA drop-off on 1st Ave S and S Charles St (outside the Pro Shop); "
                               "Link light rail Stadium and ID/Chinatown stations are wheelchair-friendly.",
            "companion_seating": "Accessible/wheelchair-convertible seating across all areas and "
                                 "price levels; companion seating next to wheelchair spaces; "
                                 "wheelchair escort available at gate entry.",
            "source": "https://www.lumenfield.com/plan-your-visit-stadium-guide/accessibility-services-guide",
        },
    },
}

# Curated food options keyed by city. `dietary` tags are curated/approximate planning hints
# (vegan / vegetarian / halal / gluten_free), NOT a live menu guarantee.
_FOOD = {
    "East Rutherford, NJ": [
        {"name": "Redd's", "cuisine": "American", "price_per_person": 25,
         "dietary": ["vegetarian", "gluten_free"]},
        {"name": "El Mariachi", "cuisine": "Mexican", "price_per_person": 18,
         "dietary": ["vegetarian", "vegan", "gluten_free"]},
    ],
    "Inglewood, CA": [
        {"name": "Stevie's Creole Cafe", "cuisine": "Creole", "price_per_person": 30,
         "dietary": ["vegetarian"]},
        {"name": "Dulan's Soul Food", "cuisine": "Soul food", "price_per_person": 16,
         "dietary": ["vegetarian"]},
    ],
    "Arlington, TX": [
        {"name": "Cane Rosso", "cuisine": "Pizza", "price_per_person": 22,
         "dietary": ["vegetarian", "vegan"]},
        {"name": "Prince Lebanese Grill", "cuisine": "Lebanese", "price_per_person": 15,
         "dietary": ["vegetarian", "vegan", "halal", "gluten_free"]},
    ],
    "Atlanta, GA": [
        {"name": "Antico Pizza", "cuisine": "Pizza", "price_per_person": 20,
         "dietary": ["vegetarian"]},
        {"name": "Busy Bee Cafe", "cuisine": "Soul food", "price_per_person": 19,
         "dietary": ["vegetarian"]},
    ],
    "Seattle, WA": [
        {"name": "Mioposto", "cuisine": "Pizza", "price_per_person": 21,
         "dietary": ["vegetarian", "vegan"]},
        {"name": "Tat's Deli", "cuisine": "Sandwiches", "price_per_person": 14,
         "dietary": ["vegetarian"]},
    ],
}

_DIETARY_TAGS = {"vegan", "vegetarian", "halal", "gluten_free"}

# Public, ordered list of supported venues (for the web form dropdown / validation).
KNOWN_VENUES = tuple(_VENUES)


def get_match_logistics(venue: str) -> dict:
    """Look up the city, public-transit route, recommended gate-arrival buffer, post-event
    egress estimate, and sourced accessibility details for a 2026 World Cup venue.

    Args:
        venue: Stadium name, e.g. 'SoFi Stadium'.

    Returns:
        A dict with city, transit, gate_buffer_min, post_event_egress_min, egress_note, and
        accessibility (parking/entrances/transit_dropoff/companion_seating/source), or an error
        listing known venues.
    """
    info = _VENUES.get(venue)
    if not info:
        return {"error": f"Unknown venue '{venue}'.", "known_venues": list(_VENUES)}
    return {"venue": venue, **info}


def find_food_near(city: str, max_price_per_person: int, dietary: str = "") -> dict:
    """Find food options in a host city at or under a per-person budget, optionally filtered
    by a dietary constraint.

    Args:
        city: City string exactly as returned by get_match_logistics, e.g. 'Inglewood, CA'.
        max_price_per_person: Maximum per-person spend in USD.
        dietary: Optional dietary constraint — one of 'vegan', 'vegetarian', 'halal',
            'gluten_free'. Empty string means no dietary filter.

    Returns:
        A dict with the city, the filters applied, and a list of matching options (name,
        cuisine, price, dietary tags). If nothing matches, options is empty and a `note`
        says so honestly (dietary tags are curated hints, not a live menu guarantee).
    """
    diet = (dietary or "").strip().lower().replace("-", "_")
    if diet and diet not in _DIETARY_TAGS:
        return {"city": city, "error": f"Unknown dietary constraint '{dietary}'.",
                "known_dietary": sorted(_DIETARY_TAGS)}

    options = []
    for opt in _FOOD.get(city, []):
        if opt["price_per_person"] > max_price_per_person:
            continue
        if diet and diet not in opt["dietary"]:
            continue
        options.append(opt)

    result = {"city": city, "max_price_per_person": max_price_per_person,
              "dietary": diet or None, "options": options}
    if not options:
        result["note"] = (
            f"No curated option in {city} matches "
            f"{'a ' + diet + ' diet ' if diet else ''}within ${max_price_per_person}. "
            "Say so honestly rather than inventing a place.")
    return result


def estimate_match_end(kickoff: str, is_knockout: bool) -> dict:
    """Estimate the earliest and latest realistic end time of a match (pure arithmetic).

    Football time structure, encoded once:
    - Normal time ends ~+113 min after kickoff (90 regulation + ~8 stoppage + 15 half-time).
    - A knockout game that goes the distance adds an extra-time tail of ~+57 min
      (~5 break + 30 extra time + ~7 ET stoppage + ~15 penalties/walk-up) -> latest ~+170 min.

    Args:
        kickoff: Kickoff time as 'HH:MM' (24h).
        is_knockout: True for a knockout match (can run to extra time + penalties).

    Returns:
        A dict with kickoff, earliest_end, latest_end (all 'HH:MM'), is_knockout, the
        minute offsets used, and a note. Reserve plans against latest_end for the long tail.
    """
    t = datetime.strptime(kickoff, "%H:%M")
    earliest_min = _NORMAL_END_MIN
    latest_min = _NORMAL_END_MIN + (_KNOCKOUT_TAIL_MIN if is_knockout else 0)
    earliest = (t + timedelta(minutes=earliest_min)).strftime("%H:%M")
    latest = (t + timedelta(minutes=latest_min)).strftime("%H:%M")
    note = (
        f"Even a knockout game can finish in normal time (~+{earliest_min} min), but reserve "
        f"against the long tail: extra time + penalties can push the end to ~+{latest_min} min."
        if is_knockout else
        f"Group-stage game: ends in normal time, ~+{earliest_min} min after kickoff "
        "(no extra time or penalties).")
    return {
        "kickoff": kickoff,
        "earliest_end": earliest,
        "latest_end": latest,
        "is_knockout": is_knockout,
        "earliest_offset_min": earliest_min,
        "latest_offset_min": latest_min,
        "note": note,
    }


def build_day_plan(venue: str, kickoff: str, food_choice: str,
                   transit_cost: int, food_cost: int,
                   tickets_paid: bool = True, post_game_cost: int = 0) -> dict:
    """Assemble the final structured match-day plan after the other tools have been called.

    Args:
        venue: Stadium name.
        kickoff: Kickoff time, e.g. '16:00'.
        food_choice: The restaurant the user/agent selected.
        transit_cost: Estimated per-person transit cost in USD.
        food_cost: Estimated per-person food cost in USD.
        tickets_paid: If True, match tickets are already purchased, so the per-person budget
            applies only to transit + food + any post-game stop (ticket price is excluded).
        post_game_cost: Estimated per-person cost of an optional post-game food/dessert stop
            in USD (0 if none).

    Returns:
        A structured plan dict including a total per-person cost estimate and a cost breakdown
        (tickets are never priced here).
    """
    breakdown = {"transit": transit_cost, "food": food_cost}
    if post_game_cost:
        breakdown["post_game_stop"] = post_game_cost
    total = transit_cost + food_cost + post_game_cost
    return {
        "venue": venue,
        "kickoff": kickoff,
        "food_choice": food_choice,
        "tickets_paid": tickets_paid,
        "estimated_cost_per_person": total,
        "cost_breakdown": breakdown,
        "budget_note": (
            "Tickets already purchased — this budget covers transit, food"
            + (" and the post-game stop." if post_game_cost else ".")
            if tickets_paid else
            "Match-ticket price is NOT included in this estimate; budget shown covers transit, "
            "food" + (" and the post-game stop." if post_game_cost else ".")),
        "status": "ready",
    }
