#!/usr/bin/env python3
"""
CLI entrypoint for ML training and scoring operations.

Usage:
    python -m app.ml.cli train [--site-id SITE_ID] [--days DAYS]
    python -m app.ml.cli score [--site-id SITE_ID] [--window WINDOW]
    python -m app.ml.cli list-models [--site-id SITE_ID]
    python -m app.ml.cli check-drift --site-id SITE_ID
    python -m app.ml.cli backfill --site-id SITE_ID --start START --end END
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def cmd_train(args):
    """Train Isolation Forest models."""
    from app.ml.training import TrainingPipeline

    pipeline = TrainingPipeline()

    if args.site_id:
        print(f"Training model for site {args.site_id}...")
        model_version, metrics = pipeline.train_model(
            site_id=args.site_id,
            days=args.days,
            contamination=args.contamination,
            n_estimators=args.n_estimators,
        )

        if model_version:
            print(f"\nTraining successful!")
            print(f"  Model ID: {model_version.model_id}")
            print(f"  Version: {model_version.version}")
            print(f"  Hash: {model_version.content_hash}")
            print(f"\nMetrics:")
            print(f"  Samples: {metrics.get('samples', 'N/A')}")
            print(f"  Features: {metrics.get('features', 'N/A')}")
            print(f"  Unique assets: {metrics.get('unique_assets', 'N/A')}")
            print(f"  Anomalies (train): {metrics.get('n_anomalies_train', 'N/A')}")
            print(f"  Contamination: {metrics.get('contamination_actual', 0):.2%}")

            if args.verbose:
                print(f"\nScore distribution:")
                score_stats = metrics.get('score_stats', {})
                for k, v in score_stats.items():
                    print(f"    {k}: {v:.4f}")
        else:
            print(f"Training failed: {metrics}")
            return 1
    else:
        print("Training models for all active sites...")
        results = pipeline.train_all_sites(
            days=args.days,
            contamination=args.contamination,
            n_estimators=args.n_estimators,
        )

        success = 0
        failed = 0
        for site_id, (mv, metrics) in results.items():
            if mv:
                print(f"  ✓ {site_id}: {mv.model_id} ({metrics.get('samples', 0)} samples)")
                success += 1
            else:
                print(f"  ✗ {site_id}: {metrics.get('error', 'unknown error')}")
                failed += 1

        print(f"\nSummary: {success} succeeded, {failed} failed")

    return 0


def cmd_score(args):
    """Score feature vectors for anomalies."""
    from app.ml.scoring import ScoringEngine

    engine = ScoringEngine()

    if args.window:
        window_start = datetime.fromisoformat(args.window)
    else:
        # Most recent complete window
        now = datetime.utcnow()
        minute = (now.minute // 5) * 5
        window_end = now.replace(minute=minute, second=0, microsecond=0)
        window_start = window_end - timedelta(minutes=5)

    print(f"Scoring window: {window_start}")

    if args.site_id:
        sites = [args.site_id]
    else:
        # Get all active sites
        from sqlalchemy import create_engine, text
        from app.config import get_settings
        settings = get_settings()
        eng = create_engine(settings.database_url)
        with eng.connect() as conn:
            result = conn.execute(text("SELECT id FROM sites WHERE status = 'active'"))
            sites = [str(row[0]) for row in result.fetchall()]

    total_scored = 0
    total_anomalies = 0

    for site_id in sites:
        scores = engine.score_window(site_id, window_start)

        if not scores:
            print(f"  {site_id}: No features to score")
            continue

        anomalies = [s for s in scores if s["is_anomaly"]]
        print(f"  {site_id}: {len(scores)} scored, {len(anomalies)} anomalies")

        total_scored += len(scores)
        total_anomalies += len(anomalies)

        if args.save:
            engine.save_scores(scores)

        if args.verbose and anomalies:
            for a in anomalies[:5]:
                print(f"    - Asset {a['asset_id']}: score={a['anomaly_score']:.3f}")

    print(f"\nTotal: {total_scored} scored, {total_anomalies} anomalies")

    if not args.save:
        print("\nNote: Scores not saved (use --save to persist)")

    return 0


def cmd_list_models(args):
    """List trained models."""
    from app.ml.model_manager import ModelManager

    manager = ModelManager()

    if args.site_id:
        sites = [args.site_id]
    else:
        # List all sites with models
        import os
        from pathlib import Path
        storage_path = Path(os.getenv("MODEL_STORAGE_PATH", "/app/models"))
        if storage_path.exists():
            sites = [d.name for d in storage_path.iterdir() if d.is_dir()]
        else:
            sites = []

    if not sites:
        print("No models found")
        return 0

    for site_id in sites:
        versions = manager.list_versions(site_id, model_type="isolation_forest")

        if not versions:
            continue

        print(f"\nSite: {site_id}")
        print("-" * 60)

        for v in versions:
            metrics = v.metrics
            print(f"  Version {v.version} ({v.created_at.strftime('%Y-%m-%d %H:%M')})")
            print(f"    Hash: {v.content_hash}")
            print(f"    Samples: {metrics.get('samples', 'N/A')}")
            print(f"    Assets: {metrics.get('unique_assets', 'N/A')}")

            if args.verbose:
                print(f"    Contamination: {metrics.get('contamination_actual', 0):.2%}")
                config = v.config
                print(f"    Estimators: {config.get('n_estimators', 'N/A')}")

    return 0


def cmd_check_drift(args):
    """Check for concept drift."""
    from app.ml.scoring import ScoringEngine

    if not args.site_id:
        print("Error: --site-id is required")
        return 1

    engine = ScoringEngine()

    # We need some recent scores to check drift
    # Score a few recent windows first
    print(f"Checking concept drift for site {args.site_id}...")

    now = datetime.utcnow()
    for i in range(args.windows):
        minute = ((now.minute // 5) * 5) - (i * 5)
        window = now.replace(minute=minute % 60, second=0, microsecond=0)
        if minute < 0:
            window = window - timedelta(hours=1)

        scores = engine.score_window(args.site_id, window)
        if scores:
            print(f"  Window {window}: {len(scores)} scores")

    drift_detected, drift_info = engine.check_drift(args.site_id)

    print(f"\nDrift Status: {drift_info.get('status', 'unknown')}")

    if drift_info.get("status") == "insufficient_data":
        print(f"  Need more data: {drift_info.get('samples', 0)} samples")
    else:
        print(f"  Baseline mean: {drift_info.get('baseline_mean', 0):.4f}")
        print(f"  Current mean: {drift_info.get('current_mean', 0):.4f}")
        print(f"  Z-score: {drift_info.get('z_score', 0):.2f}")
        print(f"  Threshold: {drift_info.get('threshold', 0):.2f}")

    if drift_detected:
        print("\n⚠️  DRIFT DETECTED - Consider retraining the model")
        return 1

    return 0


def cmd_backfill(args):
    """Backfill scoring for a historical range."""
    if not all([args.site_id, args.start, args.end]):
        print("Error: --site-id, --start, and --end are required")
        return 1

    from app.ml.scoring import ScoringEngine

    engine = ScoringEngine()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)

    # Round to 5-minute boundaries
    start = start.replace(minute=(start.minute // 5) * 5, second=0, microsecond=0)

    current = start
    total_scored = 0
    total_anomalies = 0

    print(f"Backfilling scores from {start} to {end}")

    while current < end:
        scores = engine.score_window(args.site_id, current)

        if scores:
            engine.save_scores(scores)
            anomalies = sum(1 for s in scores if s["is_anomaly"])
            total_scored += len(scores)
            total_anomalies += anomalies

            if args.verbose:
                print(f"  {current}: {len(scores)} scored, {anomalies} anomalies")

        current += timedelta(minutes=5)

    print(f"\nBackfill complete: {total_scored} scored, {total_anomalies} anomalies")

    return 0


def cmd_feature_importance(args):
    """Show feature importance for a site's model."""
    if not args.site_id:
        print("Error: --site-id is required")
        return 1

    from app.ml.training import TrainingPipeline

    pipeline = TrainingPipeline()
    importance = pipeline.get_feature_importance(args.site_id)

    if not importance:
        print(f"No model or insufficient data for site {args.site_id}")
        return 1

    print(f"\nFeature Importance for site {args.site_id}")
    print("-" * 40)

    for feature, score in importance.items():
        bar = "█" * int(score * 50)
        print(f"  {feature:25s} {score:.3f} {bar}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="NetSentinel ML Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Train command
    train_parser = subparsers.add_parser("train", help="Train Isolation Forest models")
    train_parser.add_argument("--site-id", help="Specific site to train")
    train_parser.add_argument("--days", type=int, default=14, help="Days of data to use")
    train_parser.add_argument("--contamination", type=float, default=0.05, help="Expected anomaly rate")
    train_parser.add_argument("--n-estimators", type=int, default=100, help="Number of trees")

    # Score command
    score_parser = subparsers.add_parser("score", help="Score feature vectors")
    score_parser.add_argument("--site-id", help="Specific site to score")
    score_parser.add_argument("--window", help="Specific window (ISO format)")
    score_parser.add_argument("--save", action="store_true", help="Save scores to database")

    # List models command
    list_parser = subparsers.add_parser("list-models", help="List trained models")
    list_parser.add_argument("--site-id", help="Specific site")

    # Check drift command
    drift_parser = subparsers.add_parser("check-drift", help="Check for concept drift")
    drift_parser.add_argument("--site-id", required=True, help="Site to check")
    drift_parser.add_argument("--windows", type=int, default=50, help="Windows to analyze")

    # Backfill command
    backfill_parser = subparsers.add_parser("backfill", help="Backfill scoring for time range")
    backfill_parser.add_argument("--site-id", required=True, help="Site to backfill")
    backfill_parser.add_argument("--start", required=True, help="Start time (ISO format)")
    backfill_parser.add_argument("--end", required=True, help="End time (ISO format)")

    # Feature importance command
    importance_parser = subparsers.add_parser("feature-importance", help="Show feature importance")
    importance_parser.add_argument("--site-id", required=True, help="Site to analyze")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "train": cmd_train,
        "score": cmd_score,
        "list-models": cmd_list_models,
        "check-drift": cmd_check_drift,
        "backfill": cmd_backfill,
        "feature-importance": cmd_feature_importance,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
