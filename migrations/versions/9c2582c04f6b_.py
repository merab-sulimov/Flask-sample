"""empty message

Revision ID: 9c2582c04f6b
Revises: fffd6e29487f
Create Date: 2017-11-23 12:37:09.001061

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c2582c04f6b'
down_revision = 'fffd6e29487f'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('order_offers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('price', sa.Integer(), nullable=False),
    sa.Column('delivery_time', sa.Interval(), nullable=True),
    sa.Column('extras_json', sa.Text(), nullable=False),
    sa.Column('is_closed', sa.Boolean(), nullable=True),
    sa.Column('is_accepted', sa.Boolean(), nullable=True),
    sa.Column('created_on', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('order_offers')
    # ### end Alembic commands ###
