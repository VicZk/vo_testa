/** Config do Tailwind do SITE público (build estático — substitui o Play CDN).
 *  Mesma paleta/fonte da antiga config inline do base.html. Build:
 *    npx tailwindcss@3 -i tailwind.src.css -o apps/site/static/site/css/tailwind.css --minify
 */
module.exports = {
  content: [
    "./apps/site/templates/**/*.html",
    "./apps/site/static/site/js/**/*.js",
    // Classes montadas no Python (widgets dos formulários do site, ex.: `_CAMPO`).
    // Fora daqui, o rebuild apagava o `outline-none` dos campos da reserva.
    "./apps/site/forms.py",
    "./apps/site/templatetags/**/*.py",
  ],
  theme: {
    extend: {
      colors: {
        noturno: "#051C2C",
        madeira: "#4F2C1D",
        lampiao: "#D7A048",
        pergaminho: "#EFDBB2",
        musgo: "#2E483E",
        // Cores de aviso: os MESMOS valores dos tokens semânticos do CRM
        // (`static/css/app.css`, :root). O teste de contrato do design confere.
        perigo: "#9A3B1E",
        "perigo-bg": "#F8ECE6",
        alerta: "#7A5A1E",
        "alerta-bg": "#FAF2DD",
        sucesso: "#3F6B48",
        "sucesso-bg": "#ECF1E7",
        info: "#2A5670",
        "info-bg": "#EAEFF3",
      },
      fontFamily: {
        display: ["Neco", "serif"],
        body: ["Neco", "serif"],
      },
    },
  },
  plugins: [],
};
