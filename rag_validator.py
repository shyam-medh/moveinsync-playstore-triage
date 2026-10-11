import sys
import io
# Force UTF-8 on Windows so unicode log messages don't crash
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
rag_validator.py  -- Full RAG Stack
------------------------------------
Stack:
  - Scraping     : requests + BeautifulSoup
  - Embeddings   : sentence-transformers (all-MiniLM-L6-v2) — runs locally, free
  - Vector DB    : ChromaDB  (in-memory, no server needed)
  - LLM Verdict  : Gemini API (google-generativeai)

Pipeline per review:
  1. Heuristic pre-filter  (too short / star-text mismatch)
  2. Semantic relevance    (ChromaDB cosine search against MoveInSync KB)
  3. LLM final verdict     (Gemini: "Is this a real, actionable bug?")
  4. Semantic deduplication (cluster similar validated reviews → 1 ticket/bug)
"""

import os
import re
import time
import requests
import chromadb
from google import genai
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer
from collections import defaultdict

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

KNOWLEDGE_BASE_URLS = [
    "https://play.google.com/store/apps/details?id=com.moveinsync.ets&hl=en&gl=in",
    "https://www.moveinsync.com/",
    "https://www.moveinsync.com/employee-transport/",
]

FALLBACK_CORPUS = """
MoveInSync is a B2B employee transportation management platform.
Features: real-time GPS cab tracking, OTP-based trip verification,
driver app with navigation, route optimization, employee pickup/drop scheduling,
push notifications for cab ETA, SOS emergency button, female safety features,
trip history, expense reporting, geofencing alerts, admin fleet dashboard,
multi-city transport, Android and iOS apps.
Common issues reported: GPS lag, OTP not received, app crash, login failure,
cab location not updating, driver not showing on map, app freezing on splash screen.
"""

# Thresholds
MIN_WORD_COUNT       = 5       # reviews shorter than this are rejected
RELEVANCE_THRESHOLD  = 0.65   # ChromaDB cosine distance cutoff (0=identical, 1=opposite)
DEDUP_THRESHOLD      = 0.58   # cosine similarity to cluster two reviews as "same bug"
MAX_LLM_CALLS        = 40     # cap Gemini calls to avoid quota burn

# ---------------------------------------------------------------------------
# STEP 0 — Initialise models & clients (done once, shared globally)
# ---------------------------------------------------------------------------

print("[RAG] Loading sentence-transformer model (first run may download ~80 MB)...")
_EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")

_GENAI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)

# In-memory ChromaDB (no disk, no server)
_CHROMA_CLIENT = chromadb.Client()

# ---------------------------------------------------------------------------
# STEP 1 — Build Knowledge Base
# ---------------------------------------------------------------------------

def _scrape_url(url: str, timeout: int = 8) -> str:
    """Fetch a URL and return clean plain text using BeautifulSoup."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; MoveInSyncTriageBot/2.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove script, style, nav clutter
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = re.sub(r'\s+', ' ', text)
            return text[:10000]
    except Exception as e:
        print(f"[RAG]   ✗ Scrape failed ({url[:50]}): {e}")
    return ""


def _chunk_text(text: str, chunk_size: int = 120, overlap: int = 40) -> list[str]:
    """Split text into overlapping word-level chunks."""
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i: i + chunk_size])
        if len(chunk) > 30:
            chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


def build_knowledge_base() -> chromadb.Collection:
    """
    Scrape MoveInSync public pages, embed with sentence-transformers,
    store in ChromaDB. Returns the collection for retrieval.
    """
    print("[RAG] Building knowledge base...")

    all_text = FALLBACK_CORPUS
    for url in KNOWLEDGE_BASE_URLS:
        scraped = _scrape_url(url)
        if scraped:
            all_text += " " + scraped
            print(f"[RAG]   ✓ Scraped: {url[:65]}")
        else:
            print(f"[RAG]   ✗ Using fallback for: {url[:65]}")

    chunks = _chunk_text(all_text)

    # Embed all chunks
    print(f"[RAG] Embedding {len(chunks)} knowledge chunks...")
    embeddings = _EMBEDDER.encode(chunks, show_progress_bar=False).tolist()

    # Store in ChromaDB
    try:
        _CHROMA_CLIENT.delete_collection("mis_kb")
    except Exception:
        pass

    collection = _CHROMA_CLIENT.create_collection(
        name="mis_kb",
        metadata={"hnsw:space": "cosine"}
    )
    collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=[f"chunk_{i}" for i in range(len(chunks))]
    )
    print(f"[RAG] Knowledge base ready: {len(chunks)} chunks in ChromaDB.")
    return collection


