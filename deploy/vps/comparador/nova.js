/* Comparador servido pelo Nginx em /_comparar.js, na origem de cada versão.
 * Fonte versionada para publicação isolada; não altera sessões ou dados.
 * Links nativos permanecem funcionais após a restauração do histórico HTMX.
 */
(function () {
  "use strict";

  var CFG = {
    id: "atualizada",
    base: "https://votesta-original.195-200-0-150.sslip.io",
    prefixo: "/votesta",
    tirarPrefixo: true,
    rotulo: "Versão anterior",
    dicas: true
  };

  if (window.__comparadorVoTesta) { return; }
  window.__comparadorVoTesta = true;

  // O destino acompanha a URL atual, inclusive query e fragmento.
  function destino() {
    var caminho = location.pathname;
    if (CFG.tirarPrefixo) {
      caminho = (caminho === CFG.prefixo || caminho.indexOf(CFG.prefixo + "/") === 0)
        ? caminho.slice(CFG.prefixo.length) : caminho;
      if (caminho.charAt(0) !== "/") { caminho = "/" + caminho; }
    } else {
      caminho = CFG.prefixo + caminho;
    }
    return CFG.base + caminho + location.search + location.hash;
  }

  var LINKS = "#comparador-item, #comparador-mobile, #comparador-desktop";

  function atualizarLink(link) {
    var url = destino();
    if (link.href !== url) { link.href = url; }
    if (link.getAttribute("hx-boost") !== "false") { link.setAttribute("hx-boost", "false"); }
  }

  // O cache HTMX restaura HTML, sem os listeners ligados aos nós antigos.
  // A delegação sobre document continua ativa; a navegação fica com o browser,
  // preservando Enter, Ctrl/Meta, clique do meio e a abertura por menu de contexto.
  function prepararNavegacao(ev) {
    var alvo = ev.target;
    var link = alvo && alvo.closest ? alvo.closest(LINKS) : null;
    if (link) { atualizarLink(link); }
  }

  function atualizarDestinos() {
    document.querySelectorAll(LINKS).forEach(atualizarLink);
  }

  // Setas de troca, no mesmo formato dos ícones da sidebar (viewBox 24, class ico).
  var ICONE = '<svg viewBox="0 0 24 24" class="ico" aria-hidden="true">'
            + '<path d="M4 8h13"/><path d="M14 5l3 3-3 3"/>'
            + '<path d="M20 16H7"/><path d="M10 13l-3 3 3 3"/></svg>';

  // ---- CRM: item no fim da navegação da sidebar ------------------------------
  function noCrm() {
    var nav = document.querySelector("aside.sidebar nav") ||
              document.querySelector(".sidebar nav");
    if (!nav) { return false; }
    if (document.getElementById("comparador-item")) { return true; }

    var grupo = document.createElement("div");
    grupo.className = "nav-grupo";

    var a = document.createElement("a");
    a.id = "comparador-item";
    a.className = "nav-item";
    atualizarLink(a);
    a.title = CFG.rotulo;
    a.innerHTML = ICONE + '<span class="rotulo"></span>';
    a.querySelector(".rotulo").textContent = CFG.rotulo;

    grupo.appendChild(a);
    nav.appendChild(grupo);
    rotular();
    return true;
  }

  // Espelha o rotularSidebar() do base.html da versão atualizada: no trilho do
  // desktop (sidebar recolhida e fora da gaveta) o item fica só com o ícone, e o
  // rótulo vira dica à direita. Expandido, nenhum title — o rótulo está visível.
  // A versão anterior não tem essa função: lá o title nativo é o padrão da casa.
  function rotular() {
    var a = document.getElementById("comparador-item");
    if (!a) { return; }
    if (a.dataset.nomeItem === undefined) { a.dataset.nomeItem = CFG.rotulo; }
    var app = document.getElementById("app");
    var trilho = !!app && app.classList.contains("recolhida") &&
                 !window.matchMedia("(max-width: 820px)").matches;
    if (!CFG.dicas) {
      a.setAttribute("title", a.dataset.nomeItem);
      return;
    }
    if (trilho) {
      a.removeAttribute("title");
      a.setAttribute("data-dica", a.dataset.nomeItem);
      a.setAttribute("data-dica-lado", "direita");
    } else {
      a.removeAttribute("title");
      a.removeAttribute("data-dica");
      a.removeAttribute("data-dica-lado");
    }
  }

  // ---- Site público: gaveta do celular + menu do desktop ---------------------
  function noSite() {
    var achou = false;

    var lista = document.querySelector("#mobileMenu .flex-col") ||
                document.querySelector("#mobileMenu div");
    if (lista && !document.getElementById("comparador-mobile")) {
      var modelo = lista.querySelector(".mobile-link");
      var m = document.createElement("a");
      m.id = "comparador-mobile";
      atualizarLink(m);
      m.className = modelo ? modelo.className : "mobile-link";
      m.textContent = CFG.rotulo;
      lista.appendChild(m);
      achou = true;
    }

    // O menu atualizado usa "site-nav-desktop"; os layouts anteriores usam lg/md:flex. Procuramos
    // pelo nome da classe em vez de querySelector com escape de ":".
    var desk = null;
    var navs = document.querySelectorAll("header nav, nav");
    for (var i = 0; i < navs.length; i++) {
      var cls = (navs[i].className || "").toString();
      if (navs[i].id === "mobileMenu") { continue; }
      if (cls.indexOf("site-nav-desktop") >= 0 || cls.indexOf("lg:flex") >= 0 || cls.indexOf("md:flex") >= 0) {
        desk = navs[i];
        break;
      }
    }
    if (desk && !document.getElementById("comparador-desktop")) {
      var ref = desk.querySelector("a");
      var d = document.createElement("a");
      d.id = "comparador-desktop";
      atualizarLink(d);
      d.className = ref ? ref.className : "";
      d.style.opacity = "0.7";     // discreto, como pedido
      d.textContent = CFG.rotulo;
      desk.appendChild(d);
      achou = true;
    }
    return achou;
  }

  var appObservado = null;
  var observador = window.MutationObserver ? new MutationObserver(rotular) : null;

  function observarApp() {
    var app = document.getElementById("app");
    if (!observador || app === appObservado) { return; }
    observador.disconnect();
    appObservado = app;
    if (app) {
      observador.observe(app, { attributes: true, attributeFilter: ["class"] });
    }
  }

  function instalar() {
    if (!document.body) { return; }
    noCrm();
    noSite();
    atualizarDestinos();
    rotular();
    observarApp();
  }

  ["pointerdown", "click", "auxclick", "contextmenu"].forEach(function (nome) {
    document.addEventListener(nome, prepararNavegacao, true);
  });
  ["htmx:afterSettle", "htmx:afterSwap", "htmx:historyRestore",
    "htmx:pushedIntoHistory", "htmx:replacedInHistory"].forEach(function (nome) {
    document.addEventListener(nome, instalar);
  });
  window.addEventListener("popstate", instalar);
  window.addEventListener("hashchange", instalar);
  window.addEventListener("resize", rotular);
  instalar();
})();
