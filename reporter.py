import json
import os
from datetime import datetime
from trend_tracker import get_trend_data_for_report


# ---------------------------------------------------------------------------
# Jira Payload Generator
# ---------------------------------------------------------------------------

def create_jira_ticket(review: dict) -> dict:
    """Formats a deduplicated, RAG-validated review into a Jira REST API JSON payload."""
    affected = review.get('affected_users', 1)
    severity = review.get('max_severity', review.get('score', 1))
    tags = review.get('tags', ['Uncategorized'])
    sample_reviews = review.get('sample_reviews', [review.get('content', '')])

    if affected >= 10:
        priority = "Critical"
    elif affected >= 5:
        priority = "High"
    else:
        priority = "Medium"

    samples_text = "\n".join(f"  - \"{str(s)[:120]}\"" for s in sample_reviews)

    return {
        "fields": {
            "project": {"key": "ENG"},
            "summary": f"[{'/'.join(tags)}] Play Store Bug — {affected} user(s) affected: {str(review.get('content', ''))[:60]}...",
            "description": (
                f"*Automated via MoveInSync RAG Triage Pipeline*\n\n"
                f"*Affected Users:* {affected}\n"
                f"*Lowest Rating in Cluster:* {severity}/5\n"
                f"*Category Tags:* {', '.join(tags)}\n"
                f"*RAG Relevance Score:* {review.get('rag_relevance_score', 'N/A')}\n\n"
                f"*Sample User Reviews (validated & deduplicated):*\n{samples_text}\n\n"
                f"*Action Required:* This ticket was auto-generated after semantic deduplication. "
                f"It represents a cluster of {affected} users reporting the same issue. "
                f"Please investigate and resolve."
            ),
            "issuetype": {"name": "Bug"},
            "priority": {"name": priority},
            "labels": ["play-store-triage", "user-reported", "rag-validated", f"affects-{affected}-users"]
        }
    }


def generate_jira_payload(negative_df):
    """Generates the mock_jira_tickets.json file from validated, deduplicated reviews."""
    if negative_df.empty:
        print("No validated reviews to generate Jira tickets from.")
        return

    os.makedirs('output', exist_ok=True)
    candidates = negative_df[negative_df['tags'].apply(lambda x: x != ['Uncategorized'])]
    if candidates.empty:
        candidates = negative_df

    jira_payload = [create_jira_ticket(row.to_dict()) for _, row in candidates.head(10).iterrows()]

    with open('output/mock_jira_tickets.json', 'w', encoding='utf-8') as f:
        json.dump(jira_payload, f, indent=4)
    print(f"Generated output/mock_jira_tickets.json ({len(jira_payload)} unique tickets).")


# ---------------------------------------------------------------------------
# HTML Dashboard Generator (Clean UI, 100% Real Scraped Data)
# ---------------------------------------------------------------------------

def _render_top_bug_clusters(negative_df) -> str:
    """Render top RAG-validated & deduplicated bug clusters."""
    if negative_df.empty or 'affected_users' not in negative_df.columns:
        return "<p class='no-data' style='color:#64748b; font-style:italic;'>No validated bug clusters to display.</p>"

    top = negative_df.sort_values('affected_users', ascending=False).head(5)
    cards = []
    for _, row in top.iterrows():
        affected = row.get('affected_users', 1)
        tags = row.get('tags', ['Uncategorized'])
        content = str(row.get('content', ''))[:180]
        score = row.get('max_severity', row.get('score', 1))
        rag_score = row.get('rag_relevance_score', 'N/A')
        sample_reviews = row.get('sample_reviews', [content])

        tag_pills = " ".join(f'<span class="badge badge-tag">{t}</span>' for t in tags)
        samples_html = "".join(
            f'<li class="sample-review">"{str(s)[:140]}"</li>'
            for s in (sample_reviews if isinstance(sample_reviews, list) else [sample_reviews])[:2]
        )

        badge_class = "badge-p0" if affected >= 4 else "badge-p1"
        badge_label = f"P0 — {affected} Users Affected" if affected >= 4 else f"P1 — {affected} Users Affected"

        cards.append(f"""
        <div class="cluster-card">
            <div class="cluster-header">
                <div class="cluster-tags">
                    <span class="badge {badge_class}">{badge_label}</span>
                    {tag_pills}
                </div>
                <div class="cluster-meta">
                    <span class="meta-pill">⭐ {score}/5 min rating</span>
                    <span class="meta-pill">🤖 RAG: {rag_score}</span>
                </div>
            </div>
            <p class="cluster-summary">"{content}..."</p>
            <div class="sample-box">
                <span class="sample-title">Sample user quotes in this cluster:</span>
                <ul class="sample-list">{samples_html}</ul>
            </div>
        </div>
        """)

    return "\n".join(cards)


