"""Copiar e mandar pelo WhatsApp — o que a recepção fazia na mão.

Link de pagamento, Pix copia-e-cola, QR do portal, link da página de captação: a
equipe selecionava o texto com o mouse, copiava e colava no WhatsApp. Aqui mora a
parte testável disso — normalizar o telefone para o formato que o `wa.me` aceita e
montar a mensagem pronta. O botão em si é `{% copiar %}`
(`templates/componentes/copiar.html` + `static/js/copiar.js`).
"""

from urllib.parse import quote

#: Assinatura das mensagens prontas. Uma só, para o hóspede reconhecer quem fala.
POUSADA = "Pousada Vô Testa"


def telefone_whatsapp(valor):
    """'(49) 99964-8702' → '5549999648702'. Devolve '' quando não dá para discar.

    O `wa.me` só aceita dígitos com DDI. O telefone vem do cadastro em qualquer
    formato — com máscara, com +55 na frente, ou só DDD + número — e todos os
    nossos são do Brasil, então o 55 entra quando falta. Número curto demais
    (fixo sem DDD, campo pela metade) não vira link: melhor abrir o WhatsApp sem
    destinatário do que mandar a mensagem para o número errado.
    """
    digitos = "".join(c for c in (valor or "") if c.isdigit())
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos
    if len(digitos) in (10, 11):
        return "55" + digitos
    return ""


def mensagem_whatsapp(texto, link=""):
    """Junta o recado e o link numa mensagem só, como a recepção escreveria."""
    texto = (texto or "").strip()
    link = (link or "").strip()
    if texto and link:
        return f"{texto}\n\n{link}"
    return texto or link


def link_whatsapp(mensagem, telefone=""):
    """URL do `wa.me` com a mensagem já escrita.

    Com telefone, abre a conversa daquela pessoa; sem telefone (ou com um que não
    dá para discar), abre o WhatsApp para quem está na recepção escolher o contato
    — nunca é um beco sem saída.
    """
    destino = telefone_whatsapp(telefone)
    return f"https://wa.me/{destino}?text={quote(mensagem or '')}"
