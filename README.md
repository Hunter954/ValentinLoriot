# Valentin Loriot — VPS + Dokploy + PostgreSQL

Portfólio Flask com painel administrativo e mídias em volume persistente na VPS, limitado pela aplicação a 3.000.000.000 bytes. A implantação usa o Dockerfile e o volume `valentin-loriot-media` montado em `/data`; veja [DEPLOY.md](DEPLOY.md) para configuração, validações e recuperação.

Imagens são validadas e convertidas para WebP; vídeos compactados são validados sem transcodificação. O painel mostra armazenamento real. A cota é aplicada no backend com trava PostgreSQL para uploads simultâneos; não é uma quota física do sistema de arquivos.

## Desenvolvimento

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.lock pytest==9.1.1
.venv/bin/python -m pytest -q
.venv/bin/flask --app app create-admin
.venv/bin/flask --app app run
```

Use PostgreSQL em produção; SQLite com trava de arquivo é permitido apenas no desenvolvimento. Não use seed-demo em produção. Senhas e segredos devem ser configurados fora do Git.
