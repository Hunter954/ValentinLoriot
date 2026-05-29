from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from . import db
from .models import User, Client, Project, Media, SiteSetting, SocialLink
from .utils import save_upload, slugify

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip()).first()
        if user and getattr(user, "is_active", True) and check_password_hash(user.password_hash, request.form.get("password", "")):
            login_user(user)
            return redirect(url_for("admin.dashboard"))
        flash("E-mail ou senha inválidos.", "error")
    return render_template("admin/login.html")

@admin_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))

@admin_bp.route("/")
@login_required
def dashboard():
    return render_template("admin/dashboard.html", projects=Project.query.count(), clients=Client.query.count(), media=Media.query.count())

@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    fields = ["brand_name","brand_subtitle","home_kicker","home_title","home_subtitle","about_text","years_experience","base_countries","client_count","footer_about","phone","email"]
    upload_fields = {
        "site_logo": "branding",
        "site_favicon": "branding",
        "home_hero_media": "site-media",
        "about_hero_media": "site-media",
    }
    if request.method == "POST":
        for key in fields:
            row = SiteSetting.query.filter_by(key=key).first() or SiteSetting(key=key)
            row.value = request.form.get(key, "")
            db.session.add(row)
        for key, folder in upload_fields.items():
            uploaded_path = save_upload(request.files.get(key), folder)
            if uploaded_path:
                row = SiteSetting.query.filter_by(key=key).first() or SiteSetting(key=key)
                row.value = uploaded_path
                db.session.add(row)
        db.session.commit()
        flash("Configurações salvas.", "success")
        return redirect(url_for("admin.settings"))
    settings = {s.key:s.value for s in SiteSetting.query.all()}
    return render_template("admin/settings.html", fields=fields, settings=settings, upload_fields=upload_fields)

@admin_bp.route("/clients", methods=["GET", "POST"])
@login_required
def clients():
    if request.method == "POST":
        c = Client(
            name=request.form["name"],
            website=request.form.get("website"),
            sort_order=int(request.form.get("sort_order") or 0),
            is_featured=bool(request.form.get("is_featured")),
            is_active=bool(request.form.get("is_active", "on")),
        )
        c.logo_path = save_upload(request.files.get("logo"), "clients")
        db.session.add(c); db.session.commit(); flash("Cliente criado.", "success")
        return redirect(url_for("admin.clients"))
    return render_template("admin/clients.html", clients=Client.query.order_by(Client.sort_order, Client.name).all())

@admin_bp.route("/clients/<int:id>/edit", methods=["POST"])
@login_required
def edit_client(id):
    c = Client.query.get_or_404(id)
    c.name = request.form.get("name") or c.name
    c.website = request.form.get("website")
    c.sort_order = int(request.form.get("sort_order") or 0)
    c.is_featured = bool(request.form.get("is_featured"))
    c.is_active = bool(request.form.get("is_active"))
    c.logo_path = save_upload(request.files.get("logo"), "clients") or c.logo_path
    db.session.commit(); flash("Cliente atualizado.", "success")
    return redirect(url_for("admin.clients"))

@admin_bp.route("/clients/<int:id>/toggle", methods=["POST"])
@login_required
def toggle_client(id):
    c = Client.query.get_or_404(id)
    c.is_active = not getattr(c, "is_active", True)
    db.session.commit(); flash("Status do cliente atualizado.", "success")
    return redirect(url_for("admin.clients"))

@admin_bp.route("/clients/<int:id>/delete", methods=["POST"])
@login_required
def delete_client(id):
    c = Client.query.get_or_404(id)
    for project in list(c.projects):
        project.client_id = None
    db.session.delete(c); db.session.commit(); flash("Cliente removido.", "success")
    return redirect(url_for("admin.clients"))

@admin_bp.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    if request.method == "POST":
        title = request.form["title"]
        base_slug = slugify(request.form.get("slug") or title)
        slug = base_slug
        n = 2
        while Project.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{n}"; n += 1
        p = Project(
            title=title, slug=slug, category=request.form.get("category"), location=request.form.get("location"),
            year=request.form.get("year"), type_label=request.form.get("type_label"), duration=request.form.get("duration"),
            description=request.form.get("description"), external_video_url=request.form.get("external_video_url"),
            is_featured=bool(request.form.get("is_featured")), is_reel=bool(request.form.get("is_reel")),
            sort_order=int(request.form.get("sort_order") or 0), client_id=request.form.get("client_id") or None)
        p.thumbnail_path = save_upload(request.files.get("thumbnail"), "projects")
        p.hero_path = save_upload(request.files.get("hero"), "projects") or p.thumbnail_path
        p.video_path = save_upload(request.files.get("video"), "videos")
        db.session.add(p); db.session.commit(); flash("Projeto criado.", "success")
        return redirect(url_for("admin.projects"))
    return render_template("admin/projects.html", projects=Project.query.order_by(Project.sort_order, Project.created_at.desc()).all(), clients=Client.query.order_by(Client.name).all())

