/* Links internos trocam o conteúdo, sem reapresentar ou animar todo o shell. */
(() => {
  'use strict';
  if (window.votestaNavegacao) return;
  window.votestaNavegacao = true;
  const movimentoReduzido = matchMedia('(prefers-reduced-motion: reduce)');
  let entradas = [];
  function cancelarEntradas() {
    entradas.forEach(animacao => animacao.cancel());
    entradas = [];
  }
  let conteudoAnterior = null;
  const SEM_PINTURA = 'script, style, template, input[type="hidden"], .rolagem-indicador';
  const REFERENCIA = '#conteudo, .pagina-cabecalho, .abas-secao';
  function retrato(elemento) {
    if (!elemento || elemento.matches(SEM_PINTURA)) return null;
    // O invólucro e a dica de rolagem são adicionados pelo navegador.
    if (elemento.matches('.tabela-rol') && elemento.children.length === 1 &&
        elemento.firstElementChild.matches('table')) return retrato(elemento.firstElementChild);
    const atributos = Array.from(elemento.attributes).filter(({name}) => {
      if (elemento.tagName === 'CANVAS' && ['width', 'height', 'style'].includes(name)) return false;
      if (name === 'data-navegacao-shell' || name.startsWith('data-hx-')) return false;
      if (elemento.dataset.navegacaoShell && name.startsWith('hx-')) return false;
      return true;
    }).map(({name, value}) => [name, name === 'class' ? value.split(/\s+/)
      .filter(classe => classe && !/^htmx-/.test(classe) && classe !== 'rolagem-ampla').sort().join(' ') : value])
      .sort(([a], [b]) => a.localeCompare(b));
    const filhos = Array.from(elemento.children, retrato).filter(Boolean);
    const texto = Array.from(elemento.childNodes).filter(no => no.nodeType === Node.TEXT_NODE)
      .map(no => no.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean).join(' ');
    const propria = JSON.stringify([elemento.tagName, atributos, texto]);
    // Prefixos de comprimento conservam a comparação exata sem reescapar as
    // assinaturas dos descendentes em cada nível de um formulário profundo.
    const assinatura = propria.length + ':' + propria + filhos.map(filho =>
      filho.assinatura.length + ':' + filho.assinatura).join('');
    return {elemento, filhos, assinatura, relevante: !!texto || /^(IMG|CANVAS|INPUT|SELECT|TEXTAREA|VIDEO)$/.test(elemento.tagName) || filhos.some(filho => filho.relevante)};
  }
  function guardarConteudo() { conteudoAnterior = retrato(document.getElementById('conteudo')); }
  function blocosAlterados(atual, anterior) {
    if (!atual || !anterior) return [];
    const anteriores = new Set();
    function indexar(no) {
      if (no.relevante) anteriores.add(no.assinatura);
      no.filhos.forEach(indexar);
    }
    indexar(anterior);
    function comparar(no) {
      if (!no.relevante || anteriores.has(no.assinatura)) return {estavel: no.relevante, blocos: []};
      // Abas e cabeçalhos mantêm a orientação mesmo ao trocar de módulo.
      if (no.elemento.matches('.abas-secao, .pagina-cabecalho')) return {estavel: true, blocos: []};
      const filhos = no.filhos.map(comparar);
      const estavel = filhos.some(filho => filho.estavel);
      if (!estavel && !no.elemento.matches(REFERENCIA)) return {estavel: false, blocos: [no.elemento]};
      return {estavel, blocos: filhos.flatMap(filho => filho.blocos)};
    }
    return comparar(atual).blocos;
  }
  function animarParteNova() {
    cancelarEntradas();
    const anterior = conteudoAnterior;
    conteudoAnterior = null;
    if (movimentoReduzido.matches) return;
    const conteudo = document.getElementById('conteudo');
    if (!conteudo) return;
    const blocos = blocosAlterados(retrato(conteudo), anterior);
    const css = getComputedStyle(conteudo);
    const token = css.getPropertyValue('--mov-rapido').trim();
    const duracao = parseFloat(token) * (token.endsWith('ms') ? 1 : 1000);
    blocos.forEach(bloco => {
      if (!bloco.animate || !bloco.getClientRects().length || bloco.closest('[hidden]')) return;
      const animacao = bloco.animate([{opacity: .92, translate: '0 4px'}, {opacity: 1, translate: '0 0'}], {
        duration: Number.isFinite(duracao) ? duracao : 160,
        easing: css.getPropertyValue('--curva-entrada').trim() || 'ease-out',
      });
      animacao.id = 'navegacao-conteudo-local';
      entradas.push(animacao);
    });
  }
  const NAVEGAR = 'a[href]:not([download]):not([target]):not([onclick]):not([hx-get]):not([hx-post])';
  function elegivel(link) {
    if (link.closest('[hx-boost="false"], [data-navegacao-nativa], #modal-reserva, [role="dialog"]')) return false;
    if (link.hasAttribute('hx-trigger') || link.hasAttribute('hx-target') || link.hasAttribute('data-copiar')) return false;
    const url = new URL(link.href, location.href);
    const raiz = document.getElementById('conteudo')?.dataset.crmRaiz;
    if (!raiz || url.origin !== location.origin || !url.pathname.startsWith(raiz)) return false;
    if (url.hash || /\.(pdf|csv|xlsx?|zip|png|jpe?g)$/i.test(url.pathname)) return false;
    if (url.searchParams.has('export') || url.searchParams.has('imprimir') ||
        /^(csv|pdf|xlsx?)$/i.test(url.searchParams.get('formato') || '')) return false;
    if (/(?:^|\/)(?:sair|logout|download|exportar[^/]*|imprimir[^/]*|recibo|comprovante|extrato|pdf)(?:\/|$)/i.test(url.pathname)) return false;
    return true;
  }
  function preparar() {
    if (!window.htmx) return;
    document.querySelectorAll('#conteudo a[href]').forEach(link => {
      if (!link.matches(NAVEGAR) || !elegivel(link) || link.dataset.navegacaoShell) return;
      link.dataset.navegacaoShell = '1';
      link.setAttribute('hx-boost', 'true');
      link.setAttribute('hx-target', '#conteudo');
      link.setAttribute('hx-select', '#conteudo');
      link.setAttribute('hx-swap', 'outerHTML show:none settle:0');
      link.setAttribute('hx-sync', '#conteudo:replace');
      htmx.process(link);
    });
  }
  function mostrarAba(aba) {
    const faixa = aba?.closest('.abas-secao');
    if (!faixa || faixa.scrollWidth <= faixa.clientWidth) return;
    const limite = faixa.getBoundingClientRect(), item = aba.getBoundingClientRect();
    if (item.left < limite.left) faixa.scrollLeft += item.left - limite.left;
    else if (item.right > limite.right) faixa.scrollLeft += item.right - limite.right;
  }
  function atualizar() {
    preparar();
    document.querySelectorAll('.abas-secao [aria-current="page"], .abas-secao .ativo').forEach(mostrarAba);
  }
  document.addEventListener('htmx:beforeTransition', evento => {
    if (evento.detail.target?.id === 'conteudo') evento.preventDefault();
  });
  document.addEventListener('htmx:beforeRequest', evento => {
    if (evento.detail.target?.id !== 'conteudo') return;
    cancelarEntradas();
    // Restaura scrollY antes de o HTMX salvar a página no histórico. A gaveta
    // usa body fixo e, enquanto aberta, a janela informa scrollY igual a zero.
    window.fecharSidebarMobile?.();
  });
  document.addEventListener('htmx:beforeSwap', evento => {
    const d = evento.detail;
    if (d.target?.id !== 'conteudo' || !d.xhr || !d.shouldSwap) return;
    if (d.requestConfig?.verb && d.requestConfig.verb !== 'get') return;
    const pagina = new DOMParser().parseFromString(d.serverResponse, 'text/html');
    // Login expirado, impressão e anexos conservam seu documento inteiro.
    if (!pagina.querySelector('#conteudo[data-crm-raiz]')) {
      d.shouldSwap = false;
      window.EdicaoPendente?.limpar(document);
      location.assign(d.xhr.responseURL || d.requestConfig.path);
      return;
    }
    // Troca de usuário/permissões exige renovar também a navegação autorizada.
    const menuAtual = document.getElementById('menu-principal');
    const menuNovo = pagina.getElementById('menu-principal');
    const chaves = menu => Array.from(menu?.querySelectorAll('[data-nav]') || [], el => el.dataset.nav).join('|');
    if (menuNovo?.dataset.rolagemChave !== menuAtual?.dataset.rolagemChave || chaves(menuNovo) !== chaves(menuAtual)) {
      d.shouldSwap = false;
      window.EdicaoPendente?.limpar(document);
      location.assign(d.xhr.responseURL);
      return;
    }
    // Scripts específicos atuais ficam dentro do conteúdo. Uma dependência
    // nova no head pede documento completo para preservar sua ordem de execução.
    const existentes = new Set(Array.from(document.head.querySelectorAll('script[src], link[rel="stylesheet"]'), el => el.src || el.href));
    const desconhecido = Array.from(pagina.head.querySelectorAll('script[src], link[rel="stylesheet"]'))
      .some(el => !existentes.has(el.src || el.href));
    const inline = new Set(Array.from(document.head.querySelectorAll('script:not([src]), style'), el => el.textContent));
    const inlineDesconhecido = Array.from(pagina.head.querySelectorAll('script:not([src]), style'))
      .some(el => !inline.has(el.textContent));
    if (desconhecido || inlineDesconhecido) {
      d.shouldSwap = false;
      window.EdicaoPendente?.limpar(document);
      location.assign(d.xhr.responseURL);
      return;
    }
    guardarConteudo();
  });
  document.addEventListener('htmx:afterSwap', evento => {
    atualizar();
    if (evento.detail.target?.id !== 'conteudo') return;
    window.fecharSidebarMobile?.();
    if (evento.detail.requestConfig?.elt?.closest('#menu-principal')) {
      window.scrollTo({top: 0, left: 0, behavior: 'instant'});
    }
    animarParteNova();
    if (evento.detail.xhr?.responseText) {
      const pagina = new DOMParser().parseFromString(evento.detail.xhr.responseText, 'text/html');
      pagina.querySelectorAll('#toasts .toast').forEach(aviso => {
        const tipo = (aviso.className.match(/toast-(success|error|warning|info)/) || [, 'info'])[1];
        window.toast?.(aviso.querySelector('.toast-txt')?.textContent || '', tipo);
      });
    }
  });
  window.addEventListener('popstate', guardarConteudo, true);
  document.addEventListener('htmx:beforeHistorySave', guardarConteudo);
  document.addEventListener('htmx:historyRestore', atualizar);
  document.addEventListener('htmx:historyRestore', animarParteNova);
  document.addEventListener('htmx:afterSettle', atualizar);
  document.addEventListener('focusin', evento => {
    if (evento.target.matches('.abas-secao a')) mostrarAba(evento.target);
  });
  window.addEventListener('resize', atualizar);
  movimentoReduzido.addEventListener('change', cancelarEntradas);
  document.addEventListener('DOMContentLoaded', atualizar, {once: true});
  document.fonts?.ready.then(atualizar);
  if (document.readyState !== 'loading') atualizar();
})();
