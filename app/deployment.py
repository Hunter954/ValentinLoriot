"""Poll public GitHub CI and invoke only this application's private deploy hook."""
import json
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

import click
from flask import current_app

REPO = 'Hunter954/ValentinLoriot'


def github(path):
    req = Request('https://api.github.com/repos/' + REPO + path,
                  headers={'Accept':'application/vnd.github+json','User-Agent':'valentin-deploy-watch'})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def deployment_check():
    hook = os.getenv('DEPLOY_WEBHOOK_URL', '')
    parsed = urlsplit(hook)
    if parsed.scheme != 'https' or parsed.netloc != 'nostracodes.com.br' or not parsed.path.startswith('/api/deploy/'):
        raise click.ClickException('Webhook privado do aplicativo não configurado.')
    state = Path(os.getenv('DEPLOY_STATE_FILE', '/data/deployment-state.json'))
    previous = json.loads(state.read_text())['head'] if state.exists() else os.getenv('DEPLOY_BASELINE', '')
    head = github('/commits/main')['sha']
    if head == previous:
        return {'status':'up-to-date','head':head}
    runs = github('/actions/runs?branch=main&head_sha=' + head + '&per_page=10')['workflow_runs']
    if not any(r['head_sha'] == head and r.get('head_branch') == 'main' and r.get('event') == 'push'
               and r.get('name') == 'Validate portfolio' and r.get('status') == 'completed'
               and r.get('conclusion') == 'success' for r in runs):
        return {'status':'waiting-for-ci','head':head}
    state.parent.mkdir(parents=True, exist_ok=True)
    prior_content = state.read_text() if state.exists() else None
    with tempfile.NamedTemporaryFile(mode='w', dir=state.parent, delete=False) as temp:
        json.dump({'head':head}, temp)
        temporary = Path(temp.name)
    temporary.replace(state)
    try:
        payload = {'ref':'refs/heads/main', 'head_commit':{'id':head, 'message':'Deploy main apos validacao CI'}, 'commits':[]}
        req = Request(hook, data=json.dumps(payload).encode(),
                      headers={'Content-Type':'application/json','X-GitHub-Event':'push'}, method='POST')
        with urlopen(req, timeout=30) as response:
            if not 200 <= response.status < 300:
                raise ValueError('Deploy not accepted')
    except Exception:
        if prior_content is None:
            state.unlink(missing_ok=True)
        else:
            state.write_text(prior_content)
        raise click.ClickException('Não foi possível acionar o deploy. Tentaremos no próximo ciclo.') from None
    return {'status':'deploy-triggered','head':head}


def init_deployment(app):
    @app.cli.command('deployment-watch')
    def watch():
        if not current_app.config['PRODUCTION']:
            raise click.ClickException('Deploy automático está disponível apenas em produção.')
        try:
            click.echo(json.dumps(deployment_check()))
        except (OSError, ValueError):
            raise click.ClickException('GitHub ou estado do deploy indisponível. Tente novamente no próximo ciclo.') from None
