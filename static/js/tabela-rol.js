/* Invólucro rolante das tabelas de dados (.tabela).
 *
 * Quem rola é o <div class="tabela-rol">, nunca o <table>: `display:block` num
 * <table> desmonta o layout de tabela (as colunas grudadas com position:sticky
 * passam a brigar com a caixa anônima que o navegador cria). Como são ~55 telas
 * com tabela, o invólucro nasce aqui em vez de ser repetido em cada template —
 * e vale em qualquer largura, sem a faixa 641–820px que ficava sem tratamento.
 *
 * Roda no carregamento e em cada troca do HTMX (hx-boost, partials).
 */
(function () {
  if (window.__tabelaRol) return;          // uma vez só (sobrevive aos swaps)
  window.__tabelaRol = true;

  function jaRola(el) {
    if (!el || el === document.body) return false;
    if (el.classList.contains('tabela-rol')) return true;
    var ox = getComputedStyle(el).overflowX;
    return ox === 'auto' || ox === 'scroll';
  }

  function embrulhar(raiz) {
    var tabelas = (raiz || document).querySelectorAll('table.tabela');
    for (var i = 0; i < tabelas.length; i++) {
      var t = tabelas[i];
      if (jaRola(t.parentElement)) continue;
      var box = document.createElement('div');
      box.className = 'tabela-rol';
      t.parentNode.insertBefore(box, t);
      box.appendChild(t);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { embrulhar(document); });
  } else {
    embrulhar(document);
  }
  // No `document` (não no body): este arquivo pode carregar antes do <body> existir.
  document.addEventListener('htmx:load', function (e) {
    if (e.target && e.target.querySelectorAll) embrulhar(e.target);
  });
})();
