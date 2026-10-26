"""Aba "Comparativo" da cópia atualizada na VPS: o que mudou da versão anterior para esta.

Página de apresentação, só da VPS: entra pelo settings_vps.py com COMPARATIVO_VERSOES=1,
e o item do menu vem do nova.js, como o "Versão anterior". O conteúdo é uma curadoria do
CHANGELOG (o que mais pesa para a pousada), não a lista completa. `tela` é o nome de URL
da tela onde dá para ver o item; o link da versão anterior é o mesmo caminho lá.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import get_script_prefix, reverse

ANTERIOR = "https://votesta-original.195-200-0-150.sslip.io"

INTRO = (
    "A base, a modelagem do domínio e a arquitetura deste sistema são do Gefferson. Esta página "
    "resume o que mudou da versão que está em produção para a atualizada, de 20 a 26/10/2026: o que "
    "foi corrigido, o que é novo e o que veio dele nesse meio-tempo e já está integrado. Nos itens "
    "com tela, “Ver antes” abre a mesma tela na versão anterior, em outra aba."
)
RODAPE = (
    "Curadoria das 73 entradas do CHANGELOG do fork (VicZk/vo_testa): 378 commits de 20 a "
    "26/10/2026, em 1.018 arquivos. Os testes foram contados no código das duas versões em 26/10. "
    "O detalhe, commit a commit, está no CHANGELOG."
)

# Mais graves primeiro. Falha de segurança fica por alto: esta página é aberta e a
# produção ainda roda a versão anterior.
CORRECOES = [
    {"grave": True, "area": "Dinheiro · Reservas", "titulo": "Pagamento online abate a conta",
     "antes": "Pix, cartão ou boleto pagos pelo site, pelo link do Comercial ou pelo portal não "
              "viravam crédito na reserva: no check-out, o hóspede aparecia devendo o que já tinha pago.",
     "agora": "Todo pagamento online entra como crédito na reserva (ou no fólio do grupo), com a "
              "origem registrada e garantida pelo banco.",
     "tela": "reservas:lista"},
    {"grave": True, "area": "Dinheiro · Caixa", "titulo": "Estorno volta a cobrar a conta",
     "antes": "Devolver no gateway ou estornar no caixa tirava o dinheiro, mas a conta seguia paga "
              "e o check-out fechava sem receber.",
     "agora": "O estorno desfaz o crédito na mesma transação e é recusado quando a conta já está fechada.",
     "tela": "caixa"},
    {"grave": True, "area": "Dinheiro · Formulários", "titulo": "Valor em R$ não multiplica mais por cem",
     "antes": "Um valor vindo do servidor (como 650.00 de uma cotação) chegava como 65000: ao ganhar "
              "um lead, a diária ficava cem vezes maior.",
     "agora": "O campo devolve 650,00 em qualquer formulário de R$, com teste da ida e volta do valor.",
     "tela": "comercial:funil"},
    {"grave": True, "area": "Operação", "titulo": "Rotinas da madrugada passam a rodar",
     "antes": "As rotinas de expiração de pré-reserva, reenvio de FNRH, campanhas, reenvio de e-mail "
              "e WhatsApp e backup estavam prontas, mas faltava ligar o agendador; a pré-reserva "
              "vencida seguia segurando o quarto.",
     "agora": "As rotinas rodam em dois grupos, a cada 10 min e às 03:15, com aviso de começo, fim e falha."},
    {"grave": True, "area": "Fiscal", "titulo": "ISS fora da própria base da NFS-e",
     "antes": "O ISS e a taxa de turismo entravam na base de cálculo da nota, então o ISS incidia "
              "sobre ele mesmo.",
     "agora": "A base sai sem ISS e sem taxa, e as contas antigas foram corrigidas.",
     "tela": "fiscal:painel"},
    {"grave": True, "area": "Dinheiro · Loja", "titulo": "Venda do balcão cobrada uma vez só",
     "antes": "Clique duplo ou queda de conexão podia cobrar e baixar o estoque duas vezes.",
     "agora": "Cada venda leva uma chave única: o reenvio devolve a mesma venda em vez de cobrar de novo.",
     "tela": "loja:pdv"},
    {"grave": True, "area": "Estoque", "titulo": "Estoque sem movimento dobrado",
     "antes": "Duplo clique na entrada dobrava o saldo e mexia no custo médio, e aplicar um "
              "inventário desfazia vendas feitas durante a contagem.",
     "agora": "Cada movimento é gravado uma vez só, o inventário aplica só o que foi contado e "
              "número inválido é recusado.",
     "tela": "estoque:posicao"},
    {"grave": True, "area": "LGPD", "titulo": "Medição das LPs só depois do consentimento",
     "antes": "As três landing pages carregavam GA4 e Meta Pixel ao abrir, sem aviso de cookies.",
     "agora": "Nada carrega antes do “Aceitar”; no “Recusar”, nada carrega, e o aviso vem junto com cada LP.",
     "tela": "lp:inauguracao"},
    {"grave": True, "area": "Hóspede · Contrato", "titulo": "Termos e devolução dizem a mesma coisa",
     "antes": "Os termos falavam em devolver 90% nos 7 dias, o sistema devolvia 100% (o que o CDC "
              "pede na venda pela internet), e o percentual saía num formato técnico (1E+1%).",
     "agora": "Resumo, termos e cálculo saem da mesma configuração, o percentual aparece como 10% "
              "e a reserva guarda o texto aceito, com data e hora.",
     "tela": "core:termos_servico"},
    {"area": "Caixa", "titulo": "Fechar e receber ao mesmo tempo",
     "antes": "Fechamento e recebimento simultâneos podiam se perder um do outro, e o estorno de um "
              "caixa já fechado reabria a sessão.",
     "agora": "A escrita de dinheiro trava a linha, e o estorno entra no caixa aberto de hoje sem "
              "reabrir o anterior.",
     "tela": "caixa"},
    {"area": "Reservas", "titulo": "Check-in e check-out por inteiro",
     "antes": "Um erro em outro módulo podia derrubar check-out, troca de quarto ou faxina e deixar "
              "a operação pela metade.",
     "agora": "Check-in e check-out rodam numa transação só, erro de módulo vizinho vai para o log e "
              "duplo clique não duplica."},
    {"area": "Relatórios", "titulo": "Receita por noite, ocupação só de quartos",
     "antes": "Uma estadia de 28/10 a 03/11 caía inteira em outubro, e o day use contava como quarto "
              "na ocupação e no ADR.",
     "agora": "Cada diária tem a competência da noite, as já lançadas foram acertadas e a ocupação "
              "considera só quartos.",
     "tela": ("relatorios:relatorio", "ocupacao")},
    {"area": "Segurança", "titulo": "Limites de tentativa reforçados",
     "antes": "As travas contra tentativas repetidas nem sempre seguravam o limite configurado.",
     "agora": "As travas valem o tempo e o limite definidos, em todo o servidor."},
    {"area": "Segurança", "titulo": "Trilha de auditoria sem dado sensível",
     "antes": "Alguns registros da trilha podiam guardar mais detalhe do que deviam.",
     "agora": "O evento continua auditado sem copiar segredo, e os registros antigos foram saneados, "
              "preservando autoria e datas."},
]

NUMEROS = [
    {"rotulo": "Testes automáticos", "valor": "2.863", "nota": "Eram 977 na versão anterior"},
    {"rotulo": "Testes no navegador", "valor": "282", "nota": "Eram 8, e agora rodam a cada push"},
    {"rotulo": "Correções importantes", "valor": str(len(CORRECOES)),
     "nota": f"{sum(1 for c in CORRECOES if c.get('grave'))} de impacto alto"},
    {"rotulo": "Busca de quartos no site", "valor": "18", "unidade": "consultas",
     "nota": "Eram 334, para 3 noites"},
]

NOVIDADES = [
    {"area": "Governança", "titulo": "Governança no tablet e no celular",
     "texto": "Visão geral da casa, ciclo de cada quarto com o próximo passo, plano do dia por "
              "prioridade, ficha do quarto a um toque e a “Minha fila” da camareira, distribuída "
              "entre quem está de turno.",
     "tela": "governanca:painel"},
    {"area": "Governança", "titulo": "Ronda e discrepâncias",
     "texto": "A camareira registra vago, com mala ou sem mala, e o sistema aponta quem saiu sem "
              "passar na recepção, saída não lançada e quarto não conferido. Tem ainda inspeção com "
              "reprovação e três relatórios.",
     "tela": "governanca:discrepancias"},
    {"area": "Reservas", "titulo": "Restrições de venda por período",
     "texto": "Estadia mínima, fechado para chegada ou saída e parar vendas, por casa, tipo ou "
              "quarto: o Réveillon não vende mais a noite solta de 31/12, e o site explica o motivo.",
     "tela": "reservas:restricoes"},
    {"area": "Relatórios", "titulo": "Relatórios de receita vendida",
     "texto": "Carteira dia a dia, pickup (o que entrou e saiu), ritmo de vendas por antecedência e "
              "custo de distribuição por canal.",
     "tela": ("relatorios:relatorio", "carteira")},
    {"area": "Auditoria", "titulo": "Fechamento do dia",
     "texto": "Toda madrugada fica gravado um retrato imutável do dia anterior (ocupação, chegadas, "
              "saídas, no-shows, diárias, ADR, consumo e saldo), com totais do mês e CSV.",
     "tela": "auditoria:fechamentos"},
    {"area": "Reservas", "titulo": "No-show automático, opcional",
     "texto": "Ligado na Tabela de Preços, a rotina da madrugada marca o não comparecimento, com 0 a "
              "2 dias de tolerância, e devolve as noites à venda. Dá para desfazer.",
     "tela": "tabela_precos"},
    {"area": "Reservas", "titulo": "Faturar para agência ou empresa",
     "texto": "O saldo vira conta a receber no Financeiro (30 dias por padrão) e a saída fecha; o "
              "consumo pessoal pode ficar com o hóspede, inclusive em grupo."},
    {"area": "Recepção", "titulo": "Kit de contingência",
     "texto": "Uma folha A4 com hospedados, saldos, chegadas com telefone, saídas e a situação dos "
              "24 quartos, para quando a internet cair, com cópia por e-mail toda madrugada.",
     "tela": "reservas:kit"},
    {"area": "Day pass", "titulo": "Day pass por turno",
     "texto": "Módulo próprio: agenda por turno, lotação por pessoa, ingresso, entrada e saída "
              "nominais, caixa e comanda do grupo.",
     "tela": "daypass:painel"},
    {"area": "Canais", "titulo": "Canais e OTAs pelo Channex",
     "texto": "Mapeamento de quartos, fila das reservas recebidas e publicação de disponibilidade, "
              "tarifas e restrições. Nasce desligado; a homologação depende do provedor.",
     "tela": "canais:painel"},
    {"area": "Estoque", "titulo": "Compras, lotes e validade",
     "texto": "Recebimento por embalagem, lote e validade (o vencido sai da venda), ficha técnica "
              "dos pratos e nota de entrada com recebimento parcial.",
     "tela": "estoque:notas"},
    {"area": "Lavanderia", "titulo": "Lavanderia como fila de produção",
     "texto": "Receber em um gesto e tocar a roupa por etapa (recebida, lavando, pronta), com a "
              "hora de cada passo e o extrato do enxoval.",
     "tela": "lavanderia:painel"},
    {"area": "Reservas · ECA", "titulo": "Menor de idade no check-in",
     "texto": "A FNRH pergunta se o menor está com os pais, com responsável legal ou com adulto "
              "autorizado, e o check-in confere a autorização antes de passar."},
]

DESIGN = [
    {"titulo": "Visão geral reorganizada",
     "texto": "Chegadas e saídas uma embaixo da outra, com a lista vazia numa linha só, e os recados "
              "do turno num cartão ao lado do movimento do dia.",
     "tela": "dashboard"},
    {"titulo": "Menu lateral firme",
     "texto": "Abrir e recolher não faz mais nada saltar: o menu recolhido é o aberto recortado. No "
              "celular, a gaveta funciona como janela (Esc, foco preso) e cada ícone tem nome.",
     "tela": "dashboard"},
    {"titulo": "Menos pílulas, leitura mais calma",
     "texto": "Status neutro virou bolinha e texto, e a cápsula colorida ficou só para o que pede "
              "ação: eram 252 pílulas preenchidas nas telas do CRM, agora são 28.",
     "tela": "pessoas"},
    {"titulo": "Tudo no dedo, em qualquer largura",
     "texto": "Alvos de toque abaixo de 44 px caíram de 223 para 2, nenhuma tela rola de lado e, no "
              "toque, o modal vira gaveta com os botões ao alcance do polegar.",
     "tela": "reservas:mapa"},
    {"titulo": "Dinheiro e datas em português",
     "texto": "R$ 1.234,56 em toda tela, rótulo por extenso no lugar de código do banco (no_show), "
              "datas que não somem ao reabrir a ficha e CSV que o Excel brasileiro abre certo.",
     "tela": "auditoria:trilha"},
    {"titulo": "Copiar e enviar pelo WhatsApp",
     "texto": "Link de pagamento, Pix, portal e pré check-in saem com “Copiar” e “Enviar pelo "
              "WhatsApp”, com a mensagem pronta e o telefone do hóspede.",
     "tela": "pagamentos:painel"},
    {"titulo": "Listas que crescem, impressão limpa",
     "texto": "Todas as listas paginam mantendo busca e filtros, o A4 sai sem menu e o recibo do "
              "balcão sai no cupom de 80 mm.",
     "tela": "reservas:lista"},
]

QUALIDADE = [
    {"titulo": "Testes a cada push, com navegador",
     "texto": "A suíte roda contra PostgreSQL 16 em todo push, com um job obrigatório de fluxos no "
              "navegador (Playwright e Chromium). Os testes de navegador, que rodavam só na máquina "
              "de quem tinha o Playwright, agora rodam no CI também."},
    {"titulo": "Segurança verificada a cada push",
     "texto": "pip-audit, bandit, gitleaks e semgrep rodam a cada push e barram a entrega; os 38 "
              "alertas do semgrep foram conferidos um a um."},
    {"titulo": "Backup diário com restauração conferida",
     "texto": "Rotina de backup com retenção de 30 dias, e um ensaio de restauração conferiu as "
              "tabelas e os totais de caixa, estoque e contas."},
    {"titulo": "Acesso da equipe",
     "texto": "Recuperação de senha por e-mail com link de uso único, verificação em duas etapas por "
              "perfil e trilha com retenção definida. Ação sem login (site, portal, webhook) também "
              "tem autor na trilha."},
    {"titulo": "Telas mais leves",
     "texto": "A busca de quartos do site caiu de 334 para 18 consultas ao banco, o painel de 213 "
              "para 52 e abrir um lead de 481 ms para 69 ms, com testes que acusam se voltar a crescer."},
    {"titulo": "Ambiente de teste e comparação",
     "texto": "O sistema inteiro roda numa VPS de teste, com dados de demonstração e sem integração "
              "real, e as duas versões abrem lado a lado para comparar a mesma tela."},
]

DO_ORIGINAL = [
    {"area": "24/10", "titulo": "Contábil e gerencial",
     "texto": "Plano de contas, de-para, DRE, fluxo de caixa, fechamento mensal e exportação para o "
              "contador. Ligado aos fluxos desta versão: faturado e folha contam uma vez, a compra "
              "para o estoque vira custo na saída (CMV), e entram o day pass e os descontos da conta.",
     "tela": "contabil:painel"},
    {"area": "25/10", "titulo": "NFS-e pelo Spedy, no Lucro Presumido",
     "texto": "No padrão do fiscal desta versão: a nota fica processando até o retorno, o reenvio "
              "atualiza a mesma nota, o retorno vale pela assinatura e o cancelamento só fecha com a "
              "confirmação.",
     "tela": "fiscal:painel"},
    {"area": "21/10", "titulo": "Comercial",
     "texto": "Reabrir ou mover lead ganho ou perdido, “Ganhar” com a diária da tabela, total ao "
              "vivo, sinal em R$ ou %, barra do funil refeita e o cartão Financeiro na reserva.",
     "tela": "comercial:funil"},
    {"area": "20 e 21/10", "titulo": "Reservas e preços",
     "texto": "Meia diária para crianças de 6 a 15 anos, ajustes no day use, parâmetros de preço, "
              "tarifa não reembolsável e o comando para zerar as reservas de teste.",
     "tela": "tabela_precos"},
    {"area": "Mão na volta", "titulo": "De volta para o original",
     "texto": "Quatro correções que também valem para a produção atual estão prontas como patches "
              "sobre a main, para aplicar quando fizer sentido. E um robô busca o original duas vezes "
              "por dia, testa a junção e abre um PR para revisão."},
]

PROXIMOS = [
    {"titulo": "Decidir a versão da produção",
     "texto": "A produção ainda roda a versão anterior. No ensaio de 26/10, o banco dela migrou para "
              "esta sem erro (82 migrações, 21 telas conferidas). Para trocar: rotinas no Railway, "
              "variáveis novas e backup antes."},
    {"titulo": "Ativar os provedores, um a um",
     "texto": "Spedy (conta, chave, certificado A1 e ensaio no sandbox), NFC-e (depende da inscrição "
              "estadual), Channex, e-mail e WhatsApp. No modo simulado, nada tem validade fiscal."},
    {"titulo": "Primeiro fechamento com o contador",
     "texto": "Fechar o primeiro mês no Contábil com ele e confirmar as alíquotas de IBS/CBS e se a "
              "venda sem NFC-e deve ser bloqueada."},
    {"titulo": "Regras de receita",
     "texto": "Ligar ou não o no-show automático (sugestão: 1 dia de tolerância), conferir o custo "
              "por canal (OTA começa em 18%) e definir como entra a comissão de agência."},
    {"titulo": "Governança com quem vai usar",
     "texto": "Validar com a camareira e a supervisora os nomes dos passos, dar login a quem vai "
              "usar a fila e decidir se quarto novo nasce pronto."},
    {"titulo": "Antes de abrir, em 31/10",
     "texto": "Zerar as reservas de demonstração, cadastrar a regra do Réveillon antes de vender o "
              "feriado, criar os avisos do Healthchecks.io, preencher os e-mails do kit de "
              "contingência e definir o encarregado de dados (LGPD)."},
]


def _com_links(itens):
    prefixo = get_script_prefix()
    resultado = []
    for item in itens:
        item = dict(item)
        if tela := item.get("tela"):
            nome, *args = (tela,) if isinstance(tela, str) else tela
            item["agora_url"] = reverse(nome, args=args)
            item["antes_url"] = f"{ANTERIOR}/{item['agora_url'][len(prefixo):]}"
        resultado.append(item)
    return resultado


@login_required
def comparativo(request):
    return render(request, "vps/comparativo.html", {
        "nav_ativa": "comparativo",
        "anterior": f"{ANTERIOR}/crm/",
        "intro": INTRO,
        "rodape": RODAPE,
        "numeros": NUMEROS,
        "correcoes": _com_links(CORRECOES),
        "novidades": _com_links(NOVIDADES),
        "design": _com_links(DESIGN),
        "qualidade": QUALIDADE,
        "do_original": _com_links(DO_ORIGINAL),
        "proximos": PROXIMOS,
    })
