#!/usr/bin/env python3
"""
01_build_rag.py  —  Build a searchable vector index over all transcripts.

Reads every transcripts/*.txt, splits into overlapping chunks, embeds them with
a LOCAL open-source model (free, private), and stores them in a persistent
Chroma vector database. Citations (video title/url) come from manifest.csv.

Run once after you've extracted transcripts:
    python 01_build_rag.py
Re-running is safe; it rebuilds the collection from scratch.

Setup:
    pip install chromadb sentence-transformers
"""
import csv, glob, os, re
import chromadb
from sentence_transformers import SentenceTransformer

TRANSCRIPT_DIR = "transcripts"
MANIFEST       = "manifest.csv"
DB_DIR         = "vectordb"
COLLECTION     = "trading_transcripts"
EMBED_MODEL    = "BAAI/bge-small-en-v1.5"   # small, high-quality, runs on CPU
CHUNK_CHARS    = 3000
CHUNK_OVERLAP  = 300

def load_meta():
    meta = {}
    if os.path.exists(MANIFEST):
        for row in csv.DictReader(open(MANIFEST, encoding="utf-8")):
            meta[row["video_id"]] = {"title": row.get("title", ""),
                                     "channel": row.get("channel", ""),
                                     "url": row.get("url", "")}
    return meta

def chunk(text):
    text = re.sub(r"\s+", " ", text).strip()
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + CHUNK_CHARS])
        i += CHUNK_CHARS - CHUNK_OVERLAP
    return out

def main():
    meta = load_meta()
    files = glob.glob(os.path.join(TRANSCRIPT_DIR, "*.txt"))
    if not files:
        print("No transcripts found. Run the transcript extractor first."); return
    print(f"Embedding model: {EMBED_MODEL} (downloads once, ~130MB)")
    embedder = SentenceTransformer(EMBED_MODEL)

    client = chromadb.PersistentClient(path=DB_DIR)
    try: client.delete_collection(COLLECTION)
    except Exception: pass
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    ids, docs, metas = [], [], []
    for fp in files:
        vid = os.path.splitext(os.path.basename(fp))[0]
        m = meta.get(vid, {})
        text = open(fp, encoding="utf-8").read()
        for j, ch in enumerate(chunk(text)):
            ids.append(f"{vid}_{j}")
            docs.append(ch)
            metas.append({"video_id": vid, "chunk": j,
                          "title": m.get("title", ""), "url": m.get("url", ""),
                          "channel": m.get("channel", "")})

    print(f"{len(files)} transcripts -> {len(docs)} chunks. Embedding…")
    B = 256
    for i in range(0, len(docs), B):
        emb = embedder.encode(docs[i:i+B], show_progress_bar=False).tolist()
        col.add(ids=ids[i:i+B], documents=docs[i:i+B],
                metadatas=metas[i:i+B], embeddings=emb)
        print(f"  indexed {min(i+B, len(docs))}/{len(docs)}")
    print(f"\nDone. Vector DB saved in ./{DB_DIR}/  (collection: {COLLECTION})")

if __name__ == "__main__":
    main()
