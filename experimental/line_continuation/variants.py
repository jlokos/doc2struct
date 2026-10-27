"""Small ablations using existing rule fields, not issuer-specific phrases."""
import copy


def rules_variant(base, name):
    rules = copy.deepcopy(base)
    if name == 'baseline':
        return rules
    if name in {'pages', 'rules', 'combined'}:
        rules['remove']['patterns'].append([r'^f-\d{1,4}$', False])
    if name in {'strict_notes', 'rules', 'combined'}:
        # Deliberately test the recall cost of removing unadorned numbers and
        # three-digit parenthesized markers rather than assuming it is safe.
        rules['tables']['footnote_regex'] = r'^(\*+|\((?:[a-zA-Z]|\d{1,2}|[ivxlcdmIVXLCDM]{2,4})\)|\d{1,3}[.)](?!\d)|†+)'
    if name in {'bounded_headers', 'rules', 'combined'}:
        # Only replace single-title prefix rules. Other rules legitimately
        # capture following labels or title variants and remain unchanged.
        complete = {'capitalization', 'underwriting', 'dilution', 'dividend policy',
                    'legal matters', 'prospectus summary', 'use of proceeds',
                    'executive compensation', 'legal proceedings'}
        for header in rules['headers']:
            if header['name'] in complete and header['regex'].startswith('^'):
                header['regex'] = header['regex'].rstrip('$') + r'\s*[.:]?$'
    if name == 'style_required':
        for header in rules['headers']:
            if header['name'] in {'business', 'capitalization', 'underwriting', 'dilution',
                                   'controls and procedures', 'corporate governance'}:
                header['requires'] = sorted(set(header.get('requires', [])) | {'bold'})
    if name in {'guarded_notes', 'candidate'}:
        # Keep all existing marker forms. Exclude only recognizable US phone
        # numbers and a high bare number followed by a short street address.
        guard = (r'(?i)^(?!\(\d{3}\)\s*\d{3}[-.\s]\d{4})'
                 r'(?![1-9]\d{2,4}\s+(?:[\w.\x27-]+\s+){1,5}'
                 r'(?:street|avenue|road|boulevard|drive|lane|way|st\.?|ave\.?|rd\.?|blvd\.?)\b)')
        rules['tables']['footnote_regex'] = guard + rules['tables']['footnote_regex'].removeprefix('^')
    return rules
