"""
Formatação legível da Trilha de auditoria.

Transforma (ação + alvo + detalhe) numa frase em pt-BR — "Abriu o caixa de
Reservas. Fundo: R$ 0,00" em vez do JSON cru. O detalhe bruto continua guardado
(forense); isto é só apresentação. O que não tem molde cai num texto genérico
razoável, nunca quebra.
"""

# Nomes de model → português amigável.
ALVOS = {
    "EmbalagemProduto": "embalagem de compra", "IngredienteFicha": "ingrediente da ficha técnica",
    "LoteEstoque": "lote de estoque", "RegistroLote": "registro de lote",
    "ConfiguracaoCanais": "conexão de canais",
    "MapeamentoCanal": "categoria de canal",
    "ReservaCanal": "reserva externa",
    "RevisaoCanal": "revisão de reserva externa",
    "EnvioCanal": "envio aos canais",
    "AvisoCanal": "notificação de canal",
    "SessaoCaixa": "caixa",
    "MovimentoCaixa": "movimento de caixa",
    "Reserva": "reserva",
    "ContaHospedagem": "conta de hospedagem",
    "LancamentoConta": "lançamento na conta",
    "PagamentoConta": "pagamento",
    "Adiantamento": "adiantamento",
    "ContaPagarReceber": "conta a pagar/receber",
    "Pessoa": "pessoa",
    "Usuario": "usuário",
    "OrdemServico": "ordem de serviço",
    "Venda": "venda",
    "Comanda": "comanda",
    "OrdemLavanderia": "ordem de lavanderia",
    "EntradaLogbook": "recado de turno",
    "RestricaoVenda": "restrição de venda",
}

# Rótulo de cada ação para a coluna "Ação" e o filtro da trilha. O código continua
# no banco e no CSV (forense); a tela mostra palavra de gente — eram "no_show",
# "lead_fechado_movido", "bloqueio_uh" em minúsculo, com sublinhado.
ACOES = {
    "identificacao_lote": "Identificação de saldo por lote", "contagem_lote": "Contagem de lote",
    "correcao_lote": "Correção da identificação do lote", "ficha_tecnica_salva": "Ficha técnica atualizada",
    "devolucao_estoque": "Devolução ao estoque",
    "configuracao_canais": "Configuração dos canais", "mapeamento_canal": "Mapeamento de categoria",
    "validacao_canal": "Validação da conexão", "envio_canal_conferido": "Conferência do envio aos canais",
    "sincronizacao_canal_solicitada": "Atualização dos canais solicitada", "aviso_canal_recebido": "Notificação de canal recebida",
    "revisao_canal_aplicada": "Reserva externa aplicada", "revisao_canal_conferida": "Conferência de reserva externa",
    "reserva_canal_aplicada": "Aplicação de reserva externa", "reserva_canal_conferida": "Vínculo com reserva externa",
    "login": "Entrada no sistema", "logout": "Saída do sistema",
    "criar": "Criação", "editar": "Edição", "excluir": "Exclusão",
    "ajuste_arredondamento": "Ajuste de arredondamento", "ajuste_estoque": "Ajuste de estoque",
    "alteracao_lotacao": "Alteração de lotação", "alterar_acesso": "Alteração de acesso",
    "baixa_conta": "Baixa de conta", "baixa_enxoval": "Baixa de enxoval",
    "bloqueio_uh": "Bloqueio de quarto", "liberacao_uh": "Liberação de quarto",
    "cancelamento_comanda": "Cancelamento de comanda", "cancelamento_fiscal": "Cancelamento de nota fiscal",
    "cancelamento_lavanderia": "Cancelamento de lavanderia", "cancelamento_os": "Cancelamento de OS",
    "entrega_antecipada_lavanderia": "Entrega antecipada de lavanderia",
    "desconto_lavanderia": "Desconto em lavanderia",
    "preco_lavanderia": "Preço de lavanderia alterado",
    "cancelamento_reserva": "Cancelamento de reserva", "cancelamento_venda": "Cancelamento de venda",
    "criar_grupo": "Criação de grupo", "cancelar_grupo": "Cancelamento de grupo",
    "encerrar_grupo": "Encerramento de grupo",
    "devolucao_hospede": "Devolução ao hóspede",
    "diaria_vendida_divergente": "Diária vendida divergente",
    "escala_forcar_interjornada": "Escala sem descanso entre jornadas",
    "estorno": "Estorno", "estorno_pagamento": "Estorno de pagamento",
    "expiracao_retencao": "Retenção expirada", "extensao_estadia": "Extensão de estadia",
    "faturamento_conta": "Faturamento de conta", "faxina_concluida": "Faxina concluída",
    "fechamento_caixa": "Fechamento de caixa", "reabertura_caixa": "Reabertura de caixa",
    "gasto_sincronizacao_falha": "Falha ao sincronizar gasto",
    "inspecao_reprovada": "Inspeção reprovada", "inventario_aplicado": "Inventário aplicado",
    "lead_assumido": "Lead assumido", "lead_fechado_movido": "Lead fechado movido",
    "no_show": "Não comparecimento", "no_show_desfeito": "Não comparecimento desfeito",
    "oportunidade_convertida": "Oportunidade convertida", "oportunidade_perdida": "Oportunidade perdida",
    "politica_cancelamento": "Política de cancelamento", "portal_novo_qr": "Novo QR do portal",
    "publicar_escala": "Publicação da escala", "purga_trilha": "Limpeza da trilha",
    "reabrir_ocorrencia": "Reabertura de ocorrência",
    "restricao_dispensada": "Restrição de venda dispensada",
    "transferencia_datas": "Transferência de datas", "transferencia_estoque": "Transferência de estoque",
    "troca_quarto": "Troca de quarto",
}

