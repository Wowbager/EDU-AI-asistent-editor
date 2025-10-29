"""Consolidate migration heads

Revision ID: 9d799fd2feea
Revises: e745593aeecf, 170fa3a096da
Create Date: 2025-05-20 22:18:33.431572

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d799fd2feea'
down_revision = ('e745593aeecf', '170fa3a096da')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
