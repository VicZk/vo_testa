/* Consentimento de medição (LGPD) — componente reutilizável.
 *
 * Nada de GA4, Google tag ou Meta Pixel carrega antes da escolha da pessoa. As
 * tags ficam no HTML como <script type="text/plain" data-consentimento> — tipo
 * que o navegador NÃO executa — e só são ligadas depois do "Aceitar". No
 * "Recusar" nada é carregado e a escolha é lembrada (localStorage, com cookie
 * de reserva para quando o storage está bloqueado).
 *
 * Como usar numa página:
 *   1. marque cada tag de medição:
 *        <script type="text/plain" data-consentimento data-src="https://…"></script>
 *        <script type="text/plain" data-consentimento>  …código inline…  </script>
 *   2. inclua o partial `componentes/consentimento.html` e este arquivo.
 */
(function () {
  var CHAVE = 'votesta-consentimento';   // "aceito" | "recusado"

  function ler() {
    try {
      var v = localStorage.getItem(CHAVE);
      if (v) return v;
    } catch (e) { /* storage bloqueado: cai no cookie */ }
    var m = document.cookie.match(/(?:^|;\s*)votesta_consent=(aceito|recusado)/);
    return m ? m[1] : null;
  }

  function gravar(valor) {
    try { localStorage.setItem(CHAVE, valor); } catch (e) { /* segue com o cookie */ }
    // 180 dias; SameSite=Lax basta (não é cookie de terceiro).
    document.cookie = 'votesta_consent=' + valor + ';path=/;max-age=15552000;SameSite=Lax';
  }

  // Liga as tags marcadas, preservando a ordem em que estão no documento.
  function ligarTags() {
    var tags = document.querySelectorAll('script[type="text/plain"][data-consentimento]');
    for (var i = 0; i < tags.length; i++) {
      var velha = tags[i];
      var nova = document.createElement('script');
      for (var j = 0; j < velha.attributes.length; j++) {
        var at = velha.attributes[j];
        if (at.name === 'type' || at.name === 'data-consentimento' || at.name === 'data-src') continue;
        nova.setAttribute(at.name, at.value);
      }
      if (velha.dataset.src) nova.src = velha.dataset.src;
      else nova.textContent = velha.textContent;
      velha.parentNode.insertBefore(nova, velha);
      velha.parentNode.removeChild(velha);
    }
    document.dispatchEvent(new CustomEvent('consentimento:aceito'));
  }

  function esconder(banner) {
    banner.hidden = true;
    banner.setAttribute('aria-hidden', 'true');
  }

  function iniciar() {
    var banner = document.getElementById('consentimento');
    var decisao = ler();
    if (decisao === 'aceito') { ligarTags(); if (banner) esconder(banner); return; }
    if (decisao === 'recusado') { if (banner) esconder(banner); return; }
    if (!banner) return;                       // página sem o partial: não mede nada
    banner.hidden = false;
    banner.removeAttribute('aria-hidden');
    var aceitar = banner.querySelector('[data-consent-aceitar]');
    var recusar = banner.querySelector('[data-consent-recusar]');
    if (aceitar) aceitar.addEventListener('click', function () {
      gravar('aceito'); esconder(banner); ligarTags();
    });
    if (recusar) recusar.addEventListener('click', function () {
      gravar('recusado'); esconder(banner);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
