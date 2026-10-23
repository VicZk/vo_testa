/* Atualizações internas: mantém formulários abertos e avisa quando a fila muda. */
(() => {
  if (window.govAvisosAtivos) return;
  window.govAvisosAtivos = true;
  let versao = null, ocupado = false, urlAtual = '';
  async function verificar() {
    const badge = document.querySelector('[data-governanca-avisos]');
    if (!badge || document.hidden || ocupado) return;
    ocupado = true;
    try {
      const resposta = await fetch(badge.dataset.governancaAvisos, {
        credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}
      });
      if (!resposta.ok || !resposta.headers.get('content-type')?.includes('application/json')) return;
      const dados = await resposta.json();
      const pendentes = Number(dados.pendentes);
      if (!Number.isSafeInteger(pendentes) || pendentes < 0) return;
      const numero = badge.querySelector('.nav-badge-numero');
      if (numero) numero.textContent = pendentes > 99 ? '99+' : String(pendentes);
      const descricao = `${pendentes} serviço(s) de limpeza pendente(s)`;
      badge.setAttribute('aria-label', descricao);
      badge.removeAttribute('title');
      badge.setAttribute('data-dica', `${pendentes} serviço(s) de limpeza aguardando início. Abrir a lista.`);
      badge.setAttribute('data-dica-lado', 'direita');
      if (pendentes === 0 && document.activeElement === badge) {
        badge.closest('.nav-item')?.querySelector('.nav-item-principal')?.focus({preventScroll: true});
      }
      badge.hidden = pendentes === 0;
      const atual = JSON.stringify([dados.ultima, dados.quartos_atualizados_em, dados.total, pendentes, dados.em_andamento]);
      if (urlAtual !== location.href) { versao = null; urlAtual = location.href; }
      if (versao && versao !== atual) {
        const aviso = document.querySelector('[data-governanca-atualizacao]');
        if (aviso) aviso.hidden = false;
        else if (!document.querySelector('[data-central-pendencias]') && typeof window.toast === 'function') {
          window.toast(`Governança: ${pendentes} serviço(s) aguardando início. Abra Pendências para consultar a lista.`, 'info');
        }
      }
      versao = atual;
    } catch (_) { /* Uma falha de rede não interrompe a operação da página. */ }
    finally { ocupado = false; }
  }
  document.addEventListener('DOMContentLoaded', verificar);
  document.addEventListener('htmx:afterSettle', verificar);
  document.addEventListener('visibilitychange', verificar);
  setInterval(verificar, 60000);
})();
