"""
Rule-based tagging for visa and regulatory notices.

Everything here is a SUGGESTION for a human reviewer. Rules read exact source
text; they never invent a date, a visa category or an impact rating. Dates that
the text does not state stay None, and impact stays 'unassessed' until a
reviewer records a level and a reason.
"""
from datetime import date
import re
import unicodedata

# -------------- Text --------------


def clean(text):
    """Normalise whitespace and Unicode; raw text is kept separately as evidence."""
    return ' '.join(unicodedata.normalize('NFKC', text or '').split())


# -------------- Dates --------------

MONTHS = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], start=1)}

_MONTH_NAMES = (r'january|february|march|april|may|june|july|august|september|october|'
                r'november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec')
DATE_PATTERNS = [
    ('dmy_text', re.compile(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?,?\s+(\d{{4}})\b', re.I)),
    ('iso', re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')),
    ('slash_dmy', re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b')),   # Australian day-first order
]

# Words right before a date that state when a change takes effect.
EFFECT_BEFORE = re.compile(
    r'(?:effective(?:\s+from|\s+on)?'
    r'|(?:come|comes|came)\s+into\s+(?:effect|force)(?:\s+on)?'
    r'|(?:take|takes|took)\s+effect(?:\s+on|\s+from)?'
    r'|commenc\w*(?:\s+on|\s+from)?'
    r'|starting(?:\s+on|\s+from)?'
    r'|from'
    r'|(?:increased|increases|changed|changes|change|applies|applied|apply|introduced)\s+(?:on|from)'
    r'|as\s+of|beginning(?:\s+on)?)\s*$', re.I)

# Words right before a date that state when a notice was published.
PUBLISHED_BEFORE = re.compile(
    r'(?:published|posted|released|news|media release|updated|date)\s*[|:\-]?\s*$', re.I)


def _valid(year, month, day):
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def find_dates(text):
    """All valid calendar dates in text as {'iso', 'start', 'end'}, in text order."""
    found = []
    for kind, pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            if kind == 'dmy_text':
                iso = _valid(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1]))
            elif kind == 'iso':
                iso = _valid(int(m[1]), int(m[2]), int(m[3]))
            else:
                iso = _valid(int(m[3]), int(m[2]), int(m[1]))
            if iso:
                found.append({'iso': iso, 'start': m.start(), 'end': m.end()})
    found.sort(key=lambda d: d['start'])
    return found


def extract_dates(text, listing_item=False):
    """
    Return (published_date, effective_date); each is an ISO date or None.

    Effective: a date introduced by effect wording ("from", "comes into effect on").
    Published: a date that opens the text or follows publication wording. For a
    listing item with exactly one other date, that date is taken as published,
    which the reviewer must still confirm. Collection time is never substituted.
    """
    published = effective = None
    others = []
    for d in find_dates(text):
        before = text[max(0, d['start'] - 45):d['start']]
        if effective is None and EFFECT_BEFORE.search(before):
            effective = d['iso']
        elif published is None and (d['start'] <= 40 or PUBLISHED_BEFORE.search(before)):
            published = d['iso']
        else:
            others.append(d['iso'])
    if published is None and listing_item and len(others) == 1:
        published = others[0]
    return published, effective


# -------------- Visa categories --------------

KNOWN_SUBCLASSES = {'100', '101', '186', '188', '189', '190', '309', '407', '408', '417', '457',
                    '461', '462', '476', '482', '485', '491', '494', '500', '590', '600', '801',
                    '820', '858', '870'}

NAMED_VISAS = [
    (re.compile(r'\bstudent visas?\b|\bstudent \(?subclass 500\)?', re.I), ['500']),
    (re.compile(r'temporary graduate|\bgraduate visas?\b', re.I), ['485']),
    (re.compile(r'skills? in demand|temporary skill shortage|\bTSS\b', re.I), ['482']),
    (re.compile(r'working holiday|work(?:ing)? and holiday', re.I), ['417', '462']),
    (re.compile(r'skilled work regional|regional provisional', re.I), ['491']),
    (re.compile(r'\bvisitor visas?\b', re.I), ['600']),
    (re.compile(r'student guardian', re.I), ['590']),
    (re.compile(r'\btraining visas?\b', re.I), ['407']),
]

GENERAL_MIGRATION = re.compile(r'\bvisas?\b|migration|immigration|temporary entrant', re.I)


def detect_visa_categories(text):
    """
    Return (categories, specific). A subclass number is accepted only next to the
    word subclass or visa, so "$500" is not read as a visa. When no specific visa
    is found but the text is about migration, categories is ['general_migration'].
    """
    codes = set()
    for m in re.finditer(r'\bsubclass\s*(\d{3})\b', text, re.I):
        if m[1] in KNOWN_SUBCLASSES:
            codes.add(m[1])
    for m in re.finditer(r'\b(\d{3})\s+visas?\b', text, re.I):
        if m[1] in KNOWN_SUBCLASSES:
            codes.add(m[1])
    for pattern, mapped in NAMED_VISAS:
        if pattern.search(text):
            codes.update(mapped)
    if codes:
        return sorted(codes), True
    if GENERAL_MIGRATION.search(text):
        return ['general_migration'], False
    return [], False


# -------------- Relevance, change type, suggestions --------------

RELEVANT = re.compile(
    r'\b(?:visas?|migration|immigration|international (?:students?|education)|overseas students?|'
    r'ESOS|working holiday|student intake|temporary graduate|skilled workers?|temporary entrant)\b',
    re.I)

CHANGE_TYPE_RULES = [
    ('processing_time', re.compile(r'processing (?:times?|timeframes?)|wait times?', re.I)),
    ('fee_change', re.compile(
        r'(?:application charge|\bVAC\b|\bfees?\b|\bcharges?\b).{0,80}?'
        r'(?:increase|increased|rise|rising|change|indexation)|'
        r'(?:increase|rise|change).{0,60}?(?:application charge|\bVAC\b|\bfees?\b|\bcharges?\b)', re.I)),
    ('visa_condition', re.compile(
        r'work (?:rights|limits?|hours)|visa conditions?|condition \d{4}|hours per fortnight|stay limits?', re.I)),
    ('compliance_requirement', re.compile(
        r'compliance|genuine (?:student|temporary entrant)|english (?:language )?(?:test|requirement)|'
        r'financial capacity|\bESOS\b|confirmation of enrolment|reporting obligations?', re.I)),
    ('eligibility', re.compile(
        r'eligib|age limit|criteria|\bcaps?\b|capped|pathway|who can apply|no longer (?:able|eligible)|'
        r'planning level|requirements?', re.I)),
    ('worker_policy', re.compile(
        r'minimum wage|\bawards?\b|workplace|employers?|fair work|workers?|sponsor', re.I)),
    ('education_policy', re.compile(
        r'international (?:students?|education)|education providers?|universit|\bTAFE\b|student intake', re.I)),
    ('policy_announcement', re.compile(r'announce|policy|reform|migration (?:program|strategy)|minister', re.I)),
]

HIGH_TYPES = {'eligibility', 'fee_change', 'compliance_requirement', 'visa_condition'}
MEDIUM_TYPES = {'processing_time', 'education_policy', 'worker_policy', 'policy_announcement'}
HIGH_VISAS = {'500', '485', '482', '491', '494', '417', '462'}

COVER_BY_VISA = {'500': 'OSHC', '590': 'OSHC', '600': 'OVHC',
                 '485': 'OWHC', '482': 'OWHC', '491': 'OWHC', '494': 'OWHC', '407': 'OWHC',
                 '417': 'OWHC', '462': 'OWHC', '408': 'OWHC', '186': 'OWHC', '189': 'OWHC', '190': 'OWHC'}


def is_relevant(text):
    return bool(RELEVANT.search(text))


def classify_change_type(text):
    """First matching rule wins; 'other' when none match."""
    for change_type, pattern in CHANGE_TYPE_RULES:
        if pattern.search(text):
            return change_type
    return 'other'


def suggest_impact(change_type, visa_categories):
    """
    Suggested impact level and the reasoning behind it. A hint for the reviewer:
    the published impact_level always comes from a human decision.
    """
    specific = [v for v in visa_categories if v in HIGH_VISAS]
    if change_type in HIGH_TYPES and specific:
        return 'high', f'{change_type} affecting visa {", ".join(specific)}, which drive overseas cover demand'
    if change_type in HIGH_TYPES or change_type in MEDIUM_TYPES:
        return 'medium', f'{change_type} with no high-volume visa named'
    return 'low', 'no demand-related change type detected'


def suggest_cover_types(visa_categories):
    """Cover types usually linked to the named visas; None when no link is known."""
    covers = sorted({COVER_BY_VISA[v] for v in visa_categories if v in COVER_BY_VISA})
    return covers or None
