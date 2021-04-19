# Copyright 2012 OpenStack Foundation
#
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

import datetime
import uuid

from oslo_config import cfg
from oslo_utils import timeutils
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.sql import expression

from cinder.volume import group_types as volume_group_types
from cinder.volume import volume_types

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


def define_tables(meta):
    services = sa.Table(
        'services', meta,
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
        mysql_charset='utf8'
    )

    consistencygroups = sa.Table(
        'consistencygroups', meta,
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
        mysql_charset='utf8'
    )

    cgsnapshots = sa.Table(
        'cgsnapshots', meta,
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
            index=True),
        sa.Column('user_id', sa.String(255)),
        sa.Column('project_id', sa.String(255)),
        sa.Column('name', sa.String(255)),
        sa.Column('description', sa.String(255)),
        sa.Column('status', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    groups = sa.Table(
        'groups', meta,
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

    group_snapshots = sa.Table(
        'group_snapshots', meta,
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
            index=True),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('name', sa.String(length=255)),
        sa.Column('description', sa.String(length=255)),
        sa.Column('status', sa.String(length=255)),
        sa.Column('group_type_id', sa.String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    volumes = sa.Table(
        'volumes', meta,
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
        sa.Column('volume_type_id', sa.String(36)),
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
            index=True),
        sa.Column('provider_id', sa.String(255)),
        sa.Column('multiattach', sa.Boolean),
        sa.Column('previous_status', sa.String(255)),
        sa.Column('cluster_name', sa.String(255), nullable=True),
        sa.Column(
            'group_id',
            sa.String(36),
            sa.ForeignKey('groups.id'),
            index=True),
        sa.Column(
            'service_uuid',
            sa.String(36),
            sa.ForeignKey('services.uuid'),
            nullable=True),
        sa.Column('shared_targets', sa.Boolean, default=True),
        sa.Index('volumes_service_uuid_idx', 'service_uuid', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_attachment = sa.Table(
        'volume_attachment', meta,
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
            index=True),
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
        mysql_charset='utf8'
    )

    attachment_specs = sa.Table(
        'attachment_specs', meta,
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
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshots = sa.Table(
        'snapshots', meta,
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
            index=True),
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
        sa.Column('volume_type_id', sa.String(36)),
        sa.Column(
            'cgsnapshot_id',
            sa.String(36),
            sa.ForeignKey('cgsnapshots.id'),
            index=True),
        sa.Column('provider_id', sa.String(255)),
        sa.Column('provider_auth', sa.String(255)),
        sa.Column(
            'group_snapshot_id',
            sa.String(36),
            sa.ForeignKey('group_snapshots.id'),
            index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshot_metadata = sa.Table(
        'snapshot_metadata', meta,
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
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quality_of_service_specs = sa.Table(
        'quality_of_service_specs', meta,
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            'specs_id',
            sa.String(36),
            sa.ForeignKey('quality_of_service_specs.id'),
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_types = sa.Table(
        'volume_types', meta,
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
            index=True),
        sa.Column('is_public', sa.Boolean),
        sa.Column('description', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_type_projects = sa.Table(
        'volume_type_projects', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column(
            'volume_type_id',
            sa.String(36),
            sa.ForeignKey('volume_types.id')),
        sa.Column('project_id', sa.String(255)),
        sa.Column('deleted', sa.Integer),
        sa.UniqueConstraint('volume_type_id', 'project_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_metadata = sa.Table(
        'volume_metadata', meta,
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
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_type_extra_specs = sa.Table(
        'volume_type_extra_specs', meta,
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
                name='volume_type_extra_specs_ibfk_1'),
            nullable=False,
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quotas = sa.Table(
        'quotas', meta,
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
        mysql_charset='utf8'
    )

    quota_classes = sa.Table(
        'quota_classes', meta,
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

    quota_usages = sa.Table(
        'quota_usages', meta,
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
        sa.Index('quota_usage_project_resource_idx', 'project_id', 'resource'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    reservations = sa.Table(
        'reservations', meta,
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
            index=True),
        sa.Column('project_id', sa.String(255), index=True),
        sa.Column('resource', sa.String(255)),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('expire', sa.DateTime(timezone=False)),
        sa.Column(
            'allocated_id',
            sa.Integer,
            sa.ForeignKey('quotas.id'),
            nullable=True,
            index=True),
        sa.Index('reservations_deleted_expire_idx', 'deleted', 'expire'),
        sa.Index('reservations_deleted_uuid_idx', 'deleted', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    volume_glance_metadata = sa.Table(
        'volume_glance_metadata',
        meta,
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            'volume_id',
            sa.String(36),
            sa.ForeignKey('volumes.id'),
            index=True),
        sa.Column(
            'snapshot_id',
            sa.String(36),
            sa.ForeignKey('snapshots.id'),
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    backups = sa.Table(
        'backups', meta,
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
        mysql_charset='utf8'
    )

    backup_metadata = sa.Table(
        'backup_metadata', meta,
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
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    transfers = sa.Table(
        'transfers', meta,
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
            index=True),
        sa.Column('display_name', sa.String(255)),
        sa.Column('salt', sa.String(255)),
        sa.Column('crypt_hash', sa.String(255)),
        sa.Column('expires_at', sa.DateTime(timezone=False)),
        sa.Column('no_snapshots', sa.Boolean, default=False),
        sa.Column('source_project_id', sa.String(255), nullable=True),
        sa.Column('destination_project_id', sa.String(255), nullable=True),
        sa.Column('accepted', sa.Boolean, default=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    # Sqlite needs to handle nullable differently
    is_nullable = (meta.bind.name == 'sqlite')

    encryption = sa.Table(
        'encryption', meta,
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
        sa.Column('volume_type_id', sa.String(36), nullable=is_nullable),
        # NOTE (smcginnis): nullable=True triggers this to not set a default
        # value, but since it's a primary key the resulting schema will end up
        # still being NOT NULL. This is avoiding a case in MySQL where it will
        # otherwise set this to NOT NULL DEFAULT ''. May be harmless, but
        # inconsistent with previous schema.
        sa.Column(
            'encryption_id',
            sa.String(36),
            primary_key=True,
            nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_admin_metadata = sa.Table(
        'volume_admin_metadata', meta,
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
            index=True),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    initiator_data = sa.Table(
        'driver_initiator_data', meta,
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('initiator', sa.String(255), index=True, nullable=False),
        sa.Column('namespace', sa.String(255), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.String(255)),
        sa.UniqueConstraint('initiator', 'namespace', 'key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    image_volume_cache = sa.Table(
        'image_volume_cache_entries', meta,
        sa.Column('image_updated_at', sa.DateTime(timezone=False)),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('host', sa.String(255), index=True, nullable=False),
        sa.Column('image_id', sa.String(36), index=True, nullable=False),
        sa.Column('volume_id', sa.String(36), nullable=False),
        sa.Column('size', sa.Integer, nullable=False),
        sa.Column('last_used', sa.DateTime, nullable=False),
        sa.Column('cluster_name', sa.String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    messages = sa.Table(
        'messages', meta,
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
        mysql_charset='utf8'
    )

    cluster = sa.Table(
        'clusters', meta,
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
            default='not-capable'),
        sa.Column('active_backend_id', sa.String(length=255)),
        sa.Column(
            'frozen',
            sa.Boolean,
            nullable=False,
            default=False,
            server_default=expression.false()),
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

    workers = sa.Table(
        'workers', meta,
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
            index=True),
        sa.Column(
            'race_preventer',
            sa.Integer,
            nullable=False,
            default=0,
            server_default=sa.text('0')),
        sa.UniqueConstraint('resource_type', 'resource_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_types = sa.Table(
        'group_types', meta,
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

    group_type_specs = sa.Table(
        'group_type_specs', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('key', sa.String(255)),
        sa.Column('value', sa.String(255)),
        sa.Column(
            'group_type_id',
            sa.String(36),
            sa.ForeignKey('group_types.id'),
            nullable=False,
            index=True),
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_type_projects = sa.Table(
        'group_type_projects', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column(
            'group_type_id',
            sa.String(36),
            sa.ForeignKey('group_types.id')),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        sa.UniqueConstraint('group_type_id', 'project_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    grp_vt_mapping = sa.Table(
        'group_volume_type_mapping', meta,
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
            index=True),
        sa.Column(
            'group_id',
            sa.String(36),
            sa.ForeignKey('groups.id'),
            nullable=False,
            index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    return [consistencygroups,
            cgsnapshots,
            groups,
            group_snapshots,
            services,
            volumes,
            volume_attachment,
            attachment_specs,
            snapshots,
            snapshot_metadata,
            quality_of_service_specs,
            volume_types,
            volume_type_projects,
            quotas,
            volume_metadata,
            volume_type_extra_specs,
            quota_classes,
            quota_usages,
            reservations,
            volume_glance_metadata,
            backups,
            backup_metadata,
            transfers,
            encryption,
            volume_admin_metadata,
            initiator_data,
            image_volume_cache,
            messages,
            cluster,
            workers,
            group_types,
            group_type_specs,
            group_type_projects,
            grp_vt_mapping]


def upgrade(migrate_engine):
    meta = sa.MetaData()
    meta.bind = migrate_engine

    # create all tables
    # Take care on create order for those with FK dependencies
    tables = define_tables(meta)

    for table in tables:
        table.create()

    if migrate_engine.name == "mysql":
        tables = ["consistencygroups",
                  "cgsnapshots",
                  "snapshots",
                  "snapshot_metadata",
                  "quality_of_service_specs",
                  "volume_types",
                  "volume_type_projects",
                  "volumes",
                  "volume_attachment",
                  "migrate_version",
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
                  "image_volume_cache_entries"]

        migrate_engine.execute("SET foreign_key_checks = 0")
        for table in tables:
            migrate_engine.execute(
                "ALTER TABLE %s CONVERT TO CHARACTER SET utf8" % table)
        migrate_engine.execute("SET foreign_key_checks = 1")
        migrate_engine.execute(
            "ALTER DATABASE %s DEFAULT CHARACTER SET utf8" %
            migrate_engine.url.database)
        migrate_engine.execute("ALTER TABLE %s Engine=InnoDB" % table)

    workers = sa.Table('workers', meta, autoload=True)

    # This is only necessary for mysql, and since the table is not in use this
    # will only be a schema update.
    if migrate_engine.name.startswith('mysql'):
        try:
            workers.c.updated_at.alter(mysql.DATETIME(fsp=6))
        except Exception:
            # MySQL v5.5 or earlier don't support sub-second resolution so we
            # may have cleanup races in Active-Active configurations, that's
            # why upgrading is recommended in that case.
            # Code in Cinder is capable of working with 5.5, so for 5.5 there's
            # no problem
            pass

    quota_usages = sa.Table('quota_usages', meta, autoload=True)
    try:
        quota_usages.c.resource.alter(type=sa.String(300))
    except Exception:
        # On MariaDB, max length varies depending on the version and the InnoDB
        # page size [1], so it is possible to have error 1071 ('Specified key
        # was too long; max key length is 767 bytes").  Since this migration is
        # to resolve a corner case, deployments with those DB versions won't be
        # covered.
        # [1]: https://mariadb.com/kb/en/library/innodb-limitations/#page-sizes
        if not migrate_engine.name.startswith('mysql'):
            raise

    # Set default quota class values
    quota_classes = sa.Table('quota_classes', meta, autoload=True)
    qci = quota_classes.insert()
    qci.execute({'created_at': CREATED_AT,
                 'class_name': CLASS_NAME,
                 'resource': 'volumes',
                 'hard_limit': CONF.quota_volumes,
                 'deleted': False, })
    # Set default snapshots
    qci.execute({'created_at': CREATED_AT,
                 'class_name': CLASS_NAME,
                 'resource': 'snapshots',
                 'hard_limit': CONF.quota_snapshots,
                 'deleted': False, })
    # Set default gigabytes
    qci.execute({'created_at': CREATED_AT,
                 'class_name': CLASS_NAME,
                 'resource': 'gigabytes',
                 'hard_limit': CONF.quota_gigabytes,
                 'deleted': False, })
    qci.execute({'created_at': CREATED_AT,
                 'class_name': CLASS_NAME,
                 'resource': 'consistencygroups',
                 'hard_limit': CONF.quota_consistencygroups,
                 'deleted': False, })
    qci.execute({'created_at': CREATED_AT,
                 'class_name': CLASS_NAME,
                 'resource': 'per_volume_gigabytes',
                 'hard_limit': -1,
                 'deleted': False, })
    qci.execute({'created_at': CREATED_AT,
                 'class_name': CLASS_NAME,
                 'resource': 'groups',
                 'hard_limit': CONF.quota_groups,
                 'deleted': False, })

    # TODO(geguileo): Once we remove support for MySQL 5.5 we have to create
    # an upgrade migration to remove this row.
    # Set workers table sub-second support sentinel
    workers = sa.Table('workers', meta, autoload=True)
    wi = workers.insert()
    now = timeutils.utcnow().replace(microsecond=123)
    wi.execute({'created_at': now,
                'updated_at': now,
                'deleted': False,
                'resource_type': 'SENTINEL',
                'resource_id': 'SUB-SECOND',
                'status': 'OK'})

    # Create default group type
    group_types = sa.Table('group_types', meta, autoload=True)
    group_type_specs = sa.Table('group_type_specs', meta, autoload=True)

    now = timeutils.utcnow()
    grp_type_id = "%s" % uuid.uuid4()
    group_type_dicts = {
        'id': grp_type_id,
        'name': volume_group_types.DEFAULT_CGSNAPSHOT_TYPE,
        'description': 'Default group type for migrating cgsnapshot',
        'created_at': now,
        'updated_at': now,
        'deleted': False,
        'is_public': True,
    }
    grp_type = group_types.insert()
    grp_type.execute(group_type_dicts)

    group_spec_dicts = {
        'key': 'consistent_group_snapshot_enabled',
        'value': '<is> True',
        'group_type_id': grp_type_id,
        'created_at': now,
        'updated_at': now,
        'deleted': False,
    }
    grp_spec = group_type_specs.insert()
    grp_spec.execute(group_spec_dicts)

    # Increase the resource column size to the quota_usages table.
    #
    # The resource value is constructed from (prefix + volume_type_name),
    # but the length of volume_type_name is limited to 255, if we add a
    # prefix such as 'volumes_' or 'gigabytes_' to volume_type_name it
    # will exceed the db length limit.

    # Create default volume type
    vol_types = sa.Table("volume_types", meta, autoload=True)
    volume_type_dict = {
        'id': str(uuid.uuid4()),
        'name': volume_types.DEFAULT_VOLUME_TYPE,
        'description': 'Default Volume Type',
        'created_at': now,
        'updated_at': now,
        'deleted': False,
        'is_public': True,
    }
    vol_type = vol_types.insert()
    vol_type.execute(volume_type_dict)
