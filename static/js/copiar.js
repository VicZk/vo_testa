/* Copiar para a área de transferência — um só comportamento no sistema inteiro.
 *
 * Qualquer elemento com `data-copiar="…"` vira botão de copiar. O ouvinte é
 * delegado no documento: serve para o que o HTMX troca depois (linha de cobrança,
 * cartão do funil) e para o que o Alpine escreve na hora (`:data-copiar="texto"`),
 * porque o valor é lido no clique, nunca no carregamento.
 *
 * Por que não só `navigator.clipboard`: ela só existe em contexto seguro. No
 * servidor da pousada aberto por `http://` na rede local — e em WebView antigo —
 * ela é `undefined` e o botão não fazia nada, sem dizer por quê. O plano B é o
 * `execCommand('copy')` sobre um campo fora da vista.
 *
 * O retorno é imediato: o botão troca para «Copiado» por 2 s (a mensagem e o
 * ícone já estão no HTML — ver componentes/copiar.html) e vibra de leve no
 * celular. Sem o componente (botão solto com `data-copiar`), troca o texto.
 */
(function () {
  "use strict";

  function porPlanoB(texto) {
    var campo = document.createElement("textarea");
    campo.value = texto;
    // Fora da vista sem sair do documento: `display:none` não é selecionável, e
    // `position:fixed` no topo evita a rolagem que o foco provocaria.
    campo.setAttribute("aria-hidden", "true");
    campo.className = "copiar-plano-b";
    document.body.appendChild(campo);
    campo.focus();
    campo.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(campo);
    return ok;
  }

  function copiar(texto) {
    if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
      return navigator.clipboard.writeText(texto).then(
        function () { return true; },
        function () { return porPlanoB(texto); }
      );
    }
    return Promise.resolve(porPlanoB(texto));
  }

  function avisar(botao, ok) {
    if (!ok) {
      // Nem a API nem o plano B: o texto continua na tela para copiar à mão.
      botao.title = "Não consegui copiar neste navegador — selecione o texto e use Ctrl+C.";
      return;
    }
    if (navigator.vibrate) navigator.vibrate(8);
    botao.classList.add("copiado");
    var simples = !botao.querySelector(".copiar-troca");
    if (simples) {
      if (botao.dataset.rotuloOriginal === undefined) botao.dataset.rotuloOriginal = botao.textContent;
      botao.textContent = "Copiado";
    }
    // Quem usa leitor de tela não vê a troca do rótulo: o `aria-label` do botão
    // (que, existindo, é o que a tecnologia assistiva lê) vira a confirmação e
    // volta ao normal junto com o visual.
    if (botao.hasAttribute("aria-label")) {
      if (botao.dataset.ariaOriginal === undefined) {
        botao.dataset.ariaOriginal = botao.getAttribute("aria-label");
      }
      botao.setAttribute("aria-label", "Copiado");
    }
    clearTimeout(botao._voltar);
    botao._voltar = setTimeout(function () {
      botao.classList.remove("copiado");
      if (simples && botao.dataset.rotuloOriginal !== undefined) {
        botao.textContent = botao.dataset.rotuloOriginal;
      }
      if (botao.dataset.ariaOriginal !== undefined) {
        botao.setAttribute("aria-label", botao.dataset.ariaOriginal);
      }
    }, 2000);
  }

  document.addEventListener("click", function (evento) {
    var botao = evento.target.closest("[data-copiar]");
    if (!botao) return;
    evento.preventDefault();
    var texto = botao.getAttribute("data-copiar") || "";
    if (!texto) return;
    Promise.resolve(copiar(texto)).then(function (ok) { avisar(botao, ok); });
  });
})();
