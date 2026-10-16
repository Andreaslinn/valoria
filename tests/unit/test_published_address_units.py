"""Regressions from saved Oracle details; no network or inferred civic number."""
import pytest

from domain.ingestion.published_fields import address, empty_fields
from infrastructure.scrapers.published_fields import yapo_fields


@pytest.mark.parametrize('raw,street,civic,unit', [
    ('DPTO N° 1815, 2D+1B+EST+BOD, CALLE ZENTENO, SANTIAGO CENTRO', 'CALLE ZENTENO', None, '1815'),
    ('DPTO N° 1401, HOME STUDIO, METRO IRRAZABAL', None, None, '1401'),
    ('Calle Ecuador N°5079 Dp 2307', 'Calle Ecuador', '5079', '2307'),
    ('Real Oportunidad!!  Av. Ecuador, 4707', 'Av. Ecuador', '4707', None),
    ('San Pablo 3610 , departamento 1205 Torre A', 'San Pablo', '3610', '1205'),
    ('DEPARTAMENTO EN LORD COCHRANE 635', 'LORD COCHRANE', '635', None),
    ('Av. Ecuador 5079, depto. Nro. 2307A', 'Av. Ecuador', '5079', '2307A'),
    ('Dpto. 1815', None, None, '1815'),
    ('DP 2307', None, None, '2307'),
    ('N° 1401', None, None, None),
    ('Departamento en VENTA de 1D 1B y Bodega con Excelente Vista en Macul', None, None, None),
    ('Av. Ecuador 5079, piso 23, departamentos por piso 7', 'Av. Ecuador', '5079', None),
])
def test_unit_and_street_numbers_are_separate(raw, street, civic, unit):
    fields = empty_fields('yapo', 'saved')
    address(fields, raw, 'yapo.exactAddress')
    assert fields['address_raw'] == raw
    assert fields['street'] == street
    assert fields['address_number'] == civic
    assert fields['apartment_number'] == unit


def test_saved_yapo_32266506_uses_published_intersection_without_civic_number():
    raw = 'DPTO N° 1401, HOME STUDIO, METRO IRRAZABAL'
    fields = yapo_fields(dict(id='32266506', exactAddress=raw,
        description='Ubicado en Santa Isabel/Av. Matta, cuenta con 22.33 m2 de construcción. Es el DPTO N° 1401 en Home Studio.'))
    assert fields['street'] == 'Santa Isabel'
    assert fields['address_description_raw'] == 'Santa Isabel/Av. Matta'
    assert fields['address_number'] is None
    assert fields['apartment_number'] == '1401'
    assert fields['address_raw'] == raw
