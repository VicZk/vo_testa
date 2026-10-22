/* Edição de campanhas: a pessoa decide quando salvar e mantém o lugar na ficha. */
(function () {
  'use strict';
  let vista = null;
  let quadroMudou = false;
  let focoNoQuadro = null;

  function pendentes(raiz, exceto) {
    return Array.from((raiz || document).querySelectorAll('[data-mkt-edit][data-dirty="1"]'))
      .filter(form => form !== exceto);
  }
  function podeDescartar(raiz, exceto) {
    return !pendentes(raiz, exceto).length || window.confirm(
      'Há dados que ainda não foram salvos. Deseja descartá-los? Para salvar, escolha Cancelar e use o botão Salvar.');
  }
  function alterou(ev) {
    const form = ev.target.closest && ev.target.closest('[data-mkt-edit]');
    if (!form) return;
    form.dataset.dirty = '1';
    const aviso = form.querySelector('.mkt-save-state');
    if (aviso) aviso.textContent = 'Alterações ainda não salvas';
  }
  document.addEventListener('input', alterou);
  document.addEventListener('change', alterou);
  document.addEventListener('submit', ev => {
    const form = ev.target;
    if (ev.defaultPrevented || form.hasAttribute('hx-post')) return;
    if (!podeDescartar(document, form)) { ev.preventDefault(); return; }
    pendentes(document).forEach(item => { delete item.dataset.dirty; });
  });
  document.addEventListener('htmx:confirm', ev => {
    const el = ev.detail.elt;
    const form = el && el.closest('form');
    if (!podeDescartar(document, form)) ev.preventDefault();
  });
  document.addEventListener('modal:antesFechar', ev => {
    if (!podeDescartar(ev.detail.caixa)) { ev.preventDefault(); return; }
    const ficha = ev.detail.caixa.querySelector('[data-mkt-campanha]');
    if (ficha) focoNoQuadro = ficha.dataset.mktCampanha;
  });
  window.addEventListener('beforeunload', ev => {
    if (!pendentes(document).length) return;
    ev.preventDefault();
    ev.returnValue = '';
  });
  window.fecharFichaMarketing = function (el) {
    if (el.closest('#modal-conteudo')) { window.fecharModal(); return; }
    const ficha = el.closest('[data-voltar]');
    if (ficha && podeDescartar(ficha)) {
      pendentes(ficha).forEach(form => { delete form.dataset.dirty; });
      window.location.href = ficha.dataset.voltar;
    }
  };
  document.addEventListener('htmx:beforeSwap', ev => {
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
    ev.detail.target.querySelectorAll('[data-mkt-edit]').forEach(form => {
      if (form.querySelector('.erro')) form.dataset.dirty = '1';
    });
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
  document.addEventListener('marketing:alterado', () => { quadroMudou = true; });
  document.addEventListener('modal:fechado', () => {
    if (quadroMudou && document.getElementById('marketing-quadro')) {
      quadroMudou = false;
      htmx.trigger(document.body, 'marketing:atualizar');
    }
  });
})();
