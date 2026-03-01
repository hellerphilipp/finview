"""rename parent_id to split_parent_id

Revision ID: a99e4a82224a
Revises: e675c8da2a60
Create Date: 2026-03-01 11:36:57.806329

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a99e4a82224a'
down_revision: Union[str, None] = 'e675c8da2a60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('parent_id', new_column_name='split_parent_id')


def downgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('split_parent_id', new_column_name='parent_id')
