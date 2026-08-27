"""Print all documents currently stored in ChromaDB."""

from .vector_store import get_collection


def read_all():
    collection = get_collection()
    total = collection.count()
    print(f"Total chunks in store: {total}\n")

    if total == 0:
        print("No documents found.")
        return

    results = collection.get(include=["documents", "metadatas"])

    for i, (doc, meta) in enumerate(zip(results["documents"], results["metadatas"]), 1):
        print(f"[{i}] ── Metadata ──────────────────────────────────────")
        for key, value in meta.items():
            print(f"    {key}: {value}")
        print(f"    ── Chunk ─────────────────────────────────────────")
        print(f"    {doc}")
        print()


if __name__ == "__main__":
    read_all()
