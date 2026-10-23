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
    const alterados = pendentes(raiz, exceto);
    return !alterados.length || window.confirm(alterados[0].dataset.descarteMensagem ||
      'Há dados que ainda não foram salvos. Deseja descartá-los? Para salvar, escolha Cancelar e use o botão Salvar.');
  }
  function limpar(raiz) { pendentes(raiz).forEach(form => { delete form.dataset.dirty; }); }
  function alterou(ev) {
    const form = ev.target.closest && ev.target.closest(seletor);
    if (!form || form.dataset.edicaoPendente === 'manual') return;
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
    // Um link como Cancelar pode estar dentro do formulário, mas navega para
    // outra página: só o envio/controle do próprio formulário fica dispensado.
    const formEnviado = el?.closest('a[href]') ? null : el?.closest('form');
    if (!podeDescartar(document, formEnviado)) ev.preventDefault();
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
  // O histórico do HTMX troca HTML sem disparar beforeunload. Navegadores com
  // Navigation API permitem cancelar Voltar/Avançar antes de mudar URL ou DOM.
  if (window.navigation) {
    window.navigation.addEventListener('navigate', ev => {
      if (ev.navigationType !== 'traverse' || !ev.destination.sameDocument || !ev.cancelable) return;
      if (!podeDescartar(document)) ev.preventDefault();
    });
  } else {
    // Sem cancelamento antecipado do histórico, o PDV precisa de um documento
    // próprio. Assim Voltar passa por beforeunload e conserva o carrinho se a
    // pessoa cancelar. O GET nativo também atende links externos ao menu.
    document.addEventListener('htmx:configRequest', ev => {
      if (ev.detail.verb !== 'get' || ev.detail.target?.id !== 'conteudo') return;
      const entrada = document.querySelector('[data-pdv-entrada]');
      if (!entrada) return;
      const destino = new URL(ev.detail.path, location.href);
      const pdv = new URL(entrada.href, location.href);
      if (destino.origin !== pdv.origin || destino.pathname !== pdv.pathname) return;
      ev.preventDefault();
      // htmx:confirm já autorizou descartar o formulário anterior, se existia.
      limpar(document);
      location.assign(destino.href);
    });
  }
  window.EdicaoPendente = { podeDescartar, limpar };
  window.fecharEdicao = function (el) {
    if (el.closest('#modal-conteudo')) { window.fecharModal(); return; }
    const ficha = el.closest('[data-voltar]');
    if (ficha && podeDescartar(ficha)) {
      limpar(ficha); window.location.href = ficha.dataset.voltar;
    }
  };
})();
