#!/usr/bin/env python3
"""Package a submission: answer JSON + clean-tree source zip.

Zips from `git archive`, so uncommitted files, local state and junk cannot
leak in. If it is not committed, it is not in the zip -- by design.

Usage: python make_submit.py --level 1 --answer submissions/level1.json
"""
import argparse, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--level", required=True)
    p.add_argument("--answer", required=True)
    a = p.parse_args()

    answer = pathlib.Path(a.answer)
    if not answer.exists():
        sys.exit(f"answer file missing: {answer}")

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("WARNING: uncommitted changes will NOT be in the zip:")
        print(dirty)

    if not (ROOT / "README.md").exists():
        sys.exit("README.md is required in the zip -- write it first")

    out = ROOT / "submissions" / f"level{a.level}"
    out.parent.mkdir(exist_ok=True)
    zip_path = out.with_suffix(".zip")
    subprocess.run(["git", "archive", "-o", str(zip_path), "HEAD"],
                   cwd=ROOT, check=True)

    final_answer = out.with_suffix(".json")
    if answer.resolve() != final_answer.resolve():
        shutil.copy(answer, final_answer)

    print(f"\nzip    : {zip_path}")
    print(f"answer : {final_answer}")
    print("\nRe-run verify.py against THIS answer file before uploading.")


if __name__ == "__main__":
    main()
