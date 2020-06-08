"""empty message

Revision ID: a08d859727cb
Revises: e3d663602a40
Create Date: 2017-12-26 13:10:07.189759

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = 'a08d859727cb'
down_revision = 'e3d663602a40'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('users', 'last_logged_ip',
                    existing_type=mysql.VARCHAR(length=15),
                    type_=sa.String(length=46))


def downgrade():
    op.alter_column('users', 'last_logged_ip',
                    existing_type=mysql.VARCHAR(length=46),
                    type_=sa.String(length=15))
