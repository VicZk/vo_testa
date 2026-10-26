"""Aba "Comparativo" da cópia atualizada na VPS: o que mudou da versão anterior para esta.

Página de apresentação, só da VPS: entra pelo settings_vps.py com COMPARATIVO_VERSOES=1,
e o item do menu vem do nova.js, como o "Versão anterior". O conteúdo é uma curadoria do
CHANGELOG (o que mais pesa para a pousada), escrita para quem não é da área técnica.
`tela` é o nome de URL da tela onde dá para ver o item; o link da versão anterior é o
mesmo caminho lá.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import get_script_prefix, reverse

ANTERIOR = "https://votesta-original.195-200-0-150.sslip.io"

INTRO = (
    "A base e a arquitetura deste sistema são do Gefferson. Aqui está, em linguagem do dia a dia, "
    "o que mudou da versão que está no ar para a atualizada, de 20 a 26/10/2026: o que foi consertado, "
    "o que é novo e o que veio dele nesse meio-tempo. Nos consertos, “Antes” é o que acontecia e "
    "“Agora”, como ficou. Nos itens com tela, “Ver antes” abre a mesma tela na versão anterior, em "
    "outra aba, para comparar."
)
RODAPE = (
    "Resumo das 73 entradas do CHANGELOG do fork (VicZk/vo_testa): 378 commits de 20 a 26/10/2026, "
    "em 1.018 arquivos. As conferências automáticas foram contadas no código das duas versões em "
    "26/10. O detalhe técnico, item a item, está no CHANGELOG."
)

# A mesma medida nas duas versões. Cada uma tem a sua escala (nada de eixo comum entre
# medidas diferentes); "menos é melhor" fica dito no texto.
EM_NUMEROS = [
    {"titulo": "Conferências automáticas", "destaque": "Quase 3× mais",
     "explica": "Rodam sozinhas a cada mudança, para um conserto não quebrar outra coisa.",
     "antes": 977, "agora": 2863, "antes_txt": "977", "agora_txt": "2.863"},
    {"titulo": "Conferências que usam o sistema como uma pessoa", "destaque": "35× mais",
     "explica": "Abrem o navegador, clicam e conferem as telas, sozinhas, a cada mudança.",
     "antes": 8, "agora": 282, "antes_txt": "8", "agora_txt": "282"},
    {"titulo": "Página da inauguração abrindo no celular", "destaque": "10× mais rápida",
     "explica": "Tempo até aparecer o conteúdo, num 4G lento. Menos é melhor.",
     "antes": 4.2, "agora": 0.4, "antes_txt": "4,2 s", "agora_txt": "0,4 s"},
    {"titulo": "Abrir uma oportunidade no Comercial", "destaque": "7× mais rápido",
     "explica": "Tempo para o servidor montar a tela. Menos é melhor.",
     "antes": 481, "agora": 69, "antes_txt": "0,48 s", "agora_txt": "0,07 s"},
    {"titulo": "Esforço para buscar quartos no site", "destaque": "18× menos",
     "explica": "Pedidos ao banco de dados numa busca de 3 noites. Menos pedidos, resposta mais rápida.",
     "antes": 334, "agora": 18, "antes_txt": "334", "agora_txt": "18"},
    {"titulo": "Botões pequenos demais para o dedo", "destaque": "De 223 para 2",
     "explica": "Contados em todas as telas. Os 2 que sobraram são exceções aceitas pela regra de "
                "acessibilidade.",
     "antes": 223, "agora": 2, "antes_txt": "223", "agora_txt": "2"},
]

# Impacto alto primeiro. Segurança fica por alto: esta página é aberta e a versão no ar
# ainda é a anterior.
CORRECOES = [
    {"grave": True, "area": "Dinheiro · Reservas", "titulo": "Pagamento pelo site baixa a conta",
     "antes": "O hóspede pagava o Pix ou o cartão pelo site, mas a conta dele no sistema não baixava: "
              "no check-out, aparecia devendo o que já tinha pago.",
     "agora": "Todo pagamento online cai direto na conta da reserva, com a origem anotada.",
     "tela": "reservas:lista"},
    {"grave": True, "area": "Dinheiro · Caixa", "titulo": "Devolução volta a cobrar a conta",
     "antes": "Quando um pagamento era devolvido, o dinheiro saía, mas a conta continuava como paga e "
              "o check-out fechava sem cobrar.",
     "agora": "A devolução põe o valor de volta na conta na mesma hora e não deixa mexer em conta já "
              "fechada.",
     "tela": "caixa"},
    {"grave": True, "area": "Dinheiro · Comercial", "titulo": "R$ 650,00 não vira mais R$ 65.000,00",
     "antes": "Em alguns formulários, o valor chegava cem vezes maior: ao fechar uma venda no "
              "Comercial, a diária de R$ 650,00 virava R$ 65.000,00.",
     "agora": "O valor chega igual ao digitado em todos os campos de dinheiro.",
     "tela": "comercial:funil"},
    {"grave": True, "area": "Rotinas automáticas", "titulo": "Tarefas da madrugada passam a rodar",
     "antes": "As tarefas automáticas (vencer pré-reserva, reenviar fichas, mandar campanhas, fazer "
              "backup) estavam prontas, mas faltava ligar o “despertador” que as dispara: a "
              "pré-reserva vencida seguia segurando o quarto.",
     "agora": "Elas rodam sozinhas a cada 10 minutos e às 3h15, e avisam se alguma falhar."},
    {"grave": True, "area": "Nota fiscal", "titulo": "Imposto não incide mais sobre ele mesmo",
     "antes": "O ISS entrava no valor sobre o qual ele mesmo era calculado: a nota cobrava imposto "
              "sobre imposto.",
     "agora": "O cálculo da nota segue a regra, e as contas antigas foram acertadas.",
     "tela": "fiscal:painel"},
    {"grave": True, "area": "Dinheiro · Loja", "titulo": "Venda do balcão cobrada uma vez só",
     "antes": "Um clique duplo, ou a internet caindo na hora de cobrar, podia registrar a venda duas "
              "vezes e tirar o produto do estoque em dobro.",
     "agora": "Cada venda leva um número de controle: se o pedido chegar de novo, o sistema reconhece "
              "e não cobra outra vez.",
     "tela": "loja:pdv"},
    {"grave": True, "area": "Estoque", "titulo": "Estoque sem lançamento dobrado",
     "antes": "Um clique duplo na entrada de mercadoria dobrava a quantidade e distorcia o custo "
              "médio; fechar um inventário desfazia vendas feitas durante a contagem.",
     "agora": "Cada lançamento entra uma vez só, e o inventário mexe só no que foi contado.",
     "tela": "estoque:posicao"},
    {"grave": True, "area": "LGPD · Site", "titulo": "Medição só com o “aceito” do visitante",
     "antes": "As páginas de captação ligavam o Google Analytics e o Pixel do Meta assim que abriam, "
              "sem perguntar ao visitante.",
     "agora": "Só medem depois que o visitante clica em “Aceitar”; se recusar, nada é ligado, como "
              "pede a LGPD.",
     "tela": "lp:inauguracao"},
    {"grave": True, "area": "Hóspede · Contrato", "titulo": "Termos e devolução dizem a mesma coisa",
     "antes": "Os termos prometiam devolver 90% em até 7 dias, mas o sistema devolvia 100% (o que a "
              "lei pede na venda pela internet), e o percentual aparecia num formato técnico (1E+1%).",
     "agora": "Termos, resumo e cálculo saem da mesma regra, o percentual aparece como 10%, e a "
              "reserva guarda o texto que o hóspede aceitou, com data e hora.",
     "tela": "core:termos_servico"},
    {"area": "Caixa", "titulo": "Fechar o caixa e receber ao mesmo tempo",
     "antes": "Se alguém fechasse o caixa no exato momento em que outra pessoa recebia um pagamento, "
              "um dos dois podia se perder.",
     "agora": "O sistema faz um esperar o outro terminar, e a devolução de um caixa já fechado entra "
              "no caixa aberto de hoje.",
     "tela": "caixa"},
    {"area": "Reservas", "titulo": "Check-in e check-out por inteiro",
     "antes": "Um erro em outra parte do sistema (lavanderia, restaurante) podia parar o check-out no "
              "meio e deixar a reserva pela metade.",
     "agora": "Check-in e check-out acontecem por inteiro ou não acontecem, e o erro de outra parte "
              "fica anotado para a equipe olhar."},
    {"area": "Relatórios", "titulo": "Cada noite no mês certo",
     "antes": "Uma estadia de 28/10 a 3/11 entrava toda na receita de outubro, e o day use contava "
              "como quarto ocupado, baixando a ocupação e a diária média.",
     "agora": "Cada noite entra no mês dela, e a ocupação considera só os quartos de pernoite.",
     "tela": ("relatorios:relatorio", "ocupacao")},
    {"area": "Segurança", "titulo": "Limite de tentativas de senha mais firme",
     "antes": "A trava contra quem tenta adivinhar senha nem sempre segurava o limite configurado.",
     "agora": "O limite vale para o sistema inteiro, pelo tempo definido."},
    {"area": "Segurança", "titulo": "Histórico de ações sem dado sensível",
     "antes": "Alguns registros do histórico de ações guardavam mais informação do que deviam.",
     "agora": "O histórico continua mostrando quem fez o quê, sem guardar dado sensível, e os "
              "registros antigos foram limpos."},
]

NOVIDADES = [
    {"area": "Governança", "titulo": "Arrumação no celular",
     "texto": "A camareira vê no celular os quartos dela, na ordem certa, e marca cada passo com um "
              "toque; a supervisão vê a casa inteira de uma vez e distribui a fila entre quem está de turno.",
     "tela": "governanca:painel"},
    {"area": "Governança", "titulo": "Ronda dos quartos",
     "texto": "A camareira anota se o quarto está vago, com mala ou sem mala, e o sistema avisa quando "
              "isso não bate com a recepção, como hóspede que saiu sem fechar a conta.",
     "tela": "governanca:discrepancias"},
    {"area": "Reservas", "titulo": "Regras de venda para feriados",
     "texto": "Estadia mínima, dia sem chegada ou sem saída e parar as vendas: no Réveillon, o site não "
              "vende mais só a noite do dia 31, e explica o motivo ao hóspede.",
     "tela": "reservas:restricoes"},
    {"area": "Relatórios", "titulo": "Como as vendas andam",
     "texto": "Quanto já está vendido para cada dia, o que entrou e saiu desde ontem, com quanta "
              "antecedência as pessoas reservam e quanto custa cada canal de venda.",
     "tela": ("relatorios:relatorio", "carteira")},
    {"area": "Auditoria", "titulo": "Fechamento do dia",
     "texto": "Toda madrugada o sistema tira uma “foto” do dia anterior (ocupação, chegadas, saídas, "
              "faltas, receita) que não muda mais, com os totais do mês e planilha.",
     "tela": "auditoria:fechamentos"},
    {"area": "Reservas", "titulo": "Falta sem aviso marcada sozinha",
     "texto": "Se a opção estiver ligada, quem não aparece é marcado na madrugada e o quarto volta à "
              "venda. Dá para desfazer.",
     "tela": "tabela_precos"},
    {"area": "Reservas", "titulo": "Faturar para agência ou empresa",
     "texto": "A conta vai para a empresa pagar depois (30 dias por padrão) e o hóspede sai sem "
              "pendência; o consumo pessoal pode ficar com ele."},
    {"area": "Recepção", "titulo": "Kit para quando a internet cair",
     "texto": "Uma folha para imprimir com hóspedes, saldos, chegadas com telefone, saídas e a "
              "situação dos 24 quartos, com uma cópia por e-mail toda madrugada.",
     "tela": "reservas:kit"},
    {"area": "Day pass", "titulo": "Day pass por turno",
     "texto": "Venda do uso do dia por turno, com limite de pessoas, ingresso, controle de quem entrou "
              "e saiu, caixa e comanda do grupo.",
     "tela": "daypass:painel"},
    {"area": "Canais de venda", "titulo": "Ligação com Booking, Airbnb e afins",
     "texto": "Quartos, preços e disponibilidade seguem para os canais, e as reservas de lá entram "
              "aqui. Está pronta e desligada: falta ativar com o provedor (Channex).",
     "tela": "canais:painel"},
    {"area": "Estoque", "titulo": "Compras, lotes e validade",
     "texto": "A compra entra pela embalagem (a caixa com 12), com lote e validade; o vencido sai da "
              "venda sozinho, e cada prato sabe o que gasta do estoque.",
     "tela": "estoque:notas"},
    {"area": "Lavanderia", "titulo": "Lavanderia como fila",
     "texto": "A roupa é recebida num toque e anda por etapas (recebida, lavando, pronta), com a hora "
              "de cada uma e o histórico do enxoval.",
     "tela": "lavanderia:painel"},
    {"area": "Reservas · ECA", "titulo": "Menor de idade no check-in",
     "texto": "A ficha pergunta se o menor está com os pais, com responsável ou com adulto autorizado, "
              "e o check-in pede a autorização quando precisa."},
]

DESIGN = [
    {"titulo": "Visão geral reorganizada",
     "texto": "Chegadas e saídas uma embaixo da outra, com a lista vazia numa linha só, e os recados "
              "do turno num cartão ao lado.",
     "tela": "dashboard"},
    {"titulo": "Menu que não faz a tela pular",
     "texto": "Abrir e fechar o menu não mexe mais no resto da tela; no celular, ele abre por cima, "
              "como uma gaveta.",
     "tela": "reservas:mapa"},
    {"titulo": "Menos etiquetas coloridas",
     "texto": "A etiqueta colorida ficou só para o que pede ação; o resto virou um ponto com texto, "
              "mais fácil de ler. Eram 252 nas telas, agora são 28.",
     "tela": "pessoas"},
    {"titulo": "Feito para o dedo",
     "texto": "Botões no tamanho do dedo, nada escapando para o lado no celular e janelas que abrem "
              "de baixo, com os botões perto do polegar.",
     "tela": "reservas:lista"},
    {"titulo": "Dinheiro e datas do jeito brasileiro",
     "texto": "R$ 1.234,56 em toda tela, palavras no lugar de códigos internos, datas que não somem "
              "ao reabrir a ficha e planilhas que o Excel abre certo.",
     "tela": "auditoria:trilha"},
    {"titulo": "Copiar e mandar pelo WhatsApp",
     "texto": "Link de pagamento, Pix e ficha de pré check-in têm botão para copiar e para enviar "
              "pelo WhatsApp, com a mensagem pronta.",
     "tela": "pagamentos:painel"},
]

QUALIDADE = [
    {"titulo": "Conferência a cada mudança",
     "texto": "Quase 3 mil conferências rodam sozinhas sempre que algo muda, 282 delas abrindo o "
              "sistema no navegador como uma pessoa. Se algo quebra, a mudança não entra."},
    {"titulo": "Segurança conferida antes de entregar",
     "texto": "A cada mudança, ferramentas procuram senha esquecida no código, peça de software com "
              "falha conhecida e erro comum de segurança."},
    {"titulo": "Backup todo dia",
     "texto": "Cópia dos dados toda madrugada, guardada por 30 dias, e um ensaio de recuperação "
              "conferiu que os números batem."},
    {"titulo": "Acesso da equipe",
     "texto": "“Esqueci minha senha” por e-mail, verificação em duas etapas para quem precisa e "
              "histórico de quem fez o quê, até nas ações automáticas."},
    {"titulo": "Telas mais rápidas",
     "texto": "As telas mais usadas fazem bem menos trabalho para abrir (veja os números acima), e "
              "uma conferência avisa se voltarem a ficar lentas."},
    {"titulo": "Lugar para testar sem risco",
     "texto": "Um servidor de testes, com dados de mentira e sem mandar nada de verdade, onde as duas "
              "versões abrem lado a lado para comparar."},
]

DO_ORIGINAL = [
    {"area": "24/10", "titulo": "Contábil e gerencial",
     "texto": "Plano de contas, resultado do mês, fluxo de caixa, fechamento mensal e arquivo para o "
              "contador, já conversando com o caixa, o estoque e o day pass desta versão.",
     "tela": "contabil:painel"},
    {"area": "25/10", "titulo": "Nota fiscal pelo Spedy",
     "texto": "A emissão pelo Spedy, no Lucro Presumido, encaixada no jeito desta versão: a nota "
              "espera a confirmação da prefeitura, e o cancelamento só vale quando confirmado.",
     "tela": "fiscal:painel"},
    {"area": "21/10", "titulo": "Comercial",
     "texto": "Reabrir ou mover negócio ganho ou perdido, “Ganhar” já com a diária da tabela, total "
              "na hora, sinal em R$ ou % e o resumo financeiro na reserva.",
     "tela": "comercial:funil"},
    {"area": "20 e 21/10", "titulo": "Reservas e preços",
     "texto": "Meia diária para crianças de 6 a 15 anos, ajustes no day use, regras de preço, tarifa "
              "não reembolsável e o comando para zerar as reservas de teste.",
     "tela": "tabela_precos"},
    {"area": "Mão na volta", "titulo": "De volta para o original",
     "texto": "Quatro consertos que também valem para a versão no ar estão prontos para ele aplicar "
              "quando quiser. E todo dia o sistema confere o que ele publica e propõe trazer para cá, "
              "sempre com revisão."},
]

PROXIMOS = [
    {"titulo": "Decidir qual versão vai para o ar",
     "texto": "No ar está a versão anterior. No ensaio de 26/10, os dados dela passaram para esta "
              "versão sem erro. Para trocar: ligar as tarefas automáticas no servidor, conferir as "
              "configurações e fazer backup antes."},
    {"titulo": "Ligar os serviços de verdade",
     "texto": "Nota fiscal (Spedy: conta, chave e certificado), nota do consumidor (depende da "
              "inscrição estadual), canais de venda, e-mail e WhatsApp. Por enquanto, tudo em simulação."},
    {"titulo": "Primeiro mês com o contador",
     "texto": "Fechar o mês no Contábil junto com ele e confirmar os impostos novos (IBS e CBS)."},
    {"titulo": "Regras de receita",
     "texto": "Decidir se a falta sem aviso é marcada sozinha (sugestão: 1 dia de tolerância), "
              "conferir quanto custa cada canal e como entra a comissão de agência."},
    {"titulo": "Governança com a equipe",
     "texto": "Validar com a camareira e a supervisora os nomes dos passos e dar acesso a quem vai "
              "usar a fila."},
    {"titulo": "Antes de abrir, em 31/10",
     "texto": "Zerar as reservas de teste, cadastrar a regra do Réveillon, ligar os avisos das "
              "tarefas automáticas, preencher os e-mails do kit e definir o responsável pelos dados (LGPD)."},
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


def _com_barras(medidas):
    # Largura em % como texto: o SVG pede ponto decimal, e número passado ao template
    # sairia com vírgula. 1,5% de mínimo para a barra de "2" não sumir.
    resultado = []
    for m in medidas:
        maior = max(m["antes"], m["agora"])
        resultado.append({**m, "barras": [
            {"rotulo": rotulo, "txt": m[f"{chave}_txt"], "agora": chave == "agora",
             "pct": f"{max(m[chave] / maior * 100, 1.5):.1f}"}
            for chave, rotulo in (("antes", "Antes"), ("agora", "Agora"))
        ]})
    return resultado


@login_required
def comparativo(request):
    return render(request, "vps/comparativo.html", {
        "nav_ativa": "comparativo",
        "anterior": f"{ANTERIOR}/crm/",
        "intro": INTRO,
        "rodape": RODAPE,
        "em_numeros": _com_barras(EM_NUMEROS),
        "n_correcoes": len(CORRECOES),
        "n_alto": sum(1 for c in CORRECOES if c.get("grave")),
        "correcoes": _com_links(CORRECOES),
        "novidades": _com_links(NOVIDADES),
        "design": _com_links(DESIGN),
        "qualidade": QUALIDADE,
        "do_original": _com_links(DO_ORIGINAL),
        "proximos": PROXIMOS,
    })
