import argparse
import json
from pathlib import Path
from .index import Index


def main():
    parser = argparse.ArgumentParser(description="Local retrieval with verifiable source quotations")
    parser.add_argument("--db", default="evidence.db")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("id")
    add.add_argument("file")
    add.add_argument("--title")
    add.add_argument("--chunk-lines", type=int, default=8)
    for name in ("search", "answer"):
        sub = commands.add_parser(name)
        sub.add_argument("query")
        sub.add_argument("--limit", type=int, default=3)
    commands.add_parser("documents")
    delete = commands.add_parser("delete")
    delete.add_argument("id")
    verify = commands.add_parser("verify")
    verify.add_argument("citation")
    verify.add_argument("quote")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("cases")
    args = parser.parse_args()
    try:
        index = Index(args.db)
        if args.command == "add":
            result = index.add_file(args.id, args.file, title=args.title, lines_per_chunk=args.chunk_lines)
        elif args.command == "search":
            result = index.search(args.query, limit=args.limit)
        elif args.command == "answer":
            result = index.answer(args.query, limit=args.limit)
        elif args.command == "documents":
            result = index.documents()
        elif args.command == "delete":
            result = {"deleted": index.delete(args.id)}
        elif args.command == "verify":
            result = {"valid": index.verify(args.citation, args.quote)}
        else:
            result = index.evaluate(json.loads(Path(args.cases).read_text(encoding="utf-8")))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
