// Prévia de LP (Marketing): troca a moldura entre computador e celular.
document.addEventListener("click", (evento) => {
  const botao = evento.target.closest("[data-lpv-tela]");
  if (!botao) return;
  const moldura = document.querySelector(".lpv-moldura");
  if (!moldura) return;
  moldura.dataset.tela = botao.dataset.lpvTela;
  for (const outro of botao.parentElement.querySelectorAll("[data-lpv-tela]")) {
    outro.setAttribute("aria-pressed", String(outro === botao));
  }
});
