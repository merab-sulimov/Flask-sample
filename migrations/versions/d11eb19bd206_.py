"""empty message

Revision ID: d11eb19bd206
Revises: 15aa4eba5862
Create Date: 2017-11-01 14:48:23.518755

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd11eb19bd206'
down_revision = '15aa4eba5862'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('email_messages',
    sa.Column('email_message_id', sa.Integer(), nullable=False),
    sa.Column('recipient', sa.String(length=100), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('html', sa.Text(), nullable=True),
    sa.Column('is_sent', sa.Boolean(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_on', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('email_message_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('email_messages')
    # ### end Alembic commands ###
