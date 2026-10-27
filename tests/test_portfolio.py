import io
import os
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException

from app import create_app, db
from app.models import User, Project, Media
from app import storage


def image_bytes():
    out = io.BytesIO()
    Image.new('RGBA', (64, 64), (255, 0, 0, 100)).save(out, 'PNG')
    return out.getvalue()


class DiskFiles:
    def __init__(self, directory):
        self.root = Path(directory)

    @property
    def objects(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in (self.root / "media").rglob("*") if p.is_file()}

    @property
    def virtual_used(self):
        path = self.root / "quota-test.bin"
        return path.stat().st_size if path.exists() else 0

    @virtual_used.setter
    def virtual_used(self, value):
        # A sparse file exercises real st_size quota accounting without filling disk.
        with (self.root / "quota-test.bin").open("wb") as handle:
            handle.truncate(value)


@pytest.fixture
def env(tmp_path, monkeypatch):
    database = os.getenv('TEST_DATABASE_URL', 'sqlite:///' + str(tmp_path / 'test.db'))
    if database.startswith('postgresql:'):
        assert database.rsplit('/', 1)[-1].endswith('_test'), 'Refusing non-test database'
    monkeypatch.setenv('DATABASE_URL', database)
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('ADMIN_EMAIL', raising=False)
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    monkeypatch.setenv('UPLOAD_DIR', str(tmp_path / 'uploads'))
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY='test-only-secret')
    with app.app_context():
        if database.startswith('postgresql:'):
            db.drop_all()
            db.create_all()
        db.session.add(User(name='Test', email='test@example.com', password_hash='unused'))
        db.session.commit()
    return app


def signed_client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = '1'
        s['_fresh'] = True
        s['csrf'] = 'test-token'
    return c


@pytest.fixture
def local_media(env):
    return env, DiskFiles(env.config['UPLOAD_DIR'])


def create_project(c, title='Test'):
    return c.post('/admin/projects', data={'csrf_token': 'test-token', 'title': title,
        'thumbnail': (io.BytesIO(image_bytes()), 'photo.png')})


def test_public_pages_and_csrf(env):
    c = env.test_client()
    for path in ['/', '/about', '/portfolio', '/contact', '/admin/login', '/healthz']:
        assert c.get(path).status_code == 200
    assert c.post('/admin/login', data={'email': 'x'}).status_code == 400
    assert c.post('/admin/projects', data={'title': 'bad'}).status_code == 400
    assert c.get('/admin/').status_code == 302


def test_upload_shared_reference_delete(local_media):
    app, fake = local_media
    c = signed_client(app)
    assert create_project(c).status_code == 302
    assert len(fake.objects) == 1
    key = next(iter(fake.objects))
    assert key.endswith('.webp')
    with app.app_context():
        p = Project.query.one()
        assert p.hero_path == p.thumbnail_path == key
        pid = p.id
    assert c.post('/admin/storage/delete', data={'csrf_token':'test-token','key':key}).status_code == 409
    assert len(fake.objects) == 1
    assert c.get('/portfolio/test').status_code == 200
    assert c.get('/admin/').status_code == 200
    assert c.get('/admin/storage').status_code == 200
    assert c.post(f'/admin/projects/{pid}/delete', data={'csrf_token':'test-token'}).status_code == 302
    assert not fake.objects


def test_replace_preserves_shared_media(local_media):
    app, fake = local_media
    c = signed_client(app)
    create_project(c)
    first_key = next(iter(fake.objects))
    assert c.post('/admin/projects/1/edit', data={'csrf_token':'test-token','title':'Test',
        'thumbnail':(io.BytesIO(image_bytes()), 'new.png')}).status_code == 302
    assert len(fake.objects) == 2  # old object is still the hero
    with app.app_context():
        assert Project.query.one().hero_path == first_key
    assert c.post('/admin/projects/1/edit', data={'csrf_token':'test-token','title':'Test',
        'hero':(io.BytesIO(image_bytes()), 'new.png')}).status_code == 302
    assert first_key not in fake.objects
    assert len(fake.objects) == 2


def test_exact_quota_and_orphan_accounting(local_media):
    app, fake = local_media
    c = signed_client(app)
    fake.virtual_used = storage.LIMIT
    assert create_project(c).status_code == 413
    assert not fake.objects
    with app.app_context():
        assert Project.query.count() == 0
        assert storage.usage()['available'] == 0
    fake.virtual_used = storage.LIMIT - 1
    assert create_project(c).status_code == 413


def test_boundary_allows_exact_limit(local_media):
    app, fake = local_media
    f = FileStorage(io.BytesIO(image_bytes()), filename='test.png', content_type='image/png')
    with app.app_context():
        stream, size, _, _ = storage._validated_media(f)
        stream.close()
    fake.virtual_used = storage.LIMIT - size
    assert create_project(signed_client(app)).status_code == 302
    with app.app_context():
        assert storage.usage()['used'] == storage.LIMIT


