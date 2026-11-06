"""radio stations

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06 10:00:00
"""

import json

from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

INITIAL_STATIONS = [
    ('rock-radio-beograd', 'Rock Radio Beograd', 'Beograd · rok', ['https://edge9.pink.rs/rockstream'], None),
    ('radio-s-rock', 'Radio S Rock', 'Srbija · rok', ['https://stream.radios.rs:9032/stream'], 'audio/aac'),
    ('radio-karolina', 'Radio Karolina', 'Srbija', ['http://streaming.karolina.rs:8000/karolina'], None),
    ('radio-paradise', 'Radio Paradise', 'SAD · eklektični miks', ['http://stream-uk1.radioparadise.com/mp3-128'], None),
    ('rock-antenne', 'Rock Antenne', 'Nemačka · rok', ['https://s1-webradio.rockantenne.bayern/rockantenne-bayern/stream/mp3'], None),
    (
        'classic-rock-florida',
        'Classic Rock Florida',
        'SAD · klasični rok',
        ['https://das-edge11-live365-dal03.cdnstream.com/a06375', 'http://streaming.live365.com/a06375'],
        None,
    ),
    ('aligator-classic-rock', 'Aligator Classic Rock', 'Slovačka · klasični rok', ['http://stream.aligator.sk:8000/aligator_128.mp3'], None),
]


def upgrade() -> None:
    table = op.create_table(
        'radio_stations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('sub', sa.String(length=64), nullable=True),
        sa.Column('urls_json', sa.Text(), nullable=False),
        sa.Column('content_type', sa.String(length=64), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.bulk_insert(
        table,
        [
            {
                'slug': slug,
                'name': name,
                'sub': sub,
                'urls_json': json.dumps(urls),
                'content_type': content_type,
                'sort_order': position,
            }
            for position, (slug, name, sub, urls, content_type) in enumerate(INITIAL_STATIONS, start=1)
        ],
    )


def downgrade() -> None:
    op.drop_table('radio_stations')
