import os
import json
import pandas as pd
from datetime import datetime
from collections import Counter

HISTORY_FILE = "output/rating_trend_history.json"


# ---------------------------------------------------------------------------
# 1. Real Weekly Cohort Trends (from actual 'at' review timestamps)
# ---------------------------------------------------------------------------

def compute_weekly_cohorts(total_df, negative_df):
    """
    Groups the scraped reviews by their actual posted week (using the 'at' column).
    This produces REAL data — the week each review was written, not when the
    pipeline ran.

    Returns a list of weekly cohort dicts with WoW trajectory badges.
    """
    if total_df.empty or 'at' not in total_df.columns:
        return []

    df = total_df.copy()
    df['review_date'] = pd.to_datetime(df['at'], errors='coerce')
    df = df.dropna(subset=['review_date'])
    if df.empty:
        return []

    # Derive week boundaries from actual review dates
    df['week_period'] = df['review_date'].dt.to_period('W')
    df['week_start_dt'] = df['week_period'].apply(lambda r: r.start_time)
    df['week_end_dt']   = df['week_period'].apply(lambda r: r.end_time)
    df['week_label']    = df.apply(
        lambda r: f"{r['week_start_dt'].strftime('%b %d')} – {r['week_end_dt'].strftime('%b %d, %Y')}",
        axis=1
    )

    grouped = df.groupby(['week_period', 'week_label', 'week_start_dt'])
    cohort_rows = []

    for (week_period, week_label, week_start_dt), group in grouped:
        total_w = len(group)
        if total_w < 5:          # skip sparse/partial weeks
            continue

        mean_score = group['score'].mean()
        neg_count  = int((group['score'] <= 2).sum())
        neg_pct    = round((neg_count / total_w) * 100, 1)

        # Top complaint for this week from negative reviews in the group
        neg_group = group[group['score'] <= 2]
        top_tag = "N/A"
        if not neg_group.empty and 'tags' in neg_group.columns:
            all_tags = [
                t for tags_list in neg_group['tags']
                for t in (tags_list if isinstance(tags_list, list) else [tags_list])
                if t != 'Uncategorized'
            ]
            if all_tags:
                top_tag = Counter(all_tags).most_common(1)[0][0]

        cohort_rows.append({
            'period':      week_label,
            'sort_key':    week_start_dt,
            'total':       total_w,
            'mean_rating': round(mean_score, 2),
            'neg_count':   neg_count,
            'neg_pct':     neg_pct,
            'top_tag':     top_tag,
        })

    # Sort chronologically and keep the most recent 6 weeks
    cohort_rows.sort(key=lambda x: x['sort_key'])
    cohort_rows = cohort_rows[-6:]

    # Compute WoW trajectory badges
    for i, row in enumerate(cohort_rows):
        if i == 0:
            row['trend_badge'] = "Baseline"
            row['badge_class'] = "badge-neutral"
        else:
            delta = round(row['mean_rating'] - cohort_rows[i - 1]['mean_rating'], 2)
            if delta > 0:
                row['trend_badge'] = f"▲ +{delta:.2f}"
                row['badge_class'] = "badge-up"
            elif delta < 0:
                row['trend_badge'] = f"▼ {delta:.2f}"
                row['badge_class'] = "badge-down"
            else:
                row['trend_badge'] = "— 0.00"
                row['badge_class'] = "badge-neutral"

    return cohort_rows


# ---------------------------------------------------------------------------
# 2. Persistent Run Snapshot Store (each real pipeline run appended)
# ---------------------------------------------------------------------------

def record_run_snapshot(total_df, negative_df):
    """
    Appends the metrics from THIS pipeline run into output/rating_trend_history.json.
    Each entry is a real timestamped snapshot. No fake data is seeded.
    On the first ever run the file simply starts with one entry.
    """
    os.makedirs('output', exist_ok=True)

    # Load existing history (or start fresh)
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []

    # Compute live metrics from real DataFrames
    total_reviews = len(total_df) if not total_df.empty else 0
    neg_reviews   = len(negative_df) if not negative_df.empty else 0
    mean_stars    = round(float(total_df['score'].mean()), 2) if (not total_df.empty and 'score' in total_df.columns) else 0.0
    neg_share     = round((neg_reviews / total_reviews * 100), 1) if total_reviews > 0 else 0.0

    top_complaint = "N/A"
    if not negative_df.empty and 'tags' in negative_df.columns:
        all_tags = [
            t for tags in negative_df['tags']
            for t in (tags if isinstance(tags, list) else [tags])
            if t != 'Uncategorized'
        ]
        if all_tags:
            top_complaint = Counter(all_tags).most_common(1)[0][0]

    # Determine the date range of reviews in this scrape
    date_range = "N/A"
    if not total_df.empty and 'at' in total_df.columns:
        dates = pd.to_datetime(total_df['at'], errors='coerce').dropna()
        if not dates.empty:
            d_min = dates.min().strftime('%b %d, %Y')
            d_max = dates.max().strftime('%b %d, %Y')
            date_range = f"{d_min} → {d_max}"

    now = datetime.now()
    today_date = now.strftime('%Y-%m-%d')

    # Prevent duplicate entry for same calendar day (idempotent re-runs)
    history = [h for h in history if not h.get('timestamp', '').startswith(today_date)]

    snapshot = {
        'timestamp':          now.strftime('%Y-%m-%d %H:%M:%S'),
        'scrape_date_range':  date_range,
        'total_reviews':      total_reviews,
        'mean_rating':        mean_stars,
        'negative_reviews':   neg_reviews,
        'negative_share_pct': neg_share,
        'p0_p1_clusters':     len(negative_df) if not negative_df.empty else 0,
        'top_complaint':      top_complaint,
        'source':             'live_scrape',
    }

    history.append(snapshot)

    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4)

    print(f"[TrendTracker] Snapshot saved → rating_trend_history.json "
          f"({len(history)} run(s) on record)")
    return history


# ---------------------------------------------------------------------------
# 3. Combined entry-point for reporter.py
# ---------------------------------------------------------------------------

def get_trend_data_for_report(total_df, negative_df):
    """
    Returns:
      cohort_rows  – real weekly cohorts built from review timestamps (for the trend table)
      run_history  – list of real pipeline run snapshots (for JSON persistence)
      recovery_str – human-readable overall rating recovery label
    """
    cohort_rows = compute_weekly_cohorts(total_df, negative_df)
    run_history  = record_run_snapshot(total_df, negative_df)

    # Calculate overall rating recovery across the cohorts we found
    if len(cohort_rows) >= 2:
        delta_total = round(cohort_rows[-1]['mean_rating'] - cohort_rows[0]['mean_rating'], 2)
        if delta_total > 0:
            recovery_str = f"▲ +{delta_total:.2f} rating improvement over {len(cohort_rows)} weeks"
        elif delta_total < 0:
            recovery_str = f"▼ {delta_total:.2f} rating decline over {len(cohort_rows)} weeks"
        else:
            recovery_str = f"— Stable rating over {len(cohort_rows)} weeks"
    elif len(cohort_rows) == 1:
        recovery_str = f"First snapshot: {cohort_rows[0]['mean_rating']:.2f} / 5.0"
    else:
        # Fallback: report metrics from the live run snapshot
        if run_history:
            latest = run_history[-1]
            recovery_str = (
                f"Current run: {latest['mean_rating']:.2f} / 5.0 · "
                f"{latest['negative_share_pct']}% negative share"
            )
        else:
            recovery_str = "No trend data available"

    return cohort_rows, run_history, recovery_str
