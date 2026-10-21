/* Dicas (balão de hover) — um motor só para todo [data-dica] do CRM.
 *
 * Antes a dica era um ::after dentro do próprio elemento: centrada na CAIXA dele (uma
 * célula larga do mapa punha o balão longe do que se via), cortada por qualquer
 * contêiner com overflow (a tabela do mapa, a coluna de Pessoas) e sem limite na borda
 * da tela (o selo de status do detalhe da reserva vazava à direita). O Marketing e a
 * ficha de campanha tinham motores próprios, cada um com outra cara, e o menu
 * recolhido usava o `title` do navegador (1 s de espera, colado no cursor).
 *
 * Agora: um balão fixo por cima de tudo (#dica-flutuante), centrado no que se vê —
 * ou no ponteiro, quando o elemento é largo (barra do calendário, célula comprida do
 * mapa) —, em cima quando cabe e embaixo quando não, sempre dentro da tela, com a
 * seta apontando para o elemento mesmo quando o balão encosta na borda.
 *
 * Variantes pelo próprio elemento:
 *   data-dica-lado="direita"   ao lado, centrado na altura (menu recolhido)
 *   .porta (corredor)          cartão: texto à esquerda, várias linhas, embaixo
 */
(function () {
  if (window.__dicas) return;            // uma vez só (sobrevive aos swaps do HTMX)
  window.__dicas = true;

  var MARGEM = 8, DISTANCIA = 8, LARGO = 260;
  var balao = null, alvo = null, pontoX = null, toqueTimer = null;

  function criar() {
    if (balao && balao.isConnected) return balao;
    balao = document.createElement('div');
    balao.id = 'dica-flutuante';
    balao.className = 'dica-flutuante';
    balao.setAttribute('role', 'tooltip');
    balao.hidden = true;
    document.body.appendChild(balao);
    return balao;
  }

  function textoDe(el) {
    var t = el.getAttribute('data-dica');
    return t ? t.trim() : '';
  }

  // A parte visível do elemento: o recorte da tela (e de quem rola por dentro).
  function visivel(el) {
    var r = el.getBoundingClientRect();
    var esq = Math.max(r.left, 0), dir = Math.min(r.right, innerWidth);
    var cima = Math.max(r.top, 0), baixo = Math.min(r.bottom, innerHeight);
    var p = el.parentElement;
    while (p && p !== document.body) {
      var cs = getComputedStyle(p);
      if (/(auto|scroll|hidden|clip)/.test(cs.overflowX + cs.overflowY)) {
        var pr = p.getBoundingClientRect();
        esq = Math.max(esq, pr.left); dir = Math.min(dir, pr.right);
        cima = Math.max(cima, pr.top); baixo = Math.min(baixo, pr.bottom);
      }
      p = p.parentElement;
    }
    return { left: esq, right: dir, top: cima, bottom: baixo,
             width: Math.max(0, dir - esq), height: Math.max(0, baixo - cima) };
  }

  function posicionar() {
    if (!alvo || !balao) return;
    var r = visivel(alvo);
    if (!r.width || !r.height) { esconder(); return; }
    var b = balao.getBoundingClientRect();
    var w = b.width, h = b.height, x, y, lado;

    if (alvo.getAttribute('data-dica-lado') === 'direita') {
      x = r.right + DISTANCIA;
      y = r.top + r.height / 2 - h / 2;
      lado = 'direita';
      if (x + w > innerWidth - MARGEM) { x = r.left - DISTANCIA - w; lado = 'esquerda'; }
      y = Math.min(Math.max(y, MARGEM), innerHeight - h - MARGEM);
      balao.style.setProperty('--seta-y', (r.top + r.height / 2 - y) + 'px');
    } else {
      // Centro: o do que se vê; num elemento largo, o do ponteiro (limitado a ele).
      var centro = r.left + r.width / 2;
      if (r.width > LARGO && pontoX !== null) centro = Math.min(Math.max(pontoX, r.left + 12), r.right - 12);
      var cartao = alvo.classList.contains('porta');
      var cabeEmCima = r.top - DISTANCIA - h >= MARGEM;
      lado = (!cartao && cabeEmCima) ? 'cima' : 'baixo';
      if (lado === 'baixo' && r.bottom + DISTANCIA + h > innerHeight - MARGEM && cabeEmCima) lado = 'cima';
      y = lado === 'cima' ? r.top - DISTANCIA - h : r.bottom + DISTANCIA;
      x = centro - w / 2;
      x = Math.min(Math.max(x, MARGEM), innerWidth - w - MARGEM);
      balao.style.setProperty('--seta-x', Math.min(Math.max(centro - x, 12), w - 12) + 'px');
    }
    balao.dataset.lado = lado;
    balao.style.left = Math.round(x) + 'px';
    balao.style.top = Math.round(y) + 'px';
  }

  function mostrar(el) {
    var texto = textoDe(el);
    if (!texto) return;
    criar();
    if (alvo && alvo !== el) alvo.removeAttribute('aria-describedby');
    alvo = el;
    balao.textContent = texto;
    balao.classList.toggle('cartao', el.classList.contains('porta'));
    balao.hidden = false;
    balao.classList.remove('visivel');
    posicionar();
    el.setAttribute('aria-describedby', 'dica-flutuante');
    requestAnimationFrame(function () { if (alvo === el) balao.classList.add('visivel'); });
  }

  function esconder() {
    if (alvo) alvo.removeAttribute('aria-describedby');
    alvo = null; pontoX = null;
    if (toqueTimer) { clearTimeout(toqueTimer); toqueTimer = null; }
    if (balao) { balao.classList.remove('visivel'); balao.hidden = true; }
  }

  function dono(evento) {
    var t = evento.target;
    return t && t.closest ? t.closest('[data-dica]') : null;
  }

  document.addEventListener('pointerover', function (e) {
    if (e.pointerType === 'touch') return;
    var el = dono(e);
    if (!el || !textoDe(el)) return;
    pontoX = e.clientX;
    if (el !== alvo) mostrar(el);
  }, { passive: true });

  document.addEventListener('pointermove', function (e) {
    if (!alvo || e.pointerType === 'touch') return;
    if (alvo.getBoundingClientRect().width > LARGO) { pontoX = e.clientX; posicionar(); }
  }, { passive: true });

  document.addEventListener('pointerout', function (e) {
    if (!alvo || e.pointerType === 'touch') return;
    var para = e.relatedTarget;
    if (!para || !alvo.contains(para)) esconder();
  }, { passive: true });

  // No toque não há hover: um toque mostra a dica por um instante.
  document.addEventListener('pointerdown', function (e) {
    if (e.pointerType !== 'touch') { if (alvo && !alvo.contains(e.target)) esconder(); return; }
    var el = dono(e);
    if (!el || !textoDe(el)) { esconder(); return; }
    pontoX = e.clientX;
    mostrar(el);
    if (toqueTimer) clearTimeout(toqueTimer);
    toqueTimer = setTimeout(esconder, 2500);
  }, { passive: true });

  document.addEventListener('focusin', function (e) {
    var el = dono(e);
    if (el && el.matches(':focus-visible')) { pontoX = null; mostrar(el); }
  });
  // Só o que mexe no PRÓPRIO elemento esconde a dica: um aviso que some, um campo que
  // perde o foco ou uma lista que rola em outro canto da tela não têm nada com ela.
  document.addEventListener('focusout', function (e) {
    if (alvo && (e.target === alvo || alvo.contains(e.target))) esconder();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') esconder(); });
  addEventListener('scroll', function (e) {
    if (!alvo) return;
    var t = e.target;
    if (t === document || t === document.documentElement || (t.contains && t.contains(alvo))) esconder();
  }, { capture: true, passive: true });
  addEventListener('resize', esconder, { passive: true });
  // A troca do HTMX só esconde a dica quando vai substituir o próprio elemento: o
  // painel carrega blocos logo depois de abrir, e isso não tem nada com o menu.
  document.addEventListener('htmx:beforeSwap', function (e) {
    var t = e.detail && e.detail.target;
    if (alvo && t && (t === alvo || t.contains(alvo))) esconder();
  });
  document.addEventListener('htmx:afterSwap', function () {
    if (alvo && !alvo.isConnected) esconder();
  });
})();
