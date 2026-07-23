"""Optimizer blueprint: triggers a run and serves results."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app.extensions import db
from app.models import Route, OptimizationResult, OptimizationResultStop
from app.optimizer.engine import optimize
import json

optimizer_bp = Blueprint("optimizer", __name__, url_prefix="/optimizer")


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash("You must be a Manager to access that page.", "danger")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return decorated


def _minutes_to_time_str(minutes: float) -> str:
    """Convert decimal minutes since midnight to HH:MM string."""
    h = int(minutes // 60) % 24
    m = int(minutes % 60)
    return f"{h:02d}:{m:02d}"


@optimizer_bp.route("/run/<int:route_id>", methods=["GET", "POST"])
@login_required
@manager_required
def run(route_id):
    route = Route.query.get_or_404(route_id)

    if request.method == "GET":
        return render_template("optimizer/run.html", route=route)

    day = request.form.get("day_of_week", "T")

    # Build matrix if needed
    from app.services.matrix import build_matrix_for_route
    matrix_result = build_matrix_for_route(route_id)
    if not matrix_result:
        flash("Distance matrix could not be built — check stop coordinates.", "danger")
        return redirect(url_for("optimizer.run", route_id=route_id))

    plan = optimize(route_id, day)
    if not plan:
        flash("Optimizer returned no result — check stop coordinates and service days.", "danger")
        return redirect(url_for("optimizer.run", route_id=route_id))

    # Persist result
    from datetime import time as time_type
    def mins_to_time(m):
        h = int(m // 60) % 24
        mn = int(m % 60)
        return time_type(h, mn)

    # Delete previous result for this route+day
    OptimizationResult.query.filter_by(
        route_id=route_id, day_of_week=day
    ).delete()
    db.session.flush()

    result = OptimizationResult(
        route_id=route_id,
        day_of_week=day,
        recommended_departure_time=mins_to_time(plan.departure_minutes),
        estimated_return_time=mins_to_time(plan.estimated_return_minutes),
        assistants_required=plan.assistants,
        total_distance_meters=plan.total_distance_m,
        total_drive_seconds=plan.total_drive_seconds,
        total_service_seconds=plan.total_service_seconds,
        capacity_utilization_pct=plan.capacity_utilization_pct,
        estimated_cost=round(plan.total_distance_m / 1000 * 0.621371 *
                             0.65, 2),  # km -> miles x fuel cost
        feasible=plan.feasible,
        warnings=json.dumps(plan.warnings),
    )
    db.session.add(result)
    db.session.flush()

    for sr in plan.stop_results:
        ors = OptimizationResultStop(
            optimization_result_id=result.id,
            stop_id=sr.node.node_id,
            sequence_order=sr.sequence,
            estimated_arrival_time=mins_to_time(sr.arrive_minutes),
            estimated_departure_time=mins_to_time(sr.depart_minutes),
            cumulative_volume=sr.cumulative_volume,
            time_window_ok=sr.time_window_ok,
        )
        db.session.add(ors)

    db.session.commit()
    flash("Optimization complete.", "success")
    return redirect(url_for("optimizer.results", result_id=result.id))


@optimizer_bp.route("/results/<int:result_id>")
@login_required
def results(result_id):
    result = OptimizationResult.query.get_or_404(result_id)
    route = result.route
    plant = route.plant
    warnings = json.loads(result.warnings) if result.warnings else []

    # Build map data: plant + stops in order
    map_points = [{
        "name": plant.name,
        "lat": plant.latitude,
        "lon": plant.longitude,
        "type": "plant",
    }]
    for ors in result.result_stops:
        s = ors.stop
        map_points.append({
            "name": s.name,
            "lat": s.latitude,
            "lon": s.longitude,
            "type": "stop",
            "seq": ors.sequence_order,
            "arrive": ors.estimated_arrival_time.strftime("%H:%M") if ors.estimated_arrival_time else "",
            "depart": ors.estimated_departure_time.strftime("%H:%M") if ors.estimated_departure_time else "",
            "ok": ors.time_window_ok,
        })
    # Close the loop back to plant
    map_points.append({
        "name": plant.name,
        "lat": plant.latitude,
        "lon": plant.longitude,
        "type": "return",
    })

    return render_template("optimizer/results.html",
                           result=result,
                           route=route,
                           plant=plant,
                           warnings=warnings,
                           map_points=map_points)
