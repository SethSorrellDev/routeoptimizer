"""Application factory."""
from flask import Flask

from config import Config
from app.extensions import db, migrate, login_manager, bcrypt, csrf


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Make sure the SQLite instance/ folder exists before the DB is opened.
    import os
    os.makedirs(app.instance_path, exist_ok=True)

    # Initialise extensions. render_as_batch=True tells Alembic to use SQLite's
    # "batch" mode for ALTER operations (the other half of clean migrations).
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    # Models must be imported so Flask-Migrate can see them for autogenerate.
    from app import models  # noqa: F401

    # Register blueprints.
    from app.main.routes import main_bp
    from app.auth.routes import auth_bp
    from app.manager.routes import manager_bp
    from app.ssr.routes import ssr_bp
    from app.optimizer.routes import optimizer_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(ssr_bp)
    app.register_blueprint(optimizer_bp)

    return app
