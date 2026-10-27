import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from werkzeug.security import generate_password_hash

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "admin.login"


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config["PRODUCTION"] = os.getenv("APP_ENV") == "production"
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-change-me")
    if app.config["PRODUCTION"] and len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("Production requires a unique FLASK_SECRET_KEY of at least 32 characters")
    app.config.update(SESSION_COOKIE_SECURE=app.config["PRODUCTION"], SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Lax", REMEMBER_COOKIE_SECURE=app.config["PRODUCTION"],
                      REMEMBER_COOKIE_HTTPONLY=True, REMEMBER_COOKIE_SAMESITE="Lax")
    database_url = os.getenv("DATABASE_URL", "sqlite:///portfolio.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    if database_url.startswith("postgresql:"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_size": 4, "max_overflow": 2, "pool_pre_ping": True}
    if app.config["PRODUCTION"] and not database_url.startswith("postgresql:"):
        raise RuntimeError("Production requires PostgreSQL")
    app.config["UPLOAD_DIR"] = os.getenv("UPLOAD_DIR", os.path.join(os.getcwd(), "uploads"))
    app.config["MAX_CONTENT_LENGTH"] = 90_000_000
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    from .security import init_security
    init_security(app)
    from .storage import init_storage
    init_storage(app)
    from .backups import init_backups
    init_backups(app)
    from .deployment import init_deployment
    init_deployment(app)

    from .models import User, SiteSetting

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
            return user if user and user.is_active else None
        except (TypeError, ValueError):
            return None

    from .public import public_bp
    from .admin import admin_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    @app.route("/healthz")
    def healthz():
        from sqlalchemy import text
        db.session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.cli.command("create-admin")
    def create_admin():
        import click
        email = click.prompt("E-mail").strip().lower()
        if User.query.filter_by(email=email).first():
            raise click.ClickException("Usuário já existe")
        password = click.prompt("Senha (mínimo 12 caracteres)", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("Senha muito curta")
        db.session.add(User(name="Admin", email=email, password_hash=generate_password_hash(password)))
        db.session.commit()
        click.echo("Administrador criado")

    @app.context_processor
    def inject_site_globals():
        from .utils import settings_dict, social_links
        return {"S": settings_dict(), "social_links": social_links()}

    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        ensure_defaults(app)
        print("Banco inicializado com sucesso.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        from .seed import seed_demo
        seed_demo()
        print("Conteúdo demo criado.")

    # Production schema initialization is explicit, never in each Gunicorn worker.
    if not app.config["PRODUCTION"]:
        with app.app_context():
            db.create_all()
            ensure_schema_upgrades()
            ensure_defaults(app)

    return app



def ensure_schema_upgrades():
    """Pequenas atualizações automáticas para bancos já existentes no Railway.
    db.create_all() cria tabelas novas, mas não adiciona colunas em tabelas antigas.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    dialect = db.engine.dialect.name
    upgrades = {
        "client": [("is_active", "BOOLEAN DEFAULT TRUE NOT NULL", "BOOLEAN DEFAULT 1 NOT NULL")],
        "social_link": [("is_active", "BOOLEAN DEFAULT TRUE NOT NULL", "BOOLEAN DEFAULT 1 NOT NULL")],
        "user": [("is_active", "BOOLEAN DEFAULT TRUE NOT NULL", "BOOLEAN DEFAULT 1 NOT NULL")],
    }
    with db.engine.begin() as conn:
        for table, columns in upgrades.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for column, pg_def, sqlite_def in columns:
                if column in existing:
                    continue
                table_name = f'"{table}"' if table == "user" else table
                col_def = sqlite_def if dialect == "sqlite" else pg_def
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {col_def}"))

def ensure_defaults(app):
    from .models import User, SiteSetting, SocialLink
    defaults = {
        "brand_name": "Valentin Loriot",
        "brand_subtitle": "Filmmaker & Photographer – Foz do Iguaçu",
        "home_kicker": "CINEMATIC FILMMAKER • FRANCE & BRAZIL",
        "home_title": "Valentin Loriot",
        "home_subtitle": "Je transforme vos projets\nen récits visuels",
        "home_hero_media": "",
        "about_hero_media": "",
        "about_text": "Français installé au Brésil, je travaille à l’intersection du documentaire et de la direction artistique. Mon œil cinématique s’est formé entre les vignes du Var, les hôtels de luxe et les rues de São Paulo. Je tourne en France, au Brésil, et partout où une histoire mérite d’être racontée.",
        "years_experience": "5",
        "base_countries": "2",
        "client_count": "20+",
        "footer_about": "A visual storytelling studio\ndedicated to capturing emotion.",
        "phone": "+33 6 27 44 41 24",
        "email": "loriotvalentin9@gmail.com",
    }
    for key, value in defaults.items():
        if not SiteSetting.query.filter_by(key=key).first():
            db.session.add(SiteSetting(key=key, value=value))
    if not SocialLink.query.first():
        db.session.add(SocialLink(name="Instagram", url="https://instagram.com/", icon="instagram", sort_order=1))
        db.session.add(SocialLink(name="YouTube", url="https://youtube.com/", icon="youtube", sort_order=2))
        db.session.add(SocialLink(name="LinkedIn", url="https://linkedin.com/", icon="linkedin", sort_order=3))
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if admin_email and admin_password and not User.query.filter_by(email=admin_email).first():
        db.session.add(User(name="Admin", email=admin_email, password_hash=generate_password_hash(admin_password)))
    db.session.commit()
