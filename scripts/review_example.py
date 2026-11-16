"""Explicit local maintainer approval. No LLM, live writes, or public-admin approval path."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine

from database import initialize_demo
from sql_examples import EXAMPLES_PATH, approve_example, load_examples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve", required=True, metavar="DRAFT_ID")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--review-note", required=True, help="Explain the metric, filters, grain and edge cases you reviewed.")
    parser.add_argument("--expected-results", type=Path, required=True, help="JSON array of independently reviewed fixture rows.")
    parser.add_argument("--collection", type=Path, default=EXAMPLES_PATH)
    args = parser.parse_args()
    records = list(load_examples(args.collection))
    index = next((i for i, record in enumerate(records) if record["id"] == args.approve), None)
    if index is None:
        parser.error("The draft ID is not in the collection.")
    expected = json.loads(args.expected_results.read_text(encoding="utf-8"))
    engine = create_engine("sqlite:///:memory:")
    try:
        initialize_demo(engine)
        records[index] = approve_example(records[index], engine, reviewer=args.reviewer,
                                         review_note=args.review_note, expected_rows=expected)
    finally:
        engine.dispose()
    output = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.collection.resolve().parent,
                                     prefix="reviewed-examples-", suffix=".tmp", delete=False) as handle:
        handle.write(output)
        temporary = Path(handle.name)
    temporary.replace(args.collection)
    print("Approved the reviewed draft against the disposable fixture. Live data was not changed.")


if __name__ == "__main__":
    main()
