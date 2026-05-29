import os, re, uuid
from functools import wraps
from flask import current_app, abort
from flask_login import current_user
from werkzeug.utils import secure_filename
from .models import SiteSetting, SocialLink

IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif", "svg"}
VIDEO_EXT = {"mp4", "mov", "webm", "m4v"}


def slugify(text):
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9à-ÿ]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or uuid.uuid4().hex[:10]


def save_upload(file, folder="media"):
    if not file or not file.filename:
        return None
    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in IMAGE_EXT | VIDEO_EXT:
        abort(400, "Formato não permitido.")
    final_name = f"{uuid.uuid4().hex}.{ext}"
    abs_dir = os.path.join(current_app.config["UPLOAD_DIR"], folder)
    os.makedirs(abs_dir, exist_ok=True)
    file.save(os.path.join(abs_dir, final_name))
    return f"{folder}/{final_name}"


def settings_dict():
    return {s.key: s.value for s in SiteSetting.query.all()}


def social_links():
    return SocialLink.query.filter_by(is_active=True).order_by(SocialLink.sort_order, SocialLink.id).all()
