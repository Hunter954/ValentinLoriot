"""Persistent VPS storage with a 3 GB quota and PostgreSQL write serialization.

Usage includes all files, including interrupted uploads and unreferenced files.
The lock spans quota checks, atomic file writes, DB commits and safe deletion.
"""
import json
import os
import subprocess
import tempfile
import uuid
import warnings
import fcntl
import shutil
import time
from pathlib import Path
from contextlib import contextmanager

from flask import abort, current_app, g
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text
from werkzeug.exceptions import HTTPException

from . import db

LIMIT = 3_000_000_000
LOCK_ID = 809274118
IMAGE_TYPES = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}
VIDEO_TYPES = {"mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime", "webm": "video/webm"}
Image.MAX_IMAGE_PIXELS = 16_000_000


class InsufficientStorage(HTTPException):
    code = 507


def root():
    return Path(current_app.config["UPLOAD_DIR"]).resolve()


def local_path(key):
    if not key.startswith("media/") or ".." in key or "\\" in key:
        abort(404)
    target = root() / key
    if not target.resolve().is_relative_to(root()) or target.is_symlink():
        abort(404)
    return target


def inventory():
    objects = []
    for folder, dirs, files in os.walk(root(), followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink()]
        for name in files:
            target = Path(folder) / name
            if target.is_symlink() or name == ".storage.lock":
                continue
            try:
                objects.append({"Key": target.relative_to(root()).as_posix(), "Size": target.stat().st_size})
            except FileNotFoundError:
                continue
    return sorted(objects, key=lambda o: o["Key"])


def usage():
    objects = inventory()
    used = sum(o["Size"] for o in objects)
    return {"used": used, "limit": LIMIT, "available": max(0, LIMIT - used),
            "percent": min(100, used * 100 / LIMIT), "objects": len(objects)}


@contextmanager
def write_lock():
    if db.engine.dialect.name != "postgresql":
        if current_app.config["PRODUCTION"]:
            raise RuntimeError("Production storage requires PostgreSQL locking")
        # Development/tests: a file lock also serializes independent processes.
        with (root() / ".storage.lock").open("a") as handle:
            deadline = time.monotonic() + 15
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Storage lock unavailable")
                    time.sleep(0.02)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        return
    # Separate connection: route commits must never release the storage lock early.
    with db.engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '15s'"))
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_ID})
        yield


def references():
    from .models import Client, Media, Project, SiteSetting
    paths = set()
    for row in db.session.query(Project.thumbnail_path, Project.hero_path, Project.video_path):
        paths.update(p for p in row if p)
    paths.update(p for (p,) in db.session.query(Client.logo_path) if p)
    paths.update(p for (p,) in db.session.query(Media.file_path) if p)
    paths.update(s.value for s in SiteSetting.query.filter(SiteSetting.key.in_(
        ["site_logo", "site_favicon", "home_hero_media", "about_hero_media"])) if s.value)
    return paths


def delete_unreferenced(keys):
    active = references()
    for key in set(keys) - active:
        if key.startswith("media/"):
            local_path(key).unlink(missing_ok=True)


