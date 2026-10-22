"""Contrato implementado de NPS pós-estadia; mantido no caminho da proposta original."""

PROPOSTA = {
    "titulo": "NPS pós-estadia",
    "status": "implementado",
    "implementado": True,
    "api": {
        "base": "/api/nps/v1/",
        "autenticacao": "Token do portal para resposta; sessão CRM, área NPS e CSRF para equipe.",
        "endpoints": [
            {"metodo": "POST", "path": "/api/nps/v1/respostas/"},
            {"metodo": "GET", "path": "/api/nps/v1/respostas/<reserva_id>/"},
            {"metodo": "GET", "path": "/api/nps/v1/resumo/?de=&ate="},
        ],
        "regras": [
            "Nota inteira de 0 a 10; comentário opcional de até 2000 caracteres.",
            "Após check-out efetivo, até 90 dias (NPS_JANELA_DIAS).",
            "Uma resposta por estadia; repetição igual retorna 200; alteração retorna 409.",
            "Canal: portal, email, whatsapp ou equipe (somente sessão interna).",
        ],
    },
    "documento": "docs/Proposta_NPS.md",
}