def test_partial_form_failure_cleans_uploaded_object(local_media):
    app, fake = local_media
    c = signed_client(app)
    result = c.post('/admin/projects', data={'csrf_token':'test-token','title':'Failure',
        'thumbnail':(io.BytesIO(image_bytes()), 'photo.png'),
        'video':(io.BytesIO(b'not-a-video'), 'bad.mp4')})
    assert result.status_code == 400
    assert fake.objects == {}
    with app.app_context():
        assert Project.query.count() == 0


@pytest.mark.parametrize('name,mime,content', [
    ('bad.svg','image/svg+xml',b'<svg onload="alert(1)"/>'),
    ('bad.png','image/png',b'<script>bad</script>'),
    ('bad.mp4','video/mp4',b'not a movie'),
    ('bad.png','text/html',image_bytes()),
])
def test_content_validation(local_media, name, mime, content):
    app, fake = local_media
    response = signed_client(app).post('/admin/projects', data={
        'csrf_token':'test-token','title':'Invalid','thumbnail':(io.BytesIO(content), name, mime)})
    assert response.status_code == 400
    assert not fake.objects


def test_production_fail_closed(env, monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)
    with pytest.raises(RuntimeError, match='FLASK_SECRET_KEY'):
        create_app()
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret-that-is-at-least-32-characters')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://test:test@localhost/portfolio_test')
    with pytest.raises(RuntimeError, match='persistent volume'):
        create_app()


def test_login_rate_limit(env):
    c = env.test_client()
    c.get('/admin/login')
    with c.session_transaction() as s:
        token = s['csrf']
    for i in range(15):
        assert c.post('/admin/login', data={'csrf_token':token, 'email':'unknown', 'password':'incorrect'}).status_code == 200
    assert c.post('/admin/login', data={'csrf_token':token, 'email':'unknown', 'password':'incorrect'}).status_code == 429


def test_user_crud_and_inactive_session(env):
    c = signed_client(env)
    assert c.post('/admin/users', data={'csrf_token':'test-token','email':'second@example.com','password':'long-test-password','is_active':'on'}).status_code == 302
    assert c.post('/admin/users/1/delete',data={'csrf_token':'test-token'}).status_code == 302
    with env.app_context():
        assert User.query.count() == 2
    assert c.post('/admin/users/2/delete',data={'csrf_token':'test-token'}).status_code == 302
    with env.app_context():
        assert User.query.count() == 1
        User.query.one().is_active = False
        db.session.commit()
    assert c.get('/admin/').status_code == 302


def test_redirect_url_validation_and_xss(env):
    c = signed_client(env)
    assert c.post('/admin/socials',data={'csrf_token':'test-token','name':'Unsafe','url':'javascript:alert(1)'}).status_code == 400
    assert c.post('/admin/settings',data={'csrf_token':'test-token','home_subtitle':'<script>alert(1)</script>'}).status_code == 302
    assert b'<script>alert(1)</script>' not in c.get('/').data


def test_simultaneous_uploads_cannot_exceed_quota(local_media):
    app, fake = local_media
    f = FileStorage(io.BytesIO(image_bytes()),filename='test.png',content_type='image/png')
    with app.app_context():
        stream,size,_,_ = storage._validated_media(f)
        stream.close()
    fake.virtual_used = storage.LIMIT - size
    barrier = threading.Barrier(2)
    def send(i):
        c = signed_client(app)
        barrier.wait()
        return create_project(c, 'Concurrent ' + str(i)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(send, range(2)))
    assert sorted(statuses) == [302, 413]
    with app.app_context():
        assert storage.usage()['used'] == storage.LIMIT
        assert Project.query.count() == 1


def test_valid_video_and_persistence(local_media):
    import base64
    app, fake = local_media
    content = base64.b64decode('AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAN1bW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAAMgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAp90cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAAMgAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAACAAAAAgAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAADIAAAEAAABAAAAAAIXbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAyAAAACgBVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABwm1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAYJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAACAAIABIAAAASAAAAAAAAAABFUxhdmM2MC4zMS4xMDIgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2UlsBEAAAAMAQAAADIPEiWWAAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAAHcQAAB3EAAAABhzdHRzAAAAAAAAAAEAAAAFAAACAAAAABRzdHNzAAAAAAAAAAEAAAABAAAAOGN0dHMAAAAAAAAABQAAAAEAAAQAAAAAAQAACgAAAAABAAAEAAAAAAEAAAAAAAAAAQAAAgAAAAAcc3RzYwAAAAAAAAABAAAAAQAAAAUAAAABAAAAKHN0c3oAAAAAAAAAAAAAAAUAAALKAAAADAAAAAwAAAAMAAAADAAAABRzdGNvAAAAAAAAAAEAAAOlAAAAYnVkdGEAAABabWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAtaWxzdAAAACWpdG9vAAAAHWRhdGEAAAABAAAAAExhdmY2MC4xNi4xMDAAAAAIZnJlZQAAAwJtZGF0AAACrgYF//+q3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NCByMzEwOCAzMWUxOWY5IC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyMyAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTEgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2ludHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAAAFGWIhAAz//727L4FNhTIUJZ5xxfBAAAACEGaJGxCv/5WAAAACEGeQniF/1XBAAAACAGeYXRCv1rAAAAACAGeY2pCv1rB')
    c = signed_client(app)
    response = c.post('/admin/projects', data={'csrf_token':'test-token','title':'Video',
        'video':(io.BytesIO(content),'test.mp4','video/mp4')})
    assert response.status_code == 302
    key = next(iter(fake.objects))
    assert fake.objects[key] == content
    assert c.get('/portfolio/video').status_code == 200
    response = c.get('/media/' + key)
    assert response.status_code == 200
    assert response.data == content
    ranged = c.get('/media/' + key, headers={'Range':'bytes=0-9'})
    assert ranged.status_code == 206
    assert ranged.data == content[:10]
    assert 'immutable' in response.headers['Cache-Control']
    with app.app_context():
        db.session.remove()
        assert Project.query.one().video_path == key


