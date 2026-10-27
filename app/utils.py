import re, uuid
from .models import SiteSetting, SocialLink



def slugify(text):
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9à-ÿ]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or uuid.uuid4().hex[:10]


def save_upload(file, folder="media"):
    if not file or not file.filename:
        return None
    from .storage import save
    return save(file, folder)


def settings_dict():
    return {s.key: s.value for s in SiteSetting.query.all()}


def social_links():
    return SocialLink.query.filter_by(is_active=True).order_by(SocialLink.sort_order, SocialLink.id).all()
