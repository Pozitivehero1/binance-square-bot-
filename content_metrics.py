"""Content cohorts using measured reach at comparable ages, never lifetime totals."""
from datetime import datetime, timezone
from statistics import median

# Explicit windows are intentionally narrower than legacy learning milestones.
WINDOWS = {"30m": (25, 45), "2h": (110, 150), "6h": (330, 390), "24h": (1380, 1500)}


def content_kind(post):
    if str(post.get('lane', '')).upper() == 'OUTCOME':
        return 'outcome'
    if str(post.get('direction', '')).upper() in {'LONG', 'SHORT'}:
        return 'trade_plan'
    if str(post.get('direction', '')).lower() == 'observation':
        return 'observation'
    return 'unknown'


def build_content_metrics(store, now=None):
    now = now or datetime.now(timezone.utc)
    groups = {kind: [] for kind in ('trade_plan', 'observation', 'outcome', 'unknown')}
    for post in store.get('posts', {}).values():
        try:
            published = datetime.fromisoformat(post.get('published_at', '').replace('Z', '+00:00'))
            age = (now - published).total_seconds()
        except (ValueError, TypeError):
            continue
        if 0 <= age <= 7 * 86400:
            groups[content_kind(post)].append(post)
    result = []
    for kind, posts in groups.items():
        milestones = {}
        for label, (low, high) in WINDOWS.items():
            values = []
            for post in posts:
                row = (post.get('content_milestones') or {}).get(label) or (post.get('milestones') or {}).get(label) or {}
                try:
                    age, views = float(row['age_minutes']), int(row['views'])
                except (ValueError, TypeError, KeyError):
                    continue
                if low <= age <= high and views >= 0:
                    values.append(views)
            milestones[label] = {'samples': len(values), 'median_views': median(values) if values else None}
        result.append({'kind': kind, 'posts': len(posts), 'milestones': milestones})
    return {'window_days': 7, 'age_windows_minutes': WINDOWS, 'groups': result}
