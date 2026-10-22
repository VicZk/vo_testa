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
      badge.textContent = dados.pendentes;
      badge.hidden = !dados.pendentes;
      const atual = JSON.stringify([dados.ultima, dados.quartos_atualizados_em, dados.total]);
      if (urlAtual !== location.href) { versao = null; urlAtual = location.href; }
      if (versao && versao !== atual) {
        const aviso = document.querySelector('[data-governanca-atualizacao]');
        if (aviso) aviso.hidden = false;
        else if (typeof window.toast === 'function') {
          window.toast(`Governança: ${dados.pendentes} serviço(s) pendente(s). Consulte a fila atualizada.`, 'info');
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
