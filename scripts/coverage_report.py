#!/usr/bin/env python3
"""Grade a source_probe.py search JSONL run without making provider requests."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

BUCKETS = ("recent", "older", "non_english", "indie", "upcoming", "ambiguous")
MEDIA = ("movie", "tv", "game")


def read_results(path: Path) -> dict[tuple[str, str, int | None], dict]:
    results = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if "summary" in row:
            continue
        key = (row.get("media_type"), row.get("query"), row.get("expected_id"))
        if key in results:
            raise ValueError(f"duplicate result at line {line_number}: {key}")
        results[key] = row
    return results


def summarize(fixtures: list[dict], results: dict[tuple[str, str, int | None], dict]) -> dict:
    keys = [(item["media_type"], item["query"], item.get("expected_id")) for item in fixtures]
    if len(set(keys)) != len(keys):
        raise ValueError("fixture has duplicate media_type/query/expected_id records")
    groups = defaultdict(list)
    missing = []
    ungraded = []
    for item in fixtures:
        media_type = item["media_type"]
        bucket = item.get("bucket")
        if bucket not in BUCKETS:
            raise ValueError(f"{media_type}/{item['query']}: invalid bucket")
        row = results.get((media_type, item["query"], item.get("expected_id")))
        if row is None:
            missing.append(f"{media_type}:{item['query']}")
            continue
        if "expected_id" not in item:
            ungraded.append(f"{media_type}:{item['query']}")
            continue
        rank = row.get("match_rank")
        if rank is not None and (not isinstance(rank, int) or rank < 1):
            raise ValueError(f"{media_type}/{item['query']}: invalid match rank")
        groups[("media", media_type)].append(rank)
        groups[("bucket", bucket)].append(rank)
        groups[("overall", "all")].append(rank)

    def score(ranks: list[int | None]) -> dict:
        total = len(ranks)
        return {"graded": total, "top_1": sum(rank == 1 for rank in ranks),
                "top_5": sum(rank is not None and rank <= 5 for rank in ranks),
                "top_5_percent": round(100 * sum(rank is not None and rank <= 5 for rank in ranks) / total, 1) if total else None}

    counts = Counter((item["media_type"], item["bucket"]) for item in fixtures)
    complete_fixture = len(fixtures) == 180 and all(counts[(media, bucket)] == 10 for media in MEDIA for bucket in BUCKETS)
    errors = [f"{key[0]}:{key[1]}:{key[2]}" for key, row in results.items() if row.get("error")]
    overall = score(groups[("overall", "all")])
    by_media = {media: score(groups[("media", media)]) for media in MEDIA}
    by_bucket = {bucket: score(groups[("bucket", bucket)]) for bucket in BUCKETS}
    scored_all = overall["graded"] == len(fixtures) and not errors and not missing and not ungraded
    target_met = (
        complete_fixture and scored_all and overall["top_5_percent"] >= 95
        and all(group["top_5_percent"] is not None and group["top_5_percent"] >= 90
                for group in [*by_media.values(), *by_bucket.values()])
    )
    return {"status": "target_met" if target_met else "insufficient_or_below_target",
            "fixture_count": len(fixtures), "complete_180_fixture": complete_fixture,
            "overall": overall, "by_media": by_media, "by_bucket": by_bucket,
            "missing_results": missing, "ungraded_fixtures": ungraded, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[1] / "fixtures" / "smoke.json")
    parser.add_argument("--results", type=Path, required=True, help="JSONL output from source_probe.py search")
    args = parser.parse_args()
    fixtures = json.loads(args.fixture.read_text(encoding="utf-8"))
    print(json.dumps(summarize(fixtures, read_results(args.results)), indent=2))


if __name__ == "__main__":
    main()
