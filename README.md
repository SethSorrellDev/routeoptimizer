# RouteOptimizer

A route-optimization web application built to solve a real operational problem at the Cintas Frankfort, IN plant: **manually sequencing 20-30 daily service stops is slow, error-prone, and doesn't account for time windows, truck capacity, or crew size.** RouteOptimizer replaces that manual process with a Vehicle Routing Problem with Time Windows (VRPTW) solver that computes an optimized stop order, recommended departure time, and required assistant count, in seconds.

**Live demo:** https://routeoptimizer-fgk8.onrender.com

---

## The Problem

Cintas Service Sales Representatives (SSRs) drive fixed daily routes delivering mats, uniforms, and supplies to dozens of customers. Each stop has:

- A time window (when the customer is open or willing to accept a delivery)
- A service duration (how long the stop takes)
- A volume of goods to deliver (constrained by truck capacity)

Manually sequencing these stops to minimize drive time while respecting every time window is a classic **NP-hard combinatorial optimization problem** — the number of possible orderings grows factorially with the number of stops, making brute-force search impossible past a handful of stops. RouteOptimizer applies established heuristics to find a high-quality solution in well under a second.

**Scope note:** the app targets "normal routes" — step van routes with 20-30 shorter stops. Cintas also runs "super routes" (e.g. a single account requiring a full crew for a full day) — these are a staffing problem, not a routing problem, and are intentionally out of scope.

---

## How the Optimizer Works

1. **Cost matrix assembly** — pulls cached real-world driving times and distances (OpenRouteService) between the depot and every stop on the route.
2. **Nearest-neighbor construction** — builds an initial route by greedily visiting the closest feasible unvisited stop, respecting time windows.
3. **2-opt local search** — repeatedly tests reversing segments of the route, keeping any reversal that shortens total time while remaining feasible.
4. **Constraint checking** — validates the route against time windows, truck capacity, and maximum shift length.
5. **Departure time recommendation** — back-calculates the latest departure time that still reaches the first stop right as it opens.
6. **Assistant determination** — tests 0-3 assistants against empirically-derived productivity factors and recommends the fewest that make the route feasible.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask, SQLAlchemy, Flask-Migrate (Alembic) |
| Database | PostgreSQL (production + local dev) |
| Auth | Flask-Login, Flask-Bcrypt, role-based access (Manager / SSR) |
| Geocoding & Routing | OpenRouteService API (behind a swappable DistanceProvider abstraction) |
| Maps | Leaflet.js + OpenStreetMap tiles |
| Deployment | Render (Web Service + managed PostgreSQL) |

---

## Running Locally

```bash
git clone <repo-url>
cd routeoptimizer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: set SECRET_KEY and ORS_API_KEY

flask db upgrade
python seed_roles.py
python seed_plant.py

flask --app run.py run
```

---

## Author

Built by Seth Sorrell — Cintas Service Sales Representative, Frankfort, IN plant, pursuing a CS degree via IU Online. This project models a real workflow pain point from the role, built as a portfolio piece toward an internal transition into Cintas IT / software engineering.
