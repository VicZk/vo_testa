from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_modulo
from apps.nucleo.ratelimit import limite_excedido

from . import services
from .models import SolicitacaoPortal


def _estadia_ou_404(token):
    from apps.nucleo.models import modulo_ativo
    if not modulo_ativo(Modulo.APPSITE):
        raise Http404()
    estadia = services.resolver(token)
    if not estadia:
        raise Http404()  # token inválido ou estadia encerrada
    return estadia


# ───────────────────────── Público (hóspede, por token) ─────────────────────────

@never_cache
def home(request, token):
    from apps.nps.services import reserva_por_token
    if reserva_por_token(token):
        from apps.nucleo.models import modulo_ativo
        if not modulo_ativo(Modulo.APPSITE):
            raise Http404()
        return redirect("portal:nps", token=token)
    estadia = _estadia_ou_404(token)
    return _home(request, token, estadia)


def _home(request, token, estadia, *, dados=None):
    cardapio = services.cardapio()
    if dados is not None:
        for item in cardapio:
            item["quantidade"] = dados.get(f"qtd_{item['id']}", "0")
            item["observacoes"] = dados.get(f"obs_{item['id']}", "")
            for grupo in item["grupos"]:
                escolhidas = set(dados.getlist(f"opcoes_{item['id']}_{grupo.pk}"))
                for opcao in grupo.opcoes.all():
                    opcao.escolhida = str(opcao.pk) in escolhidas
    return render(request, "portal/home.html", {
        "token": token, "e": estadia,
        "cardapio": cardapio,
        "chave_pedido": dados.get("chave_pedido", "") if dados is not None else uuid4(),
    })


@never_cache
def nps(request, token):
    from apps.nps.views import pesquisa
    from apps.nucleo.models import modulo_ativo
    if not modulo_ativo(Modulo.APPSITE):
        raise Http404()
    estadia = services.resolver(token)
    if estadia and request.method == "GET":
        return render(request, "portal/nps.html", {"token": token, "aguardando_checkout": True})
    return pesquisa(request, token)


