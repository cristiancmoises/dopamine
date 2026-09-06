from .i18n import LANGS

def l(values,lang): return values[LANGS.index(lang)]

PAPERS=[
 {'id':'knutson-2007','citation':'Knutson, Rick, Wimmer, Prelec & Loewenstein (2007). Neural predictors of purchases. Neuron 53(1), 147–156.',
  'url':'https://pubmed.ncbi.nlm.nih.gov/17196537/','doi':'10.1016/j.neuron.2006.11.010',
  'title':('Escolher envolve antecipação','Choice involves anticipation','选择涉及预期','選択には期待が関わる'),
  'kind':('Estudo com fMRI','fMRI study','功能磁共振研究','fMRI研究'),
  'observed':('Respostas cerebrais à preferência por produtos e aos preços ajudaram a prever decisões de compra em uma tarefa experimental.','Brain responses to product preference and prices helped predict purchasing decisions in an experimental task.','在实验任务中，大脑对商品偏好和价格的反应有助于预测购买决定。','実験課題で、商品への好みや価格に対する脳の反応が購入判断の予測に役立ちました。'),
  'limits':('fMRI não mede diretamente a liberação de dopamina. O estudo não prova que comprar melhora a saúde ou que este site aumenta dopamina.','fMRI does not directly measure dopamine release. This study does not establish health benefits from shopping or a dopamine increase from this site.','fMRI 不直接测量多巴胺释放。该研究未证明购物改善健康，也未证明本站增加多巴胺。','fMRIはドーパミン放出を直接測りません。買い物の健康効果や、このサイトでのドーパミン増加は示されていません。')},
 {'id':'rick-2014','citation':'Rick, Pereira & Burson (2014). The benefits of retail therapy: Making purchase decisions reduces residual sadness. Journal of Consumer Psychology 24(3), 373–380.',
  'url':'https://doi.org/10.1016/j.jcps.2013.12.004','doi':'10.1016/j.jcps.2013.12.004',
  'title':('Escolha e sensação de controle','Choice and perceived control','选择与控制感','選択とコントロール感'),
  'kind':('Três experimentos','Three experiments','三项实验','3つの実験'),
  'observed':('Em três experimentos, fazer escolhas de compra reduziu tristeza residual, com resultados compatíveis com a recuperação da sensação de controle.','Across three experiments, making purchasing choices reduced residual sadness, consistent with a restored sense of control.','三项实验中，购物选择减少了残余悲伤，结果与控制感恢复的解释一致。','3つの実験で、購入の選択により残っていた悲しみが減少し、コントロール感の回復と整合する結果でした。'),
  'limits':('Não estabelece felicidade duradoura, efeito terapêutico ou mudança de dopamina. Não justifica gastar para lidar com sofrimento; dívidas e compras compulsivas podem piorar a situação.','It establishes neither lasting happiness, treatment effects nor dopamine changes. It does not justify spending to manage distress; debt and compulsive shopping may worsen things.','这不代表持久幸福、治疗效果或多巴胺变化，也不是通过消费应对痛苦的理由。债务及强迫购物可能使情况恶化。','持続的幸福、治療効果、ドーパミン変化は示されていません。苦痛に対処するための浪費を正当化せず、借金や強迫的な買い物は状況を悪化させ得ます。')},
 {'id':'berridge-2015','citation':'Berridge & Kringelbach (2015). Pleasure systems in the brain. Neuron 86(3), 646–664.',
  'url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC4425246/','doi':'10.1016/j.neuron.2015.02.018',
  'title':('Querer não é o mesmo que gostar','Wanting is not the same as liking','想要不等于喜欢','「欲しい」と「好き」は別'),
  'kind':('Revisão de neurociência','Neuroscience review','神经科学综述','神経科学レビュー'),
  'observed':('A revisão distingue a motivação para buscar uma recompensa do prazer de recebê-la. Dopamina tem papel importante no “querer”, não é um simples medidor de felicidade.','The review distinguishes motivation to pursue a reward from the pleasure of receiving it. Dopamine matters for “wanting”; it is not a simple happiness meter.','综述区分追求奖励的动机与获得奖励的愉悦。多巴胺与“想要”有关，并非简单的幸福指标。','報酬を求める動機と、受け取る快楽を区別します。ドーパミンは「欲しい」に関わり、単なる幸福の指標ではありません。'),
  'limits':('Não é possível inferir níveis de dopamina pelos cliques, compras fictícias ou créditos. O nome Dopamine é uma metáfora criativa.','Clicks, fictional purchases and credits cannot establish dopamine levels. Dopamine is a creative metaphor for this project.','点击、模拟购买或积分无法表明多巴胺水平。Dopamine 只是本项目的创作隐喻。','クリック、架空購入、クレジットからドーパミン量は分かりません。Dopamineは創作上の比喩です。')},
 {'id':'who-2024','citation':'World Health Organization (2024, December 2). Gambling. Fact sheet.',
  'url':'https://www.who.int/news-room/fact-sheets/detail/gambling','doi':'',
  'title':('Os riscos não são fictícios','The risks are not fictional','风险并非虚构','リスクは架空ではない'),
  'kind':('Saúde pública — OMS','Public health — WHO','公共卫生 — 世界卫生组织','公衆衛生 — WHO'),
  'observed':('A OMS descreve danos financeiros, à saúde mental e aos relacionamentos associados às apostas, inclusive abaixo do limiar de um diagnóstico clínico.','WHO describes gambling-related financial, mental-health and relationship harms, including harms below a clinical diagnostic threshold.','世界卫生组织指出，赌博可损害经济、心理健康及人际关系，即使未达到临床诊断标准也会造成伤害。','WHOは、診断基準に達しない場合も含め、賭博による経済・精神健康・人間関係への害を説明しています。'),
  'limits':('Créditos sem valor eliminam a perda monetária dentro deste site, mas não provam que a simulação seja inofensiva ou reduza o desejo de apostar fora dele.','Valueless credits prevent monetary loss within this site, but do not prove the simulation harmless or that it reduces urges to gamble elsewhere.','无价值积分可避免本站内金钱损失，但不能证明模拟无害，或能减少站外赌博冲动。','無価値クレジットはサイト内での金銭的損失をなくしますが、シミュレーションの無害性や現実の賭博衝動の低減を証明しません。')},
]

