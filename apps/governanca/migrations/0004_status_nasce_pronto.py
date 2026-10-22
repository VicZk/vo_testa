"""Quarto sem registro de limpeza nasce PRONTO, não "Limpo a conferir".

Só o padrão do campo muda: nenhuma linha existente é tocada (quem já está sujo,
em limpeza, limpo ou inspecionado continua onde está). O padrão antigo ("Limpo")
punha todo quarto novo na fila de inspeção da supervisora sem ninguém ter entrado
nele — num banco novo a tela anunciava "Faltam 23 quartos para a casa ficar
pronta".
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('governanca', '0003_conferencia_ocupacao_e_inspecao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='statuslimpeza',
            name='situacao',
            field=models.CharField(choices=[('limpa', 'Limpo'), ('suja', 'Sujo'), ('em_limpeza', 'Em limpeza'), ('inspecionada', 'Inspecionado')], default='inspecionada', max_length=12, verbose_name='situação'),
        ),
    ]
