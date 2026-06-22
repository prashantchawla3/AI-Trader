import json, re, chromadb
from sentence_transformers import SentenceTransformer
CORPUS="transcripts_combined.jsonl"; DB_DIR="chroma_db"; NAME="daytradewarrior"
MODEL="all-MiniLM-L6-v2"; BATCH=256
def sents(t): return [p.strip() for p in re.split(r'(?<=[.!?])\s+', t) if p.strip()]
def chunk(text, target=250, overlap=50):
    out=[]; cur=[]; cw=0
    for s in sents(text):
        w=len(s.split())
        if cw+w>target and cur:
            out.append(" ".join(cur)); tail=[]; tw=0
            for ss in reversed(cur):
                tail.insert(0,ss); tw+=len(ss.split())
                if tw>=overlap: break
            cur=tail[:]; cw=tw
        cur.append(s); cw+=w
    if cur: out.append(" ".join(cur))
    return out
print("Loading model..."); model=SentenceTransformer(MODEL)
client=chromadb.PersistentClient(path=DB_DIR)
try: client.delete_collection(NAME)
except: pass
col=client.create_collection(NAME, metadata={"hnsw:space":"cosine"})
ids=[];docs=[];metas=[]
def flush():
    global ids,docs,metas
    if not ids: return
    emb=model.encode(docs, normalize_embeddings=True, show_progress_bar=False).tolist()
    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=emb)
    ids=[];docs=[];metas=[]
nv=nc=0
for line in open(CORPUS):
    if not line.strip(): continue
    d=json.loads(line); nv+=1
    for i,ch in enumerate(chunk(d["text"])):
        ids.append(f'{d["id"]}_{i}'); docs.append(ch)
        metas.append({"video_id":d["id"],"title":d.get("title","") or "","url":d.get("url","") or "","chunk":i}); nc+=1
        if len(ids)>=BATCH: flush()
    if nv%200==0: print(f"  {nv} videos -> {nc} chunks")
flush()
print(f"Done. {nv} videos, {nc} chunks indexed in {DB_DIR}/")
