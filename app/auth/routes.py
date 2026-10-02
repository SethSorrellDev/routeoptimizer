"""Authentication blueprint: register, login, logout.

Login is delegated to the shared identity-service. Flask-Login still owns the
browser session; identity-service only decides whether the email and password
are valid. Roles stay local to RouteOptimizer.
"""
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models import User, Role
from app.auth import identity
from app.auth.forms import RegistrationForm, LoginForm

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        role = Role.query.filter_by(name=form.role.data).first()
        user = User(
            name=form.name.data,
            username=form.username.data,
            email=form.email.data,
            role_id=role.id,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f"Account created for {user.username}. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


def _unique_username(base):
    base = (base or "user")[:56]
    candidate, n = base, 1
    while User.query.filter_by(username=candidate).first():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def _resolve_local_user(claims, password):
    """Map verified identity claims to a local User, or return (None, message).

    1. Already linked: match on the identity "sub".
    2. First SSO login for an existing local account: link it, but only if the
       local password also matches. Identity-service emails are unverified, so
       an email match alone would let anyone claim someone else's account.
    3. No local account: provision one with the least-privileged role.
    """
    sub = claims["sub"]
    email = (claims.get("email") or "").strip()

    user = User.query.filter_by(identity_sub=sub).first()
    if user:
        return user, None

    user = User.query.filter(func.lower(User.email) == email.lower()).first()
    if user:
        if user.identity_sub is not None:
            return None, "This email is already linked to a different sign-in account."
        if not user.check_password(password):
            return None, (
                "An account with this email already exists here. "
                "Sign in with your existing RouteOptimizer password to link it."
            )
        user.identity_sub = sub
        db.session.commit()
        return user, None

    role = Role.query.filter_by(name="SSR").first()
    if role is None:
        return None, "Accounts are not set up yet. Ask an administrator."
    user = User(
        name=email.split("@")[0],
        username=_unique_username(email.split("@")[0]),
        email=email,
        role_id=role.id,
        identity_sub=sub,
    )
    user.set_password(password)  # local hash is required by the schema
    db.session.add(user)
    db.session.commit()
    return user, None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            claims = identity.authenticate(form.email.data.strip(), form.password.data)
        except identity.IdentityError as exc:
            flash(str(exc), "danger")
            return render_template("auth/login.html", form=form)

        user, problem = _resolve_local_user(claims, form.password.data)
        if problem:
            flash(problem, "danger")
            return render_template("auth/login.html", form=form)

        login_user(user, remember=form.remember.data)
        flash(f"Welcome back, {user.name}.", "success")
        return redirect(url_for("main.index"))
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "warning")
    return redirect(url_for("auth.login"))
