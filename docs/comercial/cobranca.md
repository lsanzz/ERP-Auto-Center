# Cobrança das oficinas

## Como o sistema controla o pagamento
Cada instalação tem uma assinatura, controlada por você no painel do dono do sistema, em **`/sistema/admin` → Assinatura desta instalação**.

| Campo | Efeito |
|---|---|
| **Plano** | Essencial, Profissional ou Gestão (informativo) |
| **Pago até** | Data até a qual a mensalidade está paga. Sem data, o acesso não é controlado (use isso só na sua própria oficina) |
| **Suspender agora** | Bloqueia na hora, independentemente da data |

**O que a oficina vê:**
1. Até a data paga, tudo funciona normalmente.
2. Do 1º ao 7º dia de atraso (carência), aparece uma faixa vermelha em todas as telas: "A assinatura está em atraso. O acesso será bloqueado em DD/MM/AAAA."
3. A partir do 8º dia, todas as telas e a API mostram "Assinatura suspensa", com o botão de falar com o suporte. O administrador ainda consegue **baixar todos os dados**, como exige o contrato e a LGPD. Nada é apagado.
4. Ao receber o pagamento, você avança o **Pago até** no painel e o acesso volta na hora.

## Rotina mensal sugerida (manual, sem custo de integração)
1. **Dia 1:** envie a cobrança a cada oficina (Pix com QR Code, ou boleto pelo seu banco).
2. **Ao receber:** abra `/sistema/admin` da instalação e atualize **Pago até** para o último dia do mês pago.
3. **No vencimento sem pagamento:** o sistema avisa sozinho. Mande um lembrete pelo WhatsApp.
4. **No 8º dia:** o bloqueio é automático. Combine a regularização.

## Quando automatizar
Com mais de cerca de 10 oficinas, vale usar um gateway que emita Pix, boleto e cartão recorrente e avise o pagamento por webhook: **Asaas** (recomendado pelo custo e pela facilidade com Pix e boleto no Brasil), Iugu ou Stripe. A integração seria:

1. Criar a assinatura no gateway para cada oficina.
2. Receber o webhook "pagamento confirmado".
3. Atualizar `subscription_paid_until` automaticamente.

Para isso eu preciso que você abra a conta no gateway e me passe a chave da API como variável de ambiente, nunca no chat.

## Nota fiscal da mensalidade
A mensalidade é prestação de serviço: emita NFS-e da sua empresa para cada oficina, todo mês. Confirme com seu contador o código de serviço (geralmente 1.05, licenciamento de software, ou 1.07, suporte técnico) e o ISS do seu município.