# ---------------------------------------------------------------------------
# STEP 2 — Heuristic Pre-filter
# ---------------------------------------------------------------------------

_POSITIVE_WORDS = {
    'good', 'great', 'excellent', 'love', 'best', 'awesome',
    'perfect', 'nice', 'amazing', 'fantastic', 'superb', 'brilliant'
}

def _heuristic_filter(text: str, score: int) -> tuple[bool, str]:
    """
    Quick checks before hitting ChromaDB or Gemini.
    Returns (passes: bool, rejection_reason: str).
    """
    words = text.split()
    if len(words) < MIN_WORD_COUNT:
        return False, f"Too short ({len(words)} words)"

    tokens = set(text.lower().split())
    if score <= 2 and len(tokens & _POSITIVE_WORDS) >= 2:
        return False, "Star/text mismatch — likely bot or spam"

    return True, ""


# ---------------------------------------------------------------------------
# STEP 3 — ChromaDB Semantic Relevance Check
# ---------------------------------------------------------------------------

def _is_relevant(text: str, collection: chromadb.Collection) -> tuple[bool, float]:
    """
    Embed the review and query ChromaDB.
    Returns (is_relevant, best_distance).
    Distance in cosine space: 0.0 = identical, 2.0 = opposite.
    """
    embedding = _EMBEDDER.encode([text]).tolist()
    results = collection.query(
        query_embeddings=embedding,
        n_results=3,
        include=["distances"]
    )
    distances = results["distances"][0]
    best_dist = min(distances) if distances else 2.0
    return best_dist <= RELEVANCE_THRESHOLD, round(best_dist, 4)


# ---------------------------------------------------------------------------
# STEP 4 — Gemini LLM Final Verdict
# ---------------------------------------------------------------------------

_GEMINI_PROMPT = """You are a quality engineer at MoveInSync, a B2B employee transport app.
A user left this review on the Play Store:

REVIEW: "{review}"
STAR RATING: {score}/5

Answer with EXACTLY one word: REAL or FAKE.
- REAL = this is a genuine complaint about a real feature of an employee transport app
- FAKE = this is spam, off-topic, irrelevant, or not about transport software

ONE WORD ONLY:"""

_llm_call_count = 0

def _gemini_verdict(text: str, score: int, dist: float = 0.5) -> bool:
    """Call Gemini to make the final real/fake decision on ambiguous reviews. Returns True if REAL."""
    global _llm_call_count
    # Strong vector match (< 0.48 distance to MoveInSync docs) is automatically genuine
    if dist < 0.48:
        return True

    if _llm_call_count >= MAX_LLM_CALLS:
        return True  # assume valid if quota exceeded

    try:
        prompt = _GEMINI_PROMPT.format(review=text[:400], score=score)
        response = _GENAI_CLIENT.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        verdict = response.text.strip().upper()
        _llm_call_count += 1
        return verdict.startswith("REAL")
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            print(f"[RAG]   Gemini free-tier rate limit reached ({_llm_call_count} calls made). Gracefully failing open for remaining reviews.")
            _llm_call_count = MAX_LLM_CALLS
        else:
            print(f"[RAG]   Gemini call failed: {e}")
        return True   # fail open — don't drop reviews on API errors


# ---------------------------------------------------------------------------
# STEP 5 — Semantic Deduplication
# ---------------------------------------------------------------------------

