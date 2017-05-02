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

from oslo_db.sqlalchemy import utils
from oslo_log import log as logging
from sqlalchemy import MetaData

LOG = logging.getLogger(__name__)


def ensure_index_exists(migrate_engine, table_name, column):
    index_name = table_name + '_' + column + '_idx'
    columns = [column]

    if utils.index_exists_on_columns(migrate_engine, table_name, columns):
        LOG.info(
            'Skipped adding %s because an equivalent index already exists.',
            index_name
        )
    else:
        utils.add_index(migrate_engine, table_name, index_name, columns)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    for table_name, column in INDEXES_TO_CREATE:
        ensure_index_exists(migrate_engine, table_name, column)


INDEXES_TO_CREATE = (
    ('attachment_specs', 'attachment_id'),
    ('cgsnapshots', 'consistencygroup_id'),
    ('group_snapshots', 'group_id'),
    ('group_type_specs', 'group_type_id'),
    ('group_volume_type_mapping', 'group_id'),
    ('group_volume_type_mapping', 'volume_type_id'),
    ('quality_of_service_specs', 'specs_id'),
    ('reservations', 'allocated_id'),
    ('reservations', 'usage_id'),
    ('snapshot_metadata', 'snapshot_id'),
    ('snapshots', 'cgsnapshot_id'),
    ('snapshots', 'group_snapshot_id'),
    ('snapshots', 'volume_id'),
    ('transfers', 'volume_id'),
    ('volume_admin_metadata', 'volume_id'),
    ('volume_attachment', 'volume_id'),
    ('volume_glance_metadata', 'snapshot_id'),
    ('volume_glance_metadata', 'volume_id'),
    ('volume_metadata', 'volume_id'),
    ('volume_type_extra_specs', 'volume_type_id'),
    ('volume_types', 'qos_specs_id'),
    ('volumes', 'consistencygroup_id'),
    ('volumes', 'group_id'),
    ('workers', 'service_id'),
)
