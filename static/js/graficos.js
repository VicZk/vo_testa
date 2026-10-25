/* Gráficos locais acompanham a navegação HTMX e o histórico do navegador. */
(function () {
  'use strict';
  const fonteChart = document.currentScript?.dataset.chartSrc;
  let carregamento = null;
  const dadosAnteriores = new Map();
  function criarGrafico(contexto, configuracao) {
    const canvas = contexto.canvas;
    const assinatura = JSON.stringify(configuracao.data);
    canvas.dataset.graficoDados = assinatura;
    // Trocar o documento do canvas não deve reapresentar valores idênticos.
    if (dadosAnteriores.get(canvas.id) === assinatura) {
      configuracao.options = {...configuracao.options, animation: false};
    }
    dadosAnteriores.set(canvas.id, assinatura);
    return new Chart(contexto, configuracao);
  }
  function carregarChart() {
    if (window.Chart) return Promise.resolve();
    if (carregamento) return carregamento;
    carregamento = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = fonteChart;
      script.onload = resolve;
      script.onerror = () => { script.remove(); carregamento = null; reject(new Error('Gráficos indisponíveis')); };
      document.head.appendChild(script);
    });
    return carregamento;
  }
  function disponivel(id) {
    const canvas = document.getElementById(id);
    return canvas && !Chart.getChart(canvas);
  }
  function painel() {
  const fonte = document.getElementById('dados-graficos');
  if (!fonte) return;
  const dados = JSON.parse(fonte.textContent);
  if (!window.Chart) return;
  Chart.defaults.font.family = "'Hanken Grotesk', -apple-system, sans-serif";
  Chart.defaults.font.size = 12;
  // Paleta vem dos tokens da marca (app.css :root) — sem hex paralelo.
  const css = getComputedStyle(document.documentElement);
  const tk = (n, fb) => (css.getPropertyValue(n).trim() || fb);
  Chart.defaults.color = tk('--tinta-suave', '#64717B');
  const NOTURNO = tk('--noturno', '#051C2C'), LAMPIAO = tk('--lampiao', '#D7A048'),
        MUSGO = tk('--musgo', '#2E483E'), MADEIRA = tk('--madeira', '#4F2C1D'),
        INFO = tk('--info', '#2C6E7A'), ALERTA = tk('--alerta', '#B0741C'),
        SUPERF = tk('--superficie', '#fff'), FIO = tk('--fio-forte', '#E7DFCF');
  const PALETA = [NOTURNO, LAMPIAO, MUSGO, MADEIRA, INFO, ALERTA];
  const semGrade = { grid: { display: false }, border: { display: false } };
  const gradeY = { grid: { color: FIO }, border: { display: false } };
  const ctx = id => { const el = document.getElementById(id); return el ? el.getContext('2d') : null; };
  const reais = v => 'R$ ' + Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const percentual = v => Number(v).toLocaleString('pt-BR', {maximumFractionDigits: 1}) + '%';

  if (dados.ocupacao && disponivel('g-ocupacao')) {
    const cores = dados.ocupacao.fds.map(f => f ? ALERTA : LAMPIAO);
    criarGrafico(ctx('g-ocupacao'), {
      type: 'line',
      data: { labels: dados.ocupacao.labels, datasets: [{
        data: dados.ocupacao.valores, borderColor: LAMPIAO,
        backgroundColor: 'rgba(215,160,72,.14)', fill: true, tension: .35,
        borderWidth: 2, pointRadius: 3, pointBackgroundColor: cores, pointBorderColor: cores }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => 'Ocupação: ' + percentual(c.parsed.y) } } },
        scales: { x: semGrade, y: { ...gradeY, min: 0, max: 100, ticks: { callback: percentual } } } }
    });
  }
  if (dados.receita && disponivel('g-receita')) {
    criarGrafico(ctx('g-receita'), {
      type: 'bar',
      data: { labels: dados.receita.labels, datasets: [
        { label: 'Serviço', data: dados.receita.servico, backgroundColor: MUSGO, stack: 's', borderRadius: 3 },
        { label: 'Consumo', data: dados.receita.consumo, backgroundColor: LAMPIAO, stack: 's', borderRadius: 3 } ] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: c => c.dataset.label + ': ' + reais(c.parsed.y) } } },
        scales: { x: { ...semGrade, stacked: true }, y: { ...gradeY, stacked: true, ticks: { callback: v => 'R$ ' + v } } } }
    });
  }
  if (dados.tipos && disponivel('g-tipos')) {
    criarGrafico(ctx('g-tipos'), {
      type: 'bar',
      data: { labels: dados.tipos.labels, datasets: [{ data: dados.tipos.valores, backgroundColor: MUSGO, borderRadius: 4 }] },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => 'Ocupação: ' + percentual(c.parsed.x) } } },
        scales: { x: { ...gradeY, min: 0, max: 100, ticks: { callback: percentual } }, y: semGrade } }
    });
  }
  const opcoesPizza = (fmt, extra) => ({
    responsive: true, maintainAspectRatio: false, cutout: '72%', radius: '92%',
    plugins: {
      legend: {
        position: 'right',
        labels: {
          usePointStyle: true, pointStyle: 'circle', boxWidth: 8, boxHeight: 8,
          padding: 10, font: { size: 11.5 },
          generateLabels: chart => {
            const ds = chart.data.datasets[0];
            const total = ds.data.reduce((a, b) => a + b, 0) || 1;
            return chart.data.labels.map((lab, i) => ({
              text: lab + ' · ' + fmt(ds.data[i]) + ' (' + Math.round(ds.data[i] * 100 / total) + '%)',
              fillStyle: ds.backgroundColor[i], strokeStyle: ds.backgroundColor[i],
              pointStyle: 'circle', index: i,
            }));
          },
        },
      },
      ...extra,
    },
  });
  const inteiro = v => v.toLocaleString('pt-BR');
  const reaisCurto = v => 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  if (dados.canais && disponivel('g-canais')) {
    criarGrafico(ctx('g-canais'), {
      type: 'doughnut',
      data: { labels: dados.canais.labels, datasets: [{ data: dados.canais.valores, backgroundColor: PALETA, borderColor: SUPERF, borderWidth: 3, hoverOffset: 4 }] },
      options: opcoesPizza(inteiro, { tooltip: { callbacks: { label: c => c.label + ': ' + inteiro(c.parsed) + ' reserva' + (c.parsed === 1 ? '' : 's') } } })
    });
  }
  if (dados.funil && disponivel('g-funil')) {
    criarGrafico(ctx('g-funil'), {
      type: 'bar',
      data: { labels: dados.funil.labels, datasets: [{ data: dados.funil.valores, backgroundColor: MADEIRA, borderRadius: 4 }] },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ...gradeY, ticks: { precision: 0 } }, y: semGrade } }
    });
  }
  if (dados.pagamento && disponivel('g-pagamento')) {
    criarGrafico(ctx('g-pagamento'), {
      type: 'doughnut',
      data: { labels: dados.pagamento.labels, datasets: [{ data: dados.pagamento.valores, backgroundColor: PALETA, borderColor: SUPERF, borderWidth: 3, hoverOffset: 4 }] },
      options: opcoesPizza(reaisCurto, { tooltip: { callbacks: { label: c => c.label + ': ' + reais(c.parsed) } } })
    });
  }
  }
  function conciliacao() {
  const fonte = document.getElementById('dados-conciliacao');
  if (!fonte) return;
  const dados = JSON.parse(fonte.textContent);
  Chart.defaults.font.family = "'Hanken Grotesk', -apple-system, sans-serif";
  Chart.defaults.color = '#64717B';
  const MUSGO = '#2E483E', LAMPIAO = '#D7A048', MADEIRA = '#4F2C1D';
  const ctx = id => { const el = document.getElementById(id); return el ? el.getContext('2d') : null; };
  const opc = {
    responsive: true, maintainAspectRatio: false, cutout: '68%',
    plugins: { legend: { position: 'right', labels: {
      usePointStyle: true, pointStyle: 'circle', boxWidth: 8, padding: 10,
      generateLabels: chart => {
        const ds = chart.data.datasets[0], t = ds.data.reduce((a, b) => a + b, 0) || 1;
        return chart.data.labels.map((l, i) => ({
          text: l + ' · ' + ds.data[i] + ' (' + Math.round(ds.data[i] * 100 / t) + '%)',
          fillStyle: ds.backgroundColor[i], strokeStyle: ds.backgroundColor[i],
          pointStyle: 'circle', index: i,
        }));
      } } } },
  };
  const ext = disponivel('g-ext') && ctx('g-ext');
  if (ext) criarGrafico(ext, {
    type: 'doughnut',
    data: { labels: ['Conciliado', 'Pendente', 'Ignorado'], datasets: [{
      data: [dados.extrato.conciliado, dados.extrato.pendente, dados.extrato.ignorado],
      backgroundColor: [MUSGO, LAMPIAO, MADEIRA], borderColor: '#fff', borderWidth: 3, hoverOffset: 4 }] },
    options: opc });
  const car = disponivel('g-car') && ctx('g-car');
  if (car) criarGrafico(car, {
    type: 'doughnut',
    data: { labels: ['Conciliado', 'Pendente', 'Sem venda'], datasets: [{
      data: [dados.cartao.conciliado, dados.cartao.pendente, dados.cartao.sem_venda],
      backgroundColor: [MUSGO, LAMPIAO, MADEIRA], borderColor: '#fff', borderWidth: 3, hoverOffset: 4 }] },
    options: opc });
  }
  function contabil() {
  const fonteCascata = document.getElementById('ctb-wf');
  const fonteRosca = document.getElementById('ctb-donut');
  if (!fonteCascata || !fonteRosca) return;
  const wf = JSON.parse(fonteCascata.textContent);
  const dn = JSON.parse(fonteRosca.textContent);
  // Cores pelos tokens do app.css: o tema muda num lugar só.
  const css = getComputedStyle(document.documentElement);
  const tok = nome => css.getPropertyValue(nome).trim();
  const acc = tok('--lampiao'), ok = tok('--sucesso'), bad = tok('--perigo'),
    fio = tok('--fio'), sup = tok('--superficie');
  Chart.defaults.color = tok('--tinta-suave');
  Chart.defaults.font.family = "'Hanken Grotesk', -apple-system, sans-serif";
  const cascata = disponivel('ctbWaterfall') && document.getElementById('ctbWaterfall').getContext('2d');
  if (cascata) criarGrafico(cascata, {
    type: 'bar',
    data: { labels: wf.labels, datasets: [
      { data: [0, wf.receita_liquida, wf.lucro_bruto, wf.resultado, 0], backgroundColor: 'transparent', stack: 's' },
      { data: [wf.receita_bruta, wf.deducoes, wf.custos, wf.despesas, wf.resultado],
        backgroundColor: [acc, bad, bad, bad, wf.resultado < 0 ? bad : ok], borderRadius: 5, stack: 's' }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      scales: { x: { grid: { display: false }, ticks: { font: { size: 11 } } },
        y: { grid: { color: fio }, stacked: true } } },
  });
  const rosca = disponivel('ctbDonut') && document.getElementById('ctbDonut').getContext('2d');
  if (rosca) criarGrafico(rosca, {
    type: 'doughnut',
    data: { labels: ['Serviços', 'Mercadorias'], datasets: [{
      data: dn, backgroundColor: [acc, ok], borderColor: sup, borderWidth: 3 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: '60%',
      plugins: { legend: { position: 'bottom' }, tooltip: { enabled: true } } },
  });
  }
  function iniciar() {
    if (!document.querySelector('#dados-graficos, #dados-conciliacao, #ctb-wf')) return;
    if (!window.Chart) {
      if (fonteChart) carregarChart().then(iniciar).catch(() => {});
      return;
    }
    Chart.defaults.animation = matchMedia('(prefers-reduced-motion: reduce)').matches ? false : {duration: 180};
    // Um fragmento pode remover a árvore antes de recebermos seu evento final.
    Object.values(Chart.instances).forEach(chart => {
      if (!chart.canvas?.isConnected) chart.destroy();
    });
    painel();
    conciliacao();
    contabil();
  }
  function limpar(raiz) {
    if (!window.Chart || !raiz?.querySelectorAll) return;
    const canvases = Array.from(raiz.querySelectorAll('canvas'));
    if (raiz.matches?.('canvas')) canvases.push(raiz);
    canvases.forEach(canvas => Chart.getChart(canvas)?.destroy());
  }
  document.addEventListener('htmx:beforeSwap', ev => {
    if (ev.detail.shouldSwap) limpar(ev.detail.target);
  });
  document.addEventListener('htmx:beforeCleanupElement', ev => limpar(ev.detail.elt));
  document.addEventListener('htmx:afterSwap', iniciar);
  document.addEventListener('htmx:historyRestore', iniciar);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
