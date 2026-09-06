# 1.2.1 operational fixes / Correções operacionais

## English

On the audited IONOS host, IPv4 access to Wikimedia completed in about 0.21 s
while IPv6 connections timed out. `DOPAMINE_CATALOG_IPV4=1` is an opt-in build
setting for the catalog importer only; normal application networking and the
host's IPv6 remain unchanged. TLS verification, source allowlist, license and
identity checks, duplicate detection and the publication floor are preserved.
Progress is reported for each metadata block, with accepted/rejected counts.
The completed catalog contained 617 distinct verified local images.

Full startup validation against an isolated database copy took 145 seconds.
Compose now allows a 180-second startup grace; the early-1.1 updater waits up to
360 seconds for health. Checks are not skipped. Docker remains responsible for
process lifecycle; the unused Gunicorn control socket is disabled, avoiding a
write attempt under the read-only home directory. See the
[Gunicorn control setting](https://gunicorn.org/reference/settings/#control-socket-disable).

When preparing a locally modified bridge bundle, reconcile BOTH `files` and
`runtime_new` hashes against the actual candidate release. Never alter
`runtime_early`, source baseline hashes or known schema definitions to make an
unknown installation pass. The first candidate correctly rolled back after a
stale expected new-runtime hash; a later health-window failure also rolled back.
Both rollbacks retained the live data volume and did not restore an old database.

Run `python manage.py test` before deployment (160 tests passed for these code
changes). Build tests, isolated startup, migration rehearsal and public checks
are separate validations; none alone proves production deployment completed.

## Português do Brasil

Na IONOS auditada, o Wikimedia respondeu via IPv4 em cerca de 0,21 s, enquanto
IPv6 expirou. `DOPAMINE_CATALOG_IPV4=1` opta por IPv4 somente na importação do
catálogo, sem alterar a rede da aplicação ou o IPv6 do host. TLS, allowlist,
licença, identidade, duplicatas e mínimo de publicação continuam validados.
O progresso agora mostra cada bloco e suas contagens; o catálogo concluído tinha
617 fotos locais distintas e verificadas.

A inicialização com cópia isolada do banco levou 145 segundos. O Compose permite
180 segundos de tolerância inicial e o atualizador aguarda saúde por até 360
segundos, sem pular verificações. O socket administrativo não utilizado do
Gunicorn foi desativado, evitando escrita no diretório home somente leitura.

Pacotes de ponte modificados devem atualizar hashes de `files` E `runtime_new`
conforme os arquivos reais do candidato. Não altere hashes da versão antiga nem
definições conhecidas do esquema. As duas tentativas revertidas preservaram o
volume em uso; nenhum snapshot antigo foi restaurado sobre os dados ativos.
Os 160 testes locais passaram. Testes de imagem, inicialização isolada, ensaio
da migração e validação pública são etapas distintas da implantação.
