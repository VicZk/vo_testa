/* Prévia de recebimento. O motor do estoque valida e calcula os valores gravados. */
(() => {
  const dados = document.getElementById('compra-embalagens');
  if (!dados) return;
  const embalagens = JSON.parse(dados.textContent);
  const embalagem = document.getElementById('id_embalagem');
  const quantidade = document.getElementById('id_quantidade');
  const custo = document.getElementById('id_custo_embalagem');
  const previa = document.getElementById('compra-previa');
  const formato = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 3 });
  const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
  const numero = texto => Number(String(texto).replace(',', '.'));
  function atualizar() {
    const item = embalagens.find(linha => String(linha.id) === embalagem.value);
    previa.hidden = !item;
    document.getElementById('id_fator_conferido').value = item ? item.fator : '';
    if (!item) return;
    const qtd = numero(quantidade.value), preco = numero(custo.value), fator = numero(item.fator);
    document.getElementById('compra-produto').textContent = item.produto;
    document.getElementById('compra-embalagem').textContent = `${item.nome} · ${formato.format(fator)} ${item.unidade} por embalagem`;
    document.getElementById('compra-quantidade').textContent = Number.isFinite(qtd) && qtd > 0
      ? `${formato.format(qtd)} × ${formato.format(fator)} = ${formato.format(qtd * fator)} ${item.unidade}` : 'Informe a quantidade recebida';
    document.getElementById('compra-total').textContent = Number.isFinite(qtd) && qtd > 0 && custo.value !== '' && Number.isFinite(preco) && preco >= 0
      ? moeda.format(qtd * preco) : 'Informe o custo por embalagem';
  }
  [embalagem, quantidade, custo].forEach(campo => campo.addEventListener('input', atualizar));
  atualizar();
})();
