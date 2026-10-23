/* Prévia local; regras e identificadores vêm do mesmo catálogo do servidor. */
(function () {
  'use strict';
  const bloco = document.querySelector('[data-catalogo-previa]');
  const dados = document.getElementById('catalogo-ilustracoes');
  if (!bloco || !dados) return;
  const config = JSON.parse(dados.textContent);
  const regras = config.regras.map(([padrao, icone]) => [new RegExp(padrao), icone]);
  const form = bloco.closest('form');
  const nome = form.elements.nome;
  const categoria = form.elements.categoria;
  const escolha = form.elements.icone_catalogo;
  function normalizar(texto) {
    return String(texto || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function identificar() {
    if (Object.hasOwn(config.icones, escolha.value)) return escolha.value;
    const textos = [nome.value, categoria.selectedOptions[0]?.textContent];
    for (const valor of textos) {
      const texto = normalizar(valor);
      for (const grupo of [regras.slice(0, config.prioritarias), regras.slice(config.prioritarias)]) {
        const encontrados = grupo.map(([padrao, icone]) => ({match: padrao.exec(texto), icone}))
          .filter(item => item.match).sort((a, b) => a.match.index - b.match.index);
        if (!encontrados.length) continue;
        const icone = encontrados[0].icone;
        if (icone === 'glass-water' && /\b(gas|gasosa)\b/.test(texto) && !/\b(sem|s) gas\b/.test(texto)) return 'bubbles';
        return icone;
      }
    }
    return 'package';
  }
  function atualizar() {
    const icone = identificar();
    const ilustracao = config.icones[icone];
    bloco.querySelector('use').setAttribute('href', bloco.dataset.sprite + '#' + icone);
    bloco.querySelector('.produto-ilustracao').dataset.tom = ilustracao.tom;
    bloco.querySelector('[data-icone-nome]').textContent = ilustracao.rotulo;
  }
  nome.addEventListener('input', atualizar);
  categoria.addEventListener('change', atualizar);
  escolha.addEventListener('change', atualizar);
  atualizar();
}());
