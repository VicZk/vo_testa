/* Proteção compartilhada de formulários com salvamento explícito. */
(function () {
  'use strict';
  const seletor = '[data-edicao-pendente], [data-mkt-edit]';
  function pendentes(raiz, exceto) {
    raiz = raiz || document;
    const forms = Array.from(raiz.querySelectorAll(seletor));
    if (raiz.matches && raiz.matches(seletor)) forms.unshift(raiz);
    return forms
      .filter(form => form !== exceto && form.dataset.dirty === '1');
  }
  function podeDescartar(raiz, exceto) {
    return !pendentes(raiz, exceto).length || window.confirm(
      'Há dados que ainda não foram salvos. Deseja descartá-los? Para salvar, escolha Cancelar e use o botão Salvar.');
  }
  function limpar(raiz) { pendentes(raiz).forEach(form => { delete form.dataset.dirty; }); }
  function alterou(ev) {
    const form = ev.target.closest && ev.target.closest(seletor);
    if (!form) return;
    form.dataset.dirty = '1';
    const aviso = form.querySelector('[data-estado-edicao], .mkt-save-state');
    if (aviso) aviso.textContent = 'Alterações ainda não salvas';
  }
  document.addEventListener('input', alterou);
  document.addEventListener('change', alterou);
  document.addEventListener('submit', ev => {
    const form = ev.target;
    if (ev.defaultPrevented || form.hasAttribute('hx-post') || form.hasAttribute('data-preservar-erros')) return;
    if (!podeDescartar(document, form)) { ev.preventDefault(); return; }
    limpar(document);
  });
  document.addEventListener('htmx:confirm', ev => {
    const el = ev.detail.elt;
    if (!podeDescartar(document, el && el.closest('form'))) ev.preventDefault();
  });
  document.addEventListener('modal:antesFechar', ev => {
    if (!podeDescartar(ev.detail.caixa)) ev.preventDefault();
  });
  document.addEventListener('htmx:beforeOnLoad', ev => {
    if (ev.detail.xhr.status < 400 && ev.detail.xhr.getResponseHeader('HX-Redirect')) {
      limpar(document);
    }
  });
  document.addEventListener('htmx:afterSwap', ev => {
    ev.detail.target.querySelectorAll(seletor).forEach(form => {
      if (form.querySelector('.erro')) form.dataset.dirty = '1';
    });
  });
  document.addEventListener('htmx:afterSettle', ev => {
    const form = ev.detail.target.querySelector('[data-edicao-pendente]');
    if (!form) return;
    const erro = form.querySelector('.campo-erro');
    if (!erro) return;
    const secao = erro.closest('details');
    if (secao) secao.open = true;
    const campo = Array.from(erro.querySelectorAll('input:not([type=hidden]), select, textarea'))
      .find(el => el.getClientRects().length);
    if (campo) { campo.focus(); campo.scrollIntoView({ block: 'nearest' }); }
  });
  window.addEventListener('beforeunload', ev => {
    if (!pendentes(document).length) return;
    ev.preventDefault(); ev.returnValue = '';
  });
  window.EdicaoPendente = { podeDescartar, limpar };
  window.fecharEdicao = function (el) {
    if (el.closest('#modal-conteudo')) { window.fecharModal(); return; }
    const ficha = el.closest('[data-voltar]');
    if (ficha && podeDescartar(ficha)) {
      limpar(ficha); window.location.href = ficha.dataset.voltar;
    }
  };
})();
