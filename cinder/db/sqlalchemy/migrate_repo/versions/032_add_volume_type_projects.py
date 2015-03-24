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

from oslo_log import log as logging
from sqlalchemy import Boolean, Column, DateTime, UniqueConstraint
from sqlalchemy import Integer, MetaData, String, Table, ForeignKey

from cinder.i18n import _

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    volume_types = Table('volume_types', meta, autoload=True)
    is_public = Column('is_public', Boolean)

    try:
        volume_types.create_column(is_public)
        # pylint: disable=E1120
        volume_types.update().values(is_public=True).execute()
    except Exception:
        LOG.error(_("Column |%s| not created!"), repr(is_public))
        raise

    volume_type_projects = Table(
        'volume_type_projects', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('volume_type_id', String(36),
               ForeignKey('volume_types.id')),
        Column('project_id', String(length=255)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        UniqueConstraint('volume_type_id', 'project_id', 'deleted'),
        mysql_engine='InnoDB',
    )

    try:
        volume_type_projects.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(volume_type_projects))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volume_types = Table('volume_types', meta, autoload=True)
    is_public = volume_types.columns.is_public
    try:
        volume_types.drop_column(is_public)
    except Exception:
        LOG.error(_("volume_types.is_public column not dropped"))
        raise

    volume_type_projects = Table('volume_type_projects', meta, autoload=True)
    try:
        volume_type_projects.drop()
    except Exception:
        LOG.error(_("volume_type_projects table not dropped"))
        raise
