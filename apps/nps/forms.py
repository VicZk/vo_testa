from django import forms


class RespostaForm(forms.Form):
    nota = forms.TypedChoiceField(label="De 0 a 10, quanto você recomendaria a pousada?",
        choices=[(i, str(i)) for i in range(11)], coerce=int, widget=forms.RadioSelect)
    comentario = forms.CharField(label="Conte o que foi bom e o que podemos melhorar",
        required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Seu comentário é opcional"}))
    consentimento = forms.BooleanField(label="Autorizo o uso desta avaliação pela equipe da pousada para melhorar o atendimento e entrar em contato sobre meu relato. A participação é voluntária.")
