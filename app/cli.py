"""Command-line helpers. Run with: flask --app run.py <command>"""
import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models import User, Role


@click.command("grant-manager")
@click.argument("email")
@with_appcontext
def grant_manager(email):
    """Give the Manager role to the local user with this email."""
    user = User.query.filter(db.func.lower(User.email) == email.lower()).first()
    if user is None:
        raise click.ClickException(f"No local user with email {email}. Have them sign in once first.")
    role = Role.query.filter_by(name="Manager").first()
    if role is None:
        raise click.ClickException("Manager role not found. Run seed_roles.py first.")
    user.role_id = role.id
    db.session.commit()
    click.echo(f"{user.username} ({user.email}) is now a Manager.")
