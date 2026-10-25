/* O menu pertence ao documento; grupos e rolagem pertencem à aba. */
(() => {
  'use strict';
  if (window.votestaSidebar) return;
  const menu = document.getElementById('menu-principal');
  if (!menu) return;
  const chave = menu.dataset.rolagemChave;
  let trava = null;
  function salvar() {
    try { sessionStorage.setItem(chave, String(Math.max(0, menu.scrollTop))); } catch (_) {}
  }
  function marcarAtivo() {
    const conteudo = document.getElementById('conteudo');
    // O cache HTMX restaura os filhos, não os atributos do elemento histórico.
    const contexto = conteudo?.querySelector('[data-nav-contexto]');
    if (contexto) {
      if ('conteudoClasse' in contexto.dataset) conteudo.className = contexto.dataset.conteudoClasse;
      else contexto.dataset.conteudoClasse = conteudo.className;
    }
    const ativa = contexto?.dataset.navContexto ?? conteudo?.dataset.navAtiva;
    if (conteudo && ativa !== undefined) conteudo.dataset.navAtiva = ativa;
    const anterior = menu.querySelector('[data-nav].ativo')?.dataset.nav;
    menu.querySelectorAll('[data-nav]').forEach(item => {
      const selecionado = !!ativa && item.dataset.nav === ativa;
      item.classList.toggle('ativo', selecionado);
      const link = item.matches('a') ? item : item.querySelector('.nav-item-principal');
      if (selecionado) link?.setAttribute('aria-current', 'page');
      else link?.removeAttribute('aria-current');
    });
  }
  function atualizar(evento) {
    if (evento?.type === 'htmx:afterSwap' && evento.detail.target?.id !== 'conteudo') return;
    marcarAtivo();
    atualizarPista();
  }
  function travarPagina() {
    if (trava) return;
    const corpo = document.body;
    trava = {x: window.scrollX, y: window.scrollY, estilo: corpo.getAttribute('style')};
    Object.assign(corpo.style, {position: 'fixed', top: -trava.y + 'px', left: -trava.x + 'px', width: '100%'});
  }
  function soltarPagina() {
    if (!trava) return;
    const anterior = trava;
    trava = null;
    if (anterior.estilo === null) document.body.removeAttribute('style');
    else document.body.setAttribute('style', anterior.estilo);
    window.scrollTo({left: anterior.x, top: anterior.y, behavior: 'instant'});
  }
  window.votestaSidebar = {atualizar, marcarAtivo, travarPagina, soltarPagina};
  function atualizarPista() {
    menu.toggleAttribute("data-mais-abaixo", menu.scrollHeight - menu.clientHeight - menu.scrollTop > 2);
  }
  function atualizarBarra() {
    atualizarPista();
    const largura = Math.max(0, menu.offsetWidth - menu.clientWidth) + 'px';
    const sidebar = menu.closest('.sidebar');
    if (sidebar.style.getPropertyValue('--menu-scrollbar') !== largura) {
      sidebar.style.setProperty('--menu-scrollbar', largura);
    }
  }
  // O bootstrap mede antes da pintura; aqui só acompanha mudança real da barra
  // (preferência do sistema, redimensionamento ou modo sobreposto).
  if (window.ResizeObserver) new ResizeObserver(atualizarBarra).observe(menu);
  else window.addEventListener('resize', atualizarBarra);
  // Só o bootstrap inline restaura scrollTop, antes da primeira pintura.
  // Nunca repetir no DOMContentLoaded, load ou ao trocar abas.
  menu.addEventListener('scroll', () => { salvar(); atualizarPista(); }, {passive: true});
  window.addEventListener('pagehide', salvar);
  window.addEventListener('pageshow', evento => {
    if (!evento.persisted) return;
    // No BFCache o DOM já existe: a aba pode ter guardado outra posição.
    try { menu.scrollTop = Math.max(0, Number(sessionStorage.getItem(chave)) || 0); } catch (_) {}
    atualizarPista();
  });
  document.addEventListener('htmx:beforeHistorySave', salvar);
  document.addEventListener('htmx:afterSwap', atualizar);
  document.addEventListener('htmx:historyRestore', atualizar, true);
  try {
    if (localStorage.getItem(chave + ':historico') !== 'conteudo-v3') {
      localStorage.removeItem('htmx-history-cache');
      localStorage.setItem(chave + ':historico', 'conteudo-v3');
    }
  } catch (_) {}
  atualizar();
})();