def test_disk_full_and_path_escape(local_media, monkeypatch):
    from collections import namedtuple
    app, files = local_media
    c = signed_client(app)
    disk = namedtuple('Disk', 'total used free')
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda _: disk(100,100,0))
    assert create_project(c).status_code == 507
    assert not files.objects
    assert c.get('/media/../secret.txt').status_code == 404
    assert c.get('/media/media/../../secret.txt').status_code == 404


def test_survives_app_restart(local_media):
    app, files = local_media
    c = signed_client(app)
    create_project(c)
    key = next(iter(files.objects))
    second_app = create_app()
    second_app.config['TESTING'] = True
    assert second_app.test_client().get('/media/' + key).status_code == 200
    assert second_app.test_client().get('/portfolio/test').status_code == 200


def test_linebreaks_are_not_literal_html(env):
    response = env.test_client().get('/')
    assert b'&lt;br&gt;' not in response.data
    assert b'white-space:pre-line' in response.data


def test_initial_setup_is_one_time(env, monkeypatch):
    token = 'test-setup-token-32-characters-long'
    monkeypatch.setenv('ADMIN_SETUP_TOKEN', token)
    monkeypatch.setenv('ADMIN_SETUP_EMAIL','loriotvalentin9@gmail.com')
    with env.app_context():
        db.session.query(User).delete()
        db.session.commit()
    c = env.test_client()
    assert c.get('/admin/setup').status_code == 200
    with c.session_transaction() as session:
        csrf = session['csrf']
    assert c.post('/admin/setup',data={'csrf_token':csrf,'setup_token':'bad'}).status_code == 403
    assert c.post('/admin/setup',data={'csrf_token':csrf,'setup_token':token,'password':'test-long-password',
        'confirm_password':'test-long-password'}).status_code == 302
    assert c.get('/admin/setup').status_code == 404
    assert c.post('/admin/login',data={'csrf_token':csrf,'email':'loriotvalentin9@gmail.com',
        'password':'test-long-password'}).status_code == 302
    assert c.get('/admin/').status_code == 200


def test_deploy_gate_requires_successful_ci(tmp_path, monkeypatch):
    from app import deployment
    monkeypatch.setenv('DEPLOY_WEBHOOK_URL','https://nostracodes.com.br/api/deploy/test-only')
    monkeypatch.setenv('DEPLOY_STATE_FILE',str(tmp_path/'watch.json'))
    monkeypatch.setenv('DEPLOY_BASELINE','old')
    monkeypatch.setattr(deployment,'github',lambda path: {'sha':'new'} if path=='/commits/main' else {'workflow_runs':[]})
    assert deployment.deployment_check()['status'] == 'waiting-for-ci'
    assert not (tmp_path/'watch.json').exists()
    class Accepted:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
    monkeypatch.setattr(deployment,'github',lambda path: {'sha':'new'} if path=='/commits/main' else {'workflow_runs':[
        {'head_sha':'new','head_branch':'main','event':'push','name':'Validate portfolio','status':'completed','conclusion':'success'}]})
    monkeypatch.setattr(deployment,'urlopen',lambda *a,**k: Accepted())
    assert deployment.deployment_check()['status'] == 'deploy-triggered'
    assert deployment.deployment_check()['status'] == 'up-to-date'


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'),reason='PostgreSQL restore is tested in CI')
def test_postgresql_backup_and_restore(local_media, monkeypatch, tmp_path):
    from app.backups import create_snapshot, verify_snapshot
    app, files = local_media
    monkeypatch.setenv('BACKUP_DIR',str(tmp_path/'backups'))
    create_project(signed_client(app))
    with app.app_context():
        snapshot = create_snapshot()
        manifest = verify_snapshot(snapshot)
        assert manifest['tables']['project'] == 1
        assert len(manifest['files']) == 1
