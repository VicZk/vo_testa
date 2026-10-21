/* Vitrine dos quartos (/quartos/): filtrar e ordenar os cartões no próprio navegador.
 *
 * São no máximo 24 cartões, então não há ida ao servidor: cada cartão traz os dados em
 * `data-*` (capacidade, tipo, qualidades, preço, nome, ordem da casa). Sem JS a barra de
 * filtros fica escondida e a página mostra todos os quartos, como antes.
 * O filtro escolhido vai para o endereço (?pessoas=4&tipo=…&com=…&ordem=preco) para dar
 * para mandar o link filtrado pelo WhatsApp.
 */
(function () {
  "use strict";

  var raiz = document.querySelector("[data-vitrine]");
  if (!raiz) return;
  var barra = raiz.querySelector("[data-vitrine-filtros]");
  var grade = raiz.querySelector("[data-vitrine-grade]");
  if (!barra || !grade) return;

  var cards = Array.prototype.slice.call(grade.querySelectorAll("[data-quarto]"));
  var contador = raiz.querySelector("[data-vitrine-contador]");
  var vazio = raiz.querySelector("[data-vitrine-vazio]");
  var botoesLimpar = raiz.querySelectorAll("[data-vitrine-limpar]");
  var campoPessoas = barra.querySelector("[name=pessoas]");
  var campoTipo = barra.querySelector("[name=tipo]");
  var campoOrdem = barra.querySelector("[name=ordem]");
  var toggles = Array.prototype.slice.call(barra.querySelectorAll("[data-qualidade]"));
  var total = cards.length;

  barra.classList.remove("hidden");

  function qualidadesMarcadas() {
    return toggles
      .filter(function (t) { return t.getAttribute("aria-pressed") === "true"; })
      .map(function (t) { return t.getAttribute("data-qualidade"); });
  }

  function comparador(ordem) {
    var porNumero = function (atributo, sinal) {
      return function (a, b) {
        return sinal * (Number(a.getAttribute(atributo)) - Number(b.getAttribute(atributo)));
      };
    };
    if (ordem === "preco") return porNumero("data-preco", 1);
    if (ordem === "preco-desc") return porNumero("data-preco", -1);
    if (ordem === "nome") {
      return function (a, b) {
        return a.getAttribute("data-nome").localeCompare(b.getAttribute("data-nome"), "pt-BR");
      };
    }
    return porNumero("data-ordem", 1);
  }

  function aplicar(gravarNoEndereco) {
    var pessoas = Number(campoPessoas ? campoPessoas.value : 0) || 0;
    var tipo = campoTipo ? campoTipo.value : "";
    var marcadas = qualidadesMarcadas();
    var visiveis = 0;

    cards.forEach(function (card) {
      var tem = (card.getAttribute("data-qualidades") || "").split(" ");
      var cabe = Number(card.getAttribute("data-capacidade")) >= pessoas;
      var doTipo = !tipo || card.getAttribute("data-tipo") === tipo;
      var comTudo = marcadas.every(function (q) { return tem.indexOf(q) !== -1; });
      var mostra = cabe && doTipo && comTudo;
      card.classList.toggle("hidden", !mostra);
      if (mostra) visiveis += 1;
    });

    cards.slice().sort(comparador(campoOrdem ? campoOrdem.value : "")).forEach(function (card) {
      grade.appendChild(card);
    });

    var filtrando = pessoas > 0 || !!tipo || marcadas.length > 0;
    if (contador) {
      contador.textContent = filtrando
        ? visiveis + " de " + total + " quartos"
        : total + " quartos";
    }
    if (vazio) vazio.classList.toggle("hidden", visiveis > 0);
    Array.prototype.forEach.call(botoesLimpar, function (b) {
      b.classList.toggle("hidden", !filtrando);
    });

    if (gravarNoEndereco && window.history && window.history.replaceState) {
      var params = new URLSearchParams(window.location.search);
      [["pessoas", pessoas ? String(pessoas) : ""], ["tipo", tipo],
       ["com", marcadas.join(",")], ["ordem", campoOrdem ? campoOrdem.value : ""]]
        .forEach(function (par) {
          if (par[1]) params.set(par[0], par[1]); else params.delete(par[0]);
        });
      var busca = params.toString();
      window.history.replaceState(null, "", window.location.pathname + (busca ? "?" + busca : ""));
    }
  }

  function lerEndereco() {
    var params = new URLSearchParams(window.location.search);
    if (campoPessoas && params.get("pessoas")) campoPessoas.value = params.get("pessoas");
    if (campoTipo && params.get("tipo")) campoTipo.value = params.get("tipo");
    if (campoOrdem && params.get("ordem")) campoOrdem.value = params.get("ordem");
    var com = (params.get("com") || "").split(",");
    toggles.forEach(function (t) {
      t.setAttribute("aria-pressed", com.indexOf(t.getAttribute("data-qualidade")) !== -1 ? "true" : "false");
    });
  }

  [campoPessoas, campoTipo, campoOrdem].forEach(function (campo) {
    if (campo) campo.addEventListener("change", function () { aplicar(true); });
  });
  toggles.forEach(function (t) {
    t.addEventListener("click", function () {
      t.setAttribute("aria-pressed", t.getAttribute("aria-pressed") === "true" ? "false" : "true");
      aplicar(true);
    });
  });
  Array.prototype.forEach.call(botoesLimpar, function (b) {
    b.addEventListener("click", function () {
      if (campoPessoas) campoPessoas.value = "";
      if (campoTipo) campoTipo.value = "";
      toggles.forEach(function (t) { t.setAttribute("aria-pressed", "false"); });
      aplicar(true);
    });
  });

  lerEndereco();
  aplicar(false);
})();
