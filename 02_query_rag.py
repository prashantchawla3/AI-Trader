#!/usr/bin/env python3
"""
02_query_rag.py  —  Ask questions across all transcripts; get synthesized
answers with citations to the specific videos.

Retrieves the most relevant transcript chunks (local embeddings) and asks the
LLM to answer using ONLY those chunks, citing video titles/URLs.

    python 02_query_rag.py                       # interactive
    python 02_query_rag.py "best RSI strategies" # one-shot

Setup:
    pip install chromadb sentence-transformers anthropic   # (or openai)
    export ANTHROPIC_API_KEY=...    # or LLM_PROVIDER=ollama for local
"""
import sys
import chromadb
from sentence_transformers import SentenceTransformer
from llm import chat

DB_DIR="vectordb"; COLLECTION="trading_transcripts"
EMBED_MODEL="BAAI/bge-small-en-v1.5"; TOP_K=12

SYSTEM = ("You are a quantitative-trading research assistant. Answer ONLY from "
 "the provided transcript excerpts. Synthesize across sources, be concrete about "
 "indicators, parameters, entry/exit rules and timeframes when present, and cite "
 "the video title after each claim like [Title]. If the excerpts don't cover it, "
 "say so. Remind the user that described strategies are unverified and must be "
 "independently backtested; this is not financial advice.")

def main():
    embedder = SentenceTransformer(EMBED_MODEL)
    col = chromadb.PersistentClient(path=DB_DIR).get_collection(COLLECTION)

    def answer(q):
        qe = embedder.encode([q]).tolist()
        res = col.query(query_embeddings=qe, n_results=TOP_K)
        ctx = []
        for doc, m in zip(res["documents"][0], res["metadatas"][0]):
            tag = m.get("title") or m.get("video_id")
            ctx.append(f"[{tag}] ({m.get('url','')})\n{doc}")
        context = "\n\n---\n\n".join(ctx)
        user = f"Transcript excerpts:\n\n{context}\n\nQuestion: {q}"
        print("\n" + chat(SYSTEM, user, max_tokens=1500) + "\n")

    if len(sys.argv) > 1:
        answer(" ".join(sys.argv[1:])); return
    print("RAG assistant ready. Ask a question (blank line to quit).")
    while True:
        try: q = input("\n> ").strip()
        except EOFError: break
        if not q: break
        answer(q)

if __name__ == "__main__":
    main()
