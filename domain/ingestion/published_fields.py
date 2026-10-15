"""Source observations, independent of the valuation compatibility columns.

Never infer useful area from square/total, age from a year, or coordinate
accuracy from a street number. This JSON contract lives in raw_metadata so
rolling back the application does not discard evidence or require a downgrade.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import UTC, datetime


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or '').lower())
                   if unicodedata.category(c) != 'Mn')


def number(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text in {'', '$undefined', 'null'}:
        return None
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?\s*m[²2]', text):
        text = text.replace('.', '')
    match = re.fullmatch(r'(-?\d+(?:[.,]\d+)?)\s*(?:m[²2]|años?|anos?)?', text)
    if not match:
        return None
    result = float(match[1].replace(',', '.'))
    return result if math.isfinite(result) else None


def empty_fields(source, external_id, *, stage='detail'):
    return dict(version=1, source=source, external_id=str(external_id), stage=stage,
                observed_at=datetime.now(UTC).isoformat(), useful_area_m2=None,
                total_area_m2=None, constructed_area_m2=None, age_years=None,
                construction_year=None, construction_year_description=None,
                construction_year_conflict=False, floor=None, apartment_number=None,
                latitude=None, longitude=None, coordinates_origin=None,
                coordinates_precision=None, coordinates_precision_raw=None, address_raw=None, street=None,
                address_number=None, address_range=None, address_type=None,
                address_description_raw=None,
                provenance={}, originals={}, rejected={})


def put(fields, key, raw, path, *, positive=False, integer=False):
    fields['originals'][path] = raw
    fields[key + '_raw'] = raw
    if raw not in (None, '', '$undefined'):
        fields['provenance'][key] = path
    parsed = raw
    if key == 'floor' and isinstance(raw, str):
        parsed = re.sub(r'(?<=\d)\s*[°º]$', '', raw.strip())
    value = number(parsed)
    if value is None or (positive and value <= 0) or (integer and value != int(value)):
        return
    fields[key] = int(value) if integer else value
    fields['provenance'][key] = path


def coordinates(fields, lat, lon, path, precision=None):
    fields['originals'][path] = {'latitude': lat, 'longitude': lon}
    a, b = number(lat), number(lon)
    if a is None or b is None:
        return
    if (a, b) == (0, 0) or not (-90 <= a <= 90 and -180 <= b <= 180):
        fields['rejected']['coordinates'] = 'invalid_coordinate_pair'
        return
    declared = precision
    if isinstance(precision, dict):
        if precision.get('is_centroid') is True or precision.get('isCentroid') is True:
            declared = 'centroid'
        elif precision.get('approximate') is True:
            declared = 'approximate'
        else:
            declared = precision.get('precision')
    fields.update(latitude=a, longitude=b, coordinates_origin=path,
                  coordinates_precision=declared or 'unknown', coordinates_precision_raw=precision)
    fields['provenance']['coordinates'] = path


def address(fields, raw, path, *, locality=None):
    if not isinstance(raw, str) or raw.strip() in {'', '#f_location#', '$undefined'}:
        return
    raw = raw.strip()
    fields['address_raw'] = raw
    fields['provenance']['address'] = path
    fields['originals'][path] = raw
    # These describe a business address, not the property. Never extract its
    # office floor/unit/number even when it is the only address in the payload.
    if re.search(r'\b(?:oficinas?|ciudad empresarial|oficina del corredor)\b', normalized(raw)):
        fields['rejected']['address'] = {'reason': 'broker_office', 'path': path}
        fields['address_raw'] = None
        return
    # Unit labels may occur inline or before the street. Remove the whole
    # labelled unit before looking for a civic number, never just its label.
    unit_pattern = r'\b(?:dpto|depto|departamento|dp)\.?\s*(?:n(?:[°ºo.]|ro\.?)?\s*|[#°º]\s*)?(\d+[a-zA-Z]?)\b'
    unit = re.search(unit_pattern, raw, re.I)
    if unit:
        fields['apartment_number'] = unit[1]
        fields['provenance']['apartment_number'] = path + ':explicit_unit'
    without_unit = re.sub(unit_pattern, '', raw, flags=re.I)
    parts = [part.strip() for part in without_unit.split(',')]
    first = parts[0]
    if not first:
        # A unit-only prefix is not a street; skip room counts and landmarks.
        first = next((part for part in parts[1:] if re.match(
            r'^(?:calle|av\.?|avenida|pasaje|camino)\s+\S', part, re.I)), '')
    first = re.sub(r'^(?:real\s+)?oportunidad\s*[!¡:.-]*\s*', '', first, flags=re.I)
    first = re.sub(r'^departamento\s+en\s+', '', first, flags=re.I)
    if re.match(r'^venta\b', first, re.I):
        fields['address_type'] = 'no_number'
        return
    if len(parts) > 1 and re.fullmatch(r'\d+(?:[a-zA-Z]|\s*(?:[-–]|a|al)\s*\d+)?', parts[1]):
        first += ' ' + parts[1]
    # N° belongs to the civic number only after an actual street name.
    first = re.sub(r'\s+n(?:[°ºo.]|ro\.?)\s*(?=\d)', ' ', first, flags=re.I).strip()
    if locality:
        commune = str(locality).rsplit(',', 1)[-1].strip()
        if commune and normalized(first).endswith(' ' + normalized(commune)):
            shortened = first[:-(len(commune)+1)].strip()
            if not re.fullmatch(r'(?:av\.?|avenida|calle|pasaje|camino)', normalized(shortened)):
                first = shortened
    ranged = re.fullmatch(r'(.+?)\s+(\d+)\s*(?:[-–]|a|al)\s*(\d+)', first, re.I)
    exact = re.fullmatch(r'(.+?)\s+(\d+[a-zA-Z]?)', first)
    cross = re.search(r'\b(?:entre|esq|esquina|interseccion|con|al llegar a)\b|[/&]', normalized(raw))
    reference_only = re.search(r'[/&]\s*(?:departamento|depto|colegio|metro|parque)\b', normalized(raw))
    if ranged:
        fields.update(street=ranged[1], address_range=[ranged[2], ranged[3]], address_type='range')
    elif cross and not reference_only:
        street = re.split(r'\b(?:entre|esq\.?|esquina|intersecci[oó]n|con|al llegar a)\b|[/&]', first, maxsplit=1, flags=re.I)[0].strip() or None
        if normalized(first).startswith('entre '):
            pieces = re.split(r'\s+y\s+', first[6:], maxsplit=1, flags=re.I)
            street = pieces[0].strip() if len(pieces) == 2 else None
        fields.update(street=street,
                      address_type='intersection')
    elif exact:
        fields.update(street=exact[1], address_number=exact[2],
                      address_type='no_number' if exact[2] == '0' else 'exact')
    else:
        # A metro station or commune is a raw location, not an invented street.
        street = first if re.match(r'^(?:av\.?|avenida|calle|pasaje|camino)\s', normalized(first)) else None
        if street is None and (path == 'yapo.exactAddress' or path.endswith(':address')):
            from config.comunas import is_known_comuna
            reference = re.search(r'\b(?:metro|parque|sector|barrio|region|comuna|departamento|depto|oportunidad|frente|pasos|piso|edificio|condominio)\b', normalized(first))
            if not reference and not is_known_comuna(first) and first != '0':
                street = first
        fields.update(street=street, address_type='no_number')
        if first == '0':
            fields['address_number'] = '0'
    for key in ('street', 'address_number', 'address_range', 'address_type'):
        if fields[key] is not None:
            fields['provenance'][key] = path
    if fields['street'] is not None and (not fields['street'].strip() or re.fullmatch(
            r'(?:(?:dpto|depto|departamento|dp|nro|n)[\s.°º#]*)+', normalized(fields['street']))):
        for key in ('street', 'address_number', 'address_range'):
            fields[key] = None
            fields['provenance'].pop(key, None)
        fields['address_type'] = 'no_number'


def description_fields(fields, description, path):
    if not isinstance(description, str) or description.startswith('$'):
        return
    # JSON-LD often contains HTML. Tags must not separate labels from values.
    from bs4 import BeautifulSoup
    plain = BeautifulSoup(description, 'lxml').get_text(' ', strip=True)
    text = normalized(plain).replace('\xa0', ' ')
    # Preserve an explicitly introduced property address, separately from the
    # raw structured address. Do not search arbitrary business/contact text.
    end = r'(?=(?<!Av)(?<!av)(?<!AV)(?<!Avda)(?<!avda)(?<!esq)(?<!Esq)\.\s+[A-ZÁÉÍÓÚ]|$)'
    match = re.search(r'(?i:ubicaci[oó]n(?:\s+premium)?|direcci[oó]n(?:\s+de\s+la\s+propiedad)?)\s*:\s*((?i:Calle|Avenida|Av\.|Pasaje|Camino)\s+[^\n]+?)' + end, plain)
    if match is None:
        match = re.search(r'(?i:\ben\s+)((?i:av(?:da)?\.?|avenida|calle|pasaje|camino)\s+[^\n]+?)' + end, plain)
    if match is None:
        location_end = end.replace('(?=', '(?=,|;|', 1)
        match = re.search(r'(?i:\bubicado\s+en\s+)((?!La comuna\b|Un\b|El\b|Sector\b)[A-ZÁÉÍÓÚ][^,;\n]{1,100}?)' + location_end, plain)
    if match:
        candidate = match[1].strip()
        probe = empty_fields(fields['source'], fields['external_id'])
        address(probe, candidate, path + ':address', locality=fields.get('source_locality'))
        if probe['address_raw']:
            fields['address_description_raw'] = candidate
            fields['provenance']['address_description_raw'] = path + ':address'
            if fields['address_raw'] is None:
                fields['address_raw'] = candidate
                fields['provenance']['address'] = path + ':address'
            if fields['street'] is None and probe['street']:
                for key in ('street', 'address_number', 'address_range', 'address_type'):
                    fields[key] = probe[key]
                    if probe[key] is not None:
                        fields['provenance'][key] = path + ':address'
    # Only explicitly labelled areas; never interpret an unqualified m² number.
    for key, labels in [('useful_area_m2', r'util(?:es)?'),
                        ('total_area_m2', r'total(?:es)?'),
                        ('constructed_area_m2', r'construid[oa]s?')]:
        unit = r'(?:m[²2]|mts?2|metros(?:\s+cuadrados)?)'
        patterns = [rf'(\d+(?:[.,]\d+)?)\s*{unit}\s*(?:de\s+)?(?:superficie\s+)?{labels}',
                    rf'(?:superficie\s+)?{labels}\s*[:=]?\s*(?:de\s+)?(\d+(?:[.,]\d+)?)\s*{unit}',
                    rf'(\d+(?:[.,]\d+)?)\s*(?:m\s*)?{labels}\b']
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                put(fields, key + '_description', match[1], path + ':' + key, positive=True)
                fields['originals'][path + ':' + key] = match[0]
                fields[key + '_description_raw'] = match[0]
                if fields[key] is None:
                    put(fields, key, match[1], path + ':' + key, positive=True)
                elif fields[key] != fields.get(key + '_description'):
                    fields.setdefault('area_conflicts', {})[key] = {
                        'structured': fields[key], 'description': fields.get(key + '_description')}
                break
    if fields['floor'] is None:
        match = re.search(r'\bpiso\s*[:=]?\s*(?:n[°ºo.]?\s*)?(\d{1,3})\b', text)
        if match is None:
            match = re.search(r'\b(\d{1,3})\s*(?:°|º|er|do|to|mo|vo|no)?\s+piso\b', text)
        excluded_floor = r'\boficinas?\b|departamentos?\s+por\s+'
        amenity = r'(?:quincho|gimnasio|piscina|azotea)\s+(?:en\s+(?:el\s+)?)?$'
        if (match and not re.search(excluded_floor, text[max(0, match.start()-35):match.end()+50])
                and not re.search(amenity, text[max(0, match.start()-35):match.start()])):
            put(fields, 'floor', match[1], path + ':floor', integer=True)
        if fields['floor'] is None:
            words = {'primer':1,'primero':1,'uno':1,'segundo':2,'dos':2,'tercer':3,'tercero':3,'tres':3,
                     'cuarto':4,'cuatro':4,'quinto':5,'cinco':5,'sexto':6,'seis':6,'septimo':7,'siete':7,
                     'octavo':8,'ocho':8,'noveno':9,'nueve':9,'decimo':10,'diez':10}
            names = '|'.join(words)
            spelled = re.search(rf'\b({names})\s+piso\b|\bpiso\s+({names})\b', text)
            if spelled and not re.search(r'\boficinas?\b|departamentos?\s+por\s+', text[max(0, spelled.start()-35):spelled.end()+50]):
                put(fields, 'floor', words[spelled[1] or spelled[2]], path + ':floor', integer=True)
                fields['floor_raw'] = spelled[0]
    match = re.search(r'(?:ano\s*(?:de\s*)?construccion|construccion\s*(?:es\s*)?(?:del?\s*)?(?:ano\s*)?|construido\s*(?:en\s*)?(?:el\s*)?(?:ano\s*)?)\s*[:=]?\s*((?:19|20)\d{2})\b', text)
    if match is None:
        match = re.search(r'\bedificio(?:\s+[a-z]+){0,3}\s*\(((?:19|20)\d{2})\)', text)
    if match:
        put(fields, 'construction_year_description', match[1], path + ':construction_year', integer=True)
        fields['construction_year_conflict'] = (fields['construction_year'] is not None and
            fields['construction_year'] != fields['construction_year_description'])
    if fields['age_years'] is None:
        match = re.search(r'(?:antiguedad\s*[:=]?\s*(?:de\s*)?)(\d+)\s*anos?', text)
        if match is None:
            match = re.search(r'\b(\d+)\s*anos?\s*(?:de\s*)?antiguedad\b', text)
        if match:
            put(fields, 'age_years', match[1], path + ':age', integer=True)


def area_kind(raw):
    """Label the compatibility m² without changing the number used by the engine."""
    fields = (raw.get('raw_metadata') or {}).get('published_fields') or {}
    value = number(raw.get('m2'))
    # The existing motor chooses constructed, then useful, then generic m2.
    # Equal numbers do not make square into useful area.
    for key, kind in [('constructed_area_m2', 'constructed'), ('useful_area_m2', 'useful')]:
        if fields.get(key) is not None and fields[key] > 0:
            return kind
    if value is not None and fields.get('total_area_m2') == value:
        return 'total'
    origin = str((raw.get('raw_metadata') or {}).get('area_source') or '')
    return 'constructed' if origin == 'yapo_payload.square' else 'generic'


def merge_card_fields(detail, card):
    """Keep fields absent from a card, but accept its explicitly newer facts.

    Mixed snapshots retain observation dates per field. They must not present
    an older detail-only value as freshly observed on the smaller card schema.
    """
    from copy import deepcopy
    merged = deepcopy(detail)
    merged.update(stage='merged', detail_observed_at=detail.get('detail_observed_at') or detail['observed_at'],
                  card_observed_at=card['observed_at'], observed_at=card['observed_at'])
    dates = merged.setdefault('field_observed_at', {})
    keys = ['useful_area_m2','total_area_m2','constructed_area_m2','age_years','construction_year',
            'useful_area_m2_description','total_area_m2_description','constructed_area_m2_description',
            'construction_year_description','floor','apartment_number','address_raw','street',
            'address_number','address_range','address_type','address_description_raw']
    for key in ('latitude','longitude','coordinates_origin','coordinates_precision','coordinates_precision_raw'):
        if detail.get(key) is not None:
            dates.setdefault(key, detail['observed_at'])
    for key, other in [('age_years','construction_year'), ('construction_year','age_years')]:
        if card.get(key) is not None and card.get('provenance', {}).get(key) == 'yapo.age' and detail.get('provenance', {}).get(other) == 'yapo.age':
            merged[other] = None
            merged.pop(other + '_raw', None)
            merged['provenance'].pop(other, None)
            dates[other] = card['observed_at']
    if card.get('address_raw') is not None and card['address_raw'] != detail.get('address_raw'):
        for key in ('street','address_number','address_range','address_type'):
            merged[key] = card.get(key)
            merged['provenance'].pop(key, None)
            dates[key] = card['observed_at']
    for key in keys:
        if detail.get(key) is not None:
            dates.setdefault(key, detail['observed_at'])
        raw = card.get(key + '_raw')
        if key == 'address_type' and card.get('street') is None and detail.get('street') is not None and card.get('address_raw') == detail.get('address_raw'):
            continue
        if card.get(key) is None and raw in (None, '', '$undefined'):
            continue
        merged[key] = card.get(key)
        if key + '_raw' in card:
            merged[key + '_raw'] = raw
        path = (card.get('provenance') or {}).get(key)
        if path:
            merged['provenance'][key] = path
            if path in card['originals']:
                merged['originals'][path] = card['originals'][path]
        dates[key] = card['observed_at']
    if card.get('latitude') is not None and card.get('longitude') is not None:
        for key in ('latitude','longitude','coordinates_origin','coordinates_precision','coordinates_precision_raw'):
            merged[key] = card[key]
            dates[key] = card['observed_at']
        path = card['provenance']['coordinates']
        merged['provenance']['coordinates'] = path
        merged['originals'][path] = card['originals'][path]
    merged['construction_year_conflict'] = (merged.get('construction_year') is not None and
        merged.get('construction_year_description') is not None and
        merged['construction_year'] != merged['construction_year_description'])
    conflicts = {}
    for key in ('useful_area_m2','total_area_m2','constructed_area_m2'):
        described = merged.get(key + '_description')
        if merged.get(key) is not None and described is not None and merged[key] != described:
            conflicts[key] = {'structured': merged[key], 'description': described}
    if conflicts:
        merged['area_conflicts'] = conflicts
    else:
        merged.pop('area_conflicts', None)
    return merged


def synchronize_area_provenance(metadata, fields):
    for native, target in [('constructed_area_m2','built_area_parse_source'), ('useful_area_m2','usable_area_parse_source')]:
        path = (fields.get('provenance') or {}).get(native)
        if fields.get(native) is not None and path:
            metadata[target] = path
        else:
            metadata.pop(target, None)
