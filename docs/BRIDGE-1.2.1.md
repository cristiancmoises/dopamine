# Dopamine 1.2.1 — ponte específica para a primeira 1.1.0 / esquema 2

## Origem suportada
Este pacote aceita exclusivamente o código e a imagem da primeira variante 1.1.0
(catálogo original de 512 itens), com user_version=2 e estrutura SQLite conhecida.
Reconhece também as cópias EXATAS de BUILD_PROMPT.md, CHANGELOG.md, README.md,
SECURITY.md e docs/ da 1.2.0 que foram aplicadas pelas instruções anteriores.
Não é necessário desfazer essas cópias manualmente. Alterações desconhecidas continuam
bloqueadas, agora listadas em conjunto, sem sobrescrever arquivo por arquivo.

Não utilize o antigo dopamine-update-1.2.0.tar.gz, os comandos de normalização de
arquivos ou PRAGMA user_version manual. Este pacote não altera .env nem recompõe
um banco antigo sobre a base em uso.

## Arquivo e envio
Nome: dopamine-update-1.2.1-early11.tar.gz. Confira o SHA-256 fornecido junto ao download
ANTES de extrair. Não reutilize o checksum de outra versão.

No computador, com o arquivo em ~/Downloads (Fish):

```fish
scp -P 5119 ~/Downloads/dopamine-update-1.2.1-early11.tar.gz root@securityops.co:/root/
ssh -p 5119 root@securityops.co
```

Na VPS, extraia em um diretório de staging NOVO. Não mova /opt/dopamine nem
reextraia o novo source sobre ele. O entrypoint é apply.fish; opções: --target,
--npm, --check. --check faz leitura dos arquivos, runtime e metadados do banco;
cria apenas o arquivo de trava do atualizador, não aplica a versão.

```fish
set -l stage (mktemp -d /root/dopamine-bridge121.XXXXXXXX)
test -n "$stage"
and tar --no-same-owner --no-same-permissions -xzf /root/dopamine-update-1.2.1-early11.tar.gz -C "$stage"
and fish "$stage/dopamine-update-1.2.1-early11/apply.fish" --target /opt/dopamine --npm npm-attachment --check
and fish "$stage/dopamine-update-1.2.1-early11/apply.fish" --target /opt/dopamine --npm npm-attachment
```

As opções do atualizador acima não recebem senhas ou segredos. Não publique .env
ou os backups. Nenhuma senha de NPM é necessária.

## Ordem da atualização
1. Confere TODOS os hashes do pacote e dos arquivos locais gerenciados. Confere
   37 arquivos do runtime antigo, esquema 2 e a estrutura efetiva das tabelas.
2. Confere container Compose dopamine/web, NPM ativo, rede npm-bridge,
   TRUSTED_PROXY_CIDRS com IP exato, DATABASE_PATH, volume nomeado e ausência
   de portas publicadas. .env e ambiente do container precisam concordar.
3. Exige 2 GiB livres nos filesystems do projeto e do Docker e banco de até
   128 MiB para este fluxo conservador de snapshots. Não amplia esses limites
   silenciosamente. Não executa prune, down -v ou regras de firewall.
4. Retém a imagem antiga por ID, salva arquivos/configuração privadamente e
   cria um snapshot SQLite com a API de backup, incluindo conteúdo confirmado
   do WAL. Um helper temporário usa a imagem antiga e monta o volume somente
   para leitura; não recebe segredos nem acesso à rede.
5. Constrói dopamine-local:1.2.1 com testes, check-config do Gunicorn e importação
   real de fotografias. A aplicação antiga CONTINUA em execução nessa fase.
6. Ensaios em cópia: migração duas vezes, integridade, chaves estrangeiras,
   igualdade dos valores de todas as tabelas existentes e do DDL anterior.
7. Cria marcador de manutenção com nonce próprio e para SOMENTE o serviço web.
   Faz snapshot final e repete o ensaio para incluir as gravações feitas
   enquanto o build estava em andamento.
8. Copia o source validado. Remove apenas quatro arquivos funcionais antigos
   conhecidos e já salvos (módulo currency antigo, teste de release antigo e
   seus dois fixtures), evitando testes obsoletos em builds futuros.
