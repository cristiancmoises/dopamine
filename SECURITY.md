# Segurança: controles, limites e responsabilidades

Este projeto passou pelos testes próprios registrados em `docs/VALIDATION.md`. **Não recebeu auditoria independente, prova formal, teste de invasão externo ou certificação de segurança.** Não se deve equiparar um conjunto de testes a ausência de vulnerabilidades.

## Modelo de ameaça

Consideram-se visitantes anônimos, usuários autenticados maliciosos, requisições forjadas, ataques de força bruta, tentativas de acesso entre contas, repetição/concorrência de compras e jogos e cabeçalhos de proxy falsificados. Os ativos relevantes são senha, sessão, código de recuperação e dados privados do perfil/histórico. Não há ativos financeiros reais.

Confia-se no host, no Docker daemon, no operador, no NPM que termina TLS, nos arquivos do projeto e nas dependências obtidas para a imagem. A aplicação não protege contra um host/root/NPM comprometido, malware no dispositivo do usuário, roubo de senha fora do site, phishing, DDoS volumétrico ou comprometimento da cadeia de suprimentos. A rede Docker não é uma barreira contra root do próprio host.

## Identidade e autenticação

Senhas são protegidas por Argon2id com 64 MiB por verificação, custo de tempo 3, paralelismo 2, salt de 16 bytes e hash de 32 bytes. Política de 12–128 caracteres, rejeição de alguns padrões óbvios, com pelo menos quatro caracteres distintos e sem exigir classes arbitrárias de caracteres. A lista pequena de senhas comuns não substitui um banco de senhas comprometidas.

Nicknames passam por NFKC e comparação casefold para unicidade; aceitam letras/números Unicode, `_` e `-`, entre 3 e 24 caracteres. Não são identidades verificadas e podem ter caracteres visualmente semelhantes. O nickname de login não é editável; o nome de exibição é.

Sessões usam 32 bytes aleatórios, armazenados como SHA-256 no banco. O token CSRF também é aleatório e fica na sessão do servidor. Login troca o identificador; duração máxima de 12 h, inatividade de 1 h. Cookies de produção usam `__Host-`, Secure, HttpOnly, SameSite=Lax, Path=/ e nenhum Domain. Idioma tem cookie próprio, sem scripts.

O código de recuperação contém 32 bytes aleatórios; o banco armazena HMAC com o segredo do deployment. Ele é mostrado só na criação/rotação, nunca em URL. Uma recuperação bem-sucedida substitui o código e revoga todas as sessões. Se senha e código forem perdidos, não existe recuperação autônoma por e-mail. Guarde a chave em gerenciador de senhas.

Login verifica novamente o hash dentro da transação antes de emitir sessão, evitando aceitar uma verificação de senha obsoleta após reset concorrente. Alteração de senha também revalida o hash e revoga outras sessões. Uma requisição que já estava em processamento antes da revogação pode ter iniciado trabalho; não se promete cancelamento universal de operações em curso.

## Aplicação e integridade

Toda mutação exige POST e CSRF válido. Origin, quando presente, deve corresponder à origem canônica de SITE_URL. Null e origens estrangeiras continuam recusados. A política same-origin evita suprimir a origem dos formulários legítimos. Sec-Fetch-Site cross-site/same-site é recusado em mutações. Tokens de ação de compra/jogo são associados à sessão, finalidade e tempo, válidos por uma hora; chaves de idempotência são exclusivas por usuário. SQLite usa foreign keys, transações explícitas, WAL e consultas parametrizadas. Preços são lidos somente do catálogo no servidor. Recibos, coleção e rodadas são vinculados à conta autenticada.

Limites: corpo de 16 KiB, até 24 campos sem repetição, query de até 2 KiB e 16 parâmetros, textos e quantidades limitados; frequência de autenticação, sessão, reautenticação, compra e jogo limitada no SQLite, compartilhada entre workers. Chaves de frequência derivadas de IP/nickname usam HMAC e expiram. NAT compartilhado pode provocar bloqueios legítimos. Ataques distribuídos ainda exigem proteção no proxy/rede.

Templates escapam HTML. Não há uploads, comandos de shell acionados pela web, banco externo público, reset por link aberto ou painel administrativo público. Somente arquivos estáticos de uma lista pré-carregada são servidos. Não coloque segredos no diretório estático.

CSP bloqueia todos os scripts, inline script/style, objetos, frames e conexões de JavaScript. Somente CSS, imagens e fontes da mesma origem são permitidos; não há fontes externas na implementação. Cabeçalhos incluem nosniff, DENY, same-origin (Referrer-Policy), políticas de recursos restritas, COOP/CORP e HSTS apenas para o domínio, sem atingir outros subdomínios. Respostas dinâmicas usam no-store; respostas de assets não criam sessão.

