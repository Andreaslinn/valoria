"""Read explicit card facts; generic area and project ranges stay distinct."""
import re
from bs4 import BeautifulSoup
from domain.ingestion.published_fields import empty_fields, put, address, coordinates


def portal_search_fields(html):
    from infrastructure.scrapers.portalinmobiliario import _extract_nordic_initial_state
    from domain.geocoding.source_quality import mlc
    state = _extract_nordic_initial_state(BeautifulSoup(html, 'lxml')) or {}
    result = {}
    for item in state.get('results') or []:
        card = item.get('polycard') or {}
        meta = card.get('metadata') or {}
        identity = mlc(meta.get('id'))
        if not identity:
            continue
        fields = empty_fields('portalinmobiliario', identity, stage='card')
        fields['source_is_project'] = 'DEVELOPMENT' in str(meta.get('domain_id', ''))
        for component in card.get('components') or []:
            if component.get('type') == 'attributes_list':
                for text in (component.get('attributes_list') or {}).get('texts') or []:
                    path = 'portal.search.polycard.attributes_list.texts'
                    match = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(?:[-–]\s*(\d+(?:[.,]\d+)?))?\s*m[²2]\s+(útiles?|utiles?|totales?)', text.strip(), re.I)
                    if not match:
                        continue
                    key = 'useful_area_m2' if match[3].lower().startswith(('útil', 'util')) else 'total_area_m2'
                    if match[2]:
                        fields[key + '_range'] = [float(match[1].replace(',', '.')), float(match[2].replace(',', '.'))]
                        fields['provenance'][key + '_range'] = path
                        fields['originals'][path + ':' + key] = text
                    else:
                        put(fields, key, match[1], path, positive=True)
            if component.get('type') == 'location':
                address(fields, (component.get('location') or {}).get('text'), 'portal.search.polycard.location.text')
        coordinates(fields, meta.get('latitude'), meta.get('longitude'), 'portal.search.polycard.metadata',
                    {k: meta[k] for k in ('precision', 'approximate', 'is_centroid') if k in meta})
        result[identity] = fields
    return result
