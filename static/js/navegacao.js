/* A navegação anima só o conteúdo; menu e barra superior permanecem no lugar. */
(() => {
  'use strict';
  if (window.votestaNavegacao) return;
  window.votestaNavegacao = true;

  const reduzMovimento = matchMedia('(prefers-reduced-motion: reduce)');
  const trocasNativas = new WeakSet();
  let entrada = null;
  let quadroAbas = null;

  function mostrarAba(aba) {
    const faixa = aba?.closest('.abas-secao');
    if (!faixa || faixa.scrollWidth <= faixa.clientWidth) return;
    const limite = faixa.getBoundingClientRect();
    const item = aba.getBoundingClientRect();
    // scrollIntoView também deslocaria a página. Só a faixa pode se mover.
    if (item.left < limite.left) faixa.scrollLeft += item.left - limite.left;
    else if (item.right > limite.right) faixa.scrollLeft += item.right - limite.right;
  }

  function atualizarAbas() {
    if (quadroAbas !== null) cancelAnimationFrame(quadroAbas);
    quadroAbas = requestAnimationFrame(() => {
      quadroAbas = null;
      document.querySelectorAll('.abas-secao [aria-current="page"], .abas-secao .ativo')
        .forEach(mostrarAba);
    });
  }

  function cancelarEntrada() {
    if (entrada) entrada.cancel();
    entrada = null;
  }

  function animarConteudo() {
    cancelarEntrada();
    const conteudo = document.getElementById('conteudo');
    if (!conteudo || reduzMovimento.matches || !conteudo.animate) return;
    const estilo = getComputedStyle(conteudo);
    const token = estilo.getPropertyValue('--mov-padrao').trim();
    const duracao = parseFloat(token) * (token.endsWith('ms') ? 1 : 1000);
    entrada = conteudo.animate([{ opacity: 0 }, { opacity: 1 }], {
      duration: Number.isFinite(duracao) ? duracao : 240,
      easing: estilo.getPropertyValue('--curva-entrada').trim() || 'ease-out',
    });
  }

  document.addEventListener('htmx:beforeRequest', evento => {
    if (evento.detail.target?.id === 'conteudo') cancelarEntrada();
  });

  document.addEventListener('htmx:beforeTransition', evento => {
    if (evento.detail.target?.id !== 'conteudo') return;
    // A preferência vale também para o caminho HTMX, não apenas @view-transition.
    const gavetaAberta = matchMedia('(max-width: 820px)').matches
      && document.getElementById('app')?.classList.contains('sidebar-aberta');
    // Capturar a gaveta enquanto ela fecha congela uma imagem no meio do
    // caminho. No celular o menu continua vivo e só o conteúdo recebe o fade.
    if (reduzMovimento.matches || gavetaAberta) {
      evento.preventDefault();
    } else if (document.startViewTransition && evento.detail.xhr) {
      trocasNativas.add(evento.detail.xhr);
    }
  });

  document.addEventListener('htmx:afterSwap', evento => {
    if (evento.detail.target?.id !== 'conteudo') return;
    // O topo pertence à troca, não ao settle atrasado: se a pessoa já voltou,
    // esse callback antigo não pode sobrescrever a rolagem do histórico.
    if (evento.detail.requestConfig?.elt?.closest('#menu-principal')) {
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    }
    const pedido = evento.detail.xhr;
    if (pedido && trocasNativas.has(pedido)) return;
    animarConteudo();
  });

  // O HTMX restaura o histórico sem passar por beforeTransition/afterSwap.
  document.addEventListener('htmx:historyRestore', animarConteudo);
  document.addEventListener('htmx:afterSettle', atualizarAbas);
  document.addEventListener('htmx:historyRestore', atualizarAbas);
  document.addEventListener('focusin', evento => {
    if (evento.target.matches('.abas-secao a')) mostrarAba(evento.target);
  });
  window.addEventListener('resize', atualizarAbas);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', atualizarAbas, { once: true });
  } else atualizarAbas();
  document.fonts?.ready.then(atualizarAbas);
  reduzMovimento.addEventListener('change', cancelarEntrada);
})();
