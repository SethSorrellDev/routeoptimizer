"""Database models for RouteOptimizer.

Conventions baked in here (all hard-won from AssistantScheduler):
  * TimeType        -> store datetime.time as 'HH:MM:SS' text; SQLite has no TIME.
  * ondelete=CASCADE + passive_deletes -> deletions cascade at the DB layer, so
                       behaviour is identical in SQLite (dev) and Postgres (prod).
                       The SQLite FK pragma in extensions.py makes this real in dev.
  * server_default  -> every non-nullable Boolean gets one (has_dock, plant_closed,
                       feasible, time_window_ok) so future batch migrations are happy.
  * naming convention (extensions.py) -> all constraints get explicit names.
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import false, UniqueConstraint

from app.extensions import db, login_manager, bcrypt
from app.sqltypes import TimeType


def _utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    users = db.relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role {self.name}>"


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)

    role = db.relationship("Role", back_populates="users")
    routes = db.relationship(
        "Route", back_populates="assigned_ssr", passive_deletes=True
    )

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    @property
    def is_manager(self):
        return self.role is not None and self.role.name == "Manager"

    def __repr__(self):
        return f"<User {self.username}>"


# ---------------------------------------------------------------------------
# Core operational data
# ---------------------------------------------------------------------------
class Plant(db.Model):
    """The depot: where every route starts and ends."""

    __tablename__ = "plants"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    loading_time_minutes = db.Column(db.Integer, nullable=False, default=0)
    shift_start_earliest = db.Column(TimeType, nullable=False)
    max_shift_minutes = db.Column(db.Integer, nullable=False)

    stops = db.relationship("Stop", back_populates="plant")
    routes = db.relationship("Route", back_populates="plant")

    def __repr__(self):
        return f"<Plant {self.name}>"


class Stop(db.Model):
    """A customer location serviced by the plant."""

    __tablename__ = "stops"
    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey("plants.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    service_time_solo_minutes = db.Column(db.Integer, nullable=False, default=0)
    service_type = db.Column(db.String(50))
    has_dock = db.Column(
        db.Boolean, nullable=False, default=False, server_default=false()
    )
    priority_tier = db.Column(db.Integer, nullable=False, default=0)
    open_time = db.Column(TimeType)
    close_time = db.Column(TimeType)
    fixed_appointment_time = db.Column(TimeType)
    volume_units = db.Column(db.Integer, nullable=False, default=0)
    weight_lbs = db.Column(db.Float)
    special_instructions = db.Column(db.Text)

    plant = db.relationship("Plant", back_populates="stops")
    contacts = db.relationship(
        "StopContact", back_populates="stop",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    route_stops = db.relationship(
        "RouteStop", back_populates="stop", passive_deletes=True
    )
    closures = db.relationship(
        "StopClosure", back_populates="stop", passive_deletes=True
    )
    result_stops = db.relationship(
        "OptimizationResultStop", back_populates="stop", passive_deletes=True
    )

    def __repr__(self):
        return f"<Stop {self.name}>"


class StopContact(db.Model):
    """A contact person for a stop. A stop can have many contacts."""

    __tablename__ = "stop_contacts"
    id = db.Column(db.Integer, primary_key=True)
    stop_id = db.Column(
        db.Integer, db.ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40))

    stop = db.relationship("Stop", back_populates="contacts")

    def __repr__(self):
        return f"<StopContact {self.name} stop={self.stop_id}>"


class Route(db.Model):
    """An SSR's territory/assignment out of one plant."""

    __tablename__ = "routes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    plant_id = db.Column(db.Integer, db.ForeignKey("plants.id"), nullable=False)
    assigned_ssr_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    truck_capacity_volume = db.Column(db.Integer, nullable=False)
    truck_capacity_weight = db.Column(db.Float)

    plant = db.relationship("Plant", back_populates="routes")
    assigned_ssr = db.relationship("User", back_populates="routes")
    route_stops = db.relationship(
        "RouteStop", back_populates="route",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    optimization_results = db.relationship(
        "OptimizationResult", back_populates="route",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    def __repr__(self):
        return f"<Route {self.name}>"


class RouteStop(db.Model):
    """Association object: which stops belong to a route, with per-visit detail."""

    __tablename__ = "route_stops"
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(
        db.Integer, db.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False
    )
    stop_id = db.Column(
        db.Integer, db.ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    service_days = db.Column(db.String(20))
    volume_override = db.Column(db.Integer)

    route = db.relationship("Route", back_populates="route_stops")
    stop = db.relationship("Stop", back_populates="route_stops")

    __table_args__ = (
        UniqueConstraint("route_id", "stop_id", name="uq_route_stops_route_stop"),
    )

    def __repr__(self):
        return f"<RouteStop route={self.route_id} stop={self.stop_id}>"


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
class Holiday(db.Model):
    __tablename__ = "holidays"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False)
    plant_closed = db.Column(
        db.Boolean, nullable=False, default=True, server_default=false()
    )

    closures = db.relationship(
        "StopClosure", back_populates="holiday", passive_deletes=True
    )

    def __repr__(self):
        return f"<Holiday {self.name} {self.date}>"


class StopClosure(db.Model):
    """A stop closed on a specific date, even if the plant is open."""

    __tablename__ = "stop_closures"
    id = db.Column(db.Integer, primary_key=True)
    stop_id = db.Column(
        db.Integer, db.ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    date = db.Column(db.Date)
    holiday_id = db.Column(
        db.Integer, db.ForeignKey("holidays.id", ondelete="SET NULL"), nullable=True
    )

    stop = db.relationship("Stop", back_populates="closures")
    holiday = db.relationship("Holiday", back_populates="closures")

    def __repr__(self):
        return f"<StopClosure stop={self.stop_id} {self.date}>"


# ---------------------------------------------------------------------------
# Cache + computed results
# ---------------------------------------------------------------------------
class DistanceMatrixEntry(db.Model):
    """Cached road travel data so the matrix API isn't re-hit every run."""

    __tablename__ = "distance_matrix_entries"
    id = db.Column(db.Integer, primary_key=True)
    origin_type = db.Column(db.String(10), nullable=False)
    origin_id = db.Column(db.Integer, nullable=False)
    dest_type = db.Column(db.String(10), nullable=False)
    dest_id = db.Column(db.Integer, nullable=False)
    distance_meters = db.Column(db.Float)
    duration_seconds = db.Column(db.Float)
    fetched_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "origin_type", "origin_id", "dest_type", "dest_id",
            name="uq_distance_matrix_entries_pair",
        ),
    )

    def __repr__(self):
        return f"<DME {self.origin_type}:{self.origin_id}->{self.dest_type}:{self.dest_id}>"


class OptimizationResult(db.Model):
    """One computed plan for a route + day."""

    __tablename__ = "optimization_results"
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(
        db.Integer, db.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week = db.Column(db.String(10))
    generated_at = db.Column(db.DateTime, default=_utcnow)
    recommended_departure_time = db.Column(TimeType)
    estimated_return_time = db.Column(TimeType)
    assistants_required = db.Column(db.Integer, default=0)
    total_distance_meters = db.Column(db.Float)
    total_drive_seconds = db.Column(db.Float)
    total_service_seconds = db.Column(db.Float)
    capacity_utilization_pct = db.Column(db.Float)
    estimated_cost = db.Column(db.Float)
    feasible = db.Column(
        db.Boolean, nullable=False, default=False, server_default=false()
    )
    warnings = db.Column(db.Text)

    route = db.relationship("Route", back_populates="optimization_results")
    result_stops = db.relationship(
        "OptimizationResultStop", back_populates="result",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="OptimizationResultStop.sequence_order",
    )

    def __repr__(self):
        return f"<OptimizationResult route={self.route_id} {self.day_of_week}>"


class OptimizationResultStop(db.Model):
    """The ordered itinerary belonging to an OptimizationResult."""

    __tablename__ = "optimization_result_stops"
    id = db.Column(db.Integer, primary_key=True)
    optimization_result_id = db.Column(
        db.Integer,
        db.ForeignKey("optimization_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    stop_id = db.Column(
        db.Integer, db.ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    sequence_order = db.Column(db.Integer, nullable=False)
    estimated_arrival_time = db.Column(TimeType)
    estimated_departure_time = db.Column(TimeType)
    cumulative_volume = db.Column(db.Integer)
    time_window_ok = db.Column(
        db.Boolean, nullable=False, default=True, server_default=false()
    )

    result = db.relationship("OptimizationResult", back_populates="result_stops")
    stop = db.relationship("Stop", back_populates="result_stops")

    def __repr__(self):
        return f"<ORS result={self.optimization_result_id} seq={self.sequence_order}>"


# ---------------------------------------------------------------------------
# Flask-Login user loader
# ---------------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
