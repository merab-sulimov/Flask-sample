"""empty message

Revision ID: 4a14d11927b1
Revises: a08d859727cb
Create Date: 2018-01-15 21:06:05.721216

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a14d11927b1'
down_revision = 'a08d859727cb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('profile_first_name', sa.String(length=25), nullable=True))
    op.add_column('users', sa.Column('profile_last_name', sa.String(length=25), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'profile_first_name')
    op.drop_column('users', 'profile_last_name')
    # ### end Alembic commands ###
