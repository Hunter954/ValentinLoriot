"""Local snapshots in a separate volume. Never substitutes an off-server backup."""
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import click
import psycopg2
from psycopg2 import sql
from flask import current_app
from sqlalchemy import text
from sqlalchemy.engine import make_url

from . import db
from .storage import inventory, root, write_lock


def connection_settings():
    uri = make_url(current_app.config['SQLALCHEMY_DATABASE_URI'])
    return dict(host=uri.host, port=uri.port or 5432, user=uri.username,
                password=uri.password, dbname=uri.database)


def pg_env(settings):
    env = os.environ.copy()
    for field, name in [('host','PGHOST'),('port','PGPORT'),('user','PGUSER'),
                        ('password','PGPASSWORD'),('dbname','PGDATABASE')]:
        if settings.get(field) is not None:
            env[name] = str(settings[field])
    return env


def counts(connection):
    tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars()
    return {name: connection.execute(text('SELECT count(*) FROM "' + name.replace('"','""') + '"')).scalar_one()
            for name in tables if name != 'login_throttle'}


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def create_snapshot():
    backup_root = Path(os.getenv('BACKUP_DIR', '/backups')).resolve()
    if current_app.config['PRODUCTION'] and not backup_root.is_mount():
        raise click.ClickException('Configure um volume persistente separado em /backups.')
    backup_root.mkdir(parents=True, exist_ok=True)
    if backup_root.is_relative_to(root()) or root().is_relative_to(backup_root):
        raise click.ClickException('O destino de backup deve ficar separado dos uploads.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    snapshot = backup_root / ('valentin-' + stamp + '-' + uuid.uuid4().hex[:8] + '.partial')
    snapshot.mkdir(mode=0o700)
    try:
        with write_lock():
            files = inventory()
            if shutil.disk_usage(backup_root).free < sum(f['Size'] for f in files) + 1024**3:
                raise click.ClickException('Sem espaço livre suficiente para criar backup com segurança.')
            with db.engine.connect() as conn:
                record_counts = counts(conn)
            dump = snapshot / 'database.dump'
            subprocess.run(['pg_dump','--format=custom','--no-owner','--no-acl','--file',str(dump)],
                           env=pg_env(connection_settings()), check=True, timeout=300, capture_output=True)
            with tarfile.open(snapshot / 'media.tar', 'w') as archive:
                for item in files:
                    archive.add(root() / item['Key'], arcname=item['Key'], recursive=False)
            manifest = {'created_at':stamp, 'tables':record_counts, 'files':files,
                        'database_sha256':digest(dump), 'media_sha256':digest(snapshot / 'media.tar')}
            (snapshot / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        ready = snapshot.with_suffix('')
        snapshot.rename(ready)
        # Retain fourteen completed snapshots, excluding incomplete or unrelated directories.
        finished = sorted(p for p in backup_root.glob('valentin-*')
                          if p.is_dir() and p.suffix != '.partial' and (p/'manifest.json').is_file())
        for old in finished[:-14]:
            shutil.rmtree(old)
        return ready
    except BaseException:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise


def verify_snapshot(snapshot):
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    if digest(snapshot/'database.dump') != manifest['database_sha256'] or digest(snapshot/'media.tar') != manifest['media_sha256']:
        raise click.ClickException('Integridade do backup inválida.')
    with tarfile.open(snapshot/'media.tar') as archive:
        members = archive.getmembers()
        if any(not m.isfile() or Path(m.name).is_absolute() or '..' in Path(m.name).parts for m in members):
            raise click.ClickException('Caminho inválido no arquivo de mídia.')
        if {m.name:m.size for m in members} != {x['Key']:x['Size'] for x in manifest['files']}:
            raise click.ClickException('O inventário de mídias não corresponde ao backup.')
    settings = connection_settings()
    restore_name = 'valentin_restore_test_' + uuid.uuid4().hex[:16]
    conn = psycopg2.connect(**settings)
    conn.autocommit = True
    created = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(restore_name)))
            created = True
        restored = dict(settings, dbname=restore_name)
        subprocess.run(['pg_restore','--no-owner','--no-acl','--exit-on-error','--dbname',restore_name,
                        str(snapshot/'database.dump')], env=pg_env(restored), check=True, timeout=300, capture_output=True)
        with closing(psycopg2.connect(**restored)) as test_conn:
            with test_conn.cursor() as cur:
                for name, expected in manifest['tables'].items():
                    cur.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(name)))
                    if cur.fetchone()[0] != expected:
                        raise click.ClickException('Contagem divergente na restauração de teste.')
        return manifest
    finally:
        if created:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(restore_name)))
        conn.close()


def init_backups(app):
    @app.cli.command('backup-create')
    @click.option('--verify', is_flag=True, help='Testar restauração em banco descartável.')
    def backup_create(verify):
        try:
            snapshot = create_snapshot()
            if verify:
                verify_snapshot(snapshot)
            click.echo(json.dumps({'status':'ok','snapshot':snapshot.name,'restore_verified':verify}))
        except subprocess.SubprocessError:
            raise click.ClickException('A ferramenta PostgreSQL falhou. Verifique a configuração do backup.') from None

    @app.cli.command('backup-verify')
    @click.argument('snapshot', type=click.Path(exists=True, path_type=Path))
    def backup_verify(snapshot):
        try:
            verify_snapshot(snapshot)
            click.echo('Restauração descartável e inventário de mídia verificados.')
        except subprocess.SubprocessError:
            raise click.ClickException('Falha ao testar restauração do PostgreSQL.') from None
