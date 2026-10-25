/* Melhoria progressiva do cadastro: itens e embalagens, sem calcular dinheiro no navegador. */
(function () {
  'use strict';
  function preparar() {
    const form = document.getElementById('nota-form');
    if (!form || form.dataset.itensProntos) return;
    form.dataset.itensProntos = '1';
    const documentos = form.querySelector('[name="documentos"]');
    const anexosStatus = document.getElementById('nota-anexos-status');
    documentos.addEventListener('change', () => {
      const quantidade = documentos.files.length;
      anexosStatus.textContent = quantidade
        ? quantidade + (quantidade === 1 ? ' arquivo selecionado' : ' arquivos selecionados')
        : 'Nenhum arquivo selecionado';
    });
    const lista = document.getElementById('nota-itens');
    const adicionar = document.getElementById('nota-adicionar-item');
    const total = form.querySelector('[name="itens-TOTAL_FORMS"]');
    const embalagens = JSON.parse(document.getElementById('nota-embalagens').textContent);
    const modelo = document.getElementById('nota-item-vazio');
    const limite = document.getElementById('nota-limite-itens');
    function campo(linha, nome) { return linha.querySelector('[name$="-' + nome + '"]'); }
    function descrever(linha, confirmar) {
      const embalagem = embalagens.find(item => String(item.id) === campo(linha, 'embalagem').value);
      if (confirmar) campo(linha, 'fator_conferido').value = embalagem ? embalagem.fator : '';
      linha.querySelector('[data-embalagem-ajuda]').textContent = embalagem
        ? 'Cada ' + embalagem.nome + ' contém ' + embalagem.fator.replace('.', ',') + ' ' + embalagem.unidade + '.'
        : 'Recebimento na unidade base indicada no produto.';
      linha.querySelector('[data-quantidade-ajuda]').textContent = embalagem
        ? 'Informe a quantidade de ' + embalagem.nome + '.' : 'Informe a quantidade na unidade base do produto.';
      const custo = campo(linha, 'custo_unidade_compra');
      linha.querySelector('label[for="' + custo.id + '"]').textContent = embalagem
        ? 'Custo por ' + embalagem.nome + ' (R$)' : 'Custo por unidade base (R$)';
    }
    function preencher(linha, manter) {
      const select = campo(linha, 'embalagem');
      const anterior = manter ? select.value : '';
      select.replaceChildren(new Option('Unidade do produto', ''));
      embalagens.filter(item => String(item.produto) === campo(linha, 'produto').value).forEach(item => {
        select.add(new Option(item.nome + ' · ' + item.fator.replace('.', ',') + ' ' + item.unidade, item.id));
      });
      select.value = anterior;
      if (!select.value) select.value = '';
      descrever(linha, !manter);
    }
    function atualizar() {
      const ativas = Array.from(lista.querySelectorAll('[data-nota-item]')).filter(linha => !linha.hidden);
      ativas.forEach((linha, indice) => {
        linha.querySelector('[data-item-numero]').textContent = indice + 1;
        const remover = linha.querySelector('[data-nota-remover]');
        remover.hidden = false;
        remover.disabled = ativas.length === 1;
        remover.setAttribute('aria-label', 'Remover item ' + (indice + 1));
      });
      adicionar.hidden = false;
      adicionar.disabled = Number(total.value) >= 100;
      limite.hidden = !adicionar.disabled;
    }
    lista.querySelectorAll('[data-nota-item]').forEach(linha => {
      if (campo(linha, 'DELETE').checked) {
        linha.hidden = true;
        linha.querySelectorAll('input,select,textarea').forEach(input => { if (!input.name.endsWith('-DELETE')) input.disabled = true; });
      } else preencher(linha, true);
    });
    form.addEventListener('change', ev => {
      const linha = ev.target.closest('[data-nota-item]');
      if (!linha) return;
      if (ev.target.name.endsWith('-produto')) preencher(linha, false);
      else if (ev.target.name.endsWith('-embalagem')) descrever(linha, true);
    });
    adicionar.addEventListener('click', () => {
      const indice = Number(total.value);
      if (indice >= 100) return;
      const fragmento = document.createElement('template');
      fragmento.innerHTML = modelo.innerHTML.replaceAll('__prefix__', String(indice)).replaceAll('__numero__', String(indice + 1));
      const linha = fragmento.content.firstElementChild;
      lista.appendChild(linha);
      total.value = indice + 1;
      preencher(linha, false);
      atualizar();
      campo(linha, 'produto').focus();
      form.dispatchEvent(new Event('change', {bubbles: true}));
    });
    lista.addEventListener('click', ev => {
      const remover = ev.target.closest('[data-nota-remover]');
      if (!remover || remover.disabled) return;
      const linha = remover.closest('[data-nota-item]');
      campo(linha, 'DELETE').checked = true;
      linha.hidden = true;
      linha.querySelectorAll('input,select,textarea').forEach(input => { if (!input.name.endsWith('-DELETE')) input.disabled = true; });
      atualizar();
      adicionar.focus();
      form.dispatchEvent(new Event('change', {bubbles: true}));
    });
    atualizar();
  }
  preparar();
  document.addEventListener('htmx:afterSwap', preparar);
})();
