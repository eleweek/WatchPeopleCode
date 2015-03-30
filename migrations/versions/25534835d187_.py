"""empty message

Revision ID: 25534835d187
Revises: 3a7cac1b3adc
Create Date: 2015-03-25 23:25:40.668715

"""

# revision identifiers, used by Alembic.
revision = '25534835d187'
down_revision = '3a7cac1b3adc'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('stream', sa.Column('rtmp_key', sa.String(length=50), nullable=True))
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('stream', 'rtmp_key')
    ### end Alembic commands ###