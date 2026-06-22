import sys, chromadb
from sentence_transformers import SentenceTransformer
model=SentenceTransformer("all-MiniLM-L6-v2")
col=chromadb.PersistentClient(path="chroma_db").get_collection("daytradewarrior")
q=" ".join(sys.argv[1:]) or input("Question: ")
qe=model.encode([q], normalize_embeddings=True).tolist()
r=col.query(query_embeddings=qe, n_results=6)
for doc,m,dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
    print(f'\n[score {1-dist:.2f}] {m["title"]}  {m["url"]}')
    print(doc[:300]+("..." if len(doc)>300 else ""))
