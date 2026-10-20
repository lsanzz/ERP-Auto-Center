"""Conversa com o Gemini (Interactions API do SDK google-genai) usando as ferramentas do assistente."""
from __future__ import annotations

import json
import os
import time
from datetime import date

from .tools import DECLARATIONS, run_tool

MAX_ROUNDS = 6
DEFAULT_MODEL = 'gemini-3.8-flash'

SYSTEM_INSTRUCTION = """Você é o assistente do LS Hub, sistema de gestão de uma oficina mecânica no Brasil. Responda sempre em português do Brasil, curto e direto.

Você pode consultar dados e PROPOR ações. Você nunca grava nada: propor_os e propor_alteracao_os só montam um resumo que o usuário confirma na tela. Depois de propor, diga apenas para conferir o resumo e clicar em Confirmar.

Regras para não errar:
- Seja rápido: para abrir O.S., chame propor_os direto com o nome do cliente, a placa e os nomes dos itens como o usuário falou; ela localiza tudo e devolve erro com opções se houver dúvida. Formas de pagamento e funcionários já vêm em cada mensagem: use os ids de lá. Só use as ferramentas de busca quando precisar esclarecer algo. Quando precisar de várias consultas independentes, faça-as na mesma rodada.
- Nunca invente ids, clientes, placas, preços ou valores.
- Se houver mais de um cliente, veículo, serviço ou peça possível, pergunte qual é antes de propor. Se faltar algo essencial (cliente ou itens), pergunte.
- Placas ditadas por voz podem vir separadas ("d s p 2 e 32"): junte as letras e números antes de buscar.
- Use o preço do catálogo, a menos que o usuário diga outro valor.
- Itens que não existem no catálogo podem entrar como avulsos se o usuário disser o valor; avise.
- Se uma ferramenta devolver "erro", explique ao usuário ou corrija e tente de novo; não repita a mesma chamada igual.
- Relatórios: use relatorio_periodo / contas_vencendo e cite exatamente os números devolvidos, em reais (R$ 1.234,56). Não calcule valores novos além de somas simples.
- Datas relativas ("hoje", "ontem", "este mês", "setembro") devem ser convertidas para AAAA-MM-DD usando a data de hoje informada em cada mensagem.
- Assuntos fora da oficina: diga educadamente que só ajuda com o sistema."""


class AssistantUnavailable(RuntimeError):
    pass


def make_client():
    key = os.getenv('GEMINI_API_KEY')
    if not key:
        raise AssistantUnavailable('Assistente não configurado (GEMINI_API_KEY ausente).')
    from google import genai
    return genai.Client(api_key=key)


def enabled() -> bool:
    # Desligado por padrão: no nível gratuito do Gemini as respostas levaram de 50 s a mais de 2 min.
    return os.getenv('ASSISTANT_ENABLED') == '1' and bool(os.getenv('GEMINI_API_KEY'))


def run_turn(user_text: str, previous_id: str | None, user_label: str, client=None) -> tuple[str, str | None, list[dict], list[float]]:
    """Executa um turno: devolve (texto, id da interação, resultados de ferramentas com draft)."""
    client = client or make_client()
    model = os.getenv('GEMINI_MODEL') or DEFAULT_MODEL
    step_input = f'[Hoje é {date.today().isoformat()}. Usuário: {user_label}. {_context()}]\n{user_text}'
    drafts, timings = [], []
    for _ in range(MAX_ROUNDS):
        kwargs = dict(model=model, input=step_input, tools=DECLARATIONS, system_instruction=SYSTEM_INSTRUCTION,
                      generation_config={'thinking_level': os.getenv('GEMINI_THINKING') or 'minimal'})
        if previous_id:
            kwargs['previous_interaction_id'] = previous_id
        started = time.monotonic()
        interaction = client.interactions.create(**kwargs)
        timings.append(round(time.monotonic() - started, 1))
        previous_id = interaction.id
        calls = [step for step in (interaction.steps or []) if getattr(step, 'type', None) == 'function_call']
        if not calls:
            return (interaction.output_text or '').strip() or 'Pronto.', previous_id, drafts, timings
        results = []
        for call in calls:
            result = run_tool(call.name, dict(call.arguments or {}))
            if isinstance(result, dict) and result.get('draft_id'):
                drafts.append(result)
            results.append({'type': 'function_result', 'name': call.name, 'call_id': call.id,
                            'result': json.dumps(result, ensure_ascii=False, default=str)})
        step_input = results
    return 'Não consegui concluir em poucas etapas. Tente dizer o pedido de outro jeito.', previous_id, drafts, timings


def _context() -> str:
    """Listas curtas enviadas em toda mensagem para evitar rodadas extras de ferramenta."""
    from .tools import listar_formas_pagamento, listar_funcionarios
    methods = ', '.join(f"{m['nome']}={m['payment_method_id']}" for m in listar_formas_pagamento()['formas'])
    employees = ', '.join(f"{e['nome']}={e['employee_id']}" for e in listar_funcionarios()['funcionarios'])
    return f'Formas de pagamento (nome=id): {methods}. Funcionários (nome=id): {employees}.'
