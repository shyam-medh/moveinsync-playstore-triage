import pandas as pd

def categorize_reviews(df):
    """Filters negative reviews and categorizes them using NLP keyword matching."""
    if df.empty:
        return df, pd.DataFrame()
        
    # Filter for severe negative reviews (1 and 2 stars)
    negative_df = df[df['score'] <= 2].copy()
    print(f"Found {len(negative_df)} severe negative (1-2 star) reviews.")
    
    # Categorization logic using NLP Keywords
    keywords = {
        'Auth_Issue': ['otp', 'login', 'logout', 'log out', 'password', 'session'],
        'Engineering_Bug': ['crash', 'freeze', 'loading', 'slow', 'stuck', 'blank', 'bug', 'glitch'],
        'Location_Issue': ['gps', 'track', 'location', 'map', 'update', 'show', 'lag'],
        'Operations': ['driver', 'rude', 'late', 'cab', 'driver refused', 'delay']
    }

    def _apply_tags(text):
        text = str(text).lower()
        tags = []
        for tag, words in keywords.items():
            if any(word in text for word in words):
                tags.append(tag)
        return tags if tags else ['Uncategorized']

    negative_df['tags'] = negative_df['content'].apply(_apply_tags)
    return df, negative_df
