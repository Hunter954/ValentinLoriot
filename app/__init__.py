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
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-change-me")
    database_url = os.getenv("DATABASE_URL", "sqlite:///portfolio.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_DIR"] = os.getenv("UPLOAD_DIR", os.path.join(os.getcwd(), "uploads"))
    app.config["MAX_CONTENT_LENGTH"] = 900 * 1024 * 1024

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User, SiteSetting

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .public import public_bp
    from .admin import admin_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

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

    with app.app_context():
        db.create_all()
        ensure_defaults(app)

    return app


def ensure_defaults(app):
    from .models import User, SiteSetting, SocialLink
    defaults = {
        "brand_name": "Valentin Loriot",
        "brand_subtitle": "Filmmaker & Photographer – Foz do Iguaçu",
        "home_kicker": "CINEMATIC FILMMAKER • FRANCE & BRAZIL",
        "home_title": "Valentin Loriot",
        "home_subtitle": "Je transforme vos projets\nen récits visuels",
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
