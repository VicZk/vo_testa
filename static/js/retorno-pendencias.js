/* A origem acompanha apenas o fluxo aberto pela Central, inclusive modais e POST. */
(() => {
  'use strict';
  if (window.retornoPendenciasAtivo) return;
  window.retornoPendenciasAtivo = true;
  const PARAMETRO = 'retorno_pendencias';
  const ESCOPO = '#conteudo, #modal-conteudo, #modal-reserva';
  const abertosPelaCentral = new WeakSet();

  function contexto() {
    const conteudo = document.getElementById('conteudo');
    // O histórico HTMX restaura o miolo do main, não seus atributos. O link
    // pertence ao snapshot restaurado e evita herdar a origem da próxima tela.
    const retorno = conteudo?.querySelector('[data-retorno-pendencias-link]')?.getAttribute('href');
    if (!retorno) {
      if (conteudo) delete conteudo.dataset.retornoPendencias;
      return null;
    }
    conteudo.dataset.retornoPendencias = retorno;
    return {retorno, raiz: conteudo.dataset.crmRaiz, central: new URL(retorno, location.origin).pathname};
  }
  function destino(valor, ctx) {
    if (!ctx || !valor || valor.startsWith('#')) return null;
    let url;
    try { url = new URL(valor, location.href); } catch (_) { return null; }
    if (url.origin !== location.origin || !url.pathname.startsWith(ctx.raiz) ||
        url.pathname.startsWith(ctx.central) || /\/(?:entrar|sair)\/$/.test(url.pathname)) return null;
    url.searchParams.set(PARAMETRO, ctx.retorno);
    return url.pathname + url.search + url.hash;
  }
  function preparar() {
    const ctx = contexto();
    if (!ctx) return;
    document.querySelectorAll('#conteudo a[href], #modal-conteudo a[href], #modal-reserva a[href]').forEach(link => {
      if (link.hasAttribute('download') || link.hasAttribute('data-retorno-pendencias-link')) return;
      const url = destino(link.getAttribute('href'), ctx);
      if (url) link.setAttribute('href', url);
    });
    document.querySelectorAll('#conteudo form, #modal-conteudo form, #modal-reserva form').forEach(form => {
      const url = destino(form.getAttribute('action') || location.href, ctx);
      if (!url) return;
      form.setAttribute('action', url);
      let campo = form.querySelector(`input[name="${PARAMETRO}"]`);
      if (!campo) {
        campo = document.createElement('input');
        campo.type = 'hidden'; campo.name = PARAMETRO;
        form.append(campo);
      }
      campo.value = ctx.retorno;
    });
  }
  document.addEventListener('htmx:configRequest', evento => {
    const d = evento.detail, ctx = contexto();
    if (!ctx || !d.elt?.closest(ESCOPO) || d.elt.closest('[data-retorno-pendencias-link]')) return;
    const url = destino(d.path, ctx);
    if (!url) return;
    d.path = url;
  });
  document.addEventListener('submit', preparar, true);
  document.addEventListener('htmx:beforeRequest', evento => {
    const d = evento.detail;
    // A lista pode atualizar/remover a linha enquanto a resposta está em voo.
    // Registre a origem antes disso, vinculada à requisição que a abriu.
    if (d.target?.id === 'conteudo' && d.xhr && d.elt?.closest('[data-central-pendencias]')) {
      abertosPelaCentral.add(d.xhr);
    }
  });
  document.addEventListener('htmx:afterSwap', evento => {
    preparar();
    // Uma linha da lista pode estar abaixo da dobra. Ao abrir seu destino,
    // apresente o título e o retorno, em vez da posição de rolagem da lista.
    if (evento.detail.target?.id === 'conteudo' && contexto() &&
        evento.detail.xhr && abertosPelaCentral.has(evento.detail.xhr)) {
      window.scrollTo({top: 0, left: 0, behavior: 'instant'});
    }
  });
  document.addEventListener('htmx:historyRestore', preparar);
  document.addEventListener('DOMContentLoaded', preparar, {once: true});
  if (document.readyState !== 'loading') preparar();
})();
