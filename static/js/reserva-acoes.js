/* Ações da estadia: melhoria progressiva, sem interpretar expressões em HTML. */
(function () {
  'use strict';
  const seletor = '[data-reserva-acoes]';
  const estados = new WeakMap();

  function preparar(raiz) {
    const blocos = Array.from(raiz.querySelectorAll(seletor));
    if (raiz.matches && raiz.matches(seletor)) blocos.push(raiz);
    blocos.forEach(bloco => {
      if (estados.has(bloco)) return;
      const paineis = Array.from(bloco.querySelectorAll('.acao-painel'));
      const restaurado = bloco.dataset.reservaPronta === '1';
      if (!restaurado) paineis.forEach(painel => { painel.hidden = true; });
      const aberto = paineis.find(painel => !painel.hidden);
      const botoes = Array.from(bloco.querySelectorAll('[data-acao]'));
      botoes.forEach(botao => {
        botao.hidden = false;
        const ativo = !!aberto && botao.getAttribute('aria-controls') === aberto.id;
        botao.setAttribute('aria-expanded', String(ativo));
        botao.classList.toggle('acao-ligada', ativo);
      });
      bloco.querySelectorAll('[data-fechar-acao]').forEach(botao => { botao.hidden = false; });
      estados.set(bloco, {paineis, botoes, aberto, acionador: null});
      bloco.dataset.reservaPronta = '1';
    });
  }

  function fechar(bloco, devolverFoco) {
    const estado = estados.get(bloco);
    if (!estado || !estado.aberto) return;
    estado.aberto.hidden = true;
    estado.aberto = null;
    estado.botoes.forEach(botao => {
      botao.setAttribute('aria-expanded', 'false');
      botao.classList.remove('acao-ligada');
    });
    if (devolverFoco && estado.acionador) {
      const grupo = estado.acionador.closest('details');
      if (grupo) grupo.open = true;
      estado.acionador.focus({preventScroll: true});
      estado.acionador.scrollIntoView({block: 'nearest', behavior: 'auto'});
    }
  }

  document.addEventListener('click', ev => {
    const botao = ev.target.closest('[data-acao], [data-fechar-acao]');
    if (!botao) return;
    const bloco = botao.closest(seletor);
    if (!bloco) return;
    preparar(bloco);
    const estado = estados.get(bloco);
    if (botao.hasAttribute('data-fechar-acao')) { fechar(bloco, true); return; }
    const painel = estado.paineis.find(item => item.id === botao.getAttribute('aria-controls'));
    if (!painel) return;
    const eraAberto = estado.aberto === painel;
    fechar(bloco, false);
    if (eraAberto) return;
    painel.hidden = false;
    estado.aberto = painel;
    estado.acionador = botao;
    botao.setAttribute('aria-expanded', 'true');
    botao.classList.add('acao-ligada');
    const titulo = painel.querySelector('.acao-painel-titulo');
    if (titulo) titulo.focus({preventScroll: true});
    painel.scrollIntoView({block: 'nearest', behavior: 'auto'});
  });
  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape' || ev.defaultPrevented) return;
    const bloco = ev.target.closest(seletor);
    if (!bloco || !estados.get(bloco)?.aberto) return;
    ev.preventDefault();
    fechar(bloco, true);
  });
  preparar(document);
  document.addEventListener('htmx:afterSwap', ev => preparar(ev.detail.target));
  document.addEventListener('htmx:historyRestore', () => preparar(document));
  window.addEventListener('pageshow', () => preparar(document));
})();
