# Guia de uso e operação — Dopamine 1.2.1

Projeto oficial: [dopamine.securityops.co](https://dopamine.securityops.co/). Para atualização da primeira 1.1.0 com esquema 2, consulte a [ponte early11](BRIDGE-1.2.1.md). Este commit não altera a instalação hospedada.

[Índice](README.md) · [README PT-BR](../README.pt-BR.md)

## Finalidade e limites

Dopamine é um simulador de compras e jogos. Não recebe pagamentos nem oferece entregas, saques ou prêmios reais. Marcas, modelos e fotografias não implicam parceria, propriedade ou endosso. Preços e recibos são fictícios.

Não é tratamento de saúde nem garantia de melhorar bem-estar. Os resultados das mesas podem perder; o mecanismo separado de reembolso e concessão de créditos existe para a demonstração. Não confunda saldo ilimitado com alteração secreta das probabilidades.

## Arquitetura e ambiente local

A aplicação usa Python, templates Jinja, SQLite, autenticação com Argon2 e Gunicorn em produção. Um script local melhora as mesas; formulários também funcionam sem ele. Não há framework JavaScript/CDN nem autoplay. A política de scripts é restrita ao próprio site nas rotas necessárias.

Crie uma virtualenv, instale `requirements.txt`, execute `manage.py test` e depois `manage.py serve-local`. Esse modo serve apenas `127.0.0.1`, usa `local-data/dopamine.sqlite3` e mostra claramente fotos ausentes. O segredo local muda entre reinícios se `SECRET_KEY` não for fornecido; códigos de recuperação podem deixar de ser válidos. Nunca envie esse segredo ou o banco para Git.

## Uso e idiomas

Cadastre uma conta apenas no ambiente que pretende usar e guarde os meios de recuperação com segurança. Navegue nas categorias, adicione itens ao carrinho/favoritos e confirme aquisições fictícias. Não forneça dados bancários: a aplicação não precisa deles para a simulação.

O padrão é PT-BR; há inglês, chinês simplificado e japonês. BRL, USD, CNY e JPY alteram símbolos e formatação, não o valor persistido nem a conversão cambial. Recibos antigos mantêm os nomes e quantias originais.

## Mesas e demonstrações

As sete mesas incluem roleta europeia, blackjack com hit/stand/double, baccarat punto banco, três rolos, dois dados, Keno e Plinko. Os resultados aleatórios podem ganhar, perder ou empatar. O reembolso de demonstração e a concessão separada de 100 unidades não mudam esses resultados.

Os dez jogos legados permanecem na seção de demonstrações clássicas. Seus registros não são apagados para instalar as mesas novas. Créditos não são sacáveis e não conferem um ativo financeiro.

## Catálogo fotográfico

A versão fornece 1.056 candidatos em 18 categorias. Eles precisam passar por verificação de identidade do assunto, licença e unicidade. O build exige ao menos 513 fotografias aprovadas e limita a publicação a 640. As imagens não estão incluídas no pacote.

O importador registra proveniência e licenças e hospeda arquivos WebP locais, sem depender de hotlinks na navegação. Nome de modelo não basta para provar que uma foto está correta. Validação automática não substitui revisão visual e jurídica da licença.

Se a fonte estiver indisponível, limitar acessos ou oferecer metadados incompatíveis, o build deve falhar sem trocar a aplicação em funcionamento. Não reduza o limite de publicação, reutilize imagens genéricas nem invente créditos para aparentar sucesso.

## Produção, proxy e dados

Use HTTPS e domínios exatos em `ALLOWED_HOSTS`, sem wildcard. `TRUSTED_PROXY_CIDRS` deve conter somente o IP real do proxy autorizado, não toda a rede. Preserve o segredo da instalação: alterá-lo sem planejamento pode invalidar sessões e recuperação.

Na IONOS existente, o destino documentado é `dopamine-web:8000` na rede `npm-bridge`. Não mude redes ou portas de outros serviços. A atualização suportada preserva `/opt/dopamine`, `.env`, volume SQLite e encaminhamento NPM. O pacote completo de código não deve ser confundido com o pacote separado de atualização `apply.fish`.

Antes de qualquer atualização, valide o baseline, a integridade dos arquivos, o espaço disponível, a configuração real e a imagem anterior. Faça backup privado dos fontes/configuração e um snapshot consistente do SQLite. Nunca publique esses backups.

## Sequência de atualização

1. Leia [OPERATIONS.md](OPERATIONS.md) e obtenha o pacote de atualização compatível com o baseline instalado.
2. Execute o preflight em modo de conferência. Ele deve recusar alterações desconhecidas, rede incorreta e configuração inesperada.
3. Construa a imagem candidata mantendo a anterior ativa. Execute testes e validação completa de fotografias.
4. Ensaie migrações em uma cópia do banco, sem montar o volume de produção.
5. Recrie somente o serviço web, preservando volume e rede. Essa etapa pode causar uma interrupção curta da aplicação.
6. Valide `/healthz`, versão, cadastro, loja, mesa e idioma por HTTPS. Não use `-k` para declarar TLS válido.

O código não autoriza executar `compose down` global, apagar volumes, alterar segredos ou restaurar silenciosamente um banco antigo.

## Backup e recuperação

`manage.py backup CAMINHO` produz um backup consistente com verificação de integridade. Proteja o destino; ele pode conter dados pessoais. O operador deve definir retenção e proteção contra acesso indevido.

O atualizador imprime um caminho específico de rollback em seu diretório privado de backup. Use o caminho real, não um exemplo com placeholder. O rollback de código/imagem não restaura automaticamente um banco antigo, evitando apagar usuários, compras e rodadas criados depois da atualização.

Uma restauração de banco é uma ação separada de recuperação de desastre: pare escritores e preserve os dados mais recentes primeiro. A reversão automática é uma tentativa, não garantia contra falha de disco/Docker ou alterações simultâneas.

## Testes, licenças e responsabilidade

Execute `manage.py test`. Os testes de browser offline do pacote não comprovam, sozinhos, comportamento real de TLS, CSP, cookies ou NPM. Faça testes reais de navegador e de migração antes de produção.

Fonte MIT; imagens mantêm suas licenças por arquivo. Preserve LICENSE, NOTICE e créditos. Os documentos históricos de auditoria descrevem o ambiente em que foram feitos; não representam certificação independente nem uma verificação atual de vulnerabilidades.
