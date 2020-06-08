"""empty message

Revision ID: e39bcc0a49e3
Revises: f2c3cf58e20b
Create Date: 2017-10-18 12:13:12.045511

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'e39bcc0a49e3'
down_revision = 'f2c3cf58e20b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('categories', sa.Column('seo_description', sa.String(length=250), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('categories', 'seo_description')
    # ### end Alembic commands ###
