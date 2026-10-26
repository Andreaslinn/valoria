"""Vitacura geography sidecar. All request-time work is local and read-only.

OSM is geometry only. Sales come from the existing filtered closing export.
No estimator, UF conversion, attributes, or F2890 joins are implemented here.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from functools import lru_cache

from services.sii.closing_address import AddressIndex, street_key
from services.sii.geocoding import distance, interpolate
from services.sii.role_lookup import resolve_role


@lru_cache(maxsize=32768)
def _street_key(text):
    return street_key(text)


def street_score(a, b):
    a, b = _street_key(a), _street_key(b)
    if a == b:
        return 1.0
    aa, bb = a.split(), b.split()
    if len(aa) == len(bb):
        scores = [1. if x == y else .96 if min(len(x),len(y)) <= 3 and
                  (x.startswith(y) or y.startswith(x)) else SequenceMatcher(None,x,y).ratio()
                  for x,y in zip(aa,bb)]
        if min(scores) >= .8:
            return min(.96, sum(scores)/len(scores))
    matcher=SequenceMatcher(None,a,b)
    if matcher.quick_ratio() < .8:
        return 0.
    return matcher.ratio()


def street_matches(street, vocabulary):
    if street in vocabulary:
        return [street]
    ranked = sorted(((street_score(street, s), s) for s in vocabulary), reverse=True)
    if not ranked or ranked[0][0] < .8:
        return []
    # Preserve plausible alternatives; a tiny score difference is not evidence.
    return [s for score, s in ranked if score >= max(.8, ranked[0][0] - .08)]


def resolve_local(index, comuna, address):
    """Use the current resolver, adding offline number-constrained street aliases."""
    return index.resolve(comuna, address)


def osm_anchors(data):
    points = defaultdict(list)
    for e in data.get('elements', []):
        tags = e.get('tags', {})
        num = str(tags.get('addr:housenumber', ''))
        street = street_key(tags.get('addr:street', ''))
        p = e if 'lat' in e else e.get('center', {})
        if not street or not num.isdigit() or 'lat' not in p or 'lon' not in p:
            continue
        lat, lon = float(p['lat']), float(p['lon'])
        if not (-33.45 < lat < -33.30 and -70.66 < lon < -70.40):
            continue
        points[street, int(num)].append((lat, lon, f"{e['type']}/{e['id']}"))
    anchors = defaultdict(dict)
    conflicts = set()
    for (street, num), values in points.items():
        # Node + building duplicates are common. Distant duplicate addresses abstain.
        if any(distance(values[0][:2], v[:2]) > 40 for v in values):
            conflicts.add((street, num))
            continue
        anchors[street][num] = (median(v[0] for v in values), median(v[1] for v in values))
    return anchors, points, conflicts


def locate_osm(rows, data, source):
    anchors, evidence, conflicts = osm_anchors(data)
    names = set(anchors)
    aliases = {s: street_matches(s, names) for s in {r['street'] for r in rows}}
    located = {}
    for r in rows:
        matches = aliases[r['street']]
        if len(matches) != 1 or not str(r['number']).isdigit():
            continue
        street, num = matches[0], int(r['number'])
        if (street, num) in conflicts:
            continue
        detail = {'street_osm': street, 'street_score': street_score(r['street'], street)}
        point = anchors[street].get(num)
        if point:
            method, precision = 'osm_direct', 25.0
            detail['osm_ids'] = [v[2] for v in evidence[street, num]]
        else:
            result = interpolate(num, anchors[street])
            if result is None:
                continue
            point, precision = result[:2], result[2]
            method = 'osm_interpolated'
            detail['anchor_numbers'] = result[3:]
            detail['anchor_points'] = [anchors[street][n] for n in result[3:]]
        located[r['rol']] = {'lat': point[0], 'lon': point[1], 'method': method,
            'precision_m': precision, 'quality': 'address_match' if method == 'osm_direct' else 'estimated',
            'source': source, 'evidence': detail, 'source_id': r['source']}
    return located


def block_fallback(rows, located):
    groups = defaultdict(list)
    for r in rows:
        if r['rol'] in located:
            groups[r['block']].append((r['rol'], located[r['rol']]))
    centers = {}
    for block, group in groups.items():
        # Count distinct points, not apartment roles sharing one building point.
        points = {(g['lat'], g['lon']) for _, g in group}
        if len(points) < 2:
            continue
        center = median(p[0] for p in points), median(p[1] for p in points)
        spread = max(distance(center, p) for p in points)
        if spread > 300:
            continue
        centers[block] = {'lat': center[0], 'lon': center[1], 'method': 'block_median',
            'precision_m': max(100., spread + median(g['precision_m'] for _, g in group)),
            'quality': 'approximate_block', 'source': 'derived_local_anchors',
            'evidence': {'distinct_anchors': len(points), 'spread_m': spread,
                         'anchor_roles': [rol for rol, _ in group]}}
    for r in rows:
        if r['rol'] not in located and r['block'] in centers:
            located[r['rol']] = {**centers[r['block']], 'source_id': r['source']}


GEO_SCHEMA = '''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE geo(rol TEXT PRIMARY KEY,source_id INTEGER,lat REAL,lon REAL,
 method TEXT,precision_m REAL,quality TEXT,source TEXT,evidence TEXT);
CREATE INDEX geo_lat ON geo(lat,lon);
CREATE TABLE sale(raw_id INTEGER PRIMARY KEY,rol TEXT,date TEXT,kind TEXT,payload TEXT);
CREATE INDEX sale_role ON sale(rol,date);
'''


def write_geography(path, located, sales, metadata):
    """Build a complete generation then atomically replace; stale points disappear."""
    path = Path(path)
    temp = path.with_suffix('.building.sqlite')
    if temp.exists():
        temp.unlink()
    with closing(sqlite3.connect(temp)) as db:
        db.executescript(GEO_SCHEMA)
        db.executemany('INSERT INTO geo VALUES (?,?,?,?,?,?,?,?,?)', [
            (rol,g['source_id'],g['lat'],g['lon'],g['method'],g['precision_m'],g['quality'],g['source'],
             json.dumps(g['evidence'])) for rol,g in located.items()])
        db.executemany('INSERT INTO sale VALUES (?,?,?,?,?)', [
            (s['raw_id'],s['rol'],s['date'],s['kind'],json.dumps(s)) for s in sales])
        db.executemany('INSERT INTO metadata VALUES (?,?)',[(k,json.dumps(v)) for k,v in metadata.items()])
        db.commit()
    temp.replace(path)


class LocalGeography:
    def __init__(self, root):
        self.root = Path(root)

    def nearby(self, *, address='', rol=None, radius_m=800, as_of=None, limit=30):
        as_of = as_of or date.today().isoformat()
        date.fromisoformat(as_of)
        if not math.isfinite(radius_m) or not 0 < radius_m <= 5000 or not 1 <= limit <= 200:
            raise ValueError('invalid_radius_or_limit')
        index = AddressIndex(self.root/'address-index.sqlite')
        try:
            resolution = resolve_role(index,15160,rol) if rol else resolve_local(index,15160,address)
            if resolution['status'] in {'ambiguous','unresolved'}:
                return resolution
            candidates = resolution['candidates']
            if len(candidates) != 1:
                return {**resolution,'status':'ambiguous','reason':'unit_required'}
            subject = candidates[0]
            with closing(sqlite3.connect((self.root/'geography.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory = sqlite3.Row
                g = db.execute('SELECT * FROM geo WHERE rol=? AND source_id=?',
                               (subject['rol'],subject['source'])).fetchone()
                if not g:
                    return {'status':'unlocated','role':subject['rol'],'address':subject['raw']}
                lat, lon = g['lat'], g['lon']
                dy = math.degrees(radius_m/6371000)
                dx = dy/math.cos(math.radians(lat))
                # Attach the same read-only index to guard sale geography against stale catastro.
                db.execute('ATTACH DATABASE ? AS cat',((self.root/'address-index.sqlite').resolve().as_uri()+'?mode=ro',))
                rows = db.execute('''SELECT s.payload,g.* FROM geo g JOIN sale s ON s.rol=g.rol
                    JOIN cat.role r ON r.rol=g.rol AND r.source=g.source_id
                    WHERE g.lat BETWEEN ? AND ? AND g.lon BETWEEN ? AND ?
                    AND s.date < ? AND s.rol <> ? AND s.kind=?''',
                    (lat-dy,lat+dy,lon-dx,lon+dx,as_of,subject['rol'],subject['kind'])).fetchall()
                found=[]
                for r in rows:
                    d=distance((lat,lon),(r['lat'],r['lon']))
                    if d <= radius_m:
                        error=g['precision_m']+r['precision_m']
                        found.append({**json.loads(r['payload']),'distance_m':round(d,1),
                            'geo_method':r['method'],'estimated_uncertainty_m':error,
                            'distance_range_m':[max(0,round(d-error)),round(d+error)],
                            'radius_membership':'uncertain' if d+error>radius_m else 'estimated_inside'})
                found.sort(key=lambda s:(s['distance_m'],s['raw_id']))
                return {'status':'ok','role':subject['rol'],'address':subject['raw'],
                    'location':dict(g),'radius_m':radius_m,'total':len(found),'sales':found[:limit],
                    'attribution':'© OpenStreetMap contributors, ODbL',
                    'precision_note':'Incertidumbre estimada; no es error máximo certificado.'}
        finally:
            index.close()
