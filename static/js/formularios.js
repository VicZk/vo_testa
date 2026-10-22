/* Mantém o formulário original até o servidor confirmar o resultado. */
(function () {
  'use strict';
  const seletor = 'form[data-preservar-erros]';
  function aviso(form, mensagens) {
    let caixa = form.querySelector('[data-erros-envio]');
    if (!caixa) {
      caixa = document.createElement('div');
      caixa.className = 'mensagem error';
      caixa.dataset.errosEnvio = '';
      caixa.setAttribute('role', 'alert');
      caixa.setAttribute('tabindex', '-1');
      form.prepend(caixa);
    }
    caixa.replaceChildren();
    mensagens.forEach(texto => {
      const p = document.createElement('p');
      p.textContent = texto;
      caixa.appendChild(p);
    });
    let pai = form.parentElement;
    while (pai) { if (pai.tagName === 'DETAILS') pai.open = true; pai = pai.parentElement; }
    form.dataset.dirty = '1';
    caixa.focus({preventScroll: true});
    caixa.scrollIntoView({block: 'nearest', behavior: 'auto'});
  }
  function preparar(raiz) {
    const forms = Array.from(raiz.querySelectorAll(seletor));
    if (raiz.matches && raiz.matches(seletor)) forms.push(raiz);
    forms.forEach(form => form.setAttribute('data-edicao-pendente', ''));
  }
  document.addEventListener('submit', async ev => {
    const form = ev.target;
    if (!form.matches(seletor) || ev.defaultPrevented || form.hasAttribute('hx-post')) return;
    const origem = new URL(form.action || location.href, location.href);
    if (origem.origin !== location.origin || form.method.toLowerCase() !== 'post') return;
    ev.preventDefault();
    if (form.dataset.enviando === '1') return;
    if (window.EdicaoPendente && !EdicaoPendente.podeDescartar(document, form)) return;
    const dados = new FormData(form);
    if (ev.submitter && ev.submitter.name) dados.append(ev.submitter.name, ev.submitter.value);
    form.querySelectorAll('.mascara-reais[name]').forEach(campo => {
      if (!campo.disabled && campo.value) dados.set(campo.name, campo.value.replace(/\./g, '').replace(',', '.'));
    });
    const botoes = Array.from(form.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"]'));
    const estados = botoes.map(botao => botao.disabled);
    form.dataset.enviando = '1';
    form.setAttribute('aria-busy', 'true');
    botoes.forEach(botao => { botao.disabled = true; });
    const erroAntigo = form.querySelector('[data-erros-envio]');
    if (erroAntigo) erroAntigo.remove();
    const controle = new AbortController();
    const limite = setTimeout(() => controle.abort(), 45000);
    try {
      const resposta = await fetch(origem.href, {method: 'POST', body: dados,
        signal: controle.signal, credentials: 'same-origin', headers: {'X-Form-Preserve': '1', 'Accept': 'application/json'}});
      const json = (resposta.headers.get('Content-Type') || '').includes('application/json') ? await resposta.json() : null;
      if (resposta.ok && json && json.redirect) {
        if (window.EdicaoPendente) EdicaoPendente.limpar(document);
        location.assign(json.redirect);
        return;
      }
      if (json && Array.isArray(json.errors)) {
        aviso(form, json.errors);
      } else {
        aviso(form, [resposta.status === 403
          ? 'A sessão expirou ou você não tem permissão para esta ação. Seus dados continuam neste formulário.'
          : 'Não foi possível confirmar o envio. Seus dados continuam aqui. Confira o resultado antes de reenviar.']);
      }
    } catch (_) {
      aviso(form, ['Não foi possível confirmar o envio. Seus dados continuam aqui. Confira a conexão e o resultado da operação antes de reenviar.']);
    } finally {
      clearTimeout(limite);
      delete form.dataset.enviando;
      form.removeAttribute('aria-busy');
      botoes.forEach((botao, i) => { botao.disabled = estados[i]; });
    }
  });
  preparar(document);
  document.addEventListener('htmx:afterSwap', ev => preparar(ev.detail.target));
  document.addEventListener('htmx:afterRequest', ev => {
    const form = ev.detail.elt && ev.detail.elt.closest('form[data-preservar-erros-hx]');
    if (!form) return;
    const xhr = ev.detail.xhr;
    let gatilhos = {};
    try { gatilhos = JSON.parse(xhr.getResponseHeader('HX-Trigger') || '{}'); } catch (_) { /* Sem aviso estruturado. */ }
    if (gatilhos.aviso && gatilhos.aviso.tipo === 'error') {
      aviso(form, [gatilhos.aviso.texto]);
    } else if (ev.detail.failed) {
      aviso(form, ['Não foi possível confirmar o envio. Seus dados continuam aqui. Confira o resultado antes de reenviar.']);
    }
  });
})();
