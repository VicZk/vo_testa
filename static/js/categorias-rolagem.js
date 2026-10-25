/* A dica aparece somente quando a faixa de categorias tem conteúdo para rolar. */
(function () {
  'use strict';
  if (window.prepararCategoriasRolagem) {
    window.prepararCategoriasRolagem();
    return;
  }
  const ativos = new Map();
  function preparar() {
    for (const [lista, observadores] of ativos) {
      if (!lista.isConnected) {
        observadores.forEach(observador => observador.disconnect());
        ativos.delete(lista);
      }
    }
    document.querySelectorAll('[data-categorias-lista]').forEach(lista => {
      if (ativos.has(lista)) return;
      const dica = lista.closest('.pdv-produtos').querySelector('[data-categorias-rolagem]');
      if (!dica) return;
      const medir = () => { dica.hidden = lista.scrollWidth - lista.clientWidth <= 2; };
      const tamanho = new ResizeObserver(medir);
      const conteudo = new MutationObserver(medir);
      tamanho.observe(lista);
      conteudo.observe(lista, {childList: true, subtree: true, characterData: true});
      ativos.set(lista, [tamanho, conteudo]);
      medir();
      if (document.fonts) document.fonts.ready.then(medir);
    });
  }
  window.prepararCategoriasRolagem = preparar;
  document.addEventListener('htmx:afterSwap', preparar);
  preparar();
})();
