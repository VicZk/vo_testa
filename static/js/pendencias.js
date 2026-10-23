/* Atualiza somente os resultados: filtros, foco e navegação continuam com a pessoa. */
(() => {
  if (window.pendenciasAtivas) return;
  window.pendenciasAtivas = true;
  let ocupado = false;

  async function atualizar() {
    const raiz = document.querySelector('[data-central-pendencias]');
    if (!raiz || document.hidden || ocupado) return;
    ocupado = true;
    const pagina = location.href;
    const aviso = raiz.querySelector('[data-pendencias-conexao]');
    const botao = raiz.querySelector('[data-pendencias-recarregar]');
    if (botao) botao.disabled = true;
    try {
      const url = new URL(raiz.dataset.pendenciasAtualizacoes, location.origin);
      url.search = location.search;
      const resposta = await fetch(url, {
        credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}
      });
      if (!resposta.ok || !resposta.headers.get('content-type')?.includes('application/json')) throw new Error('indisponível');
      const dados = await resposta.json();
      if (!Number.isSafeInteger(dados.total) || dados.total < 0 || typeof dados.html !== 'string') throw new Error('resposta inválida');
      if (!raiz.isConnected || pagina !== location.href) return;
      const resultados = raiz.querySelector('#pendencias-resultados');
      if (resultados) {
        const foco = document.activeElement;
        const estavaDentro = resultados.contains(foco);
        const itemFocado = foco?.closest('[data-pendencia-id]')?.dataset.pendenciaId;
        const hrefFocado = foco?.getAttribute('href');
        resultados.innerHTML = dados.html;
        if (window.htmx) window.htmx.process(resultados);
        // A contagem pode chegar a zero com um link focado. Restaurar o link
        // equivalente, ou o título quando a pendência acabou, mantém o teclado
        // no contexto sem deixar resultados desatualizados por tempo indefinido.
        if (estavaDentro) {
          const equivalente = [...resultados.querySelectorAll('a[href]')].find(link =>
            link.getAttribute('href') === hrefFocado &&
            (!itemFocado || link.closest('[data-pendencia-id]')?.dataset.pendenciaId === itemFocado));
          const alvo = equivalente || resultados.querySelector('h2');
          if (alvo) {
            if (!equivalente) alvo.setAttribute('tabindex', '-1');
            alvo.focus({preventScroll: true});
          }
        }
      }
      if (aviso) { aviso.hidden = true; aviso.textContent = ''; }
    } catch (_) {
      if (raiz.isConnected && pagina === location.href && aviso) {
        aviso.textContent = 'A atualização automática está indisponível. Os resultados exibidos são da última consulta; tente Atualizar agora.';
        aviso.hidden = false;
      }
    } finally {
      ocupado = false;
      if (botao) botao.disabled = false;
    }
  }
  document.addEventListener('click', evento => {
    if (evento.target.closest('[data-pendencias-recarregar]')) atualizar();
  });
  document.addEventListener('DOMContentLoaded', atualizar);
  document.addEventListener('htmx:afterSettle', evento => {
    if (evento.detail?.target?.id !== 'pendencias-resultados') atualizar();
  });
  document.addEventListener('visibilitychange', atualizar);
  setInterval(atualizar, 60000);
})();
