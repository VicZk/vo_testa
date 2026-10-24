/* A tela acompanha o saldo confirmado pelo servidor e mostra o desconto antes de fechar. */
(function () {
  'use strict';
  if (window.restauranteComandaAtivo) return;
  window.restauranteComandaAtivo = true;
  const raiz = () => document.querySelector('[data-restaurante-comanda]');
  const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
  const quantidade = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 3 });

  function centavos(valor) {
    const partes = String(valor || '0').replace(',', '.').match(/^(\d+)(?:\.(\d{0,2}))?$/);
    if (!partes) return null;
    const total = Number(partes[1]) * 100 + Number((partes[2] || '').padEnd(2, '0'));
    return Number.isSafeInteger(total) ? total : null;
  }

  function totalizar() {
    const tela = raiz();
    if (!tela) return;
    const itens = tela.querySelector('#comanda-itens');
    const campo = tela.querySelector('[name="desconto"]');
    const total = tela.querySelector('[data-restaurante-total]');
    if (!campo || !itens || !total) return;
    const subtotal = centavos(itens.dataset.subtotal);
    const desconto = centavos(campo.value);
    const valido = subtotal !== null && desconto !== null && desconto <= subtotal;
    total.textContent = valido ? moeda.format((subtotal - desconto) / 100) : 'Confira o desconto';
    total.classList.toggle('texto-perigo', !valido);
    const barra = tela.querySelector('[data-barra-total]');
    if (barra) barra.textContent = valido ? total.textContent : '—';
    const semCobranca = tela.querySelector('[data-restaurante-sem-cobranca]');
    if (semCobranca) semCobranca.hidden = !valido || subtotal !== desconto || itens.dataset.temItens !== '1';
    const botao = tela.querySelector('.pdv-finalizar');
    if (botao) botao.disabled = itens.dataset.temItens !== '1';
  }

  function filtrar() {
    const tela = raiz();
    if (!tela) return;
    const busca = (tela.querySelector('[data-restaurante-busca]')?.value || '').toLocaleLowerCase('pt-BR');
    const categoria = tela.querySelector('[data-restaurante-categoria]')?.value || '';
    const disponiveis = tela.querySelector('[data-restaurante-disponiveis]')?.checked;
    let encontrados = 0;
    tela.querySelectorAll('[data-restaurante-produto]').forEach(botao => {
      const nome = botao.querySelector('.pdv-produto-nome').textContent.toLocaleLowerCase('pt-BR');
      const mostrar = nome.includes(busca) && (!categoria || botao.dataset.categoria === categoria)
        && (!disponiveis || !botao.disabled);
      botao.hidden = !mostrar;
      if (mostrar) encontrados++;
    });
    const vazio = tela.querySelector('[data-restaurante-vazio]');
    if (vazio) vazio.hidden = encontrados !== 0;
  }

  function navegar(tela, painel, rolar = false) {
    if (!['cardapio', 'conta'].includes(painel)) return;
    tela.dataset.comandaPainel = painel;
    tela.classList.add('comanda-navegavel');
    tela.querySelectorAll('.restaurante-atalhos [data-comanda-abrir]').forEach(link => {
      if (link.dataset.comandaAbrir === painel) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
    if (rolar) tela.querySelector('#restaurante-' + painel)?.scrollIntoView({block: 'start', behavior: 'auto'});
  }

  function preparar() {
    const tela = raiz();
    if (!tela) return;
    navegar(tela, tela.dataset.comandaPainel);
    filtrar(); totalizar();
  }
  document.addEventListener('click', ev => {
    const link = ev.target.closest('[data-comanda-abrir]');
    const tela = raiz();
    if (!link || !tela || !tela.contains(link) || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    navegar(tela, link.dataset.comandaAbrir, true);
  });
  document.addEventListener('input', ev => {
    if (ev.target.matches('[data-restaurante-busca]')) filtrar();
    if (ev.target.matches('[data-restaurante-comanda] [name="desconto"]')) totalizar();
  });
  document.addEventListener('change', ev => {
    if (ev.target.matches('[data-restaurante-categoria], [data-restaurante-disponiveis]')) filtrar();
  });
  document.addEventListener('restauranteEstoque', ev => {
    const tela = raiz();
    const detalhe = ev.detail || {};
    if (!tela || String(detalhe.comanda) !== tela.dataset.restauranteComanda) return;
    tela.querySelectorAll('[data-restaurante-produto]').forEach(botao => {
      const valor = detalhe.saldos?.[botao.dataset.restauranteProduto];
      if (valor === undefined) {
        botao.disabled = true;
        botao.classList.add('esgotado');
        botao.querySelector('.pdv-saldo').textContent = 'Indisponível';
        return;
      }
      const saldo = Number(valor);
      if (!Number.isFinite(saldo)) return;
      botao.disabled = saldo <= 0;
      botao.classList.toggle('esgotado', saldo <= 0);
      botao.querySelector('.pdv-saldo').textContent = saldo > 0
        ? 'Saldo ' + quantidade.format(saldo) + (botao.dataset.unidade ? ' ' + botao.dataset.unidade : '') : 'Esgotado';
    });
    preparar();
  });
  document.addEventListener('pedidoSalvo', () => {
    if (!raiz()) return;
    const modal = document.querySelector('#modal-conteudo');
    if (modal) window.EdicaoPendente?.limpar(modal);
    window.fecharModal();
    totalizar();
  });
  document.addEventListener('htmx:afterSwap', preparar);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', preparar);
  else preparar();
})();
