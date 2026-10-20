"""Anti-robô leve para formulários públicos (pedido de proposta, páginas de captação).

Duas camadas silenciosas, sem captcha:
- **armadilha**: um campo que pessoas não veem nem preenchem (fora da tela, sem foco,
  oculto do leitor de tela); robô que preenche tudo se denuncia;
- **tempo mínimo**: um carimbo assinado com a hora em que o formulário foi montado;
  envio em menos de `TEMPO_MINIMO` segundos não é de gente.

Quem chama finge sucesso para o robô (não revela a defesa) e descarta o envio.
Carimbo vencido (aba aberta por horas) ou ausente (página em cache antiga) não bloqueia:
na dúvida, o lead de verdade passa.
"""
import time

from django.core import signing

CAMPO_ARMADILHA = "empresa_site"
CAMPO_CARIMBO = "form_ts"
TEMPO_MINIMO = 2.0  # segundos
_SAL = "antirrobo"


def carimbo() -> str:
    return signing.dumps(time.time(), salt=_SAL)


def parece_robo(dados) -> bool:
    """`dados` = request.POST (ou um dict). True se caiu na armadilha ou foi rápido
    demais para ser gente."""
    if (dados.get(CAMPO_ARMADILHA) or "").strip():
        return True
    bruto = dados.get(CAMPO_CARIMBO) or ""
    if not bruto:
        return False
    try:
        inicio = float(signing.loads(bruto, salt=_SAL, max_age=12 * 3600))
    except signing.SignatureExpired:
        return False
    except (signing.BadSignature, TypeError, ValueError):
        return True  # carimbo forjado
    return (time.time() - inicio) < TEMPO_MINIMO