@admin_bp.route("/projects/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(id):
    p = Project.query.get_or_404(id)
    if request.method == "POST":
        for field in ["title","category","location","year","type_label","duration","description","external_video_url"]:
            setattr(p, field, request.form.get(field))
        new_slug = slugify(request.form.get("slug") or p.title)
        if new_slug != p.slug and not Project.query.filter_by(slug=new_slug).first(): p.slug = new_slug
        p.client_id = request.form.get("client_id") or None
        p.sort_order = int(request.form.get("sort_order") or 0)
        p.is_featured = bool(request.form.get("is_featured")); p.is_reel = bool(request.form.get("is_reel"))
        p.thumbnail_path = save_upload(request.files.get("thumbnail"), "projects") or p.thumbnail_path
        p.hero_path = save_upload(request.files.get("hero"), "projects") or p.hero_path
        p.video_path = save_upload(request.files.get("video"), "videos") or p.video_path
        db.session.commit(); flash("Projeto atualizado.", "success")
        return redirect(url_for("admin.edit_project", id=p.id))
    return render_template("admin/edit_project.html", p=p, clients=Client.query.order_by(Client.name).all())

@admin_bp.route("/projects/<int:id>/delete", methods=["POST"])
@login_required
def delete_project(id):
    db.session.delete(Project.query.get_or_404(id)); db.session.commit(); flash("Projeto removido.", "success")
    return redirect(url_for("admin.projects"))

@admin_bp.route("/projects/<int:id>/media", methods=["POST"])
@login_required
def add_media(id):
    Project.query.get_or_404(id)
    file_path = save_upload(request.files.get("file"), "gallery")
    m = Media(project_id=id, media_type=request.form.get("media_type", "photo"), file_path=file_path, external_url=request.form.get("external_url"), caption=request.form.get("caption"), sort_order=int(request.form.get("sort_order") or 0))
    db.session.add(m); db.session.commit(); flash("Mídia adicionada.", "success")
    return redirect(url_for("admin.edit_project", id=id))

@admin_bp.route("/media/<int:id>/delete", methods=["POST"])
@login_required
def delete_media(id):
    m = Media.query.get_or_404(id); pid = m.project_id
    db.session.delete(m); db.session.commit(); flash("Mídia removida.", "success")
    return redirect(url_for("admin.edit_project", id=pid))

@admin_bp.route("/socials", methods=["GET", "POST"])
@login_required
def socials():
    if request.method == "POST":
        db.session.add(SocialLink(
            name=request.form["name"],
            url=request.form["url"],
            icon=request.form.get("icon", "instagram"),
            sort_order=int(request.form.get("sort_order") or 0),
            is_active=bool(request.form.get("is_active", "on")),
        ))
        db.session.commit(); flash("Rede social adicionada.", "success")
        return redirect(url_for("admin.socials"))
    return render_template("admin/socials.html", socials=SocialLink.query.order_by(SocialLink.sort_order, SocialLink.id).all())

@admin_bp.route("/socials/<int:id>/edit", methods=["POST"])
@login_required
def edit_social(id):
    s = SocialLink.query.get_or_404(id)
    s.name = request.form.get("name") or s.name
    s.url = request.form.get("url") or s.url
    s.icon = request.form.get("icon") or s.icon
    s.sort_order = int(request.form.get("sort_order") or 0)
    s.is_active = bool(request.form.get("is_active"))
    db.session.commit(); flash("Rede social atualizada.", "success")
    return redirect(url_for("admin.socials"))

@admin_bp.route("/socials/<int:id>/toggle", methods=["POST"])
@login_required
def toggle_social(id):
    s = SocialLink.query.get_or_404(id)
    s.is_active = not getattr(s, "is_active", True)
    db.session.commit(); flash("Status da rede social atualizado.", "success")
    return redirect(url_for("admin.socials"))

@admin_bp.route("/socials/<int:id>/delete", methods=["POST"])
@login_required
def delete_social(id):
    db.session.delete(SocialLink.query.get_or_404(id)); db.session.commit(); flash("Rede removida.", "success")
    return redirect(url_for("admin.socials"))

@admin_bp.route("/users", methods=["GET", "POST"])
@login_required
def users():
    if request.method == "POST":
        db.session.add(User(
            name=request.form.get("name") or "Admin",
            email=request.form["email"],
            password_hash=generate_password_hash(request.form["password"]),
            is_active=bool(request.form.get("is_active", "on")),
        ))
        db.session.commit(); flash("Usuário criado.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/users.html", users=User.query.order_by(User.created_at.desc()).all())

@admin_bp.route("/users/<int:id>/edit", methods=["POST"])
@login_required
def edit_user(id):
    u = User.query.get_or_404(id)
    u.name = request.form.get("name") or u.name
    u.email = request.form.get("email") or u.email
    password = request.form.get("password")
    if password:
        u.password_hash = generate_password_hash(password)
    if u.id != current_user.id:
        u.is_active = bool(request.form.get("is_active"))
    db.session.commit(); flash("Usuário atualizado.", "success")
    return redirect(url_for("admin.users"))

@admin_bp.route("/users/<int:id>/toggle", methods=["POST"])
@login_required
def toggle_user(id):
    u = User.query.get_or_404(id)
    if u.id == current_user.id:
        flash("Você não pode desativar o próprio usuário logado.", "error")
    else:
        u.is_active = not getattr(u, "is_active", True)
        db.session.commit(); flash("Status do usuário atualizado.", "success")
    return redirect(url_for("admin.users"))

@admin_bp.route("/users/<int:id>/delete", methods=["POST"])
@login_required
def delete_user(id):
    u = User.query.get_or_404(id)
    if u.id == current_user.id:
        flash("Você não pode remover o próprio usuário logado.", "error")
    elif User.query.count() <= 1:
        flash("Não é possível remover o único usuário do painel.", "error")
    else:
        db.session.delete(u); db.session.commit(); flash("Usuário removido.", "success")
    return redirect(url_for("admin.users"))
