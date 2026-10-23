/* Filtros de leitura preservam todos os campos e o salvamento da tabela inteira. */
(function () {
  'use strict';
  const preparados = new WeakSet();

  function preparar(raiz) {
    const forms = Array.from(raiz.querySelectorAll('.precos-form'));
    if (raiz.matches && raiz.matches('.precos-form')) forms.push(raiz);
    forms.forEach(form => {
      if (preparados.has(form)) return;
      preparados.add(form);
      const filtros = form.previousElementSibling;
      if (!filtros || !filtros.matches('[data-precos-filtros]')) return;
      const ala = filtros.querySelector('[data-precos-ala-filtro]');
      const quarto = filtros.querySelector('[data-precos-quarto-filtro]');
      const resumo = filtros.querySelector('[data-precos-resumo]');
      const linhas = Array.from(form.querySelectorAll('[data-precos-quarto]'));
      const grupos = Array.from(form.querySelectorAll('[data-precos-grupo]'));
      const opcoes = Array.from(quarto.options);

      function aplicar() {
        opcoes.forEach(opcao => {
          const disponivel = !opcao.value || !ala.value || opcao.dataset.ala === ala.value;
          opcao.hidden = !disponivel;
          opcao.disabled = !disponivel;
        });
        if (quarto.selectedOptions[0]?.disabled) quarto.value = '';
        const visiveis = linhas.filter(linha => {
          const mostrar = (!ala.value || linha.dataset.precosAla === ala.value) &&
            (!quarto.value || linha.dataset.precosQuarto === quarto.value);
          linha.hidden = !mostrar;
          return mostrar;
        });
        grupos.forEach(grupo => {
          grupo.hidden = !visiveis.some(linha => linha.dataset.precosAla === grupo.dataset.precosGrupo);
        });
        filtros.dataset.selecaoAla = ala.value;
        filtros.dataset.selecaoQuarto = quarto.value;
        resumo.textContent = `Mostrando ${visiveis.length} de ${linhas.length} quarto${linhas.length === 1 ? '' : 's'}.`;
      }

      function mostrarTodos() {
        ala.value = '';
        quarto.value = '';
        aplicar();
      }

      ala.addEventListener('change', () => { quarto.value = ''; aplicar(); });
      quarto.addEventListener('change', aplicar);
      filtros.querySelector('[data-precos-mostrar-todos]').addEventListener('click', mostrarTodos);
      filtros.hidden = false;
      if (form.dataset.precosMetodo !== 'POST') {
        if ('selecaoQuarto' in filtros.dataset) {
          ala.value = filtros.dataset.selecaoAla || '';
          quarto.value = filtros.dataset.selecaoQuarto || '';

        }
      }
      aplicar();

      // A resposta de erro mantém este formulário. Expõe todos os campos para
      // que um valor inválido nunca fique escondido por um filtro de leitura.
      new MutationObserver(registros => {
        if (!registros.some(registro => Array.from(registro.addedNodes).some(no =>
          no.nodeType === Node.ELEMENT_NODE && (no.matches('[data-erros-envio]') || no.closest('[data-erros-envio]'))))) return;
        mostrarTodos();
        const estado = form.querySelector('[data-estado-edicao]');
        if (estado) estado.textContent = 'Revise os campos; alterações ainda não salvas';
      }).observe(form, {childList:true, subtree:true});

      form.addEventListener('invalid', () => mostrarTodos(), true);
    });
  }

  preparar(document);
  document.addEventListener('htmx:afterSwap', ev => preparar(ev.detail.target));
  document.addEventListener('htmx:historyRestore', () => preparar(document));
})();
