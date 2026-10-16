"""Compare persisted observations with an independently reviewed factual reference."""
import json
from pathlib import Path

GROUPS = {
    'useful_area': ['useful_area_m2'],
    'total_area': ['total_area_m2'],
    'constructed_area': ['constructed_area_m2'],
    'age_or_year': ['age_years', 'construction_year', 'construction_year_description', 'construction_year_conflict'],
    'floor': ['floor'],
    'coordinates': ['latitude', 'longitude', 'coordinates_precision'],
    'address': ['address_raw', 'street', 'address_number', 'address_range', 'address_type'],
}


def compare(persisted, references):
    indexed = {(row['source'], row['id']): row['fields'] for row in persisted}
    result, errors = {}, []
    for source in ('yapo', 'portalinmobiliario'):
        rows = [row for row in references if row['source'] == source]
        assert len(rows) == 30 and len({row['id'] for row in rows}) == 30
        result[source] = {}
        for name, keys in GROUPS.items():
            published, captured = 0, 0
            for row in rows:
                expected = row['expected']
                actual = indexed[(source, row['id'])]
                relevant = [key for key in keys if key in expected]
                exists = any(expected[key] is not None and key not in {'construction_year_conflict', 'coordinates_precision'} for key in relevant)
                correct = all(actual.get(key) == expected[key] for key in relevant)
                if exists:
                    published += 1
                    captured += correct
                if not correct:
                    errors.append({'source': source, 'id': row['id'], 'group': name,
                        'differences': {key: {'expected': expected[key], 'actual': actual.get(key)}
                                        for key in relevant if actual.get(key) != expected[key]}})
            rate = 100 * captured / published if published else None
            result[source][name] = {'published': published, 'captured': captured, 'percent': rate}
            assert rate is None or rate >= 95, (source, name, rate, errors)
    assert not errors, errors  # Includes absent fields: false imputations also fail.
    return {'random_seed': 20261016, 'reviewed_per_source': 30, 'minimum_percent': 95,
            'source_reference_independent_of_capture': True, 'results': result, 'errors': errors}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('persisted', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    proof = compare(json.loads(args.persisted.read_text(encoding='utf8')),
                    json.loads(args.reference.read_text(encoding='utf8')))
    args.output.write_text(json.dumps(proof, indent=2), encoding='utf8')
    print(json.dumps(proof))
