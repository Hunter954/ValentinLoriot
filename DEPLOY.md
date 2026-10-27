# Valentin Loriot — implantação Dokploy

A implantação parte de banco novo, conforme confirmado pelo proprietário. Não existe origem a migrar.

## Aplicação

- Dockerfile, Python 3.11, usuário 10001 não-root, Gunicorn 1 worker / 2 threads.
- Porta interna 5000; publicar somente pelo Traefik com HTTPS.
- Limite CPU 500000000 nanoCPUs; reserva 100000000.
- Limite RAM 536870912 bytes; reserva 134217728.
- Não montar Docker socket, diretórios do host ou portas administrativas.
- Inicialização explícita `flask --app app init-db` antes do Gunicorn. Não usar seed-demo em produção.
- Primeiro administrador: comando interativo `flask --app app create-admin`. A senha não entra no código nem no histórico de comandos.
- Configurar log driver local ou json-file com max-size=10m, max-file=3 e restart on-failure no serviço específico.

## Variáveis privadas

`APP_ENV=production`, `FLASK_SECRET_KEY` aleatória com pelo menos 32 caracteres, `DATABASE_URL` privada do PostgreSQL exclusivo, `PORT=5000`.

`UPLOAD_DIR=/data/uploads`. Montar o volume Docker exclusivo `valentin-loriot-media` em `/data`. O Dockerfile prepara o diretório para UID/GID 10001. A aplicação em produção recusa iniciar se `/data` não for uma montagem persistente ou se o caminho de upload estiver fora dele. PostgreSQL é obrigatório.

Armazenamento de mídias na própria VPS, conforme decisão do proprietário. Sem integração R2, credenciais Cloudflare ou serviço de bucket externo.

## Cota e mídias

Limite exato de 3.000.000.000 bytes. O backend soma os tamanhos reais de todos os arquivos no volume, incluindo órfãos e uploads interrompidos. Um advisory lock PostgreSQL em conexão separada serializa as escritas durante checagem, gravação atômica, commit do banco e exclusão sem referências. Arquivos temporários são gravados no diretório de destino, sincronizados e renomeados atomicamente. Há verificação de espaço livre antes de gravar, com reserva de 256 MiB para não esgotar o disco.

Essa é uma cota da aplicação, não uma reserva física de 3 GB nem uma quota imposta pelo sistema de arquivos ao volume Docker. Quem puder executar código arbitrário no contêiner pode contornar a cota da aplicação. Para garantia contra código modificado pelo cliente, exigir revisão antes de produção ou usar serviço de upload isolado/quotas do sistema de arquivos configuradas pelo administrador.

Imagens até 16 MB e 16 megapixels, WebP qualidade 90, máximo 4096 px, transparência preservada, metadados removidos. GIF/WebP animados são rejeitados com orientação para usar vídeo. SVG é bloqueado. Vídeos até 80 MB, validação por assinatura e ffprobe limitado a 15 segundos; sem transcodificação. Requisição inteira até 90 MB. MP4 H.264 e WebM são os formatos recomendados; links HTTP(S) externos continuam suportados.

O painel mostra uso real, disponível, porcentagem e alertas de 80/95/100%. Objetos compartilhados permanecem enquanto houver referências. A exclusão no painel de arquivos bloqueia objetos em uso. Falhas de limpeza deixam os objetos contabilizados para exclusão manual segura.

`flask --app app storage-reconcile` recalcula e imprime o inventário real e a quantidade sem referências. Agendar diariamente no serviço específico. O indicador também reconcilia ao abrir o painel e antes de cada upload; não depende do agendamento para aplicar a cota.

URLs `/media/...` são persistentes e servem os arquivos locais com suporte a Range (vídeos) e cache imutável de um ano. Caminhos fora do diretório, symlinks e arquivos temporários não são servidos.

## Deploy e rollback

CI usa PostgreSQL 16 descartável, banco `portfolio_test`, para testar concorrência real. Credencial CI no workflow é apenas do banco efêmero, sem vínculo com produção. Builds Docker também passam no CI.

