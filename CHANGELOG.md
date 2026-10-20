# Changelog

Tudo o que muda neste fork (`VicZk/vo_testa`), push a push. Cada entrada diz **o que
melhorou**, ou seja, o efeito para a pousada, e **o que foi modificado**, ou seja, onde
o código mexeu, com os commits. A explicação completa de cada commit (o que mudou, por
quê e como foi testado) está na mensagem dele no GitHub.

A entrada mais nova fica no topo. As datas são as do push.

---

## 20/10/2026 — Novidades do original: Tabela de Preços (`dae8904`)

**O que melhorou**
- Os campos da Tabela de Preços mostram o valor inteiro: juntamos a correção que o
  Gefferson publicou hoje com a que já existia aqui, e as duas se completam.

**O que foi modificado**
- Merge dos commits `723a7ea`, `e71dd5f` e `8fb5eee` do original, que chegaram pelo
  PR #1 aberto pela automação. Um conflito em `templates/nucleo/tabela_precos.html`,
  resolvido mantendo as duas correções:
  - daqui: o cartão do formulário deixa de limitar a 620px, que era a causa do aperto;
  - de lá: regra mais forte e `flex: 0 0 auto`, para o campo nunca encolher, com
    números tabulares;
  - largura do campo: 5.75rem, conferida na tela com "1.250,00".

**Como foi testado**
- A tela já tinha sido conferida com essa largura; a regra nova só impede o campo de
  encolher. CI roda a suíte inteira neste push.

---

## 20/10/2026 — Acompanhamento automático do projeto original

**O que melhorou**
- O fork passa a acompanhar sozinho o que o Gefferson publica no projeto original. Duas
  vezes por dia (8h e 17h), se houver commit novo lá, o GitHub junta as novidades com o
  `dev`, roda a suíte de testes nesse merge e abre um Pull Request "Novidades do
  original (Gefferson)" com a lista de commits e o resultado dos testes.
- Nada entra no `dev` sozinho: quem decide é quem revisa o PR. Se as novidades
  conflitarem com o que existe aqui, o PR avisa que o merge precisa ser resolvido à mão.

**O que foi modificado**
- `.github/workflows/novidades-do-original.yml` (novo): busca a `main` do original,
  atualiza o espelho `main` deste fork, faz o merge com o `dev` no branch
  `sincronizar/original`, testa e abre ou atualiza o PR.
- `.github/workflows/testes.yml`: pode ser chamado por outro workflow com o branch a
  testar (`workflow_call`), para o mesmo CI valer para o merge com o original.
- `CHANGELOG.md` (este arquivo, novo): histórico de tudo o que já subiu, e de agora em
  diante uma entrada por push.

**Como foi testado**
- Rodado de verdade no GitHub logo depois do push, contra as 3 novidades que o Gefferson
  publicou hoje na Tabela de Preços. Ele atualizou o espelho `main` e abriu o PR #1
  avisando do conflito com a correção que já existia aqui (resolvida na entrada acima).
  O caminho sem conflito (merge + testes + PR) roda na próxima novidade do original.

---

## 20/10/2026 — Documentação atualizada e fork abrindo no `dev` (`44bb7d0`)

**O que melhorou**
- Quem abre `github.com/VicZk/vo_testa` vê o README completo: o fork passou a abrir no
  `dev`, e não mais no espelho do original.
- O Gefferson foi convidado como colaborador do fork e o README tem o passo a passo para
  ele levar daqui o que quiser (commit a commit, tudo de uma vez ou por PR).
- A documentação descreve o sistema como ele é hoje, com as 12 melhorias abaixo.

**O que foi modificado**
- `README.md`, `docs/ARQUITETURA.md`, `docs/MODULOS_E_FLUXOS.md`: regra dos sinais,
  check-in/out atômicos, tolerância de arredondamento, day use de um dia, travas da
  comanda e da conta, healthcheck, logs, CI de testes, `estrutura_inicial`, HTMX e Alpine
  locais, e o modelo de colaboração do fork.
- No GitHub: branch padrão do fork = `dev`; convite de colaborador para o Gefferson.

