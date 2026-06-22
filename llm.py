"""
llm.py — one small abstraction over the LLM provider, used by the RAG and
strategy-extraction scripts. Switch providers with an env var; no code changes.

  LLM_PROVIDER=anthropic   (default) -> needs ANTHROPIC_API_KEY
  LLM_PROVIDER=openai                -> needs OPENAI_API_KEY
  LLM_PROVIDER=ollama                -> needs a local Ollama server running

Models (override via env LLM_MODEL):
  anthropic default: claude-haiku-4-5   (cheap+fast, great for batch extraction)
  openai    default: gpt-4o-mini
  ollama    default: llama3.1:8b
"""
import os, json, urllib.request

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
MODEL = os.environ.get("LLM_MODEL")

def chat(system: str, user: str, max_tokens: int = 1200, temperature: float = 0.2) -> str:
    if PROVIDER == "anthropic":
        return _anthropic(system, user, max_tokens, temperature)
    if PROVIDER == "openai":
        return _openai(system, user, max_tokens, temperature)
    if PROVIDER == "ollama":
        return _ollama(system, user, temperature)
    raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER}")

def _anthropic(system, user, max_tokens, temperature):
    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    model = MODEL or "claude-haiku-4-5"
    r = client.messages.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        system=system, messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in r.content if b.type == "text")

def _openai(system, user, max_tokens, temperature):
    from openai import OpenAI
    client = OpenAI()  # reads OPENAI_API_KEY
    model = MODEL or "gpt-4o-mini"
    r = client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    return r.choices[0].message.content

def _ollama(system, user, temperature):
    model = MODEL or "llama3.1:8b"
    body = json.dumps({
        "model": model, "stream": False,
        "options": {"temperature": temperature},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request("http://localhost:11434/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["message"]["content"]