@never_cache
def pedir(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        if limite_excedido(request, "portal_acoes", limite=20, janela_seg=300,
                           sufixo=str(token)):
            messages.error(request, "Muitas solicitações em pouco tempo. Aguarde um instante.")
            return redirect("portal:home", token=token)
        pedidos = []
        for chave, valor in request.POST.items():
            if chave.startswith("qtd_") and valor.strip():
                produto_id = chave[4:]
                opcoes = [opcao for campo, valores in request.POST.lists()
                          if campo.startswith(f"opcoes_{produto_id}_") for opcao in valores if opcao]
                pedidos.append({"produto_id": produto_id, "quantidade": valor,
                                "observacoes": request.POST.get(f"obs_{produto_id}", ""), "opcoes": opcoes})
        try:
            from apps.restaurante.services import validar_chave_pedido

            chave = validar_chave_pedido(request.POST.get("chave_pedido"), obrigatoria=True)
            comanda = services.pedir_restaurante(estadia, pedidos, chave_pedido=chave)
            messages.success(request, f"Pedido enviado! Comanda #{comanda.pk}.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return _home(request, token, estadia, dados=request.POST)
    return redirect("portal:home", token=token)


def solicitar(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        if limite_excedido(request, "portal_acoes", limite=20, janela_seg=300,
                           sufixo=str(token)):
            messages.error(request, "Muitas solicitações em pouco tempo. Aguarde um instante.")
            return redirect("portal:home", token=token)
        tipo = request.POST.get("tipo")
        if tipo == "limpeza":
            services.solicitar_limpeza(estadia)
            messages.success(request, "Limpeza extra solicitada. Já avisamos a governança.")
        elif tipo == "manutencao":
            services.solicitar_manutencao(estadia, request.POST.get("descricao", ""))
            messages.success(request, "Solicitação registrada. A manutenção vai atender.")
    return redirect("portal:home", token=token)


def checkout(request, token):
    estadia = _estadia_ou_404(token)
    return render(request, "portal/checkout.html", {"token": token, "e": estadia})


def pagar_saldo(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        try:
            cobranca = services.cobrar_saldo(estadia, request.POST.get("metodo") or "pix")
            services.solicitar_checkout(estadia)
            return redirect("pagamentos:pagar", token=cobranca.token)
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("portal:checkout", token=token)


def solicitar_checkout_recepcao(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        services.solicitar_checkout(estadia)
        messages.success(request, "Check-out solicitado. A recepção vai finalizar.")
    return redirect("portal:home", token=token)


# ───────────────────────── Pré check-in (FNRH) — hóspede, por token ─────────────

@never_cache
def checkin(request, token):
    """Check-in online: o hóspede responsável preenche a FNRH de todos num só
    aparelho. Funciona antes da hospedagem (reserva ainda ativa)."""
    from apps.nucleo.models import modulo_ativo
    from apps.reservas import services as reservas_services

    if not modulo_ativo(Modulo.APPSITE):
        raise Http404()
    # TM-003: rate limit por IP — abranda brute-force de token e abuso da PII.
    if limite_excedido(request, "fnrh_portal", limite=30, janela_seg=60):
        return HttpResponse("Muitas requisições. Aguarde um momento.", status=429)
    acesso = services.acesso_por_token(token)
    if not acesso:
        raise Http404()
    reserva, queryset = reservas_services.preparar_fnrh(acesso.reserva_id)
    if reserva is None or not reserva.ativa:
        raise Http404()

    if request.method == "POST":
        formset = reservas_services.fnrh_formset(data=request.POST, queryset=queryset)
        if formset.is_valid():
            fichas = formset.save()
            reservas_services.marcar_fichas_preenchidas(
                fichas or queryset, origem="portal"
            )
            messages.success(request, "Ficha enviada. Obrigado!")
            return redirect("portal:checkin", token=token)
        messages.error(request, "Confira os campos destacados.")
    else:
        formset = reservas_services.fnrh_formset(queryset=queryset)

    fichas = list(reserva.fichas_fnrh.all())
    return render(request, "portal/checkin.html", {
        "token": token, "formset": formset, "reserva": reserva,
        "pronta": reserva.fnrh_pronta,
        "total": len(fichas),
        "completas": sum(1 for f in fichas if f.completa),
    })


# ───────────────────────── Recepção (staff): QR do hóspede ─────────────────────────

def _telefone_da_reserva(reserva_id) -> str:
    """Telefone de quem recebe o link — o QR só serve a quem está no balcão."""
    from apps.reservas.services import contato_da_reserva
    return contato_da_reserva(reserva_id).get("telefone", "")


@requer_modulo(Modulo.APPSITE)
def qr(request, reserva_id):
    from apps.reservas.services import estadia_ativa
    if not estadia_ativa(reserva_id):
        raise Http404("Reserva não está hospedada.")
    acesso = services.get_acesso(reserva_id)
    url = request.build_absolute_uri(reverse("portal:home", args=[acesso.token]))
    return render(request, "portal/qr.html", {
        "url": url, "svg": _qr_svg(url), "reserva_id": reserva_id, "voltar": "portal:qr",
        "rotulo_link": "Link do portal do hóspede",
        "telefone_hospede": _telefone_da_reserva(reserva_id),
        "recado_whatsapp": 'Olá! Acesse sua estadia na Pousada Vô Testa pelo link abaixo. Você pode consultar a conta do quarto, fazer pedidos ao restaurante e solicitar limpeza. Não precisa de senha:',
    })


@requer_modulo(Modulo.APPSITE)
def qr_novo(request, reserva_id):
    """Gera um token novo para o portal da reserva; o QR antigo deixa de valer."""
    if request.method == "POST":
        services.rotacionar_acesso(reserva_id, request.user)
        messages.success(request, "QR novo gerado. O anterior não abre mais o portal.")
    destino = request.POST.get("voltar") or "portal:qr"
    if destino not in ("portal:qr", "portal:qr_fnrh"):
        destino = "portal:qr"
    return redirect(destino, reserva_id=reserva_id)


@requer_modulo(Modulo.APPSITE)
def qr_fnrh(request, reserva_id):
    """QR do pré check-in: o hóspede lê e preenche a FNRH antes de chegar."""
    from apps.reservas.services import preparar_fnrh
    reserva, _ = preparar_fnrh(reserva_id)
    if reserva is None or not reserva.ativa:
        raise Http404("Reserva não está ativa.")
    acesso = services.get_acesso(reserva_id)
    url = request.build_absolute_uri(reverse("portal:checkin", args=[acesso.token]))
    return render(request, "portal/qr.html", {
        "url": url, "svg": _qr_svg(url), "reserva_id": reserva_id,
        "finalidade": "FNRH (check-in online)", "voltar": "portal:qr_fnrh",
        "rotulo_link": "Link do pré check-in",
        "telefone_hospede": _telefone_da_reserva(reserva_id),
        "recado_whatsapp": "Olá! Para a sua entrada na Pousada Vô Testa ser rápida, "
                           "preencha a ficha de hospedagem por este link antes de "
                           "chegar (dá para preencher a de todos num celular só):",
    })


def _qr_svg(url):
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


@requer_modulo(Modulo.APPSITE)
def solicitacoes(request):
    """Painel interno das solicitações vindas do portal."""
    pagina = paginar(request, SolicitacaoPortal.objects.all())
    return render(request, "portal/solicitacoes.html", {
        "solicitacoes": pagina, "pagina": pagina,
    })
