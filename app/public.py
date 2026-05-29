from flask import Blueprint, render_template, send_from_directory, current_app
from .models import Project, Client

public_bp = Blueprint("public", __name__)

@public_bp.route("/media/<path:filename>")
def media(filename):
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename)

@public_bp.route("/")
def home():
    projects = Project.query.filter_by(is_featured=True).order_by(Project.sort_order, Project.created_at.desc()).limit(3).all()
    clients = Client.query.filter_by(is_featured=True, is_active=True).order_by(Client.sort_order, Client.name).all()
    hero = Project.query.filter_by(is_featured=True).order_by(Project.sort_order, Project.created_at.desc()).first()
    return render_template("home.html", projects=projects, clients=clients, hero=hero, active="home")

@public_bp.route("/about")
def about():
    return render_template("about.html", active="about")

@public_bp.route("/portfolio")
def portfolio():
    projects = Project.query.order_by(Project.sort_order, Project.created_at.desc()).all()
    categories = ["Tous", "Corporate", "Vigne & hôtellerie", "Événements", "Mariage", "Tourisme"]
    reels = Project.query.filter_by(is_reel=True).order_by(Project.sort_order, Project.created_at.desc()).all()
    return render_template("portfolio.html", projects=projects, reels=reels, categories=categories, active="portfolio")

@public_bp.route("/portfolio/<slug>")
def project_detail(slug):
    project = Project.query.filter_by(slug=slug).first_or_404()
    return render_template("project_detail.html", project=project, active="portfolio")

@public_bp.route("/contact")
def contact():
    return render_template("contact.html", active="contact")