Fonte de verdade: GitHub. Conectar Dokploy à branch main e configurar acionamento após sucesso do CI. Se o provedor instalado não suportar esse gatilho, usar webhook privado disparado por workflow após testes; o segredo deve ser cadastrado nas configurações GitHub, nunca no YAML. Não habilitar push direto sem gate de testes.

Rollback: voltar à imagem/commit previamente validado no histórico de deploys. A primeira implantação ainda não tem versão anterior de produção; manter o banco persistente, nunca reconstruí-lo para reverter código.

## Backups

Configurar backup PostgreSQL diário com retenção de 14 dias em destino separado do volume de mídia. Testar restauração em outro banco descartável e comparar tabelas/contagens. Configurar também backup diário do volume `valentin-loriot-media`, com retenção definida e teste de restauração. Backups não contam na cota de mídia. Uma cópia no mesmo disco não protege contra perda da VPS; manter cópia externa independente. Não declarar backup disponível antes de configurar e testar.

## Acesso do cliente

E-mail informado: loriotvalentin9@gmail.com. Papel Member, somente este projeto e somente permissões comprovadamente seguras. Não liberar terminal, segredos, alterações de recursos/rede/volumes, exclusões de serviço nem acesso global. Código executável pode ler segredos da própria aplicação: limitar permissões do painel não impede exfiltração pelo código. Manter revisão de código antes de publicar alterações do cliente. A cota da aplicação requer controle do código que aplica a validação, conforme explicado acima.

## Estado de validação

Testes locais: páginas públicas, CSRF, CRUD de usuários, conta inativa, MIME/conteúdo, cota exata, excedente, concorrência com trava de arquivo de desenvolvimento, disco cheio, limpeza em falha, referências compartilhadas, Range de vídeo e persistência após reiniciar a aplicação. O job de CI valida também a trava PostgreSQL. HTTPS, consumo, volume montado após redeploy, backup/restore e conta Member só podem ser marcados concluídos após testes no ambiente publicado.

## Operação automatizada

- Volume adicional `valentin-loriot-backups` em `/backups`, separado de `/data`.
- `flask --app app backup-create --verify`: snapshot do PostgreSQL e tar de mídias sob a mesma trava dos uploads; manifesto com SHA-256 e contagens; restauração em banco descartável com exclusão somente desse banco de teste. Retenção de 14 snapshots completos. A cópia local não protege contra perda do servidor; exportar cópia para outro destino continua necessário.
- Agendar backup diariamente às 06:10 UTC (03:10 em Brasília), dentro do próprio contêiner, com usuário 10001. Configurar `BACKUP_DIR=/backups`.
- `flask --app app deployment-watch`: consultar o commit de `main` e o resultado do workflow `Validate portfolio`; acionar somente o webhook privado deste serviço depois de sucesso. Agendar a cada 5 minutos. Definir `DEPLOY_WEBHOOK_URL` no ambiente privado e `DEPLOY_BASELINE` como o commit inicialmente publicado. O estado é persistido em `/data/deployment-state.json`, fora da cota de mídias.
- Desativar o agendamento de deploy antes de um rollback manual para impedir que o observador recoloque a versão mais recente automaticamente.
- Primeiro acesso: configurar `ADMIN_SETUP_EMAIL=loriotvalentin9@gmail.com` e `ADMIN_SETUP_TOKEN` aleatório com pelo menos 32 caracteres. Abrir `/admin/setup`; o operador fornece a chave pelo formulário e o cliente define a senha. A página fica indisponível depois que existe o primeiro usuário. A chave nunca deve entrar no Git ou em links públicos; remover a variável depois da criação.
- `backup-verify /backups/<snapshot>` permite testar novamente o banco e o inventário da mídia. Uma recuperação real deve ser feita pelo administrador em ambiente novo, usando `pg_restore` e o arquivo `media.tar`, após validar o manifesto e os caminhos; não sobrescrever produção como teste.
