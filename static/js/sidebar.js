/* Posição do menu é da aba, não da página aberta dentro de um módulo. */
(() => {
  'use strict';

  // O histórico antigo guardava o body inteiro; agora só guarda #conteudo.
  // Descartar esse cache uma vez evita inserir outro menu dentro do conteúdo
  // ao voltar para uma página aberta antes desta versão. Preferências ficam.
  try {
    const raiz = document.getElementById('menu-principal');
    const versao = raiz && `${raiz.dataset.rolagemChave}:historico`;
    if (versao && localStorage.getItem(versao) !== 'conteudo-v1') {
      localStorage.removeItem('htmx-history-cache');
      localStorage.setItem(versao, 'conteudo-v1');
    }
  } catch (_) { /* Histórico é opcional quando o armazenamento está bloqueado. */ }

  // O histórico do HTMX pode recriar o body e executar o script novamente.
  // Há um controlador por documento; cada nav antigo solta seus observadores.
  if (window.votestaSidebar) {
    window.votestaSidebar.atualizar();
    return;
  }

  const memoria = new Map();
  let menu = null, sidebar = null, chave = '';
  let restauro = null, observador = null;
  let quadro = 0, quadroSalvar = 0, quadroFinal = 0;
  let fontesProntas = !document.fonts;
  const escutasMenu = [];

  function lerPosicao() {
    if (!chave) return null;
    try {
      const salvo = sessionStorage.getItem(chave);
      if (salvo !== null && salvo.trim() !== '') {
        const numero = Number(salvo);
        if (Number.isFinite(numero) && numero >= 0) return numero;
      }
    } catch (_) {
      // Bloqueio de armazenamento não impede a navegação nem o alinhamento.
    }
    return memoria.has(chave) ? memoria.get(chave) : null;
  }

  function salvarPosicao() {
    if (!menu || !menu.isConnected || !chave) return;
    // Uma fonte ainda carregando pode limitar temporariamente o scrollTop.
    const top = restauro ? restauro.top : Math.max(0, menu.scrollTop);
    memoria.set(chave, top);
    try { sessionStorage.setItem(chave, String(top)); } catch (_) { /* Aba privada. */ }
  }

  function agendarSalvamento() {
    if (quadroSalvar) return;
    quadroSalvar = requestAnimationFrame(() => {
      quadroSalvar = 0;
      salvarPosicao();
    });
  }

  function medirBarra() {
    if (!menu || !menu.isConnected || !sidebar) return;
    // Barras sobrepostas medem zero; Windows pode reservar largura real.
    const largura = Math.max(0, menu.offsetWidth - menu.clientWidth) + 'px';
    if (sidebar.style.getPropertyValue('--menu-scrollbar') !== largura) {
      sidebar.style.setProperty('--menu-scrollbar', largura);
    }
  }

  function aplicarPosicao() {
    if (!restauro || !menu || !menu.isConnected) return;
    const limite = Math.max(0, menu.scrollHeight - menu.clientHeight);
    menu.scrollTop = Math.min(restauro.top, limite);
    restauro.aplicada = menu.scrollTop;
  }

  function finalizarRestauro() {
    if (!restauro || !fontesProntas || document.readyState !== 'complete') return;
    if (quadroFinal) cancelAnimationFrame(quadroFinal);
    const atual = restauro;
    // Duas pinturas deixam fonte e dimensões finais participarem da medida.
    quadroFinal = requestAnimationFrame(() => {
      quadroFinal = requestAnimationFrame(() => {
        quadroFinal = 0;
        if (restauro !== atual) return;
        aplicarPosicao();
        restauro = null;
        salvarPosicao();
      });
    });
  }

  function ajustar() {
    if (quadro) return;
    quadro = requestAnimationFrame(() => {
      quadro = 0;
      medirBarra();
      aplicarPosicao();
      finalizarRestauro();
    });
  }

  function interromperRestauro() {
    restauro = null;
    if (quadroFinal) cancelAnimationFrame(quadroFinal);
    quadroFinal = 0;
  }

  function rolou() {
    // Além de roda/toque/teclado, respeita scroll feito por foco ou outro código.
    // O evento assíncrono do nosso próprio scrollTop não cancela a restauração.
    if (restauro && Math.abs(menu.scrollTop - restauro.aplicada) > 1) {
      interromperRestauro();
    }
    agendarSalvamento();
  }

  function escutarMenu(tipo, funcao, opcoes) {
    menu.addEventListener(tipo, funcao, opcoes);
    escutasMenu.push(() => menu.removeEventListener(tipo, funcao, opcoes));
  }

  function desconectarMenu() {
    salvarPosicao();
    escutasMenu.splice(0).forEach(remover => remover());
    if (observador) observador.disconnect();
    observador = null;
    if (quadro) cancelAnimationFrame(quadro);
    if (quadroSalvar) cancelAnimationFrame(quadroSalvar);
    quadro = quadroSalvar = 0;
    interromperRestauro();
  }

  function atualizar() {
    const novo = document.getElementById('menu-principal');
    if (novo === menu && (!novo || novo.dataset.rolagemChave === chave)) {
      // hx-boost preserva este nav: não reatribuir scroll nem mover o foco.
      ajustar();
      return;
    }
    desconectarMenu();
    menu = novo;
    sidebar = menu && menu.closest('.sidebar');
    chave = menu ? menu.dataset.rolagemChave || '' : '';
    if (!menu) return;

    const top = lerPosicao();
    restauro = top === null ? null : { top, aplicada: menu.scrollTop };
    escutarMenu('scroll', rolou, { passive: true });
    ['wheel', 'touchstart', 'pointerdown'].forEach(tipo => {
      escutarMenu(tipo, interromperRestauro, { passive: true });
    });
    escutarMenu('keydown', interromperRestauro);
    escutarMenu('focusin', interromperRestauro);

    if ('ResizeObserver' in window) {
      observador = new ResizeObserver(ajustar);
      observador.observe(menu);
      if (sidebar) observador.observe(sidebar);
      // O nav tem altura fixa; seus grupos denunciam mudanças de fonte/altura.
      Array.from(menu.children).forEach(grupo => observador.observe(grupo));
    }
    medirBarra();
    aplicarPosicao();
    ajustar();
  }

  window.votestaSidebar = { atualizar };
  window.addEventListener('resize', ajustar, { passive: true });
  window.addEventListener('load', ajustar);
  window.addEventListener('pageshow', evento => {
    atualizar();
    // O BFCache reapresenta um documento vivo, com uma posição mais antiga
    // que a usada na última página da aba. O armazenamento é a referência.
    if (evento.persisted && menu) {
      const top = lerPosicao();
      if (top !== null) {
        restauro = { top, aplicada: menu.scrollTop };
        aplicarPosicao();
        ajustar();
      }
    }
  });
  window.addEventListener('pagehide', salvarPosicao);
  window.addEventListener('popstate', salvarPosicao);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) salvarPosicao();
  });
  document.addEventListener('htmx:beforeSwap', salvarPosicao);
  document.addEventListener('htmx:beforeHistorySave', salvarPosicao);
  document.addEventListener('htmx:afterSwap', atualizar);
  document.addEventListener('htmx:afterSettle', atualizar);
  document.addEventListener('htmx:historyRestore', atualizar);

  if (document.fonts) {
    document.fonts.ready.then(() => {
      fontesProntas = true;
      ajustar();
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', atualizar, { once: true });
  } else {
    atualizar();
  }
})();
