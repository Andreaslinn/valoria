"""Compare two saved 400-detail extractions offline; never fetch or write a DB."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re

ADDRESS_KEYS = ['address_raw', 'street', 'address_number', 'address_range',
                'address_type', 'apartment_number', 'address_description_raw']
ALLOWED_CHANGES = set(ADDRESS_KEYS) | {'originals', 'provenance', 'rejected'}


def audit(before, after, output):
    original = {(r['source'], r['id']): r for r in before}
    assert len(before) == len(after) == len(original) == 400
    changed, units, missing = [], [], []
    for row in after:
        old = original[(row['source'], row['id'])]['fields']
        fields = row['fields']
        assert fields['address_raw'] == old['address_raw'], row['id']
        for key in (old.keys() | fields.keys()) - ALLOWED_CHANGES:
            assert old.get(key) == fields.get(key), (row['id'], key)
        street = fields['street']
        if street is not None:
            assert street.strip(), row['id']
            assert not re.fullmatch(r'(?:(?:dpto|depto|departamento|dp|nro|n)[\s.°º#]*)+', street, re.I), row['id']
        else:
            missing.append({'source': row['source'], 'id': row['id'], 'address_raw': fields['address_raw']})
        if fields['apartment_number'] is not None:
            units.append({'source': row['source'], 'id': row['id'], 'apartment_number': fields['apartment_number']})
        if any(old.get(k) != fields.get(k) for k in ADDRESS_KEYS):
            for stage, values in [('before', old), ('after', fields)]:
                changed.append({'source': row['source'], 'id': row['id'], 'stage': stage,
                                **{k: values.get(k) for k in ADDRESS_KEYS}})
    output.mkdir(parents=True, exist_ok=True)
    with (output/'addresses-affected-before-after.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=['source', 'id', 'stage'] + ADDRESS_KEYS)
        writer.writeheader()
        for row in changed:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()})
    proof = {'offline_only': True, 'reviewed': 400, 'affected': len(changed)//2,
             'raw_addresses_unchanged': True, 'non_address_fields_unchanged': True,
             'empty_string_or_unit_only_streets': 0, 'apartment_number_count': len(units),
             'apartment_numbers_by_source': dict(Counter(r['source'] for r in units)),
             'apartment_numbers': units, 'null_streets': len(missing),
             'null_original_addresses': sum(r['address_raw'] is None for r in missing),
             'literal_all_400_streets_present': not missing,
             'limitation': 'NULL is retained where street identification is unresolved; filling all 400 would require unsupported inference.',
             'missing_street_evidence': missing}
    (output/'addresses-proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in proof.items() if k != 'missing_street_evidence'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit(json.loads(args.before.read_text(encoding='utf8')),
          json.loads(args.after.read_text(encoding='utf8')), args.output)
