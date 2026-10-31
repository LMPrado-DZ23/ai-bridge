"""Matriz de compatibilidade por provedor.

Regra do projeto: uma capacidade só é anunciada como **verificada** quando existe
evidência real (teste executado contra a API). O que é plausível mas não foi
verificado aparece como `False` com nota — nunca como promessa.

Cada provedor declara:
  chat / responses / streaming / tools / images
e um campo `verified` com as capacidades efetivamente comprovadas.
"""
from __future__ import annotations

CAPABILITIES = ('chat', 'responses', 'streaming', 'tools', 'images')

MATRIX = {
    'OpenAI': {
        'chat': True, 'responses': True, 'streaming': True, 'tools': True, 'images': True,
        'verified': {'chat', 'streaming', 'tools'},
        'notes': 'Responses depende do modelo (gpt-4o/o1 usam /v1/responses).',
    },
    'DeepSeek': {
        'chat': True, 'responses': True, 'streaming': True, 'tools': True, 'images': False,
        'verified': {'chat', 'responses', 'streaming'},
        'notes': 'Responses nativo verificado; tools testadas em turno real do Codex. Sem imagens.',
    },
    'Anthropic (API key)': {
        'chat': False, 'responses': False, 'streaming': True, 'tools': True, 'images': True,
        'verified': {'streaming', 'tools'},
        'notes': 'Protocolo Messages (não é Chat Completions).',
    },
    'Gemini': {
        'chat': True, 'responses': False, 'streaming': True, 'tools': True, 'images': True,
        'verified': {'chat', 'streaming'},
        'notes': 'OpenAI-compat para chat; Responses não validado.',
    },
    'Groq': {
        'chat': True, 'responses': False, 'streaming': True, 'tools': True, 'images': False,
        'verified': {'chat', 'streaming'},
        'notes': 'Chat Completions; Responses não validado.',
    },
    'Mistral': {
        'chat': True, 'responses': False, 'streaming': True, 'tools': True, 'images': False,
        'verified': {'chat'},
        'notes': 'Chat Completions; tools variam por modelo.',
    },
    'OpenRouter': {
        'chat': True, 'responses': False, 'streaming': True, 'tools': True, 'images': True,
        'verified': {'chat', 'streaming'},
        'notes': 'Capacidades dependem do modelo roteado.',
    },
    'Ollama': {
        'chat': True, 'responses': False, 'streaming': True, 'tools': False, 'images': True,
        'verified': {'chat', 'streaming'},
        'notes': 'Local; tools dependem do modelo e do runtime.',
    },
    'Codex (OAuth)': {
        'chat': False, 'responses': True, 'streaming': True, 'tools': True, 'images': True,
        'verified': {'responses', 'streaming'},
        'notes': 'Backend ChatGPT: exige store=false, stream=true e input em lista.',
    },
    'Claude (OAuth)': {
        'chat': False, 'responses': True, 'streaming': True, 'tools': True, 'images': True,
        'verified': {'responses', 'streaming'},
        'notes': 'Anthropic Messages via OAuth da CLI.',
    },
}


def capabilities(provider_name: str) -> dict:
    """Capacidades declaradas + quais foram verificadas com evidência."""
    entry = MATRIX.get(provider_name)
    if not entry:
        return {'known': False, 'capabilities': {c: None for c in CAPABILITIES}, 'verified': set(), 'notes': ''}
    return {
        'known': True,
        'capabilities': {c: bool(entry.get(c)) for c in CAPABILITIES},
        'verified': set(entry.get('verified', set())),
        'notes': entry.get('notes', ''),
    }


def supports(provider_name: str, capability: str) -> bool:
    """True apenas se a capacidade está declarada E foi verificada."""
    if capability not in CAPABILITIES:
        raise ValueError(f'capacidade desconhecida: {capability}')
    data = capabilities(provider_name)
    return data['known'] and capability in data['verified']