9. Recria SOMENTE web, no mesmo volume e rede. O entrypoint aplica a migração
   aditiva. Confere imagem por ID, 47 hashes do runtime novo, esquema/recursos,
   fotografias e HTTP do NPM para /healthz, /shop e /signup.
10. Remove SOMENTE seu próprio marcador e libera os POSTs. NPM não é reiniciado,
    seu banco não é editado e porta 8000 não é publicada.

## Migração e histórico
O número do core continua **user_version=2**. A tabela rounds original, seus
nove jogos, IDs, request_key, timestamps, valores e result_json não são regravados.
São adicionadas extra_rounds, all_rounds, interactive_rounds, interactive_actions,
schema_features e seus índices. O marcador early11_bridge=1 identifica a ponte;
interactive_tables=1 identifica o recurso interativo. Nenhum user_version é
rebaixado para 1. Não usamos writable_schema, nem DROP/rename da tabela rounds.

As 512 identidades históricas vêm da PRIMEIRA 1.1.0, não da segunda variante.
Recibos conservam nomes e preços armazenados, sem transformá-los em produtos
reais. Resultados antigos com tiles são exibidos a partir do JSON salvo, sem
nova rodada. Login, recuperação e hash das senhas não são recalculados.
Limpeza rotineira de sessões expiradas continua sendo função do aplicativo.

## Fotografias e build
O pacote mantém os recursos interativos da 1.2.0. Contém 1.056 candidatos reais,
não 1.056 produtos já verificados. Como a origem contém 512 itens, o piso desta
ponte é **513 itens/fotos aceitos**, com teto de 640. Nomes, identidades e fotos
compartilhadas entre itens são rejeitados conforme as regras do importador.
Não há fallback genérico nem cópias repetidas para preencher catálogo. O build
falha antes do cutover se a importação não atingir o piso. Nenhuma fotografia
real nova foi baixada ou revisada visualmente nesta execução de autoria.
A checagem de metadados e similaridade não substitui revisão humana das imagens.

O fixture tests/fixtures/early11-source.tar.gz é código histórico de teste,
não contém banco de usuários, segredos de produção ou fotografias. O Dockerfile
inclui explicitamente esse fixture para executar os testes da ponte no build.

## Validação pública após o update
```fish
curl --fail --silent --show-error --connect-timeout 10 --max-time 20 -D - https://dopamine.securityops.co/healthz
```
Esperado: HTTP 200, x-dopamine-version: 1.2.1 e corpo
{"status":"ok","service":"dopamine"}. Não use -k como prova de certificado válido.
O updater valida HTTP interno a partir do NPM; não certifica DNS/TLS público.

NPM permanece: domínio dopamine.securityops.co, scheme http, host dopamine-web,
porta 8000, rede npm-bridge. Não altere seu certificado ou o upstream.

## Falhas e rollback
O diretório exato é impresso antes do build, sob:
/opt/dopamine-backups/bridge121-<timestamp>/

O comando exato também é impresso:
fish /opt/dopamine-backups/bridge121-<timestamp>/rollback.fish

Antes do cutover: falhas de build/importação/primeiro ensaio deixam o app antigo
em execução. Após parar web e antes de copiar source: uma falha tenta iniciar
novamente o container antigo e limpar somente o marcador próprio.
Depois da troca: uma falha tenta restaurar source e imagem retida, sem restaurar
um snapshot sobre os dados atuais. A mesma estrutura core-2 permite o runtime
antigo voltar a usar o banco. Tabelas novas permanecem preservadas, mas seus
jogos podem ficar invisíveis no runtime antigo até a reatualização.

O rollback manual também preserva gravações posteriores. Ele recusa .env,
backup, imagem ou source alterados desde a atualização. Não presume recuperação
bem-sucedida se Docker/host falharem: imprime o diretório e o comando para inspeção.
Morte abrupta do processo/servidor pode deixar manutenção ativa; utilize o rollback
salvo. Não remova marcadores desconhecidos e não rode dois updaters simultaneamente.

Backups são privados (diretório 0700; arquivos sensíveis 0600), mas NÃO criptografados.
Não os exponha na web nem os cole na conversa. Retenção não é automatizada por
este patch; não remova os backups antes de validar o serviço.
