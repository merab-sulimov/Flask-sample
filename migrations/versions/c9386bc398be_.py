"""empty message

Revision ID: c9386bc398be
Revises: cdb7582c3369
Create Date: 2017-02-26 18:48:07.996478

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'c9386bc398be'
down_revision = 'cdb7582c3369'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('photo_data', sa.Text(), nullable=True))
    op.drop_column('users', 'photo_filename')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('photo_filename', mysql.VARCHAR(length=255), nullable=True))
    op.drop_column('users', 'photo_data')
    # ### end Alembic commands ###
