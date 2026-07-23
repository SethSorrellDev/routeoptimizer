"""Manager blueprint: CRUD for Stop, Route, Holiday.

(Final version: includes the Phase 2 geocoding hooks on stops and the
Phase 2 map view at the bottom.)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app.extensions import db
from app.models import (Plant, Stop, StopContact, Route, RouteStop,
                        User, Role, Holiday, StopClosure)
from app.manager.forms import (StopForm, RouteForm, RouteStopForm,
                                HolidayForm, StopClosureForm)

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash("You must be a Manager to access that page.", "danger")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return decorated


def get_plant():
    return db.get_or_404(Plant, 1)


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------
@manager_bp.route("/stops")
@login_required
@manager_required
def stop_list():
    plant = get_plant()
    stops = Stop.query.filter_by(plant_id=plant.id).order_by(Stop.name).all()
    return render_template("manager/stop_list.html", stops=stops)


@manager_bp.route("/stops/new", methods=["GET", "POST"])
@login_required
@manager_required
def stop_new():
    plant = get_plant()
    form = StopForm()
    if form.validate_on_submit():
        stop = Stop(
            plant_id=plant.id,
            name=form.name.data,
            address=form.address.data,
            latitude=form.latitude.data,
            longitude=form.longitude.data,
            service_type=form.service_type.data or None,
            service_time_solo_minutes=form.service_time_solo_minutes.data,
            open_time=form.open_time.data,
            close_time=form.close_time.data,
            volume_units=form.volume_units.data,
            special_instructions=form.special_instructions.data,
        )
        db.session.add(stop)
        db.session.flush()
        for c in form.contacts.data:
            if c["name"]:
                db.session.add(StopContact(
                    stop_id=stop.id,
                    name=c["name"],
                    phone=c["phone"],
                ))
        db.session.commit()

        # Auto-geocode if address present and no manual coords given
        if stop.address and not (stop.latitude and stop.longitude):
            from app.services.geocoding import geocode_stop
            if geocode_stop(stop):
                flash(f"Stop '{stop.name}' created and geocoded.", "success")
            else:
                flash(f"Stop '{stop.name}' created — geocoding failed, "
                      f"set coordinates manually.", "warning")
        else:
            flash(f"Stop '{stop.name}' created.", "success")
        return redirect(url_for("manager.stop_list"))
    return render_template("manager/stop_form.html", form=form, title="New Stop")


@manager_bp.route("/stops/<int:stop_id>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def stop_edit(stop_id):
    stop = db.get_or_404(Stop, stop_id)
    form = StopForm(obj=stop)
    if request.method == "GET":
        while len(form.contacts) > 0:
            form.contacts.pop_entry()
        for contact in stop.contacts:
            form.contacts.append_entry({
                "name": contact.name,
                "phone": contact.phone or "",
            })
        if len(form.contacts) == 0:
            form.contacts.append_entry()
    if form.validate_on_submit():
        stop.name = form.name.data
        stop.address = form.address.data
        stop.latitude = form.latitude.data
        stop.longitude = form.longitude.data
        stop.service_type = form.service_type.data or None
        stop.service_time_solo_minutes = form.service_time_solo_minutes.data
        stop.open_time = form.open_time.data
        stop.close_time = form.close_time.data
        stop.volume_units = form.volume_units.data
        stop.special_instructions = form.special_instructions.data
        for c in stop.contacts:
            db.session.delete(c)
        db.session.flush()
        for c in form.contacts.data:
            if c["name"]:
                db.session.add(StopContact(
                    stop_id=stop.id,
                    name=c["name"],
                    phone=c["phone"],
                ))
        db.session.commit()
        flash(f"Stop '{stop.name}' updated.", "success")
        return redirect(url_for("manager.stop_list"))
    return render_template("manager/stop_form.html", form=form, title="Edit Stop")


@manager_bp.route("/stops/<int:stop_id>/geocode", methods=["POST"])
@login_required
@manager_required
def stop_geocode(stop_id):
    """Re-geocode a stop from its address — triggered by the UI button."""
    stop = db.get_or_404(Stop, stop_id)
    if not stop.address:
        flash("No address on file — add one first.", "warning")
        return redirect(url_for("manager.stop_edit", stop_id=stop.id))
    from app.services.geocoding import geocode_stop
    # Force re-geocode by clearing existing coords first
    stop.latitude = None
    stop.longitude = None
    db.session.commit()
    if geocode_stop(stop):
        flash(f"Geocoded OK: {stop.latitude:.6f}, {stop.longitude:.6f}", "success")
    else:
        flash("Geocoding failed — set coordinates manually.", "danger")
    return redirect(url_for("manager.stop_edit", stop_id=stop.id))


@manager_bp.route("/stops/<int:stop_id>/delete", methods=["POST"])
@login_required
@manager_required
def stop_delete(stop_id):
    stop = db.get_or_404(Stop, stop_id)
    name = stop.name
    db.session.delete(stop)
    db.session.commit()
    flash(f"Stop '{name}' deleted.", "warning")
    return redirect(url_for("manager.stop_list"))


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
def _ssr_choices():
    ssr_role = Role.query.filter_by(name="SSR").first()
    if not ssr_role:
        return []
    users = User.query.filter_by(role_id=ssr_role.id).order_by(User.name).all()
    return [(u.id, u.name) for u in users]


@manager_bp.route("/routes")
@login_required
@manager_required
def route_list():
    plant = get_plant()
    routes = Route.query.filter_by(plant_id=plant.id).order_by(Route.name).all()
    return render_template("manager/route_list.html", routes=routes)


@manager_bp.route("/routes/new", methods=["GET", "POST"])
@login_required
@manager_required
def route_new():
    plant = get_plant()
    form = RouteForm()
    form.assigned_ssr_id.choices = [(0, "— unassigned —")] + _ssr_choices()
    if form.validate_on_submit():
        route = Route(
            name=form.name.data,
            plant_id=plant.id,
            assigned_ssr_id=form.assigned_ssr_id.data or None,
            truck_capacity_volume=form.truck_capacity_volume.data,
        )
        db.session.add(route)
        db.session.commit()
        flash(f"Route '{route.name}' created.", "success")
        return redirect(url_for("manager.route_detail", route_id=route.id))
    return render_template("manager/route_form.html", form=form, title="New Route")


@manager_bp.route("/routes/<int:route_id>")
@login_required
@manager_required
def route_detail(route_id):
    route = db.get_or_404(Route, route_id)
    assigned_stop_ids = {rs.stop_id for rs in route.route_stops}
    plant = get_plant()
    available_stops = (Stop.query
                       .filter_by(plant_id=plant.id)
                       .filter(Stop.id.notin_(assigned_stop_ids))
                       .order_by(Stop.name)
                       .all())
    form = RouteStopForm()
    form.stop_id.choices = [(s.id, s.name) for s in available_stops]
    return render_template("manager/route_detail.html",
                           route=route, form=form,
                           available_stops=available_stops)


@manager_bp.route("/routes/<int:route_id>/edit", methods=["GET", "POST"])
@login_required
@manager_required
def route_edit(route_id):
    route = db.get_or_404(Route, route_id)
    form = RouteForm(obj=route)
    form.assigned_ssr_id.choices = [(0, "— unassigned —")] + _ssr_choices()
    if form.validate_on_submit():
        route.name = form.name.data
        route.assigned_ssr_id = form.assigned_ssr_id.data or None
        route.truck_capacity_volume = form.truck_capacity_volume.data
        db.session.commit()
        flash(f"Route '{route.name}' updated.", "success")
        return redirect(url_for("manager.route_detail", route_id=route.id))
    return render_template("manager/route_form.html", form=form, title="Edit Route")


@manager_bp.route("/routes/<int:route_id>/delete", methods=["POST"])
@login_required
@manager_required
def route_delete(route_id):
    route = db.get_or_404(Route, route_id)
    name = route.name
    db.session.delete(route)
    db.session.commit()
    flash(f"Route '{name}' deleted.", "warning")
    return redirect(url_for("manager.route_list"))


@manager_bp.route("/routes/<int:route_id>/stops/add", methods=["POST"])
@login_required
@manager_required
def route_stop_add(route_id):
    route = db.get_or_404(Route, route_id)
    plant = get_plant()
    assigned_stop_ids = {rs.stop_id for rs in route.route_stops}
    available_stops = (Stop.query
                       .filter_by(plant_id=plant.id)
                       .filter(Stop.id.notin_(assigned_stop_ids))
                       .order_by(Stop.name)
                       .all())
    form = RouteStopForm()
    form.stop_id.choices = [(s.id, s.name) for s in available_stops]
    if form.validate_on_submit():
        rs = RouteStop(
            route_id=route.id,
            stop_id=form.stop_id.data,
            service_days=form.service_days.data.upper(),
            volume_override=form.volume_override.data,
        )
        db.session.add(rs)
        db.session.commit()
        flash("Stop added to route.", "success")
    return redirect(url_for("manager.route_detail", route_id=route.id))


@manager_bp.route("/routes/<int:route_id>/stops/<int:rs_id>/delete", methods=["POST"])
@login_required
@manager_required
def route_stop_delete(route_id, rs_id):
    rs = db.get_or_404(RouteStop, rs_id)
    db.session.delete(rs)
    db.session.commit()
    flash("Stop removed from route.", "warning")
    return redirect(url_for("manager.route_detail", route_id=route_id))


# ---------------------------------------------------------------------------
# Holiday + StopClosure
# ---------------------------------------------------------------------------
@manager_bp.route("/holidays")
@login_required
@manager_required
def holiday_list():
    holidays = Holiday.query.order_by(Holiday.date).all()
    closures = StopClosure.query.order_by(StopClosure.date).all()
    plant = get_plant()
    closure_form = StopClosureForm()
    closure_form.stop_id.choices = [
        (s.id, s.name) for s in
        Stop.query.filter_by(plant_id=plant.id).order_by(Stop.name).all()
    ]
    return render_template("manager/holiday_list.html",
                           holidays=holidays,
                           closures=closures,
                           closure_form=closure_form)


@manager_bp.route("/holidays/new", methods=["GET", "POST"])
@login_required
@manager_required
def holiday_new():
    form = HolidayForm()
    if form.validate_on_submit():
        holiday = Holiday(
            name=form.name.data,
            date=form.date.data,
            plant_closed=form.plant_closed.data,
        )
        db.session.add(holiday)
        db.session.commit()
        flash(f"Holiday '{holiday.name}' added.", "success")
        return redirect(url_for("manager.holiday_list"))
    return render_template("manager/holiday_form.html", form=form,
                           title="New Holiday")


@manager_bp.route("/holidays/<int:holiday_id>/delete", methods=["POST"])
@login_required
@manager_required
def holiday_delete(holiday_id):
    holiday = db.get_or_404(Holiday, holiday_id)
    name = holiday.name
    db.session.delete(holiday)
    db.session.commit()
    flash(f"Holiday '{name}' deleted.", "warning")
    return redirect(url_for("manager.holiday_list"))


@manager_bp.route("/holidays/closures/add", methods=["POST"])
@login_required
@manager_required
def stop_closure_add():
    plant = get_plant()
    form = StopClosureForm()
    form.stop_id.choices = [
        (s.id, s.name) for s in
        Stop.query.filter_by(plant_id=plant.id).order_by(Stop.name).all()
    ]
    if form.validate_on_submit():
        closure = StopClosure(
            stop_id=form.stop_id.data,
            date=form.date.data,
        )
        db.session.add(closure)
        db.session.commit()
        flash("Stop closure added.", "success")
    return redirect(url_for("manager.holiday_list"))


@manager_bp.route("/holidays/closures/<int:closure_id>/delete", methods=["POST"])
@login_required
@manager_required
def stop_closure_delete(closure_id):
    closure = db.get_or_404(StopClosure, closure_id)
    db.session.delete(closure)
    db.session.commit()
    flash("Stop closure removed.", "warning")
    return redirect(url_for("manager.holiday_list"))


# ---------------------------------------------------------------------------
# Map (Phase 2)
# ---------------------------------------------------------------------------
@manager_bp.route("/map")
@login_required
@manager_required
def map_view():
    plant = get_plant()
    stops = Stop.query.filter_by(plant_id=plant.id).order_by(Stop.name).all()
    stop_data = [
        {"name": s.name, "address": s.address,
         "lat": s.latitude, "lon": s.longitude}
        for s in stops
    ]
    return render_template("manager/map.html",
                           plant=plant, stops=stops, stop_data=stop_data)
