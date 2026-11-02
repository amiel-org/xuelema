"""Validate a dashboard JSON without starting a server or exposing its contents."""
import argparse
import json
from pathlib import Path
from server import validate

parser = argparse.ArgumentParser(description="校验学了么看板数据")
parser.add_argument("data", type=Path)
args = parser.parse_args()
data = validate(json.loads(args.data.read_text(encoding="utf-8")))
print(json.dumps({
    "ok": True,
    "subjects": len(data["subjects"]),
    "targets": len(data["targets"]),
    "records": len(data["records"]),
    "reviews": len(data["reviews"]),
    "locks": data["locks"],
}, ensure_ascii=False, indent=2))
