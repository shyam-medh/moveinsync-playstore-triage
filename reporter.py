import json
import os
from datetime import datetime

def create_jira_ticket(review):
    """Formats a single review into a Jira REST API JSON payload."""
    return {
        "fields": {
            "project": {"key": "ENG"},
            "summary": f"Play Store Bug: {review['content'][:50]}...",
            "description": f"User: {review['userName']}\nRating: {review['score']}/5\nVersion: {review.get('reviewCreatedVersion', 'Unknown')}\n\nFull Review:\n{review['content']}",
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
            "labels": ["play-store-triage", "user-reported"]
        }
    }

def generate_jira_payload(negative_df):
    """Generates the mock_jira_tickets.json file."""
    if negative_df.empty:
        return
        
    os.makedirs('output', exist_ok=True)
    engineering_bugs = negative_df[negative_df['tags'].apply(lambda x: 'Engineering_Bug' in x)]
    jira_payload = [create_jira_ticket(row.to_dict()) for _, row in engineering_bugs.head(10).iterrows()]
    
    with open('output/mock_jira_tickets.json', 'w', encoding='utf-8') as f:
        json.dump(jira_payload, f, indent=4)
    print("Generated output/mock_jira_tickets.json for top critical bugs.")

def generate_html_dashboard(total_df, negative_df):
    """Generates the app_health_report.html dashboard."""
    total_reviews = len(total_df)
    bad_reviews = len(negative_df)
    health_score = ((total_reviews - bad_reviews) / total_reviews) * 100 if total_reviews > 0 else 0
    
    engineering_bugs = len(negative_df[negative_df['tags'].apply(lambda x: 'Engineering_Bug' in x)])
    auth_issues = len(negative_df[negative_df['tags'].apply(lambda x: 'Auth_Issue' in x)])
    location_issues = len(negative_df[negative_df['tags'].apply(lambda x: 'Location_Issue' in x)])
    ops_issues = len(negative_df[negative_df['tags'].apply(lambda x: 'Operations' in x)])
    
    html_content = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <title>MoveInSync App Health Triage Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; margin: 40px; background-color: #f9f9f9;">
        <div style="background-color: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #333;">🚀 MoveInSync Play Store Triage Report</h2>
            <p><strong>Generated on:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Recent App Health Score:</strong> <span style="font-size: 24px; font-weight: bold; color: {'#e74c3c' if health_score < 70 else '#2ecc71'};">{health_score:.1f}/100</span></p>
            <p style="color: #666;"><i>(Based on sentiment of the last {total_reviews} reviews)</i></p>
            <hr style="border: 1px solid #eee; margin: 20px 0;">
            <h3 style="color: #333;">🚨 Triage Breakdown (1 & 2 Star Reviews)</h3>
            <ul>
                <li><strong>Engineering Bugs (Crashes/Freezes):</strong> {engineering_bugs}</li>
                <li><strong>Authentication Issues (OTP/Login):</strong> {auth_issues}</li>
                <li><strong>Location/Tracking Lags:</strong> {location_issues}</li>
                <li><strong>Operations (Driver/Cab issues):</strong> {ops_issues}</li>
            </ul>
        </div>
    </body>
    </html>
    """
    
    os.makedirs('output', exist_ok=True)
    with open('output/app_health_report.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("Generated output/app_health_report.html")
