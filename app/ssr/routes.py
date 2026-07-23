"""SSR blueprint: read-only views of a rep's own assigned route."""
from flask import Blueprint, render_template
from flask_login import login_required

ssr_bp = Blueprint("ssr", __name__, url_prefix="/ssr")


@ssr_bp.route("/")
@login_required
def dashboard():
    return render_template("manager/coming_soon.html", title="SSR Dashboard")
