"""Content cohorts using measured reach at comparable ages, never lifetime totals."""
from datetime import datetime, timezone
from statistics import median
from evidence_metrics import WINDOWS, observation

# Explicit windows are intentionally narrower than legacy learning milestones.



def content_kind(post):
    if str(post.get('lane', '')).upper() == 'NEWS':
        return 'news'
    if str(post.get('lane', '')).upper() == 'OUTCOME':
        return 'outcome'
    if str(post.get('direction', '')).upper() in {'LONG', 'SHORT'}:
        return 'trade_plan'
    if str(post.get('direction', '')).lower() == 'observation':
        return 'observation'
    return 'unknown'


def build_content_metrics(store, now=None):
    now = now or datetime.now(timezone.utc)
    groups = {kind: [] for kind in ('trade_plan', 'observation', 'news', 'outcome', 'unknown')}
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
            interaction_totals = {name: 0 for name in ('likes', 'comments', 'quotes', 'shares')}
            for post in posts:
                row = observation(post, label) or {}
                try:
                    age, views = float(row['age_minutes']), int(row['views'])
                except (ValueError, TypeError, KeyError):
                    continue
                if low <= age <= high and views >= 0:
                    values.append(views)
                    for name in interaction_totals:
                        try:
                            interaction_totals[name] += max(0, int(row.get(name, 0) or 0))
                        except (ValueError, TypeError):
                            pass
            count = len(values)
            total_views = sum(values)
            total_interactions = sum(interaction_totals.values())
            over_100 = sum(value >= 100 for value in values)
            over_300 = sum(value >= 300 for value in values)
            milestones[label] = {
                'samples': count,
                'median_views': median(values) if values else None,
                'posts_100_plus': over_100,
                'rate_100_plus_pct': round(100 * over_100 / count, 1) if count else None,
                'posts_300_plus': over_300,
                'rate_300_plus_pct': round(100 * over_300 / count, 1) if count else None,
                'views_sum': total_views,
                'interactions': total_interactions,
                'interaction_rate_pct': round(100 * total_interactions / total_views, 3) if total_views else None,
                'interactions_per_1000_views': round(1000 * total_interactions / total_views, 2) if total_views else None,
                'coverage_pct': round(100 * count / len(posts), 1) if posts else None,
                **interaction_totals,
            }
        result.append({'kind': kind, 'posts': len(posts), 'milestones': milestones})
    return {'window_days': 7, 'age_windows_minutes': WINDOWS, 'groups': result}
