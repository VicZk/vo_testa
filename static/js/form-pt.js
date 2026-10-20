/* Validação de formulário em português.
 *
 * Sem isto, enviar um formulário incompleto mostra o balão nativo do Chrome:
 * "Please fill out this field." — o único texto em inglês do produto, e logo
 * na tela de cadastro mais usada. O balão também some sozinho, não fica junto
 * do campo e não é lido por leitor de tela de forma confiável.
 *
 * O que fazemos: desligamos o balão (`novalidate`) e escrevemos a mensagem
 * embaixo do campo, com as classes que o CSS já tem (`.campo-erro` + `.erro`),
 * iguais às mensagens que vêm do servidor. Quem não tem JS continua protegido
 * pela validação do Django no POST.
 */
(function () {
  'use strict';

  var CLASSE = 'erro erro-js';

  function rotulo(campo) {
    var envolve = campo.closest('.campo');
    var el = envolve && envolve.querySelector('label');
    var texto = el ? el.textContent : (campo.getAttribute('aria-label') || '');
    return texto.replace(/[:*]\s*$/, '').trim();
  }

  function mensagem(campo) {
    var v = campo.validity;
    var tipo = (campo.type || '').toLowerCase();
    if (v.valueMissing) {
      if (tipo === 'checkbox') return 'Marque esta caixa para continuar.';
      if (tipo === 'radio') return 'Escolha uma das opções.';
      if (campo.tagName === 'SELECT') return 'Escolha uma opção.';
      var nome = rotulo(campo);
      return nome ? 'Preencha o campo ' + nome + '.' : 'Preencha este campo.';
    }
    if (v.typeMismatch) {
      if (tipo === 'email') return 'Digite um e-mail válido, como nome@dominio.com.br.';
      if (tipo === 'url') return 'Digite um endereço de site válido.';
      return 'O formato não está certo.';
    }
    if (v.patternMismatch) return campo.title || 'O formato não está certo.';
    if (v.tooShort) return 'Use pelo menos ' + campo.minLength + ' caracteres.';
    if (v.tooLong) return 'Use no máximo ' + campo.maxLength + ' caracteres.';
    if (v.rangeUnderflow) return 'O menor valor aceito é ' + campo.min + '.';
    if (v.rangeOverflow) return 'O maior valor aceito é ' + campo.max + '.';
    if (v.stepMismatch) return 'Esse valor não é aceito aqui.';
    if (v.badInput) {
      if (tipo === 'number') return 'Digite um número.';
      if (tipo === 'date' || tipo === 'datetime-local') return 'Digite uma data válida.';
      return 'Não consegui entender o que foi digitado.';
    }
    return 'Confira este campo.';
  }

  function limpar(campo) {
    var envolve = campo.closest('.campo') || campo.parentElement;
    if (!envolve) return;
    envolve.classList.remove('campo-erro');
    var antigo = envolve.querySelector('.erro-js');
    if (antigo) antigo.remove();
    campo.removeAttribute('aria-invalid');
  }

  function marcar(campo) {
    var envolve = campo.closest('.campo') || campo.parentElement;
    if (!envolve) return;
    limpar(campo);
    envolve.classList.add('campo-erro');
    campo.setAttribute('aria-invalid', 'true');
    var aviso = document.createElement('small');
    aviso.className = CLASSE;
    aviso.textContent = mensagem(campo);
    // Depois do campo (ou do rótulo que o embrulha, no caso do checkbox).
    var depois = campo.closest('label') || campo;
    if (depois.parentElement === envolve) {
      depois.insertAdjacentElement('afterend', aviso);
    } else {
      envolve.appendChild(aviso);
    }
  }

  function desligarBalao(raiz) {
    var alvos = (raiz || document).querySelectorAll('form:not([novalidate])');
    Array.prototype.forEach.call(alvos, function (f) {
      f.setAttribute('novalidate', '');
    });
  }

  document.addEventListener('DOMContentLoaded', function () { desligarBalao(); });
  document.body && desligarBalao();
  document.addEventListener('htmx:afterSwap', function (e) { desligarBalao(e.target); });

  // Captura: o nosso "não" precisa valer também para formulários do HTMX, que
  // escutam o submit no próprio <form> (fase-alvo).
  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.semValidacao !== undefined) return;
    var enviador = ev.submitter;
    if (enviador && enviador.hasAttribute('formnovalidate')) return;

    var invalidos = [];
    Array.prototype.forEach.call(form.elements, function (campo) {
      if (!campo.willValidate || campo.disabled) return;
      limpar(campo);
      if (!campo.checkValidity()) invalidos.push(campo);
    });
    if (!invalidos.length) return;

    ev.preventDefault();
    ev.stopPropagation();
    invalidos.forEach(marcar);
    var primeiro = invalidos[0];
    // Um campo escondido dentro de um <details> fechado não dá para corrigir.
    var dobra = primeiro.closest('details');
    if (dobra && !dobra.open) dobra.open = true;
    primeiro.focus({ preventScroll: true });
    primeiro.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, true);

  document.addEventListener('input', function (ev) {
    var campo = ev.target;
    if (campo && campo.willValidate && campo.checkValidity()) limpar(campo);
  });
  document.addEventListener('change', function (ev) {
    var campo = ev.target;
    if (campo && campo.willValidate && campo.checkValidity()) limpar(campo);
  });
})();
