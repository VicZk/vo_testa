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
  var regioes = new Map();
  var observador = window.ResizeObserver ? new ResizeObserver(atualizarTodas) : null;

  function atualizar(box, dica) {
    if (!box.isConnected) {
      if (observador) observador.unobserve(box);
      if (observador && box.firstElementChild) observador.unobserve(box.firstElementChild);
      regioes.delete(box);
      return;
    }
    var sobra = box.scrollWidth - box.clientWidth;
    var esquerda = box.scrollLeft > 2, direita = box.scrollLeft < sobra - 2;
    dica.hidden = sobra <= 2;
    dica.textContent = esquerda && direita ? '← Mais colunas nos dois lados →' :
      esquerda ? '← Volte para as primeiras colunas' : 'Deslize para ver as demais colunas →';
    box.classList.toggle('rolagem-ampla', sobra > 2);
    if (sobra > 2) {
      if (!box.hasAttribute('tabindex')) box.setAttribute('tabindex', '0');
      if (!box.hasAttribute('role')) box.setAttribute('role', 'region');
      if (!box.hasAttribute('aria-label')) box.setAttribute('aria-label', 'Tabela com rolagem horizontal');
    }
  }

  function atualizarTodas() { regioes.forEach(function (dica, box) { atualizar(box, dica); }); }

  function sinalizar(box) {
    if (regioes.has(box)) return;
    var dica = box.previousElementSibling;
    if (!dica || !dica.classList.contains('rolagem-indicador')) {
      dica = document.createElement('p');
      dica.className = 'rolagem-indicador';
      dica.setAttribute('aria-hidden', 'true');
      dica.hidden = true;
      box.parentNode.insertBefore(dica, box);
    }
    regioes.set(box, dica);
    box.addEventListener('scroll', function () { atualizar(box, dica); }, {passive: true});
    if (observador) {
      observador.observe(box);
      if (box.firstElementChild) observador.observe(box.firstElementChild);
    }
    atualizar(box, dica);
  }

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
      if (jaRola(t.parentElement)) { sinalizar(t.parentElement); continue; }
      var box = document.createElement('div');
      box.className = 'tabela-rol';
      t.parentNode.insertBefore(box, t);
      box.appendChild(t);
      sinalizar(box);
    }
    (raiz || document).querySelectorAll('[data-tabela-ampla], .mapa-rolagem, .escala-grade-wrap, .cal-scroll, .mk-colunas, .mk-ocup-barras').forEach(sinalizar);
    atualizarTodas();
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
  document.addEventListener('htmx:afterSettle', atualizarTodas);
  window.addEventListener('resize', atualizarTodas);
  if (document.fonts) document.fonts.ready.then(atualizarTodas);
})();
