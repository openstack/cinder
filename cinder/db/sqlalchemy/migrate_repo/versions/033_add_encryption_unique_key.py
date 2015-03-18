#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import uuid

from migrate import PrimaryKeyConstraint, ForeignKeyConstraint
from sqlalchemy import Column, MetaData, Table
from sqlalchemy import String, Integer, Boolean, DateTime


def upgrade(migrate_engine):
    """Add UUID primary key column to encryption."""
    meta = MetaData()
    meta.bind = migrate_engine

    encryptions = Table('encryption', meta, autoload=True)

    # NOTE: SQLite doesn't support 'drop constraint' statament
    if migrate_engine.name == 'sqlite':
        _upgrade_sqlite(meta, encryptions)
    else:
        encryption_id_column_kwargs = {}
        if migrate_engine.name == 'ibm_db_sa':
            # NOTE(junxiebj): DB2 10.5 doesn't support primary key
            # constraints over nullable columns, so we have to
            # make the column non-nullable in the DB2 case.
            encryption_id_column_kwargs['nullable'] = False
        encryption_id = Column('encryption_id', String(36),
                               **encryption_id_column_kwargs)
        encryptions.create_column(encryption_id)

        encryption_items = list(encryptions.select().execute())

        for item in encryption_items:
            encryptions.update().\
                where(encryptions.c.volume_type_id == item['volume_type_id']).\
                values(encryption_id=str(uuid.uuid4())).execute()

        # NOTE (e0ne): need to drop FK first for MySQL
        if migrate_engine.name == 'mysql':
            ref_table = Table('volume_types', meta, autoload=True)
            params = {'columns': [encryptions.c['volume_type_id']],
                      'refcolumns': [ref_table.c['id']],
                      'name': 'encryption_ibfk_1'}
            volume_type_fk = ForeignKeyConstraint(**params)
            volume_type_fk.drop()

        volume_type_pk = PrimaryKeyConstraint('volume_type_id',
                                              table=encryptions)
        volume_type_pk.drop()

        pkey = PrimaryKeyConstraint(encryptions.columns.encryption_id)
        pkey.create()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    encryptions = Table('encryption', meta, autoload=True)
    encryption_id_pk = PrimaryKeyConstraint(encryptions.columns.encryption_id)

    encryption_id_pk.drop()
    encryptions.drop_column(encryptions.columns.encryption_id)

    volume_type_pk = PrimaryKeyConstraint(encryptions.columns.volume_type_id)
    volume_type_pk.create()

    ref_table = Table('volume_types', meta, autoload=True)
    params = {'columns': [encryptions.c['volume_type_id']],
              'refcolumns': [ref_table.c['id']],
              'name': 'encryption_ibfk_1'}
    volume_type_fk = ForeignKeyConstraint(**params)
    volume_type_fk.create()


def _upgrade_sqlite(meta, encryptions):
    new_encryptions = Table(
        'encryption_33', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('cipher', String(255)),
        Column('key_size', Integer),
        Column('provider', String(255)),
        Column('control_location', String(255)),
        Column('encryption_id', String(36), primary_key=True),
        Column('volume_type_id', String(36))
    )
    new_encryptions.create()
    encryption_items = list(encryptions.select().execute())
    for item in encryption_items:
        new_encryptions.insert().\
            values(created_at=item['created_at'],
                   updated_at=item['updated_at'],
                   deleted_at=item['deleted_at'],
                   deleted=item['deleted'],
                   cipher=item['cipher'],
                   key_size=item['key_size'],
                   provider=item['provider'],
                   control_location=item['control_location'],
                   encryption_id=str(uuid.uuid4()),
                   volume_type_id=item['volume_type_id']).execute()

    encryptions.drop()
    new_encryptions.rename('encryption')