def deduplicate_reviews(records: list[dict]) -> list[dict]:
    """
    Cluster reviews using sentence-transformer embeddings + cosine similarity.
    Returns one enriched representative per cluster.

    Each cluster representative gets:
      - affected_users     : number of users reporting this bug
      - sample_reviews     : up to 3 example texts
      - max_severity       : lowest star rating in cluster
      - rag_relevance_score: distance from knowledge base
    """
    if not records:
        return []

    texts = [str(r.get('content', '')) for r in records]
    embeddings = _EMBEDDER.encode(texts, show_progress_bar=False)

    # Greedy clustering
    assigned = [-1] * len(records)
    clusters: list[list[int]] = []

    for i in range(len(records)):
        if assigned[i] != -1:
            continue
        cluster = [i]
        assigned[i] = len(clusters)
        for j in range(i + 1, len(records)):
            if assigned[j] != -1:
                continue
            # Cosine similarity via dot product of L2-normalised vectors
            ei = embeddings[i] / (embeddings[i].dot(embeddings[i]) ** 0.5 + 1e-9)
            ej = embeddings[j] / (embeddings[j].dot(embeddings[j]) ** 0.5 + 1e-9)
            sim = float(ei.dot(ej))
            if sim >= DEDUP_THRESHOLD:
                cluster.append(j)
                assigned[j] = len(clusters)
        clusters.append(cluster)

    result = []
    for cluster_indices in clusters:
        cluster_records = [records[i] for i in cluster_indices]
        # Pick the most severe (lowest star) as representative
        rep = min(cluster_records, key=lambda r: r.get('score', 5))
        enriched = dict(rep)
        enriched['affected_users']      = len(cluster_indices)
        enriched['sample_reviews']      = [records[i]['content'] for i in cluster_indices[:3]]
        enriched['max_severity']        = min(r.get('score', 5) for r in cluster_records)
        result.append(enriched)

    result.sort(key=lambda r: r['affected_users'], reverse=True)
    print(f"[RAG] Deduplication: {len(records)} reviews → {len(result)} unique bug clusters.")
    return result


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def run_rag_validation(negative_df):
    """
    Full RAG pipeline:
      Step 1 → Build knowledge base (scrape + embed + ChromaDB)
      Step 2 → Heuristic pre-filter
      Step 3 → ChromaDB semantic relevance check
      Step 4 → Gemini LLM final verdict
      Step 5 → Semantic deduplication

    Returns enriched DataFrame of validated, deduplicated bugs.
    """
    import pandas as pd

    collection = build_knowledge_base()
    records = negative_df.to_dict('records')

    valid_records = []
    stats = defaultdict(int)

    for r in records:
        text  = str(r.get('content', ''))
        score = int(r.get('score', 1))

        # Step 2: Heuristic
        passes, reason = _heuristic_filter(text, score)
        if not passes:
            stats['heuristic_rejected'] += 1
            print(f"[RAG] ✗ HEURISTIC: \"{text[:55]}\" → {reason}")
            continue

        # Step 3: ChromaDB relevance
        relevant, dist = _is_relevant(text, collection)
        if not relevant:
            stats['relevance_rejected'] += 1
            print(f"[RAG] ✗ OFF-TOPIC (dist={dist}): \"{text[:55]}\"")
            continue

        # Step 4: Gemini verdict on ambiguous reviews
        is_real = _gemini_verdict(text, score, dist)
        if not is_real:
            stats['gemini_rejected'] += 1
            print(f"[RAG] ✗ GEMINI FAKE: \"{text[:55]}\"")
            continue

        r['rag_relevance_score'] = dist
        valid_records.append(r)
        stats['valid'] += 1

    print(
        f"\n[RAG] Validation summary:"
        f"\n  Total input     : {len(records)}"
        f"\n  ✓ Valid         : {stats['valid']}"
        f"\n  ✗ Too short/spam: {stats['heuristic_rejected']}"
        f"\n  ✗ Off-topic     : {stats['relevance_rejected']}"
        f"\n  ✗ Gemini FAKE   : {stats['gemini_rejected']}"
        f"\n  Gemini API calls: {_llm_call_count}"
    )

    # Step 5: Deduplicate
    deduped = deduplicate_reviews(valid_records)
    return pd.DataFrame(deduped) if deduped else pd.DataFrame()