## NPM e Docker

O deployment preserva a rede compartilhada `npm-bridge`, já funcional na VPS. A aplicação não tem `ports:` publicados. Outros peers dessa bridge podem conectar às portas do container: não é isolamento dedicado. O app não precisa de acesso externo para servir fotos, mas esta bridge não proíbe egress por si só. O NPM mantém suas redes existentes; o patch não as modifica.

A confiança nos cabeçalhos limita-se ao IP exato do NPM (`/32` ou `/128`). O app usa X-Real-IP apenas desse peer, e ignora X-Forwarded-For. O Gunicorn não faz interpretação adicional de cabeçalhos de esquema ou encaminhamento de PATH_INFO. O NPM deve sobrescrever X-Real-IP, passar Host correto, transmitir o esquema original e **forçar HTTPS**. Configurações de CDN/real-IP que você adicionar exigem revisão específica; não foram testadas aqui.

Mudança/recriação do NPM pode alterar IP e ligação de rede. Isso deve falhar de forma visível, não ampliar confiança automaticamente: execute novamente `deploy.fish --skip-build`. O patch não modifica o Compose original do NPM; ao recriar esse proxy, preserve conscientemente a ligação à rede compartilhada no deployment dele.

Runtime UID/GID 10001, read-only, cap-drop ALL, no-new-privileges, tmpfs limitada e sem execução, volume privado, pids e memória limitados. Apenas um serviço e um volume local. Rootless Docker, Podman, Swarm, Kubernetes, NFS e múltiplos hosts não foram validados.

## Retenção, backups e atualizações

O app remove sessões e chaves de rate limit expiradas periodicamente durante requisições e na inicialização. Perfil/histórico persistem até a exclusão da conta. Exclusão apaga registros do banco ativo, **não apaga automaticamente logs do NPM nem backups externos**. Os backups fornecidos não são criptografados. A limpeza padrão de 14 dias ocorre quando `backup.fish` é executado; configure uma agenda real e publique sua política efetiva.

O log do app evita IP, query, cookies, user-agent e corpo; registra método, caminho, status e tempo. Caminhos podem conter IDs aleatórios de recibos/rodadas. NPM/host podem registrar IP e outros dados: revise as configurações e a retenção desses componentes.

Guarde `.env` em 0600. A alteração de SECRET_KEY invalida códigos de recuperação antigos e tokens de ação, mas o segredo **não cifra o banco**. Como tokens de sessão são hashes independentes do segredo, uma rotação emergencial da chave deve ser acompanhada de revogação explícita das sessões. Não faça rotações silenciosas ou sem estratégia de recuperação.

As dependências estão fixadas por versão, não por todos os hashes de wheels. A imagem base usa tag atualizável; não se promete build bit-a-bit reproduzível. Confira alertas upstream, execute scanner de dependências/imagem, teste a atualização e fixe um digest auditado conforme seu processo. Não houve consulta automatizada completa de vulnerabilidades nem build da imagem no ambiente de criação.

## Saúde, idade e conformidade

A declaração 18+ não verifica idade ou identidade. A pausa é por conta: criação de outra conta pode contorná-la. Não é uma ferramenta universal de autoexclusão nem de tratamento. Créditos fictícios eliminam perda financeira *dentro desta aplicação*, mas não comprovam ausência de gatilhos ou outros efeitos adversos.

Não se declara conformidade legal automática, enquadramento regulatório, certificação LGPD ou validação clínica. Revise operação, público-alvo, avisos, políticas, direitos das fotos e regras aplicáveis antes de abrir o serviço.

## Relatar problemas

Use o contato configurado em `CONTACT_EMAIL` e não publique senhas, cookies, tokens, chaves de recuperação ou dados de outros usuários. O endereço inicial deve ser confirmado pelo operador. Não há programa formal de recompensas ou autorização ampla para testes contra a VPS.

Referências técnicas primárias: https://argon2-cffi.readthedocs.io/ ; https://jinja.palletsprojects.com/ ; https://gunicorn.org/reference/settings/ ; https://docs.docker.com/engine/network/drivers/bridge/ ; https://www.gnu.org/software/librejs/

## Revisão 1.1.0

Resultados atuais e limites estão em `docs/AUDIT.md`. Rollback de código não restaura o snapshot sobre o banco ativo; a migração é aditiva e preserva o histórico novo. Não houve certificação, varredura completa de CVEs ou execução de Docker/Fish neste ambiente.