**Como foi testado**
- Só documentação, conferida trecho a trecho contra o código. CI: 898 testes OK.

---

## 20/10/2026 — 12 melhorias encontradas na auditoria (`1aa5175` a `27ac05c`)

**O que melhorou**
- **Check-out, troca de quarto, faxina e manutenção não caem mais por erro de outro
  módulo** (`1aa5175`). Um erro no Comercial, na Governança ou na Lavanderia vai para o
  log; a operação da recepção continua valendo.
- **Check-in e check-out atômicos** (`e07b9b2`): se um lançamento falhar, nada fica pela
  metade; clique duplo não duplica; consumo nunca entra em conta já fechada.
- **Check-out não trava por centavos** (`32ba4e2`): sobra de arredondamento até R$ 0,10
  (configurável) vira desconto automático, registrado na trilha.
- **Day use só aceita um dia** (`c13a9e9`): um erro de digitação não ocupa mais a unidade
  de day use por vários dias.
- **Comanda do restaurante travada** (`80caff6`): dois garçons lançando ao mesmo tempo
  não perdem quantidade, e não entra item em comanda fechada.
- **Healthcheck confere o banco e os erros aparecem no Railway** (`b356d54`): um
  container sem banco não substitui o que está no ar; erros 500 saem nos logs.
- **CI de testes** (`00cbeaf`): a suíte inteira roda com PostgreSQL a cada push e PR.
- **Banco novo montável do zero** (`bc2ac8c`): `estrutura_inicial` cria tipos e os 24
  quartos (com `--completo`, também camas, tarifas e vitrine).
- **Toda ação mostra que está carregando e avisa erro** (`4038b0b`); HTMX e Alpine
  servidos pelo próprio sistema, sem depender de CDN.
- **Telas no celular e Tabela de Preços** (`9f8ae05`): painel sem quartos cortados,
  valores legíveis, moeda no formato R$ 1.234,56.
- **Link do site com foto no WhatsApp e no Facebook** (`f71e2ac`), e canonical sem
  query string para o Google.
- **Dependências com versão fixa** (`27ac05c`): `qrcode` e `Pillow`; `.env.example`
  limpo e documentado.

**O que foi modificado**
- `apps/nucleo/sinais.py` (novo) e os emissores/receptores de sinais de Reservas,
  Governança, Manutenção, Pagamentos, Comercial e Lavanderia.
- `apps/reservas/models.py` e `services.py` (check-in/out, arredondamento, day use,
  `lancar_na_conta`), `apps/restaurante/services.py`, `config/urls.py`,
  `config/settings.py` (LOGGING, tolerância), `.github/workflows/testes.yml`,
  `apps/nucleo/management/commands/estrutura_inicial.py`, `templates/base.html`,
  `static/css/app.css`, `static/vendor/`, templates do site, `requirements.txt`,
  `.env.example`.

**Como foi testado**
- Testes novos para cada correção. Suíte completa: 898 testes no CI (Linux +
  PostgreSQL 16).

---

## 20/10/2026 — Novidades do original até `62fbaf5` (`f0313bc`)

**O que melhorou**
- Trazidos do projeto original: meia diária para crianças de 6 a 15 anos, ajustes no
  day use, parâmetros de preço e a opção de tarifa não reembolsável.

**O que foi modificado**
- Merge da `main` do original no `dev` (16 arquivos de Reservas e da Tabela de Preços).

---

## 20/10/2026 — Documentação completa do sistema (`e94061b`)

**O que melhorou**
- O sistema ganhou um mapa: como rodar, como as peças se encaixam e como desenvolver
  em cima dele.

**O que foi modificado**
- `README.md` (reescrito), `docs/ARQUITETURA.md` e `docs/MODULOS_E_FLUXOS.md` (novos).

---

## 20/10/2026 — Fork preparado para Windows (`ef3f309`)

**O que melhorou**
- O projeto passa a ser clonado no Windows: dois arquivos da documentação da SafraPay
  tinham `?` no nome, caractere proibido no Windows, e travavam o clone.

**O que foi modificado**
- Renomeados os arquivos de `docs/SafraPay/` com `?` no nome (só documentação).
