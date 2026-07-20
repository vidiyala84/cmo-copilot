"""Export each benchmark question's campaign-level data as a parquet file.

One file per question in data/questions/<id>.parquet — the full 300-campaign ×
90-day table AFTER that question's perturbation, at the raw daily grain (the same
data the group rollups and answers are computed from). Plus a manifest.csv that
maps each question to its difficulty, correct answer, and file.

    python -m scripts.export_data  ->  data/questions/{SIM,MED,CPX}*.parquet + manifest.csv
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

import pandas as pd  # noqa: E402

from cmo.benchmark import generate  # noqa: E402
from cmo.datagen import generate_base  # noqa: E402
from cmo.tools import ScenarioEnv  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "questions"


def _answer(exp):
    if exp.get("plan"):
        return "PLAN: " + "; ".join(f"{it['action']}@{it['group'] or 'NEW'}" for it in exp["plan"])
    tgt = exp["acceptable_targets"][0] if exp["acceptable_targets"] else ""
    return f"{exp['root_cause']} -> {exp['action']}" + (f" ({tgt})" if tgt else "")


def export():
    OUT.mkdir(parents=True, exist_ok=True)
    base = generate_base()
    manifest = []
    for sc in generate():
        env = ScenarioEnv(base, sc)
        df = pd.DataFrame(env.rows)
        f = OUT / f"{sc['id']}.parquet"
        df.to_parquet(f, index=False)  # pyarrow, snappy-compressed
        manifest.append({
            "question_id": sc["id"], "difficulty": sc["difficulty"], "name": sc["name"],
            "correct_answer": _answer(sc["expected"]),
            "n_rows": len(df), "n_campaigns": df["campaign_id"].nunique(),
            "n_days": df["day"].nunique(), "file": f"questions/{f.name}",
        })
    man = pd.DataFrame(manifest)
    man.to_csv(OUT / "manifest.csv", index=False)
    total_mb = sum(p.stat().st_size for p in OUT.glob("*.parquet")) / 1e6
    print(f"wrote {len(manifest)} parquet files ({total_mb:.1f} MB) + manifest.csv -> {OUT}")
    print(f"each file: {manifest[0]['n_rows']} rows × {len(pd.read_parquet(OUT/(manifest[0]['question_id']+'.parquet')).columns)} cols "
          f"({manifest[0]['n_campaigns']} campaigns × {manifest[0]['n_days']} days)")


if __name__ == "__main__":
    export()
