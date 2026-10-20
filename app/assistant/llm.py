"""Conversa com o Groq (API compatível com OpenAI, SDK `groq`) usando as ferramentas do assistente."""
from __future__ import annotations

import json
import os
import time
from datetime import date

from .tools import DECLARATIONS, run_tool

MAX_ROUNDS = 6
HISTORY_MESSAGES = 6  # só texto de usuário/assistente; resultados de ferramentas não voltam ao histórico
DEFAULT_MODEL = 'openai/gpt-oss-120b'
TOOLS = [{'type': 'function', 'function': {k: v for k, v in decl.items() if k != 'type'}} for decl in DECLARATIONS]

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
    key = os.getenv('GROQ_API_KEY')
    if not key:
        raise AssistantUnavailable('Assistente não configurado (GROQ_API_KEY ausente).')
    from groq import Groq
    return Groq(api_key=key, timeout=45, max_retries=1)


def enabled() -> bool:
    # O Gemini gratuito levou de 50 s a mais de 2 min por pedido; o assistente usa o Groq.
    return bool(os.getenv('GROQ_API_KEY')) and os.getenv('ASSISTANT_ENABLED') != '0'


def run_turn(user_text: str, history: list[dict] | None, user_label: str, client=None) -> tuple[str, list[dict], list[dict], list[float]]:
    """Executa um turno: devolve (texto, histórico curto atualizado, propostas criadas, tempos de cada chamada)."""
    client = client or make_client()
    model = os.getenv('GROQ_MODEL') or DEFAULT_MODEL
    history = list(history or [])[-HISTORY_MESSAGES:]
    prompt = f'[Hoje é {date.today().isoformat()}. Usuário: {user_label}. {_context()}]\n{user_text}'
    messages = [{'role': 'system', 'content': SYSTEM_INSTRUCTION}, *history, {'role': 'user', 'content': prompt}]
    drafts, timings = [], []
    for _ in range(MAX_ROUNDS):
        options = dict(model=model, messages=messages, tools=TOOLS, tool_choice='auto', temperature=0.2)
        if 'gpt-oss' in model:
            options['reasoning_effort'] = os.getenv('GROQ_REASONING') or 'low'
        started = time.monotonic()
        response = client.chat.completions.create(**options)
        timings.append(round(time.monotonic() - started, 1))
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            reply = (message.content or '').strip() or 'Pronto.'
            history += [{'role': 'user', 'content': user_text}, {'role': 'assistant', 'content': reply[:1500]}]
            return reply, history[-HISTORY_MESSAGES:], drafts, timings
        messages.append({'role': 'assistant', 'content': message.content or '',
                         'tool_calls': [{'id': c.id, 'type': 'function',
                                         'function': {'name': c.function.name, 'arguments': c.function.arguments}} for c in calls]})
        for call in calls:
            try:
                arguments = json.loads(call.function.arguments or '{}')
            except json.JSONDecodeError:
                result = {'erro': 'Argumentos em JSON inválido; tente de novo.'}
            else:
                result = run_tool(call.function.name, arguments if isinstance(arguments, dict) else {})
            if isinstance(result, dict) and result.get('draft_id'):
                drafts.append(result)
            messages.append({'role': 'tool', 'tool_call_id': call.id, 'name': call.function.name,
                             'content': json.dumps(result, ensure_ascii=False, default=str)})
    reply = 'Não consegui concluir em poucas etapas. Tente dizer o pedido de outro jeito.'
    return reply, history, drafts, timings


def _context() -> str:
    """Listas curtas enviadas em toda mensagem para evitar rodadas extras de ferramenta."""
    from .tools import listar_formas_pagamento, listar_funcionarios
    methods = ', '.join(f"{m['nome']}={m['payment_method_id']}" for m in listar_formas_pagamento()['formas'])
    employees = ', '.join(f"{e['nome']}={e['employee_id']}" for e in listar_funcionarios()['funcionarios'])
    return f'Formas de pagamento (nome=id): {methods}. Funcionários (nome=id): {employees}.'
