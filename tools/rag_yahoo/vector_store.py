"""Embed article summaries and store/query ChromaDB."""

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import CHROMA_DB_PATH, COLLECTION_NAME, EMBEDDING_MODEL, TOP_K_RESULTS


_embedding_fn = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedding_fn,
    )


def upsert_articles(articles: list[dict]) -> int:
    collection = get_collection()
    ids, documents, metadatas = [], [], []

    for article in articles:
        text = article["condensed_summary"]
        chunks = _splitter.split_text(text)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{article['id']}_{i}"
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "ticker": article["ticker"],
                "title": article["title"],
                "link": article["link"],
                "published": article["published"],
                "rating": article.get("rating", 0),
            })

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(ids)


def semantic_search(query: str, ticker: str | None = None, n_results: int = TOP_K_RESULTS) -> list[dict]:
    collection = get_collection()
    where = {"ticker": ticker} if ticker else None
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({"content": doc, "metadata": meta, "distance": dist})
    return hits


if __name__ == "__main__":
    hits = semantic_search("Where Will Dell Technologies Stock Be in 3 Years")  #"earnings beat revenue growth")
    for h in hits:
        print(f"[{h['metadata']['ticker']}] {h['content'][:100]}  (dist={h['distance']:.3f})")
    print("May be no hits")
