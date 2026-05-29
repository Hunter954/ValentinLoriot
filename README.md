# Valentin Loriot Portfolio — Flask + PostgreSQL + Railway Volume

Projeto pronto para GitHub/Railway, com site público no layout preto + amarelo das referências e painel administrativo para gerenciar clientes, portfólio, vídeos, fotos, redes sociais e textos.

## O que vem pronto

- Home, About, Portfolio, detalhe do projeto e Contact.
- Painel `/admin` moderno e responsivo.
- Upload de imagens e vídeos para uma pasta persistente.
- PostgreSQL via `DATABASE_URL`.
- Volume Railway via `UPLOAD_DIR=/data/uploads`.
- Redes sociais no bloco **RETROUVEZ-MOI** e no rodapé abaixo da logomarca, em ícones brancos pequenos.
- CRUD de clientes, projetos, galeria de mídias, usuários e textos do site.

## Rodar local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app app init-db
flask --app app seed-demo
flask --app app run --debug
```

Depois acesse:

- Site: `http://127.0.0.1:5000`
- Admin: `http://127.0.0.1:5000/admin/login`

Para criar o primeiro admin local, configure no `.env`:

```env
ADMIN_EMAIL=admin@site.com
ADMIN_PASSWORD=123456
```

Reinicie o app. O usuário é criado automaticamente se ainda não existir.

## Subir no Railway

1. Crie um projeto no Railway conectado ao repositório GitHub.
2. Adicione um banco PostgreSQL.
3. Crie um volume e monte em `/data`.
4. Configure as variáveis:

```env
FLASK_SECRET_KEY=gere-uma-chave-grande
DATABASE_URL=${{Postgres.DATABASE_URL}}
UPLOAD_DIR=/data/uploads
ADMIN_EMAIL=seuemail@dominio.com
ADMIN_PASSWORD=senha-forte-aqui
```

5. Deploy. O `railway.json` e o `Procfile` já iniciam com Gunicorn usando `run:app`.

## Como usar o painel

1. Entre em `/admin/login`.
2. Cadastre os clientes e envie as logos, preferencialmente PNG branco/transparente.
3. Crie os projetos com thumbnail, capa/hero, vídeo local ou link externo.
4. Edite o projeto e adicione fotos/vídeos na galeria.
5. Em **Redes sociais**, cadastre Instagram, YouTube e LinkedIn. Eles aparecem no About e no rodapé.
6. Em **Textos do site**, ajuste telefone, e-mail, biografia, números de experiência e subtítulos.

## Correção importante para Railway

Este pacote inclui `run.py` porque alguns deploys do Railway/Gunicorn procuram automaticamente por `run:app`. Sem esse arquivo, o container pode cair com `ModuleNotFoundError: No module named 'run'`.

## Observações importantes

- Para vídeos grandes, aumente o limite do proxy/plano se necessário. O app já aceita até 900 MB por upload.
- Em produção, use senha forte e `FLASK_SECRET_KEY` exclusiva.
- O layout foi montado para ficar visualmente fiel às imagens enviadas, com tipografia Poppins, preto absoluto, amarelo forte, cards arredondados e bordas finas amarelas.