PRIVACY=[
 (('O que fica armazenado','What is stored','存储哪些数据','保存するもの'),
  ('Nickname, hash Argon2id da senha, hash do código de recuperação, preferências, dados opcionais do perfil e histórico fictício. Senhas e códigos de recuperação não são armazenados em texto simples. A chave de recuperação é exibida uma única vez.','Nickname, Argon2id password hash, recovery-code hash, preferences, optional profile details and fictional history. Passwords and recovery codes are not stored as plaintext. The recovery key is shown only once.','存储昵称、Argon2id 密码哈希、恢复代码哈希、偏好、可选资料和模拟历史。不会明文存储密码或恢复代码。恢复密钥仅显示一次。','ニックネーム、Argon2idパスワードハッシュ、回復コードのハッシュ、設定、任意プロフィール、架空の履歴を保存します。パスワードと回復コードは平文保存しません。回復キーは一度だけ表示します。')),
 (('Cookies e acesso','Cookies and access','Cookie 与访问','Cookieとアクセス'),
  ('Um cookie HttpOnly mantém a sessão por até 12 horas, com expiração após uma hora sem atividade. Outro cookie guarda o idioma. A proteção contra abuso usa identificadores derivados do IP com HMAC, temporários. Não há analytics, publicidade ou pixels.','An HttpOnly cookie maintains a session for up to 12 hours, expiring after one hour of inactivity. Another cookie stores language. Abuse prevention uses temporary HMAC-derived IP identifiers. No analytics, advertising or tracking pixels.','HttpOnly Cookie 保持会话最多 12 小时，闲置一小时后过期。另一 Cookie 保存语言。防滥用使用临时 HMAC 派生的 IP 标识。没有分析、广告或追踪像素。','HttpOnly Cookieで最長12時間のセッションを維持し、1時間操作がないと失効します。別のCookieで言語を保存。濫用防止にはIPからHMACで導出した一時識別子を使います。分析・広告・追跡ピクセルはありません。')),
 (('Fotografias e fontes externas','Photos and external sources','图片与外部来源','写真と外部資料'),
  ('Na implantação padrão, as fotos são importadas do Unsplash e servidas pelo próprio site. Ao abrir um artigo ou o crédito de uma foto, você visita um serviço externo sujeito à política dele. Não enviamos suas compras fictícias a esses serviços.','In the default deployment, photos are imported from Unsplash and served by this site. Opening a paper or photo credit visits an external service subject to its policy. We do not send your fictional purchases to those services.','默认部署将 Unsplash 图片导入后由本站提供。打开论文或图片来源会访问第三方，其隐私政策适用。我们不会向这些服务发送模拟购买记录。','標準構成ではUnsplashの写真をインポートし、このサイトから配信します。論文や写真の出典を開くと外部サービスの方針が適用されます。架空購入記録は外部サービスに送信しません。')),
 (('Exclusão e limites de retenção','Deletion and retention limits','删除与保留限制','削除と保持の限界'),
  ('Você pode exportar seus dados e excluir a conta com a senha atual. A exclusão remove os registros do banco ativo. Backups e logs de infraestrutura são controlados pelo operador; a ferramenta incluída remove backups com mais de 14 dias quando executada, por padrão. A política efetiva deve ser confirmada com o operador.','You can export data and delete your account using your current password. Deletion removes active-database records. Infrastructure logs and backups are operator-controlled; the included backup tool removes backups older than 14 days when run, by default. Confirm the effective policy with the operator.','使用当前密码可导出数据或删除账户。删除会移除当前数据库记录。基础设施日志和备份由运营者管理；附带备份工具默认在运行时清理超过 14 天的备份。实际政策需向运营者确认。','現在のパスワードでデータの取得・アカウント削除ができます。削除対象は稼働DBです。インフラログとバックアップは運営者管理で、付属ツールは実行時に14日超のバックアップを削除する設定です。実際の方針は運営者に確認してください。')),
 (('Sem coleta financeira','No financial collection','不收集财务信息','金融情報は収集しません'),
  ('Não pedimos e-mail no cadastro, telefone, documentos, cartão, Pix ou endereço de entrega. Campos opcionais não devem conter dados sensíveis. Não existe perfil público ou comunicação entre usuários nesta versão.','Registration asks for no email, phone, ID, card, payment details or delivery address. Optional fields should not contain sensitive data. This version has no public profiles or user-to-user messaging.','注册不需要邮箱、电话、证件、银行卡、支付资料或收货地址。可选字段不应包含敏感数据。此版本无公开资料页或用户间消息。','登録時にメール・電話・身分証・カード・決済情報・配送先は求めません。任意欄に機微情報を入れないでください。この版には公開プロフィールやユーザー間メッセージはありません。')),
]

def papers(lang):
    return [{k:(l(v,lang) if isinstance(v,tuple) else v) for k,v in p.items()} for p in PAPERS]
def privacy(lang): return [(l(title,lang),l(body,lang)) for title,body in PRIVACY]
