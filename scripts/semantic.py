"""
Search by meaning. Every indexed document also gets a "meaning vector" from a small multilingual model
(multilingual-e5-small, 8-bit, ~120 MB, MIT licence, works offline, understands Urdu and English), stored in the
same SQLite file - the doc2vec / CocoIndex idea, sized for an 8 GB laptop.

So "woh steel wali deal jo garmiyon mein hui thi" can find "Quotation QT-114 Bilal Steel Mills (June)" even
though none of those words match. Keyword search still runs first; meaning search fills in when it finds nothing
exact, and the doc_find_by_meaning tool uses it directly for vague requests.
"""
import shutil
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
MODELS = ROOT / "data" / "models"
FILES = {"e5-small-int8.onnx": 100_000_000, "e5-tokenizer.json": 1_000_000}
SHA256 = {"e5-small-int8.onnx": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
          "e5-tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"}


def _sha(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
MIRRORS = ["https://github.com/Tawwlel/Jarvis-/releases/download/models/{f}",
           "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/{hf}"]
HF_NAME = {"e5-small-int8.onnx": "onnx/model_quantized.onnx", "e5-tokenizer.json": "tokenizer.json"}
MAX_TOKENS = 256
_model = {}
_lock = threading.Lock()


def _download() -> bool:
    MODELS.mkdir(parents=True, exist_ok=True)
    for f, min_size in FILES.items():
        dest = MODELS / f
        if dest.exists() and dest.stat().st_size >= min_size:
            continue
        for m in MIRRORS:
            try:
                tmp = dest.with_suffix(".part")
                with urllib.request.urlopen(m.format(f=f, hf=HF_NAME[f]), timeout=300) as r, open(tmp, "wb") as out:
                    shutil.copyfileobj(r, out)
                if tmp.stat().st_size >= min_size and _sha(tmp) == SHA256[f]:  # only the exact expected file
                    tmp.replace(dest)
                    break
                tmp.unlink(missing_ok=True)
            except Exception as e:
                print(f"[meaning] download {f} from {m[:40]}... failed: {e}")
        if not dest.exists():
            return False
    return True


def _load():
    with _lock:
        if "sess" in _model:
            return _model
        if not _download():
            return None
        import onnxruntime as ort
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(MODELS / "e5-tokenizer.json"))
        tok.enable_truncation(MAX_TOKENS)
        tok.enable_padding()
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2  # leave the laptop responsive
        sess = ort.InferenceSession(str(MODELS / "e5-small-int8.onnx"), so, providers=["CPUExecutionProvider"])
        _model.update(tok=tok, sess=sess, inputs={i.name for i in sess.get_inputs()})
        return _model


def embed(texts: list[str]):
    """Unit-length vectors (numpy float32, shape [n, 384])."""
    import numpy as np
    m = _load()
    if m is None:
        return None
    enc = m["tok"].encode_batch(texts)
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feed = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in m["inputs"]:
        feed["token_type_ids"] = np.zeros_like(ids)
    out = m["sess"].run(None, feed)[0]  # [n, tokens, 384]
    v = (out * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)
    return (v / np.linalg.norm(v, axis=1, keepdims=True)).astype("float32")


def _passage(name, chat, typ, text):
    return f"passage: {Path(name).stem.replace('_', ' ')}. {typ or ''}. {chat or ''}. {(text or '')[:1500]}"


def update_vectors(batch=16) -> int:
    """Adds meaning vectors for new/changed documents. Returns how many were added."""
    import docsearch
    db = docsearch._db()
    db.execute("CREATE TABLE IF NOT EXISTS vecs(path TEXT PRIMARY KEY, mtime REAL, vec BLOB)")
    todo = db.execute("""SELECT d.path, d.mtime, d.name, d.chat, d.doc_type, d.text FROM docs d
                         LEFT JOIN vecs v ON v.path = d.path WHERE v.path IS NULL OR v.mtime != d.mtime""").fetchall()
    db.execute("DELETE FROM vecs WHERE path NOT IN (SELECT path FROM docs)")
    db.commit()
    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        vec = embed([_passage(n, c, t, x) for _, _, n, c, t, x in chunk])
        if vec is None:
            break
        db.executemany("REPLACE INTO vecs VALUES(?,?,?)",
                       [(p, mt, v.tobytes()) for (p, mt, *_), v in zip(chunk, vec)])
        db.commit()
        done += len(chunk)
    db.close()
    return done


