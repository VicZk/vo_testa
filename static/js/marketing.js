/* Edição de campanhas: a pessoa decide quando salvar e mantém o lugar na ficha. */
(function () {
  'use strict';
  let vista = null;
  let quadroMudou = false;
  let focoNoQuadro = null;
  let focoNaEntrega = null;

  document.addEventListener('modal:antesFechar', ev => {
    if (ev.defaultPrevented) return;
    const ficha = ev.detail.caixa.querySelector('[data-mkt-campanha]');
    if (ficha) focoNoQuadro = ficha.dataset.mktCampanha;
  });
  window.fecharFichaMarketing = function (el) { window.fecharEdicao(el); };
  document.addEventListener('htmx:beforeRequest', ev => {
    if (ev.detail.target.id !== 'modal-conteudo') return;
    const entrega = ev.detail.elt.closest('[data-entrega]');
    if (entrega) focoNaEntrega = entrega.dataset.entrega;
  });
  document.addEventListener('htmx:beforeSwap', ev => {
    if (ev.detail.target.id === 'modal-conteudo') {
      const entrega = document.activeElement && document.activeElement.closest('[data-entrega]');
      if (entrega) focoNaEntrega = entrega.dataset.entrega;
    }
    if (ev.detail.target.id === 'marketing-quadro') {
      const card = document.activeElement && document.activeElement.closest('[data-camp]');
      focoNoQuadro = (card && card.dataset.camp) || focoNoQuadro;
    }
    if (ev.detail.target.id !== 'ficha-slot') return;
    const ficha = ev.detail.target;
    const corpo = ficha.querySelector('.fx-corpo');
    vista = {
      scroll: corpo ? corpo.scrollTop : 0,
      abertos: Array.from(ficha.querySelectorAll('details[open] > summary')).map(el => el.textContent),
      foco: document.activeElement && document.activeElement.id,
    };
  });
  document.addEventListener('htmx:afterSwap', ev => {
    if (ev.detail.target.id === 'marketing-quadro' && focoNoQuadro) {
      const card = document.querySelector('#marketing-quadro [data-camp="' + CSS.escape(focoNoQuadro) + '"] .mk-card-nome');
      if (card) card.focus({ preventScroll: true });
      focoNoQuadro = null;
    }
    if (ev.detail.target.id !== 'ficha-slot' || !vista) return;
    const ficha = ev.detail.target;
    ficha.querySelectorAll('details > summary').forEach(el => {
      if (vista.abertos.includes(el.textContent)) el.parentElement.open = true;
    });
    const corpo = ficha.querySelector('.fx-corpo');
    if (corpo) corpo.scrollTop = vista.scroll;
    const erro = ficha.querySelector('.campo-erro input, .campo-erro select, .campo-erro textarea');
    const anterior = vista.foco && document.getElementById(vista.foco);
    if (erro) { erro.focus(); erro.scrollIntoView({ block: 'nearest' }); }
    else if (anterior) anterior.focus({ preventScroll: true });
    vista = null;
  });
  document.addEventListener('htmx:afterSettle', ev => {
    if (!['marketing-entregas', 'marketing-calendario'].includes(ev.detail.target.id) || !focoNaEntrega) return;
    const painel = document.getElementById(ev.detail.target.id);
    if (!painel) return;
    const entrega = painel.querySelector('[data-entrega="' + CSS.escape(focoNaEntrega) + '"] .mkt-entrega-editar');
    const titulo = painel.querySelector('h1');
    if (entrega) entrega.focus({ preventScroll: true });
    else if (titulo) { titulo.setAttribute('tabindex', '-1'); titulo.focus({ preventScroll: true }); }
    focoNaEntrega = null;
  });
  document.addEventListener('marketing:alterado', () => { quadroMudou = true; });
  document.addEventListener('modal:fechado', () => {
    if (quadroMudou && document.querySelector('#marketing-quadro, #marketing-entregas, #marketing-calendario')) {
      quadroMudou = false;
      htmx.trigger(document.body, 'marketing:atualizar');
    }
  });
})();
