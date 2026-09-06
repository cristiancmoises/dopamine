# Validação — Dopamine 1.2.1 / early11-schema2-v1

## Escopo e materiais
Análise e implementação feitas a partir dos arquivos montados nesta conversa:
- dopamine-1.1.0.tar.gz: PRIMEIRA variante 1.1.0, SHA-256
  c52967c53247d3556daad5684d75714cdd790199b41a9a659896212ff0b5a073.
- dopamine-update-1.2.0.tar.gz: pacote original incompatível, SHA-256
  8b0f9e32224d4972d859ee767c3ccf4ce7bfe55f182ab91f311a605f60d94a9d.
- Diagnóstico apresentado pelo usuário: seis âncoras locais e cinco de runtime
  correspondem à primeira variante; user_version=2; rounds contém result_json.

Nenhum banco, senha, cookie ou dado de usuário da VPS foi transferido para este
ambiente. Nenhuma conexão SSH/deploy na VPS foi executada pelo assistente.

## Correção
1. Os manifests agora reconhecem a primeira 1.1.0 especificamente e verificam
   o conjunto de arquivos, não apenas a string ambígua de versão.
2. Copiar documentação para passar um hash não era uma migração válida. A ponte
   aceita as cópias exatas já indicadas anteriormente, conservando os backups,
   mas rejeita código desconhecido e apresenta todas as divergências juntas.
3. Para schema 2, a migração valida o DDL efetivo contra a origem conhecida,
   índices e recursos permitidos. Adiciona tabelas, view e índices em transação.
   rounds e demais tabelas antigas não são reconstruídas. user_version continua 2.
   Marcador: schema_features('early11_bridge',1).
4. O catálogo histórico é o de 512 itens da origem correta. Resultados antigos
   do tipo {'schema':1,'tiles':...} têm renderização explícita e escapada, sem
   reexecução. A roleta antiga aparece como demonstração histórica.
5. Snapshot antes do build e snapshot final com web parado; ensaio em cópias
   isoladas; mesma .env, SECRET_KEY, rede npm-bridge e volume. Marcador próprio
   de manutenção bloqueia POSTs até os testes de runtime/upstream concluírem.
6. Falha de build não para o app; falha antes de trocar source reinicia o antigo;
   falha após a troca tenta rollback da imagem/source. Nenhum caminho restaura
   automaticamente snapshot antigo sobre a base atual.

## Testes realmente executados
`python manage.py test` passou com **156 métodos de teste**, em execução completa
seguida de repetição. O teste final está em docs/evidence-1.2.1/regression.txt.
São 123 testes herdados de regressão, 17 testes de migração/compatibilidade e
16 testes específicos do atualizador da ponte. Não confundir métodos de teste
com a contagem de todas as páginas/opções percorridas dentro deles.

Os testes específicos de compatibilidade executaram:
- Extração do source histórico com SHA-256 verificado e execução real dessa
  primeira 1.1.0 em subprocesso Python.
- Cadastro, compras e rodadas dos nove jogos na implementação antiga, em banco
  descartável. Em seguida, migração e repetição da inicialização.
- Comparação de TODOS os valores nas tabelas existentes e dos seus DDLs antes/
  depois do ensaio, preservando senhas/recuperação como valores sem imprimi-los.
- Renderização dos recibos e resultados nos quatro idiomas, incluindo roleta;
  preservação das 512 identidades/preços históricos; login/sessão antigos;
  exportação sem credenciais; exclusão com cascata; escape de tiles.
- Rejeição de esquema 2 arbitrário/incompleto, recurso de revisão desconhecida,
  chaves estrangeiras quebradas; rollback transacional em SQL inválido.
- Três inicializações concorrentes sem reaplicar dados ou duplicar recursos.
- Execução do source 1.1.0 ORIGINAL após a adição das tabelas: leitura e gravação
  de nova rodada; reatualização sem perda de registros extras.

Os testes do atualizador usam **Docker simulado**, com operações reais de
arquivos e SQLite. Cobrem pré-voo, hashes corrompidos, todos os conflitos,
edição de .env durante build, build interrompido, snapshot/ensaio final falhando,
startup/probe novo falhando, retomada e retirada do marcador próprio,
rollback manual que preserva registros gravados após o upgrade, e restauração
correta dos arquivos antigos removidos deliberadamente.

Os helpers de snapshot e marcador também foram executados realmente em
subprocessos Python, com caminhos temporários em vez de /data:
- A cópia incluiu registro confirmado existente em WAL não checkpointado.
- Nonce incorreto não apagou o marcador; symlink não apagou/alterou seu alvo.

A saída `PHOTOS VERIFIED: 2 local slots; 1 distinct downloaded images` nos testes
é de um fixture que exercita o importador ANTIGO e seu caso de fallback. Não é
um download da coleção real e não é aceito pelo importador real da nova versão.

## Limites claros
- Docker e Fish não estão instalados neste ambiente. Nenhum Docker build,
  Docker daemon/Compose ou script Fish foi executado aqui. O wrapper entregue
  não usa heredoc de Bash; chama o Python de atualização com argumentos separados.
- Gunicorn de produção, NPM, DNS, TLS público e sessão real do navegador do
  usuário não foram executados/verificados aqui.
- A suíte inclui integração HTTP local com a biblioteca padrão, mas isso não é
  uma validação ponta a ponta do Docker/NPM da VPS.
- O pacote herdou as funcionalidades visuais 1.2.0; não foram executados novos
  testes visuais completos ou a extensão LibreJS nesta correção.
- Não houve nova importação de fotos reais, revisão visual/licenciamento humano
  do catálogo final, auditoria independente, teste de carga ou varredura CVE atual.
- O piso é 513 itens/fotos qualificados (teto 640), pois a origem tinha 512 itens.
  A importação pode falhar; nesse caso o build não chega ao cutover. Metadados e
  fingerprints não garantem detecção de toda foto mal rotulada ou quase duplicada.
- Hardware, espaço do Docker, conectividade externa e permissões reais só serão
  validados na VPS. O fluxo recusa banco maior que 128 MiB e exige 2 GiB livres
  nos filesystems do projeto e do Docker.

## Referências técnicas usadas no desenho
A migração é aditiva e transacional; não edita sqlite_schema/writable_schema.
Snapshots utilizam a API de backup SQLite, não uma cópia isolada do arquivo
.sqlite3 enquanto existe WAL ativo. Documentação primária:
https://www.sqlite.org/backup.html
https://www.sqlite.org/c3ref/backup_finish.html
https://www.sqlite.org/lang_altertable.html

Este relatório descreve revisão de código e testes reproduzíveis, não uma
certificação de segurança nem garantia de ausência de todos os bugs.