# Roman-Urdu words the model doesn't know: add the English meaning to the question
GLOSSARY = {"bijli": "electricity", "kiraya": "rent", "kirayanama": "rent agreement", "dukaan": "shop", "dukan": "shop",
            "parchi": "receipt", "raseed": "receipt", "kapra": "fabric cloth", "kapre": "fabric cloth",
            "garmi": "summer", "garmiyon": "summer", "sardi": "winter", "sardiyon": "winter", "sauda": "deal",
            "tankhwah": "salary", "naukri": "job", "dawai": "medicine", "gari": "car vehicle", "gaari": "car vehicle",
            "makaan": "house", "zameen": "land plot", "qarz": "loan", "udhaar": "credit loan", "jurmana": "penalty fine",
            "muahida": "agreement contract", "muahidah": "agreement contract", "ijazat": "permission",
            "bank": "bank", "hisaab": "account statement", "khata": "ledger account", "maal": "goods stock",
            "lohay": "steel iron", "loha": "steel iron", "cement": "cement", "taxi": "taxi", "petrol": "petrol fuel",
            "khana": "food", "sabzi": "vegetables groceries", "beema": "insurance", "fees": "fees", "school": "school"}


def _expand(q: str) -> str:
    import re
    extra = [GLOSSARY[w] for w in re.findall(r"[a-z]+", q.lower()) if w in GLOSSARY]
    return q + (" (" + ", ".join(extra) + ")" if extra else "")


def search(query: str, source="any", k=10, min_score=0.78, margin=0.03):
    """[(score, path)] best first. e5 scores bunch together (0.75-0.9), so we keep the top one plus anything
    within `margin` of it, and nothing under `min_score`."""
    import numpy as np
    import docsearch
    q = embed([f"query: {_expand(query)}"])
    if q is None:
        return []
    db = docsearch._db()
    try:
        rows = db.execute("SELECT v.path, v.vec FROM vecs v JOIN docs d ON d.path = v.path"
                          + ("" if source in ("any", "") else " WHERE d.source=?"),
                          () if source in ("any", "") else (source,)).fetchall()
    except Exception:
        rows = []
    db.close()
    if not rows:
        return []
    mat = np.frombuffer(b"".join(v for _, v in rows), dtype="float32").reshape(len(rows), -1)
    sims = mat @ q[0]
    # blend in plain word overlap ("steel" in the question and in the file) - the small model alone mixes up
    # documents that look alike, a shared word settles it
    import re
    words = {w for w in re.findall(r"[a-z]{4,}|[\u0600-\u06FF]{3,}", _expand(query).lower())
             if w not in {"wali", "wala", "jiss", "mein", "document", "file", "that", "with", "from", "the", "about"}}
    cand = np.argsort(-sims)[:max(k * 3, 20)]
    db = docsearch._db()
    scored = []
    for i in cand:
        row = db.execute("SELECT lower(name || ' ' || coalesce(chat,'') || ' ' || substr(text,1,3000)) FROM docs "
                         "WHERE path=?", (rows[i][0],)).fetchone()
        hay = row[0] if row else ""
        hit = sum(1 for w in words if w in hay or (len(w) > 5 and w[:5] in hay))
        scored.append((float(sims[i]) + 0.04 * min(hit, 3), rows[i][0]))
    db.close()
    scored.sort(reverse=True)
    if not scored or scored[0][0] < min_score:
        return []
    top = scored[0][0]
    return [(s, p) for s, p in scored[:k] if s >= max(min_score, top - margin)]


def ready() -> bool:
    return all((MODELS / f).exists() for f in FILES)
