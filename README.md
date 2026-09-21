# RouteOptimizer

[![CI](https://github.com/SethSorrellDev/routeoptimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/SethSorrellDev/routeoptimizer/actions/workflows/ci.yml)

A route-optimization web application that replaces manual stop sequencing for a
uniform-and-facility-services delivery operation. A driver's normal route runs
20–30 stops a day, each with its own delivery window, service duration, and
volume. RouteOptimizer solves that as a **Vehicle Routing Problem with Time
Windows (VRPTW)** and returns an ordered itinerary, a recommended departure
time, and the number of assistants the route needs — in under a second.

**Live demo:** https://routeoptimizer-fgk8.onrender.com

> Hosted on Render's free tier, which spins services down when idle. The first
> request after a quiet period can take up to 60 seconds to wake the instance.

**Demo login:** not yet provisioned — see "Creating a demo login" below.

---

## The Problem

Service representatives drive fixed daily routes delivering mats, uniforms, and
supplies. Every stop carries three constraints:

- **A time window** — when the customer will actually accept a delivery
- **A service duration** — how long the stop takes on the ground
- **A volume** — units of product, bounded by what the truck can hold

Sequencing those stops to minimize drive time while respecting every window is
**NP-hard**: the number of possible orderings grows factorially, so exhaustive
search stops being viable past a handful of stops. In practice the ordering
lives in a driver's head and on a paper manifest. A route that looks fine on
paper can quietly blow past a customer's close time three stops in, and nobody
finds out until the driver is standing at a locked gate.

RouteOptimizer makes that failure visible *before* the truck leaves, and
proposes a better ordering.

**Scope note:** this targets "normal routes" — step-van routes of 20–30 shorter
stops. Large single-account operations that occupy a full crew for a full day
are a staffing problem rather than a routing problem, and are deliberately out
of scope.

---

## How the Optimizer Works

The pipeline lives in [`app/optimizer/engine.py`](app/optimizer/engine.py):

1. **Cost matrix assembly** — reads cached road travel times and distances
   between the depot and every stop. The cache (`DistanceMatrixEntry`) means the
   routing API is called once per new pair, never once per optimization run.
2. **Nearest-neighbor construction** — greedily builds an initial route,
   choosing the closest *feasible* unvisited stop at each step and costing in
   any wait time a not-yet-open customer would impose.
3. **2-opt local search** — repeatedly tests reversing each contiguous segment,
   keeping a reversal only if it shortens total time *and* survives the
   constraint check. Repeats until no improvement remains.
4. **Constraint checking** — validates time windows, cumulative truck capacity,
   and maximum shift length.
5. **Departure recommendation** — back-calculates the latest departure that
   still reaches the first stop as it opens, so the truck isn't idling outside
   a closed customer.
6. **Assistant determination** — searches 0–3 assistants against empirical
   productivity factors (with diminishing returns) and reports the fewest that
   make the route feasible.

Output is a full itinerary with per-stop arrival and departure times, a
feasibility verdict, and explicit warnings naming any violated window.

---

## Screenshots

_Screenshots coming soon — results dashboard, route map, itinerary table, and
stop editor._

---

## Testing

```
84 tests · 99% statement coverage on the optimizer engine
```

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs on every push and pull request via GitHub Actions. It uses
in-memory SQLite and makes **no network calls** — travel times are written
directly into the cache table, which is exactly how the optimizer reads them in
production.

Coverage is concentrated where correctness actually matters:

| Area | What's covered |
|---|---|
| Constraint checking | Time-window violations, cumulative capacity overflow, shift-length overrun including the return leg |
| 2-opt | Improves a deliberately crossed route, never returns a worse one, preserves the stop set, keeps a feasible route feasible |
| Nearest-neighbor | Visits every stop exactly once, prefers the nearer stop, doesn't silently drop an unreachable one |
| Timing | Wait-time accounting, window flags, cumulative volume, sequence numbering |
| Assistants | Monotonic and diminishing productivity factors, minimum sufficient count, cannot paper over a capacity overflow, does not mutate the caller's matrix |
| Matrix assembly | Every `None` guard — unknown route, missing plant or stop coordinates, no stops on the requested day, missing cache entry |
| Seeds | Plant coordinates present and in the right hemisphere, idempotency, demo route fits the truck |

Two of these are **regression tests for bugs that actually shipped**, and both
fail if the fix is reverted:

- `test_optimize_return_time_is_never_before_the_last_stop_departure` — the
  dashboard once displayed a return time *earlier* than the truck's departure
  from its final stop, because `estimated_return` was re-summed from drive and
  service time and silently dropped wait time. Against the old code this test
  reports: `return 510 is before the last stop's departure 915`.
- `test_seed_plant_sets_coordinates` — the plant seed originally set a name and
  address but no latitude or longitude, so the first production optimizer run
  failed with *"Distance matrix could not be built."*

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask, SQLAlchemy, Flask-Migrate (Alembic) |
| Database | PostgreSQL (production and local dev) |
| Auth | Flask-Login, Flask-Bcrypt, role-based access (Manager / SSR) |
| Geocoding & routing | OpenRouteService, behind a swappable `DistanceProvider` |
| Maps | Leaflet.js + OpenStreetMap |
| CI | GitHub Actions (pytest on Python 3.12 and 3.13) |
| Deployment | Render — web service + managed PostgreSQL |

**Why the `DistanceProvider` abstraction?** The optimizer and geocoding code
never call OpenRouteService directly — only a thin wrapper does. Swapping
providers means rewriting one file, not touching the solver.

**Why PostgreSQL locally as well as in production?** SQLite has no real boolean
type and accepts things Postgres correctly rejects. The initial migration
against Postgres failed with *"column is of type boolean but default expression
is of type integer"* — SQLite had been silently swallowing
`server_default=sa.text('0')` on four boolean columns. Developing against the
production engine surfaced that immediately.

---

## Data Model

Twelve tables. The decisions worth calling out:

- **`RouteStop` is an association object**, not a plain join table. It carries
  per-route scheduling (`service_days`, `volume_override`) so one physical stop
  can sit on several routes with different schedules, instead of duplicating
  stop records.
- **`DistanceMatrixEntry` caches every ordered pair**, keyed by
  `(origin_type, origin_id, dest_type, dest_id)`. Travel times are asymmetric —
  one-way streets and turn restrictions are real — so A→B and B→A are stored
  separately.
- **`StopContact` is its own table.** The original design put a single contact
  name and phone on `Stop`; real customers have several.

---

## Running Locally

```bash
git clone https://github.com/SethSorrellDev/routeoptimizer.git
cd routeoptimizer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# Set SECRET_KEY, and ORS_API_KEY from https://openrouteservice.org (free tier)

flask db upgrade
python seed_roles.py
python seed_plant.py
python seed_demo.py      # optional: a five-stop demo route

flask --app run.py run
```

Then open http://127.0.0.1:5000 and register a Manager account.

`seed_demo.py` seeds stops **without** coordinates, since geocoding needs an API
key. With `ORS_API_KEY` set it geocodes them for you; otherwise use the
"Re-geocode from address" button on each stop. Rural and industrial addresses
are exactly where public geocoders go wrong, so every stop also accepts a manual
latitude and longitude — the plant's own address resolves about three miles off.

### Creating a demo login

Credentials are never committed. Pass them through the environment:

```bash
DEMO_USERNAME=demo DEMO_PASSWORD='choose-something' python seed_demo.py
```

---

## Project Status

**Working:** full CRUD for stops, routes, holidays and plant settings;
geocoding with manual override; distance-matrix caching; the VRPTW optimizer;
the results dashboard; per-stop schedule editing; 84 tests in CI.

**Known limitations, by priority rather than oversight:**

- Single vehicle per route — no fleet-wide optimization across trucks
- No OR-Tools cross-validation of the heuristic against a known optimum
- Render's free tier cold-starts the service and expires the database
  periodically without manual renewal

---

## Author

Built by Seth Sorrell. The problem comes from a route I drive myself; the
solution is an exercise in applying operations-research techniques to a
logistics problem I already understood from the ground up.
