"""Matrix v2 interval/cron calculation; the existing durable trigger queue owns delivery.

Five numeric cron fields: minute, hour, day, month, weekday (Sunday 0 or 7).
No shell command, environment settings, randomness, network or terminal timer.
"""
from datetime import datetime, timedelta, timezone
import math
import re
from zoneinfo import ZoneInfo
from .errors import Invalid


def interval(value):
    match = re.fullmatch(r'(\d{1,8})(s|m|h|d)', value)
    if not match: raise Invalid('Use an interval such as 15m, 1h or 1d.')
    seconds = int(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2]]
    if not 60 <= seconds <= 31 * 86400: raise Invalid('A Matrix interval is between one minute and 31 days.')
    return {'kind': 'interval', 'seconds': seconds}


def cron(expression, zone='UTC'):
    from .timing import zone_name
    if not isinstance(expression, str) or len(expression) > 128 or not zone_name(zone):
        raise Invalid('Use five numeric cron fields and an IANA time zone.')
    words = expression.split()
    if len(words) != 5: raise Invalid('Cron needs minute, hour, day, month and weekday fields.')
    fields = []
    for word, (low, high) in zip(words, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))):
        values = set()
        for part in word.split(','):
            match = re.fullmatch(r'(\*|\d{1,2}(?:-\d{1,2})?)(?:/(\d{1,2}))?', part)
            if not match: raise Invalid('Cron fields accept numbers, *, ascending ranges, comma lists and range steps.')
            term, step = match[1], int(match[2] or 1)
            if not 1 <= step <= high - low + 1 or match[2] and term != '*' and '-' not in term:
                raise Invalid('Use a positive cron step after * or a range.')
            start, end = (low, high) if term == '*' else map(int, term.split('-')) if '-' in term else (int(term), int(term))
            if not low <= start <= end <= high: raise Invalid('A cron field is out of range.')
            values.update(range(start, end + 1, step))
        fields.append(sorted(values))
    fields[-1] = sorted({day % 7 for day in fields[-1]})
    trigger = {'kind': 'cron', 'expression': ' '.join(words), 'zone': zone, 'fields': fields,
               'day_or': '*' not in words[2] and '*' not in words[4]}
    # Reject impossible dates while parsing, rather than leaving an enabled
    # definition that can never acquire a next occurrence.
    next_at(trigger, datetime(2000, 1, 1, tzinfo=timezone.utc))
    return trigger


def next_at(trigger, after):
    after = after.astimezone(timezone.utc)
    if trigger['kind'] == 'interval':
        seconds = trigger['seconds']
        return datetime.fromtimestamp((math.floor(after.timestamp() / seconds) + 1) * seconds, timezone.utc)
    minute, hour, day, month, weekday = trigger['fields']
    tz = ZoneInfo(trigger['zone']);first = after.astimezone(tz).date()
    for offset in range(366 * 8 + 1):
        date = first + timedelta(days=offset)
        if date.month not in month: continue
        dom, dow = date.day in day, (date.weekday() + 1) % 7 in weekday
        if not (dom or dow if trigger['day_or'] else dom and dow): continue
        for h in hour:
            for m in minute:
                local = datetime(date.year, date.month, date.day, h, m, tzinfo=tz, fold=0)
                moment = local.astimezone(timezone.utc)
                # Gap: skip nonexistent wall time. Fold: first occurrence only.
                if moment.astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None): continue
                if moment > after: return moment
    raise Invalid('This cron has no occurrence within the bounded eight-year search.')