def generate_html_dashboard(total_df, raw_negative_df, validated_df=None):
    """
    Generates app_health_report.html with 100% real live data.

    Args:
        total_df:        All 1,000 scraped reviews (for star counts, mean rating, trend cohorts).
        raw_negative_df: All 1-2 star reviews BEFORE RAG filtering (for headline metrics: count, share, categories).
        validated_df:    RAG-validated & deduplicated clusters (for bug cluster cards and Jira tickets).
                         Falls back to raw_negative_df if not provided.
    """
    os.makedirs('output', exist_ok=True)

    # Use raw negative reviews for accurate headline numbers
    neg_df_for_metrics = raw_negative_df if (raw_negative_df is not None and not raw_negative_df.empty) else (validated_df if validated_df is not None else raw_negative_df)
    cluster_df = validated_df if (validated_df is not None and not validated_df.empty) else raw_negative_df

    total_reviews = len(total_df) if not total_df.empty else 0
    neg_reviews   = len(neg_df_for_metrics) if not neg_df_for_metrics.empty else 0
    rag_clusters  = len(cluster_df) if not cluster_df.empty else 0
    mean_stars    = f"{total_df['score'].mean():.2f}" if (not total_df.empty and 'score' in total_df.columns) else "N/A"
    neg_share     = f"{(neg_reviews / total_reviews * 100):.1f}" if total_reviews > 0 else "0.0"

    star_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    if not total_df.empty and 'score' in total_df.columns:
        for s in range(1, 6):
            star_counts[s] = int((total_df['score'] == s).sum())

    # Category mentions from raw negatives (reflects true mention frequency)
    def get_category_count(cat_name):
        if neg_df_for_metrics.empty or 'tags' not in neg_df_for_metrics.columns:
            return 0
        return int(neg_df_for_metrics['tags'].apply(lambda tags: cat_name in (tags if isinstance(tags, list) else [tags])).sum())

    booking_mentions = get_category_count('Booking')
    crash_mentions   = get_category_count('Crashes/Performance')
    gps_mentions     = get_category_count('GPS/Tracking')
    otp_mentions     = get_category_count('OTP/Login')

    def get_pct(count):
        return f"{(count / neg_reviews * 100):.1f}" if neg_reviews > 0 else "0.0"

    booking_pct = get_pct(booking_mentions)
    crash_pct   = get_pct(crash_mentions)
    gps_pct     = get_pct(gps_mentions)
    otp_pct     = get_pct(otp_mentions)

    # Rating Trend: real weekly cohorts from actual review timestamps
    cohort_rows, _run_history, recovery_str = get_trend_data_for_report(total_df, neg_df_for_metrics)

    if cohort_rows:
        trend_tr_list = []
        for tr in cohort_rows:
            trend_tr_list.append(f"""
            <tr>
                <td><strong>{tr['period']}</strong></td>
                <td>{tr['total']:,} reviews</td>
                <td><strong>{tr['mean_rating']:.2f}</strong> / 5.0</td>
                <td>{tr['neg_pct']:.1f}% ({tr['neg_count']} reports)</td>
                <td><span class="badge {tr['badge_class']}">{tr['trend_badge']}</span></td>
            </tr>
            """)
        trend_table_html = "\n".join(trend_tr_list)
    else:
        trend_table_html = "<tr><td colspan='5' style='color:#64748b; font-style:italic; padding:12px;'>No sufficient weekly data in scraped reviews to plot trends. Run the pipeline again next week to build history.</td></tr>"

    clusters_html = _render_top_bug_clusters(cluster_df)
    generated_at = datetime.now().strftime('%B %d, %Y at %H:%M:%S')

    # ---- Actionable next steps: data-driven from real category mention counts ----
    TRIAGE_LIBRARY = {
        'Booking': {
            'action': 'Reproduce failed self-booking across roster, cutoff, and network states; add structured booking error telemetry; fix top confirmed error codes.',
            'track': 'Booking completion rate, booking failures / 1,000 attempts'
        },
        'Crashes/Performance': {
            'action': 'Instrument crashes by app version and device; reproduce highest-frequency stack traces and deploy targeted fixes.',
            'track': 'Crash-free sessions %, app startup p95'
        },
        'GPS/Tracking': {
            'action': 'Measure device GPS accuracy and stale tracking updates; provide refresh/retry UI and last-updated timestamps.',
            'track': 'Location freshness p95, inaccurate pickup reports / day'
        },
        'OTP/Login': {
            'action': 'Trace OTP generation, delivery and verification error rates; implement resend cooldown and clear recoverable error messages.',
            'track': 'OTP verification success %, p95 OTP delivery time'
        },
    }

    # Rank categories by real mention count from live data
    category_counts = {
        'Booking': booking_mentions,
        'Crashes/Performance': crash_mentions,
        'GPS/Tracking': gps_mentions,
        'OTP/Login': otp_mentions,
    }
    # Sort descending by count; only keep categories with at least 1 mention
    ranked = sorted(
        [(cat, count) for cat, count in category_counts.items() if count > 0],
        key=lambda x: x[1],
        reverse=True
    )

    steps_rows = []
    for rank, (cat, count) in enumerate(ranked):
        triage_level = 'P0 candidate' if rank < 2 else 'P1 candidate'
        badge_cls = 'badge-p0' if rank < 2 else 'badge-p1'
        lib = TRIAGE_LIBRARY.get(cat, {
            'action': f'Investigate and resolve the {cat} issues reported by users.',
            'track': f'{cat} error rate, user-reported failures'
        })
        steps_rows.append(f"""
                    <tr>
                        <td>{cat}</td>
                        <td><span class="badge {badge_cls}">{triage_level}</span></td>
                        <td>{lib['action']}</td>
                        <td>{lib['track']}</td>
                    </tr>""")

    if steps_rows:
        actionable_steps_html = '\n'.join(steps_rows)
    else:
        actionable_steps_html = "<tr><td colspan='4' style='color:#64748b; font-style:italic; padding:12px;'>No categorized complaints found in this run.</td></tr>"
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MoveInSync Play Store Review Triage</title>
    <style>
        *, *::before, *::after {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #edf2f7;
            color: #1e293b;
            line-height: 1.5;
            padding: 24px 16px;
        }}

        .container {{
            max-width: 860px;
            margin: 0 auto;
        }}

        .card {{
            background: #ffffff;
            border-radius: 6px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
            padding: 22px 24px;
            margin-bottom: 18px;
        }}

        .header-title {{
            font-size: 1.25rem;
            font-weight: 700;
            color: #0f172a;
            letter-spacing: -0.01em;
        }}

        .header-sub {{
            font-size: 0.75rem;
            color: #64748b;
            margin-top: 4px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}

        .alert-banner {{
            background-color: #fff8ee;
            border: 1px solid #fdecd2;
            border-radius: 4px;
            padding: 10px 14px;
            color: #855307;
            font-size: 0.75rem;
            line-height: 1.45;
            margin-top: 14px;
            margin-bottom: 20px;
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }}

        .metric-box {{
            background-color: #edf2f7;
            border-radius: 6px;
            padding: 10px 14px;
        }}

        .metric-label {{
            font-size: 0.72rem;
            color: #475569;
            font-weight: 500;
            margin-bottom: 3px;
        }}

        .metric-val {{
            font-size: 1.25rem;
            font-weight: 700;
            color: #0f172a;
        }}

        .card-title {{
            font-size: 1rem;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 12px;
        }}

        .card-subtitle {{
            font-size: 0.72rem;
            color: #64748b;
            margin-top: -6px;
            margin-bottom: 12px;
        }}

        .triage-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.775rem;
        }}

        .triage-table th {{
            background-color: #eaf0f6;
            color: #334155;
            font-weight: 600;
            text-align: left;
            padding: 8px 14px;
            font-size: 0.75rem;
        }}

        .triage-table td {{
            padding: 9px 14px;
            color: #334155;
            border-bottom: 1px solid #edf2f7;
            vertical-align: top;
        }}

        .triage-table tr:last-child td {{
            border-bottom: none;
        }}

        .steps-table td {{
            line-height: 1.45;
        }}

        .steps-table td:nth-child(1) {{
            font-weight: 600;
            width: 18%;
        }}

        .steps-table td:nth-child(2) {{
            width: 16%;
        }}

        .steps-table td:nth-child(3) {{
            width: 42%;
        }}

        .steps-table td:nth-child(4) {{
            width: 24%;
            color: #475569;
        }}

        /* ---- Badges & Cluster Cards ---- */
        .badge {{
            display: inline-block;
            font-size: 0.72rem;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 4px;
            white-space: nowrap;
        }}

        .badge-p0 {{
            background-color: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }}

        .badge-p1 {{
            background-color: #fef3c7;
            color: #92400e;
            border: 1px solid #fde68a;
        }}

        .badge-tag {{
            background-color: #edf2f7;
            color: #475569;
            border: 1px solid #e2e8f0;
        }}

        .badge-up {{
            background-color: #dcfce7;
            color: #15803d;
            border: 1px solid #bbf7d0;
        }}

        .badge-down {{
            background-color: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }}

        .badge-neutral {{
            background-color: #f1f5f9;
            color: #475569;
            border: 1px solid #e2e8f0;
        }}

        .cluster-card {{
            border: 1px solid #edf2f7;
            background-color: #fafbfc;
            border-radius: 6px;
            padding: 14px 16px;
            margin-top: 12px;
        }}

        .cluster-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
            flex-wrap: wrap;
            gap: 6px;
        }}

        .cluster-tags {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .cluster-meta {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .meta-pill {{
            font-size: 0.72rem;
            color: #64748b;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            padding: 2px 6px;
            border-radius: 4px;
        }}

        .cluster-summary {{
            font-size: 0.85rem;
            font-weight: 600;
            color: #1e293b;
            margin-bottom: 6px;
            line-height: 1.4;
        }}

        .sample-box {{
            background: #ffffff;
            border: 1px solid #f1f5f9;
            border-radius: 4px;
            padding: 8px 12px;
            margin-top: 6px;
        }}

        .sample-title {{
            font-size: 0.7rem;
            color: #64748b;
            font-weight: 600;
            display: block;
            margin-bottom: 3px;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}

        .sample-list {{
            list-style: none;
            padding-left: 0;
        }}

        .sample-review {{
            font-size: 0.775rem;
            color: #475569;
            font-style: italic;
            padding: 2px 0;
        }}

        .export-footer {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 14px;
            padding-top: 10px;
            border-top: 1px solid #edf2f7;
            font-size: 0.75rem;
            color: #64748b;
        }}

        @media (max-width: 640px) {{
            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">

        <!-- Header Card -->
        <div class="card">
            <h1 class="header-title">MoveInSync Play Store Review Triage</h1>
            <div class="header-sub">Source: Google Play Store live scrape (package: com.moveinsync.ets)</div>
            <div class="alert-banner">
                Sample mean &ne; official Google Play listing rating. Categories are heuristic, may overlap, and are not verified root causes. Priorities are investigation suggestions.
            </div>

            <div class="metrics-grid" style="grid-template-columns: repeat(5, 1fr);">
                <div class="metric-box">
                    <div class="metric-label">Reviews scraped</div>
                    <div class="metric-val">{total_reviews:,}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Sample mean stars</div>
                    <div class="metric-val">{mean_stars}/5</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">1–2 star reviews</div>
                    <div class="metric-val">{neg_reviews:,}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Negative share</div>
                    <div class="metric-val">{neg_share}%</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">RAG-validated bugs</div>
                    <div class="metric-val">{rag_clusters}</div>
                </div>
            </div>
        </div>

        <!-- Star distribution Card -->
        <div class="card">
            <h2 class="card-title">Star distribution</h2>
            <table class="triage-table">
                <thead>
                    <tr>
                        <th style="width: 50%;">Rating</th>
                        <th style="width: 50%;">Count</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>1 stars</td>
                        <td>{star_counts[1]:,}</td>
                    </tr>
                    <tr>
                        <td>2 stars</td>
                        <td>{star_counts[2]:,}</td>
                    </tr>
                    <tr>
                        <td>3 stars</td>
                        <td>{star_counts[3]:,}</td>
                    </tr>
                    <tr>
                        <td>4 stars</td>
                        <td>{star_counts[4]:,}</td>
                    </tr>
                    <tr>
                        <td>5 stars</td>
                        <td>{star_counts[5]:,}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- Rating Trend & Historical Trajectory (Solves Problem 4) -->
        <div class="card">
            <h2 class="card-title">Rating Trend &amp; Historical Trajectory</h2>
            <div class="card-subtitle">Tracks weekly rating progression and persistent snapshots across pipeline runs to measure whether engineering fixes raise ratings.</div>
            <table class="triage-table">
                <thead>
                    <tr>
                        <th style="width: 32%;">Period (Weekly Cohort)</th>
                        <th style="width: 18%;">Review Volume</th>
                        <th style="width: 18%;">Average Rating</th>
                        <th style="width: 18%;">Negative Share</th>
                        <th style="width: 14%;">WoW Trajectory</th>
                    </tr>
                </thead>
                <tbody>
                    {trend_table_html}
                </tbody>
            </table>
            <div class="export-footer">
                <span>📁 Snapshot history retained at <code>output/rating_trend_history.json</code> for weekly CI/CD comparison</span>
                <span>{recovery_str}</span>
            </div>
        </div>

        <!-- Complaint categories Card -->
        <div class="card">
            <h2 class="card-title">Complaint categories (1–2 star sample)</h2>
            <div class="card-subtitle">One review may match multiple categories; percentages need not sum to 100%.</div>
            <table class="triage-table">
                <thead>
                    <tr>
                        <th style="width: 45%;">Category</th>
                        <th style="width: 25%;">Mentions</th>
                        <th style="width: 30%;">% of negative reviews</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Booking</td>
                        <td>{booking_mentions}</td>
                        <td>{booking_pct}%</td>
                    </tr>
                    <tr>
                        <td>Crashes/Performance</td>
                        <td>{crash_mentions}</td>
                        <td>{crash_pct}%</td>
                    </tr>
                    <tr>
                        <td>GPS/Tracking</td>
                        <td>{gps_mentions}</td>
                        <td>{gps_pct}%</td>
                    </tr>
                    <tr>
                        <td>OTP/Login</td>
                        <td>{otp_mentions}</td>
                        <td>{otp_pct}%</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- Actionable next steps Card -->
        <div class="card">
            <h2 class="card-title">Actionable next steps</h2>
            <div class="card-subtitle">Priority assigned by real mention volume from this scrape run — top 2 categories get P0, rest get P1.</div>
            <table class="triage-table steps-table">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Suggested triage</th>
                        <th>First engineering action</th>
                        <th>Track</th>
                    </tr>
                </thead>
                <tbody>
                    {actionable_steps_html}
                </tbody>
            </table>
        </div>

        <!-- RAG-Validated & Deduplicated Engineering Bug Clusters -->
        <div class="card">
            <h2 class="card-title">RAG-Validated &amp; Deduplicated Bug Clusters</h2>
            <div class="card-subtitle">Verified against MoveInSync feature documentation via ChromaDB + Gemini 2.5 Flash, then clustered via sentence embeddings.</div>
            {clusters_html}
            <div class="export-footer">
                <span>📋 Jira API payload generated at <code>output/mock_jira_tickets.json</code></span>
                <span>Generated on {generated_at}</span>
            </div>
        </div>

    </div>
</body>
</html>
"""

    with open('output/app_health_report.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("Generated output/app_health_report.html with rating trend history.")
