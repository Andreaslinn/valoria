"""Persist a bound detail observation without changing commercial freshness."""
from domain.ingestion.published_fields import area_kind, synchronize_area_provenance
from datetime import UTC, datetime


async def record_detail_attempt(factory, source, external_id):
    """Rotate failed/inactive URLs too; they cannot occupy the first slots forever."""
    from sqlalchemy import select
    from infrastructure.db.models import ListingORM
    async with factory() as session:
        row = await session.scalar(select(ListingORM).where(ListingORM.source == source,
            ListingORM.external_id == external_id).with_for_update())
        if row is not None:
            row.raw_metadata = {**(row.raw_metadata or {}),
                'published_detail_attempted_at': datetime.now(UTC).isoformat()}
            await session.commit()


def apply_published_fields(row, fields):
    if not isinstance(fields, dict) or fields.get('version') != 1 or fields.get('stage') != 'detail':
        return False
    def identity(value):
        return ''.join(c for c in str(value) if c.isdigit())
    if row.source != fields.get('source') or not identity(row.external_id) or identity(row.external_id) != identity(fields.get('external_id')):
        return False
    row.built_area_m2 = fields.get('constructed_area_m2')
    row.usable_area_m2 = fields.get('useful_area_m2')
    metadata = {**(row.raw_metadata or {}), 'published_fields': fields}
    metadata['published_detail_fields'] = fields
    synchronize_area_provenance(metadata, fields)
    metadata['valuation_m2_kind'] = area_kind({
        'm2': row.built_area_m2 or row.usable_area_m2 or row.m2,
        'raw_metadata': metadata,
    })
    row.raw_metadata = metadata
    return True
