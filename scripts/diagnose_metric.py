"""
Show why a leaderboard metric produces no value.

Rebuilds the exact per-sample context tasks.process_submission would use —
including any Ground Truth Source override — then reports, per sample, which
argument mappings resolve and what the metric returns.

Usage (from the repo root):

    python scripts/diagnose_metric.py <leaderboard_metric_id> [submission_id] [--samples N]

    python scripts/diagnose_metric.py 179            # first submission on the board
    python scripts/diagnose_metric.py 179 512        # a specific submission
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, Sample, Submission, LeaderboardMetric  # noqa: E402
from metric_engine import (evaluate_dynamic_metric, MetricContextBuilder,  # noqa: E402
                           GtSourceContextBuilder, apply_gt_source)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('metric_id', type=int, help='LeaderboardMetric id (the <id> in lm_<id>)')
    ap.add_argument('submission_id', type=int, nargs='?', help='Submission to score (default: first on the board)')
    ap.add_argument('--samples', type=int, default=3, help='How many samples to report (default 3)')
    args = ap.parse_args()

    with app.app_context():
        lm = db.session.get(LeaderboardMetric, args.metric_id)
        if not lm:
            sys.exit(f"No LeaderboardMetric with id {args.metric_id}")

        lb = lm.leaderboard
        mappings = json.loads(lm.arg_mappings or '{}')
        gt_sub = lm.gt_source_submission

        print(f"=== lm_{lm.id}: {lm.target_name or lm.global_metric.name} "
              f"(global metric '{lm.global_metric.name}') ===")
        print(f"  leaderboard      : {lb.id} {lb.name}")
        print(f"  aggregated       : {lm.global_metric.is_aggregated}")
        print(f"  pooling          : {lm.pooling_type} {lm.pooling_percentile or ''}")
        print(f"  tag_filter       : {lm.tag_filter or '(none)'}")
        print(f"  GT source        : {f'submission {gt_sub.id} ({gt_sub.name})' if gt_sub else 'dataset GT (default)'}")
        if lm.gt_source_submission_id and not gt_sub:
            print(f"  !! gt_source_submission_id={lm.gt_source_submission_id} no longer exists")
        print(f"  arg_mappings     : {json.dumps(mappings)}")
        print("  code:")
        for line in (lm.global_metric.python_code or '').splitlines():
            print(f"      {line}")

        sub = (db.session.get(Submission, args.submission_id) if args.submission_id
               else (lb.submissions[0] if lb.submissions else None))
        if not sub:
            sys.exit("No submission to score against — pass a submission_id.")
        print(f"\n  scoring submission: {sub.id} ({sub.name}, status={sub.processing_status})")

        dataset_ids = [d.id for d in lb.datasets] if lb.datasets else [lb.dataset_id]
        samples = Sample.query.filter(Sample.dataset_id.in_(dataset_ids)).limit(args.samples).all()
        if not samples:
            sys.exit("Leaderboard has no samples.")

        folder = os.path.join(app.config['UPLOAD_FOLDER'], 'submissions', str(sub.id))
        ctx_builder = MetricContextBuilder(samples, sub, submission_folder=folder)
        gt_builder = None
        if gt_sub:
            gt_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'submissions', str(gt_sub.id))
            gt_builder = GtSourceContextBuilder(samples, gt_sub, gt_folder)

        for sample in samples:
            context = ctx_builder.context_for(sample)
            if gt_builder:
                override = gt_builder.override_for(sample)
                context = apply_gt_source(context, override)
                print(f"\n  --- {sample.name} ---")
                print(f"      GT source provides: {', '.join(sorted(override)) or '(NOTHING for this sample)'}")
            else:
                print(f"\n  --- {sample.name} ---")

            for arg, key in mappings.items():
                if key.startswith('SCALAR:'):
                    print(f"      {arg:<14} <- {key}")
                elif key in context:
                    print(f"      {arg:<14} <- {key} = {context[key]!r}")
                else:
                    print(f"      {arg:<14} <- {key}   ** MISSING (passed as None) **")

            value, error = evaluate_dynamic_metric(lm.global_metric, context, lm.arg_mappings)
            print(f"      => value: {value!r}")
            if error:
                for line in error.strip().splitlines():
                    print(f"         {line}")


if __name__ == '__main__':
    main()
