from datetime import datetime
from flask_login import UserMixin
from . import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Admin")
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    logo_path = db.Column(db.String(255))
    website = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0)
    is_featured = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    projects = db.relationship("Project", back_populates="client", cascade="all, delete-orphan")

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False)
    category = db.Column(db.String(80), default="Vigne & hôtellerie")
    location = db.Column(db.String(180), default="Var, France")
    year = db.Column(db.String(20), default="2024")
    type_label = db.Column(db.String(80), default="Film")
    duration = db.Column(db.String(50), default="3 min 42 s")
    description = db.Column(db.Text)
    thumbnail_path = db.Column(db.String(255))
    hero_path = db.Column(db.String(255))
    video_path = db.Column(db.String(255))
    external_video_url = db.Column(db.String(500))
    is_featured = db.Column(db.Boolean, default=True)
    is_reel = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"))
    client = db.relationship("Client", back_populates="projects")
    media = db.relationship("Media", back_populates="project", cascade="all, delete-orphan", order_by="Media.sort_order")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    media_type = db.Column(db.String(20), default="photo")
    file_path = db.Column(db.String(255))
    external_url = db.Column(db.String(500))
    caption = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    project = db.relationship("Project", back_populates="media")

class SocialLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    icon = db.Column(db.String(40), default="instagram")
    sort_order = db.Column(db.Integer, default=0)