GRAVIDADES = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}


def _frase_curta(codigo: str) -> str:
    """Código desconhecido vira texto legível: sublinhado → espaço, inicial maiúscula."""
    texto = (codigo or "").replace("_", " ").strip()
    return texto[:1].upper() + texto[1:]


def rotulo_acao(codigo: str) -> str:
    return ACOES.get(codigo) or _frase_curta(codigo)


def rotulo_alvo(nome_model: str) -> str:
    """"SessaoCaixa" → "Caixa", "OrdemServico" → "Ordem de serviço"."""
    nome = ALVOS.get(nome_model)
    return (nome[:1].upper() + nome[1:]) if nome else (nome_model or "")


def rotulo_gravidade(codigo: str) -> str:
    return GRAVIDADES.get(codigo) or _frase_curta(codigo)


# Verbos de movimento de caixa.
_MOV = {
    "recebimento": "Recebeu", "reforco": "Reforço de",
    "sangria": "Sangria de", "estorno": "Estornou",
}


def _rs(v):
    """Dinheiro em pt-BR pelo formatador único do sistema (um só, para não divergir)."""
    from apps.nucleo.templatetags.moeda import intcomma_brl
    return intcomma_brl(v)


def frase(registro) -> str:
    acao = registro.acao
    alvo = registro.alvo
    from apps.nucleo.audit import redigir_credenciais

    d = redigir_credenciais(registro.detalhe or {})
    valores = d.get("valores", {}) if isinstance(d, dict) else {}
    nome = ALVOS.get(alvo, alvo)

    # Entrar / sair
    if acao == "login":
        return "Entrou no sistema"
    if acao == "logout":
        return "Saiu do sistema"

    # Caixa (abrir / fechar / reabrir)
    if acao == "criar" and alvo == "SessaoCaixa":
        return (f"Abriu o caixa de {valores.get('modulo', '—')} "
                f"— fundo {_rs(valores.get('fundo_troco', 0))}")
    if acao == "fechamento_caixa":
        return (f"Fechou o caixa. Valor contado: {_rs(d.get('contado', 0))} "
                f"(diferença {_rs(d.get('diferenca', 0))})")
    if acao == "reabertura_caixa":
        return f"Reabriu o caixa. Motivo: {d.get('motivo', '—')}"

    # Movimento de caixa (recebimento, reforço, sangria)
    if acao == "criar" and alvo == "MovimentoCaixa":
        verbo = _MOV.get(valores.get("tipo"), "Movimento de")
        desc = valores.get("descricao")
        return f"{verbo} {_rs(valores.get('valor', 0))}" + (f" — {desc}" if desc else "")

    # Estorno
    if acao == "estorno":
        return f"Estornou {_rs(d.get('valor', 0))}. Motivo: {d.get('motivo', '—')}"

    # Grupo de reserva
    if acao == "criar_grupo":
        return f"Criou o grupo {d.get('rotulo', '')}".rstrip()

    # Ações semânticas de reserva/caixa (nomeadas)
    semanticas = {
        "checkout_automatico": "Fez o check-out (vencido) da reserva",
        "troca_quarto": "Trocou a reserva de quarto",
        "confirmar_reserva": "Confirmou a reserva",
        "cancelamento": "Cancelou a reserva",
        "fechamento_grupo": "Encerrou o grupo",
        "restricao_dispensada": "Vendeu com as vendas paradas (gerência)",
    }
    if acao in semanticas:
        extra = ""
        if "de" in d and "para" in d:
            extra = f", de {d['de']} para {d['para']}"
        elif "motivo" in d:
            extra = f". Motivo: {d['motivo']}"
        return f"{semanticas[acao]}{extra}"

    # Genéricos da auto-auditoria (criar / editar / excluir)
    if acao == "criar":
        # Verbo mais natural para algumas entidades operacionais.
        if alvo == "EntradaLogbook":
            return "Deixou um recado no turno"
        verbos = {
            "OrdemServico": "Abriu ordem de serviço",
            "Venda": "Registrou venda",
            "Comanda": "Abriu comanda",
            "OrdemLavanderia": "Abriu ordem de lavanderia",
        }
        if alvo in verbos:
            return f"{verbos[alvo]} #{registro.alvo_id}"
        return f"Criou {nome} #{registro.alvo_id}"
    if acao == "excluir":
        return f"Excluiu {nome} #{registro.alvo_id}"
    if acao == "editar":
        alteracoes = d.get("alteracoes", {}) if isinstance(d, dict) else {}
        if alteracoes:
            partes = []
            for campo, par in list(alteracoes.items())[:3]:
                antes, depois = (par + [None, None])[:2] if isinstance(par, list) else (None, par)
                partes.append(f"{campo}: {antes if antes not in (None, '') else '—'} → "
                              f"{depois if depois not in (None, '') else '—'}")
            reticencia = " …" if len(alteracoes) > 3 else ""
            return f"Alterou {nome}: " + "; ".join(partes) + reticencia
        return f"Alterou {nome} #{registro.alvo_id}"

    # Fallback: humaniza o código da ação, nunca mostra JSON cru.
    return f"{acao.replace('_', ' ').capitalize()} — {nome} #{registro.alvo_id}"