def _validated_media(file):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if not size or size > 80_000_000:
        abort(413, "Cada arquivo deve ter entre 1 byte e 80 MB.")
    if ext in IMAGE_TYPES:
        if size > 16_000_000:
            abort(413, "Imagens devem ter no máximo 16 MB.")
        if file.mimetype not in {"image/jpeg", "image/png", "image/webp", "image/gif", "application/octet-stream"}:
            abort(400, "MIME da imagem inválido.")
        out = tempfile.TemporaryFile()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(file.stream) as im:
                    if im.format != IMAGE_TYPES[ext]:
                        abort(400, "O conteúdo da imagem não corresponde à extensão.")
                    # Do not silently flatten animated GIF/WebP files.
                    if getattr(im, "is_animated", False):
                        abort(400, "Envie animações como vídeo MP4 ou WebM.")
                    im.load()
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
                    im = im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")
                    im.save(out, "WEBP", quality=90, method=4)
            out.seek(0, os.SEEK_END)
            result_size = out.tell()
            out.seek(0)
            return out, result_size, "webp", "image/webp"
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            out.close()
            abort(400, "Imagem inválida ou superior a 16 megapixels.")
        except BaseException:
            out.close()
            raise
    if ext not in VIDEO_TYPES:
        abort(400, "Use JPG, PNG, WebP, GIF estático, MP4, MOV, M4V ou WebM. SVG não é permitido.")
    header = file.stream.read(16)
    file.stream.seek(0)
    if (ext == "webm" and not header.startswith(b"\x1a\x45\xdf\xa3")) or (
            ext != "webm" and header[4:8] != b"ftyp"):
        abort(400, "O conteúdo do vídeo não corresponde à extensão. Use MP4/MOV moderno ou WebM.")
    if file.mimetype not in {VIDEO_TYPES[ext], "video/mp4", "application/octet-stream"}:
        abort(400, "MIME do vídeo inválido.")
    out = tempfile.NamedTemporaryFile(suffix="." + ext)
    try:
        while chunk := file.stream.read(1024 * 1024):
            out.write(chunk)
        out.flush()
        result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-max_alloc", "33554432", "-probesize", "5000000",
                                 "-analyzeduration", "3000000", "-show_entries", "stream=codec_type,codec_name",
                                 "-of", "json", out.name], capture_output=True, timeout=15, check=True)
        streams = json.loads(result.stdout).get("streams", [])
        if not any(s.get("codec_type") == "video" for s in streams):
            abort(400, "O arquivo não contém um vídeo válido.")
        out.seek(0)
        return out, size, ext, VIDEO_TYPES[ext]
    except (subprocess.SubprocessError, ValueError):
        out.close()
        abort(400, "Vídeo inválido. Prefira MP4 H.264 ou WebM compactado para web.")
    except BaseException:
        out.close()
        raise


def save(file, folder):
    if not getattr(g, "storage_locked", False):
        raise RuntimeError("Upload attempted without the storage quota lock")
    stream, size, ext, mime = _validated_media(file)
    try:
        if usage()["used"] + size > LIMIT:
            abort(413, "Este arquivo ultrapassa os 3 GB disponíveis. Exclua mídias ou envie um arquivo menor.")
        key = f"media/{folder}/{uuid.uuid4().hex}.{ext}"
        if shutil.disk_usage(root()).free < size + 256 * 1024 * 1024:
            raise InsufficientStorage("O servidor está sem espaço suficiente. Contate o administrador.")
        target = local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        g.new_storage_keys.append(key)
        temporary = target.with_name(".pending-" + target.name)
        try:
            with temporary.open("xb") as output:
                shutil.copyfileobj(stream, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        except OSError:
            raise InsufficientStorage("Não foi possível armazenar o arquivo. Tente novamente ou contate o administrador.")
        finally:
            temporary.unlink(missing_ok=True)
        return key
    finally:
        stream.close()


def init_storage(app):
    if app.config["PRODUCTION"]:
        mount = Path("/data")
        upload_root = Path(app.config["UPLOAD_DIR"]).resolve()
        if not mount.is_mount() or not upload_root.is_relative_to(mount):
            raise RuntimeError("Production requires a persistent volume mounted at /data and UPLOAD_DIR=/data/uploads")
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    @app.cli.command("storage-reconcile")
    def reconcile():
        """Recalculate usage from every real object. Read-only; no orphan deletion."""
        with write_lock():
            stats = usage()
            stats["unreferenced"] = len({o["Key"] for o in inventory()} - references())
            print(json.dumps(stats))

    @app.before_request
    def lock_mutations():
        from flask import request
        from flask_login import current_user
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        if not current_user.is_authenticated:
            return
        ctx = write_lock()
        try:
            ctx.__enter__()
        except Exception:
            app.logger.warning("Storage lock unavailable")
            abort(503, "Outro envio está sendo processado. Aguarde e tente novamente.")
        g.storage_lock_context = ctx
        g.storage_locked = True
        g.new_storage_keys = []
        g.old_storage_keys = references()

    @app.after_request
    def cleanup(response):
        if getattr(g, "storage_locked", False):
            try:
                # Roll back unsaved route state before testing references.
                db.session.rollback()
                keys = g.new_storage_keys + (list(g.old_storage_keys) if response.status_code < 400 else [])
                delete_unreferenced(keys)
            except Exception:
                # Orphans remain counted toward quota and are reported by reconciliation.
                app.logger.exception("Storage cleanup failed; objects remain included in quota")
        return response

    @app.teardown_request
    def unlock(_error):
        ctx = g.pop("storage_lock_context", None)
        if ctx:
            ctx.__exit__(None, None, None)
