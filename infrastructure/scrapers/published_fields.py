"""Publication-bound source facts. No HTTP, valuation or geocoding calls."""
import json
import re

from domain.ingestion.published_fields import (
    address, coordinates, description_fields, empty_fields, normalized, put,
)


def portal_fields(state, components, external_id):
    fields = empty_fields('portalinmobiliario', external_id)
    if components.get('quotable_models'):
        return None  # Projects publish ranges, not the attributes of a unit.
    bound = re.sub(r'[^0-9]', '', str(state.get('id', '')))
    if bound != re.sub(r'[^0-9]', '', str(external_id)):
        return None
    tech = components.get('technical_specifications') or {}
    fields['technical_table_observed'] = bool(tech.get('specs'))
    labels = {'superficie util': 'useful_area_m2', 'superficie total': 'total_area_m2',
              'superficie construida': 'constructed_area_m2',
              'numero de piso de la unidad': 'floor', 'antiguedad': 'age_years',
              'ano de construccion': 'construction_year', 'ano construccion': 'construction_year'}
    for index, spec in enumerate(tech.get('specs') or []):
        for attr in spec.get('attributes') or []:
            label = normalized(attr.get('id') or attr.get('name') or attr.get('title')).strip()
            key = labels.get(label)
            if label in {'numero de departamento', 'numero de unidad'} and attr.get('text'):
                fields['apartment_number'] = str(attr['text'])
                fields['provenance']['apartment_number'] = 'portal.technical_specifications.' + label
            if key:
                put(fields, key, attr.get('text'),
                    f'portal.technical_specifications.specs[{index}].{attr.get("id")}',
                    positive=key.endswith('_m2'), integer=key in {'floor', 'age_years', 'construction_year'})
    # Some responses render only highlighted labelled surfaces. An unqualified
    # "80 m²" is still generic and must never become useful area.
    highlighted = components.get('highlighted_specs_res') or {}
    for index, attr in enumerate(highlighted.get('attributes') or []):
        text = (attr.get('label') or {}).get('text') or ''
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*m[²2]\s*(?:de\s+)?(util(?:es)?|total(?:es)?|construid[oa]s?)', normalized(text))
        if match:
            key = ('useful_area_m2' if match[2].startswith('util') else 'total_area_m2'
                   if match[2].startswith('total') else 'constructed_area_m2')
            if fields[key] is None:
                path = f'portal.highlighted_specs_res.attributes[{index}].label.text'
                put(fields, key, match[1], path, positive=True)
                fields[key + '_raw'] = text
                fields['originals'][path] = text
    for name in ('location_and_points', 'location'):
        info = (components.get(name) or {}).get('map_info') or {}
        point = info.get('location') or {}
        if point and fields['latitude'] is None:
            coordinates(fields, point.get('latitude'), point.get('longitude'),
                        f'portal:{name}.map_info.location',
                        {k: info[k] for k in ('precision', 'accuracy', 'approximate', 'radius', 'is_centroid', 'isCentroid') if k in info} or None)
        if info.get('item_address') and fields['address_raw'] is None:
            address(fields, info['item_address'], f'portal:{name}.map_info.item_address')
    description_fields(fields, (components.get('description') or {}).get('content'),
                       'portal.description.content')
    return fields


def yapo_description(soup, item):
    description = item.get('description')
    if isinstance(description, str) and not description.startswith('$'):
        return description
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        objects = value if isinstance(value, list) else [value]
        for obj in objects:
            if isinstance(obj, dict) and obj.get('@type') == 'Product':
                # Ignore a related Product if the document supplies its identity.
                product_url = obj.get('url') or (obj.get('offers') or {}).get('url')
                if product_url and str(item['id']) not in str(product_url):
                    continue
                return obj.get('description') or ''
    return ''


def yapo_fields(item, soup=None, *, stage='detail', description_origin=None):
    fields = empty_fields('yapo', item['id'], stage=stage)
    for key, native in [('constructed_area_m2', 'square'), ('total_area_m2', 'lotSize'),
                        ('useful_area_m2', 'usableArea'), ('floor', 'floor')]:
        put(fields, key, item.get(native), 'yapo.' + native,
            positive=key.endswith('_m2'), integer=key == 'floor')
    age = item.get('age')
    from domain.ingestion.published_fields import number
    numeric = number(age)
    if numeric is not None:
        put(fields, 'construction_year' if 1800 <= numeric <= 2100 else 'age_years',
            age, 'yapo.age', integer=True)
    location = item.get('location') or {}
    fields['source_locality'] = location.get('locality')
    coordinates(fields, location.get('lat'), location.get('lon'), 'yapo.location',
                {k: location[k] for k in ('precision', 'accuracy', 'approximate', 'radius', 'is_centroid', 'isCentroid') if k in location} or None)
    # location.address can be the broker's office. exactAddress is the
    # publication's own field; locality is preserved raw, never a street guess.
    address(fields, item.get('exactAddress'), 'yapo.exactAddress', locality=location.get('locality'))
    office = location.get('address')
    if office and re.search(r'\b(?:oficinas?|ciudad empresarial)\b', normalized(office)):
        fields['rejected']['location.address'] = {'reason': 'broker_office', 'raw': office}
    if soup is not None:
        if fields['latitude'] is None:
            from infrastructure.scrapers.yapo import _property_map_coordinates
            lat, lon = _property_map_coordinates(soup)
            coordinates(fields, lat, lon, 'yapo:property_map.q')
        original = item.get('description')
        origin = ('yapo.payload.description' if isinstance(original, str) and not original.startswith('$')
                  else 'yapo.jsonld.Product.description')
        description_fields(fields, yapo_description(soup, item), description_origin or origin)
    else:
        description_fields(fields, item.get('description'), description_origin or 'yapo.payload.description')
    return fields
