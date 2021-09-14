# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Initial migration.

Revision ID: 921e1a36b076
Revises:
Create Date: 2020-11-02 11:27:29.952490
"""

import datetime
import uuid

from alembic import op
from oslo_config import cfg
from oslo_utils import timeutils
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.sql import expression

from cinder.volume import group_types as volume_group_types
from cinder.volume import volume_types

# revision identifiers, used by Alembic.
revision = '921e1a36b076'
down_revision = None
branch_labels = None
depends_on = None

# Get default values via config.  The defaults will either
# come from the default values set in the quota option
# configuration or via cinder.conf if the user has configured
# default values for quotas there.
CONF = cfg.CONF
CONF.import_opt('quota_volumes', 'cinder.quota')
CONF.import_opt('quota_snapshots', 'cinder.quota')
CONF.import_opt('quota_gigabytes', 'cinder.quota')
CONF.import_opt('quota_consistencygroups', 'cinder.quota')

CLASS_NAME = 'default'
CREATED_AT = datetime.datetime.now()  # noqa


def upgrade():
    connection = op.get_bind()

    op.create_table(
        'services',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('host', sa.String(255)),
        sa.Column('binary', sa.String(255)),
        sa.Column('topic', sa.String(255)),
        sa.Column('report_count', sa.Integer, nullable=False),
        sa.Column('disabled', sa.Boolean),
        sa.Column('availability_zone', sa.String(255)),
        sa.Column('disabled_reason', sa.String(255)),
        sa.Column('modified_at', sa.DateTime(timezone=False)),
        sa.Column('rpc_current_version', sa.String(36)),
        sa.Column('object_current_version', sa.String(36)),
        sa.Column('replication_status', sa.String(36), default='not-capable'),
        sa.Column('frozen', sa.Boolean, default=False),
        sa.Column('active_backend_id', sa.String(255)),
        sa.Column('cluster_name', sa.String(255), nullable=True),
        sa.Column('uuid', sa.String(36), nullable=True),
        sa.Index('services_uuid_idx', 'uuid', unique=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'consistencygroups',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(255)),
        sa.Column('project_id', sa.String(255)),
        sa.Column('host', sa.String(255)),
        sa.Column('availability_zone', sa.String(255)),
        sa.Column('name', sa.String(255)),
        sa.Column('description', sa.String(255)),
        sa.Column('volume_type_id', sa.String(255)),
        sa.Column('status', sa.String(255)),
        sa.Column('cgsnapshot_id', sa.String(36)),
        sa.Column('source_cgid', sa.String(36)),
        sa.Column('cluster_name', sa.String(255), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'cgsnapshots',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            'consistencygroup_id',
            sa.String(36),
            sa.ForeignKey('consistencygroups.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('user_id', sa.String(255)),
        sa.Column('project_id', sa.String(255)),
        sa.Column('name', sa.String(255)),
        sa.Column('description', sa.String(255)),
        sa.Column('status', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'groups',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('cluster_name', sa.String(255)),
        sa.Column('host', sa.String(length=255)),
        sa.Column('availability_zone', sa.String(length=255)),
        sa.Column('name', sa.String(length=255)),
        sa.Column('description', sa.String(length=255)),
        sa.Column('group_type_id', sa.String(length=36)),
        sa.Column('status', sa.String(length=255)),
        sa.Column('group_snapshot_id', sa.String(36)),
        sa.Column('source_group_id', sa.String(36)),
        sa.Column('replication_status', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'group_snapshots',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'group_id',
            sa.String(36),
            sa.ForeignKey('groups.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('name', sa.String(length=255)),
        sa.Column('description', sa.String(length=255)),
        sa.Column('status', sa.String(length=255)),
        sa.Column('group_type_id', sa.String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'volumes',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('ec2_id', sa.String(255)),
        sa.Column('user_id', sa.String(255)),
        sa.Column('project_id', sa.String(255)),
        sa.Column('host', sa.String(255)),
        sa.Column('size', sa.Integer),
        sa.Column('availability_zone', sa.String(255)),
        sa.Column('status', sa.String(255)),
        sa.Column('attach_status', sa.String(255)),
        sa.Column('scheduled_at', sa.DateTime),
        sa.Column('launched_at', sa.DateTime),
        sa.Column('terminated_at', sa.DateTime),
        sa.Column('display_name', sa.String(255)),
        sa.Column('display_description', sa.String(255)),
        sa.Column('provider_location', sa.String(256)),
        sa.Column('provider_auth', sa.String(256)),
        sa.Column('snapshot_id', sa.String(36)),
        sa.Column('volume_type_id', sa.String(36), nullable=False),
        sa.Column('source_volid', sa.String(36)),
        sa.Column('bootable', sa.Boolean),
        sa.Column('provider_geometry', sa.String(255)),
        sa.Column('_name_id', sa.String(36)),
        sa.Column('encryption_key_id', sa.String(36)),
        sa.Column('migration_status', sa.String(255)),
        sa.Column('replication_status', sa.String(255)),
        sa.Column('replication_extended_status', sa.String(255)),
        sa.Column('replication_driver_data', sa.String(255)),
        sa.Column(
            'consistencygroup_id',
            sa.String(36),
            sa.ForeignKey('consistencygroups.id'),
            index=True,
        ),
        sa.Column('provider_id', sa.String(255)),
        sa.Column('multiattach', sa.Boolean),
        sa.Column('previous_status', sa.String(255)),
        sa.Column('cluster_name', sa.String(255), nullable=True),
        sa.Column(
            'group_id',
            sa.String(36),
            sa.ForeignKey('groups.id'),
            index=True,
        ),
        sa.Column(
            'service_uuid',
            sa.String(36),
            sa.ForeignKey('services.uuid'),
            nullable=True,
        ),
        sa.Column('shared_targets', sa.Boolean, default=True),
        sa.Column('use_quota', sa.Boolean, nullable=True),
        sa.Index('volumes_service_uuid_idx', 'service_uuid', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'volume_attachment',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            'volume_id',
            sa.String(36),
            sa.ForeignKey('volumes.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('attached_host', sa.String(255)),
        sa.Column('instance_uuid', sa.String(36)),
        sa.Column('mountpoint', sa.String(255)),
        sa.Column('attach_time', sa.DateTime),
        sa.Column('detach_time', sa.DateTime),
        sa.Column('attach_mode', sa.String(36)),
        sa.Column('attach_status', sa.String(255)),
        sa.Column('connection_info', sa.Text),
        sa.Column('connector', sa.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'attachment_specs',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(), default=False),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'attachment_id',
            sa.String(36),
            sa.ForeignKey('volume_attachment.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'snapshots',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            'volume_id',
            sa.String(36),
            sa.ForeignKey('volumes.id', name='snapshots_volume_id_fkey'),
            nullable=False,
            index=True,
        ),
        sa.Column('user_id', sa.String(255)),
        sa.Column('project_id', sa.String(255)),
        sa.Column('status', sa.String(255)),
        sa.Column('progress', sa.String(255)),
        sa.Column('volume_size', sa.Integer),
        sa.Column('scheduled_at', sa.DateTime),
        sa.Column('display_name', sa.String(255)),
        sa.Column('display_description', sa.String(255)),
        sa.Column('provider_location', sa.String(255)),
        sa.Column('encryption_key_id', sa.String(36)),
        sa.Column('volume_type_id', sa.String(36), nullable=False),
        sa.Column(
            'cgsnapshot_id',
            sa.String(36),
            sa.ForeignKey('cgsnapshots.id'),
            index=True,
        ),
        sa.Column('provider_id', sa.String(255)),
        sa.Column('provider_auth', sa.String(255)),
        sa.Column(
            'group_snapshot_id',
            sa.String(36),
            sa.ForeignKey('group_snapshots.id'),
            index=True,
        ),
        sa.Column('use_quota', sa.Boolean, nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'snapshot_metadata',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'snapshot_id',
            sa.String(36),
            sa.ForeignKey('snapshots.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'quality_of_service_specs',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            'specs_id',
            sa.String(36),
            sa.ForeignKey('quality_of_service_specs.id'),
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    volume_types_table = op.create_table(
        'volume_types',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('name', sa.String(255)),
        sa.Column(
            'qos_specs_id',
            sa.String(36),
            sa.ForeignKey('quality_of_service_specs.id'),
            index=True,
        ),
        sa.Column('is_public', sa.Boolean),
        sa.Column('description', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'volume_type_projects',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column(
            'volume_type_id', sa.String(36), sa.ForeignKey('volume_types.id')
        ),
        sa.Column('project_id', sa.String(255)),
        sa.Column('deleted', sa.Integer),
        sa.UniqueConstraint('volume_type_id', 'project_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'volume_metadata',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'volume_id',
            sa.String(36),
            sa.ForeignKey('volumes.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'volume_type_extra_specs',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'volume_type_id',
            sa.String(36),
            sa.ForeignKey(
                'volume_types.id',
                name='volume_type_extra_specs_ibfk_1',
            ),
            nullable=False,
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'quotas',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('project_id', sa.String(255)),
        sa.Column('resource', sa.String(255), nullable=False),
        sa.Column('hard_limit', sa.Integer),
        sa.Column('allocated', sa.Integer, default=0),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    quota_classes_table = op.create_table(
        'quota_classes',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('class_name', sa.String(255), index=True),
        sa.Column('resource', sa.String(255)),
        sa.Column('hard_limit', sa.Integer(), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'quota_usages',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.String(255), index=True),
        sa.Column('resource', sa.String(255)),
        sa.Column('in_use', sa.Integer(), nullable=False),
        sa.Column('reserved', sa.Integer(), nullable=False),
        sa.Column('until_refresh', sa.Integer(), nullable=True),
        sa.Column('race_preventer', sa.Boolean, nullable=True),
        sa.Index('quota_usage_project_resource_idx', 'project_id', 'resource'),
        sa.UniqueConstraint('project_id', 'resource', 'race_preventer'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'reservations',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), nullable=False),
        sa.Column(
            'usage_id',
            sa.Integer(),
            sa.ForeignKey('quota_usages.id'),
            nullable=True,
            index=True,
        ),
        sa.Column('project_id', sa.String(255), index=True),
        sa.Column('resource', sa.String(255)),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('expire', sa.DateTime(timezone=False)),
        sa.Column(
            'allocated_id',
            sa.Integer,
            sa.ForeignKey('quotas.id'),
            nullable=True,
            index=True,
        ),
        sa.Index('reservations_deleted_expire_idx', 'deleted', 'expire'),
        sa.Index('reservations_deleted_uuid_idx', 'deleted', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'volume_glance_metadata',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            'volume_id',
            sa.String(36),
            sa.ForeignKey('volumes.id'),
            index=True,
        ),
        sa.Column(
            'snapshot_id',
            sa.String(36),
            sa.ForeignKey('snapshots.id'),
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'backups',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('volume_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(255)),
        sa.Column('project_id', sa.String(255)),
        sa.Column('host', sa.String(255)),
        sa.Column('availability_zone', sa.String(255)),
        sa.Column('display_name', sa.String(255)),
        sa.Column('display_description', sa.String(255)),
        sa.Column('container', sa.String(255)),
        sa.Column('status', sa.String(255)),
        sa.Column('fail_reason', sa.String(255)),
        sa.Column('service_metadata', sa.String(255)),
        sa.Column('service', sa.String(255)),
        sa.Column('size', sa.Integer()),
        sa.Column('object_count', sa.Integer()),
        sa.Column('parent_id', sa.String(36)),
        sa.Column('temp_volume_id', sa.String(36)),
        sa.Column('temp_snapshot_id', sa.String(36)),
        sa.Column('num_dependent_backups', sa.Integer, default=0),
        sa.Column('snapshot_id', sa.String(36)),
        sa.Column('data_timestamp', sa.DateTime),
        sa.Column('restore_volume_id', sa.String(36)),
        sa.Column('encryption_key_id', sa.String(36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'backup_metadata',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(), default=False),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'backup_id',
            sa.String(36),
            sa.ForeignKey('backups.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'transfers',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            'volume_id',
            sa.String(36),
            sa.ForeignKey('volumes.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('display_name', sa.String(255)),
        sa.Column('salt', sa.String(255)),
        sa.Column('crypt_hash', sa.String(255)),
        sa.Column('expires_at', sa.DateTime(timezone=False)),
        sa.Column('no_snapshots', sa.Boolean, default=False),
        sa.Column('source_project_id', sa.String(255), nullable=True),
        sa.Column('destination_project_id', sa.String(255), nullable=True),
        sa.Column('accepted', sa.Boolean, default=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    # Sqlite needs to handle nullable differently
    is_nullable = connection.engine.name == 'sqlite'

    op.create_table(
        'encryption',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('cipher', sa.String(255)),
        sa.Column('control_location', sa.String(255), nullable=is_nullable),
        sa.Column('key_size', sa.Integer),
        sa.Column('provider', sa.String(255), nullable=is_nullable),
        # NOTE(joel-coffman): The volume_type_id must be unique or else the
        # referenced volume type becomes ambiguous. That is, specifying the
        # volume type is not sufficient to identify a particular encryption
        # scheme unless each volume type is associated with at most one
        # encryption scheme.
        sa.Column('volume_type_id', sa.String(36), nullable=False),
        # NOTE (smcginnis): nullable=True triggers this to not set a default
        # value, but since it's a primary key the resulting schema will end up
        # still being NOT NULL. This is avoiding a case in MySQL where it will
        # otherwise set this to NOT NULL DEFAULT ''. May be harmless, but
        # inconsistent with previous schema.
        sa.Column(
            'encryption_id',
            sa.String(36),
            primary_key=True,
            nullable=True,
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'volume_admin_metadata',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'volume_id',
            sa.String(36),
            sa.ForeignKey('volumes.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'driver_initiator_data',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('initiator', sa.String(255), index=True, nullable=False),
        sa.Column('namespace', sa.String(255), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.String(255)),
        sa.UniqueConstraint('initiator', 'namespace', 'key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'image_volume_cache_entries',
        sa.Column('image_updated_at', sa.DateTime(timezone=False)),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('host', sa.String(255), index=True, nullable=False),
        sa.Column('image_id', sa.String(36), index=True, nullable=False),
        sa.Column('volume_id', sa.String(36), nullable=False),
        sa.Column('size', sa.Integer, nullable=False),
        sa.Column('last_used', sa.DateTime, nullable=False),
        sa.Column('cluster_name', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'messages',
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(255), nullable=False),
        sa.Column('request_id', sa.String(255)),
        sa.Column('resource_type', sa.String(36)),
        sa.Column('resource_uuid', sa.String(255), nullable=True),
        sa.Column('event_id', sa.String(255), nullable=False),
        sa.Column('message_level', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean),
        sa.Column('expires_at', sa.DateTime(timezone=False), index=True),
        sa.Column('detail_id', sa.String(10), nullable=True),
        sa.Column('action_id', sa.String(10), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'clusters',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(), default=False),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('binary', sa.String(255), nullable=False),
        sa.Column('disabled', sa.Boolean(), default=False),
        sa.Column('disabled_reason', sa.String(255)),
        sa.Column('race_preventer', sa.Integer, nullable=False, default=0),
        sa.Column(
            'replication_status',
            sa.String(length=36),
            default='not-capable',
        ),
        sa.Column('active_backend_id', sa.String(length=255)),
        sa.Column(
            'frozen',
            sa.Boolean,
            nullable=False,
            default=False,
            server_default=expression.false(),
        ),
        # To remove potential races on creation we have a constraint set on
        # name and race_preventer fields, and we set value on creation to 0, so
        # 2 clusters with the same name will fail this constraint.  On deletion
        # we change this field to the same value as the id which will be unique
        # and will not conflict with the creation of another cluster with the
        # same name.
        sa.UniqueConstraint('name', 'binary', 'race_preventer'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    workers_table = op.create_table(
        'workers',
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(), default=False),
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('resource_type', sa.String(40), nullable=False),
        sa.Column('resource_id', sa.String(36), nullable=False),
        sa.Column('status', sa.String(255), nullable=False),
        sa.Column(
            'service_id',
            sa.Integer,
            sa.ForeignKey('services.id'),
            nullable=True,
            index=True,
        ),
        sa.Column(
            'race_preventer',
            sa.Integer,
            nullable=False,
            default=0,
            server_default=sa.text('0'),
        ),
        sa.UniqueConstraint('resource_type', 'resource_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_types_table = op.create_table(
        'group_types',
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean),
        sa.Column('is_public', sa.Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_type_specs_table = op.create_table(
        'group_type_specs',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        sa.Column(
            'group_type_id',
            sa.String(36),
            sa.ForeignKey('group_types.id'),
            nullable=False,
            index=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'group_type_projects',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column(
            'group_type_id', sa.String(36), sa.ForeignKey('group_types.id')
        ),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.UniqueConstraint('group_type_id', 'project_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'group_volume_type_mapping',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'volume_type_id',
            sa.String(36),
            sa.ForeignKey('volume_types.id'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'group_id',
            sa.String(36),
            sa.ForeignKey('groups.id'),
            nullable=False,
            index=True,
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'default_volume_types',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column(
            'volume_type_id',
            sa.String(36),
            sa.ForeignKey('volume_types.id'),
            index=True),
        sa.Column(
            'project_id',
            sa.String(length=255),
            primary_key=True,
            nullable=False),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    if connection.engine.name == "mysql":
        tables = [
            "consistencygroups",
            "cgsnapshots",
            "snapshots",
            "snapshot_metadata",
            "quality_of_service_specs",
            "volume_types",
            "volume_type_projects",
            "volumes",
            "volume_attachment",
            "quotas",
            "services",
            "volume_metadata",
            "volume_type_extra_specs",
            "quota_classes",
            "quota_usages",
            "reservations",
            "volume_glance_metadata",
            "backups",
            "backup_metadata",
            "transfers",
            "encryption",
            "volume_admin_metadata",
            "driver_initiator_data",
            "image_volume_cache_entries",
        ]

        connection.execute("SET foreign_key_checks = 0")

        for table in tables:
            connection.execute(
                "ALTER TABLE %s CONVERT TO CHARACTER SET utf8" % table
            )

        connection.execute("SET foreign_key_checks = 1")
        connection.execute(
            "ALTER DATABASE %s DEFAULT CHARACTER SET utf8"
            % connection.engine.url.database
        )
        connection.execute("ALTER TABLE %s Engine=InnoDB" % table)

    # This is only necessary for mysql, and since the table is not in use this
    # will only be a schema update.
    if connection.engine.name.startswith('mysql'):
        try:
            with op.batch_alter_table('workers') as batch_op:
                batch_op.alter_column(
                    'updated_at', type_=mysql.DATETIME(fsp=6)
                )
        except Exception:
            # MySQL v5.5 or earlier don't support sub-second resolution so we
            # may have cleanup races in Active-Active configurations, that's
            # why upgrading is recommended in that case.
            # Code in Cinder is capable of working with 5.5, so for 5.5 there's
            # no problem
            pass

    # Increase the resource column size to the quota_usages table.
    #
    # The resource value is constructed from (prefix + volume_type_name),
    # but the length of volume_type_name is limited to 255, if we add a
    # prefix such as 'volumes_' or 'gigabytes_' to volume_type_name it
    # will exceed the db length limit.
    try:
        with op.batch_alter_table('quota_usages') as batch_op:
            batch_op.alter_column('resource', type_=sa.String(300))
    except Exception:
        # On MariaDB, max length varies depending on the version and the InnoDB
        # page size [1], so it is possible to have error 1071 ('Specified key
        # was too long; max key length is 767 bytes").  Since this migration is
        # to resolve a corner case, deployments with those DB versions won't be
        # covered.
        # [1]: https://mariadb.com/kb/en/library/innodb-limitations/#page-sizes
        if not connection.engine.name.startswith('mysql'):
            raise

    op.bulk_insert(
        quota_classes_table,
        [
            # Set default quota class values
            {
                'created_at': CREATED_AT,
                'class_name': CLASS_NAME,
                'resource': 'volumes',
                'hard_limit': CONF.quota_volumes,
                'deleted': False,
            },
            {
                'created_at': CREATED_AT,
                'class_name': CLASS_NAME,
                'resource': 'snapshots',
                'hard_limit': CONF.quota_snapshots,
                'deleted': False,
            },
            # Set default gigabytes
            {
                'created_at': CREATED_AT,
                'class_name': CLASS_NAME,
                'resource': 'gigabytes',
                'hard_limit': CONF.quota_gigabytes,
                'deleted': False,
            },
            {
                'created_at': CREATED_AT,
                'class_name': CLASS_NAME,
                'resource': 'consistencygroups',
                'hard_limit': CONF.quota_consistencygroups,
                'deleted': False,
            },
            {
                'created_at': CREATED_AT,
                'class_name': CLASS_NAME,
                'resource': 'per_volume_gigabytes',
                'hard_limit': -1,
                'deleted': False,
            },
            {
                'created_at': CREATED_AT,
                'class_name': CLASS_NAME,
                'resource': 'groups',
                'hard_limit': CONF.quota_groups,
                'deleted': False,
            },
        ],
    )

    # TODO(geguileo): Once we remove support for MySQL 5.5 we have to create
    # an upgrade migration to remove this row.
    # Set workers table sub-second support sentinel
    now = timeutils.utcnow().replace(microsecond=123)
    op.bulk_insert(
        workers_table,
        [
            {
                'created_at': now,
                'updated_at': now,
                'deleted': False,
                'resource_type': 'SENTINEL',
                'resource_id': 'SUB-SECOND',
                'status': 'OK',
            },
        ],
    )

    # Create default group type
    now = timeutils.utcnow()
    grp_type_id = "%s" % uuid.uuid4()
    op.bulk_insert(
        group_types_table,
        [
            {
                'id': grp_type_id,
                'name': volume_group_types.DEFAULT_CGSNAPSHOT_TYPE,
                'description': 'Default group type for migrating cgsnapshot',
                'created_at': now,
                'updated_at': now,
                'deleted': False,
                'is_public': True,
            },
        ],
    )
    op.bulk_insert(
        group_type_specs_table,
        [
            {
                'key': 'consistent_group_snapshot_enabled',
                'value': '<is> True',
                'group_type_id': grp_type_id,
                'created_at': now,
                'updated_at': now,
                'deleted': False,
            },
        ],
    )

    # Create default volume type
    op.bulk_insert(
        volume_types_table,
        [
            {
                'id': str(uuid.uuid4()),
                'name': volume_types.DEFAULT_VOLUME_TYPE,
                'description': 'Default Volume Type',
                'created_at': now,
                'updated_at': now,
                'deleted': False,
                'is_public': True,
            },
        ],
    )
