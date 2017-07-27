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

from oslo_config import cfg
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index
from sqlalchemy import Integer, MetaData, String, Table, Text, UniqueConstraint

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
    services = Table(
        'services', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(255)),
        Column('binary', String(255)),
        Column('topic', String(255)),
        Column('report_count', Integer, nullable=False),
        Column('disabled', Boolean),
        Column('availability_zone', String(255)),
        Column('disabled_reason', String(255)),
        Column('modified_at', DateTime(timezone=False)),
        Column('rpc_current_version', String(36)),
        Column('object_current_version', String(36)),
        Column('replication_status', String(36), default='not-capable'),
        Column('frozen', Boolean, default=False),
        Column('active_backend_id', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    consistencygroups = Table(
        'consistencygroups', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('user_id', String(255)),
        Column('project_id', String(255)),
        Column('host', String(255)),
        Column('availability_zone', String(255)),
        Column('name', String(255)),
        Column('description', String(255)),
        Column('volume_type_id', String(255)),
        Column('status', String(255)),
        Column('cgsnapshot_id', String(36)),
        Column('source_cgid', String(36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    cgsnapshots = Table(
        'cgsnapshots', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('consistencygroup_id', String(36),
               ForeignKey('consistencygroups.id'),
               nullable=False),
        Column('user_id', String(255)),
        Column('project_id', String(255)),
        Column('name', String(255)),
        Column('description', String(255)),
        Column('status', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volumes = Table(
        'volumes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('ec2_id', String(255)),
        Column('user_id', String(255)),
        Column('project_id', String(255)),
        Column('host', String(255)),
        Column('size', Integer),
        Column('availability_zone', String(255)),
        Column('status', String(255)),
        Column('attach_status', String(255)),
        Column('scheduled_at', DateTime),
        Column('launched_at', DateTime),
        Column('terminated_at', DateTime),
        Column('display_name', String(255)),
        Column('display_description', String(255)),
        Column('provider_location', String(256)),
        Column('provider_auth', String(256)),
        Column('snapshot_id', String(36)),
        Column('volume_type_id', String(36)),
        Column('source_volid', String(36)),
        Column('bootable', Boolean),
        Column('provider_geometry', String(255)),
        Column('_name_id', String(36)),
        Column('encryption_key_id', String(36)),
        Column('migration_status', String(255)),
        Column('replication_status', String(255)),
        Column('replication_extended_status', String(255)),
        Column('replication_driver_data', String(255)),
        Column('consistencygroup_id', String(36),
               ForeignKey('consistencygroups.id')),
        Column('provider_id', String(255)),
        Column('multiattach', Boolean),
        Column('previous_status', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_attachment = Table(
        'volume_attachment', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('volume_id', String(36), ForeignKey('volumes.id'),
               nullable=False),
        Column('attached_host', String(255)),
        Column('instance_uuid', String(36)),
        Column('mountpoint', String(255)),
        Column('attach_time', DateTime),
        Column('detach_time', DateTime),
        Column('attach_mode', String(36)),
        Column('attach_status', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshots = Table(
        'snapshots', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('volume_id', String(36),
               ForeignKey('volumes.id', name='snapshots_volume_id_fkey'),
               nullable=False),
        Column('user_id', String(255)),
        Column('project_id', String(255)),
        Column('status', String(255)),
        Column('progress', String(255)),
        Column('volume_size', Integer),
        Column('scheduled_at', DateTime),
        Column('display_name', String(255)),
        Column('display_description', String(255)),
        Column('provider_location', String(255)),
        Column('encryption_key_id', String(36)),
        Column('volume_type_id', String(36)),
        Column('cgsnapshot_id', String(36),
               ForeignKey('cgsnapshots.id')),
        Column('provider_id', String(255)),
        Column('provider_auth', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshot_metadata = Table(
        'snapshot_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('snapshot_id', String(36), ForeignKey('snapshots.id'),
               nullable=False),
        Column('key', String(255)),
        Column('value', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quality_of_service_specs = Table(
        'quality_of_service_specs', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('specs_id', String(36),
               ForeignKey('quality_of_service_specs.id')),
        Column('key', String(255)),
        Column('value', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_types = Table(
        'volume_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('name', String(255)),
        Column('qos_specs_id', String(36),
               ForeignKey('quality_of_service_specs.id')),
        Column('is_public', Boolean),
        Column('description', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_type_projects = Table(
        'volume_type_projects', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('volume_type_id', String(36),
               ForeignKey('volume_types.id')),
        Column('project_id', String(255)),
        Column('deleted', Integer),
        UniqueConstraint('volume_type_id', 'project_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_metadata = Table(
        'volume_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_id', String(36), ForeignKey('volumes.id'),
               nullable=False),
        Column('key', String(255)),
        Column('value', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_type_extra_specs = Table(
        'volume_type_extra_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_type_id', String(36),
               ForeignKey('volume_types.id',
                          name='volume_type_extra_specs_ibfk_1'),
               nullable=False),
        Column('key', String(255)),
        Column('value', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quotas = Table(
        'quotas', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('project_id', String(255)),
        Column('resource', String(255), nullable=False),
        Column('hard_limit', Integer),
        Column('allocated', Integer, default=0),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_classes = Table(
        'quota_classes', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True,
                                  name=None)),
        Column('id', Integer(), primary_key=True),
        Column('class_name', String(255), index=True),
        Column('resource', String(255)),
        Column('hard_limit', Integer(), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    quota_usages = Table(
        'quota_usages', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True,
                                  name=None)),
        Column('id', Integer(), primary_key=True),
        Column('project_id', String(255), index=True),
        Column('resource', String(255)),
        Column('in_use', Integer(), nullable=False),
        Column('reserved', Integer(), nullable=False),
        Column('until_refresh', Integer(), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    reservations = Table(
        'reservations', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True,
                                  name=None)),
        Column('id', Integer(), primary_key=True),
        Column('uuid', String(36), nullable=False),
        Column('usage_id',
               Integer(),
               ForeignKey('quota_usages.id'),
               nullable=True),
        Column('project_id', String(255), index=True),
        Column('resource', String(255)),
        Column('delta', Integer(), nullable=False),
        Column('expire', DateTime(timezone=False)),
        Column('allocated_id', Integer, ForeignKey('quotas.id'),
               nullable=True),
        Index('reservations_deleted_expire_idx',
              'deleted', 'expire'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    volume_glance_metadata = Table(
        'volume_glance_metadata',
        meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('volume_id', String(36), ForeignKey('volumes.id')),
        Column('snapshot_id', String(36),
               ForeignKey('snapshots.id')),
        Column('key', String(255)),
        Column('value', Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    backups = Table(
        'backups', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('volume_id', String(36), nullable=False),
        Column('user_id', String(255)),
        Column('project_id', String(255)),
        Column('host', String(255)),
        Column('availability_zone', String(255)),
        Column('display_name', String(255)),
        Column('display_description', String(255)),
        Column('container', String(255)),
        Column('status', String(255)),
        Column('fail_reason', String(255)),
        Column('service_metadata', String(255)),
        Column('service', String(255)),
        Column('size', Integer()),
        Column('object_count', Integer()),
        Column('parent_id', String(36)),
        Column('temp_volume_id', String(36)),
        Column('temp_snapshot_id', String(36)),
        Column('num_dependent_backups', Integer, default=0),
        Column('snapshot_id', String(36)),
        Column('data_timestamp', DateTime),
        Column('restore_volume_id', String(36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    transfers = Table(
        'transfers', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('volume_id', String(36), ForeignKey('volumes.id'),
               nullable=False),
        Column('display_name', String(255)),
        Column('salt', String(255)),
        Column('crypt_hash', String(255)),
        Column('expires_at', DateTime(timezone=False)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    # Sqlite needs to handle nullable differently
    is_nullable = (meta.bind.name == 'sqlite')

    encryption = Table(
        'encryption', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('cipher', String(255)),
        Column('control_location', String(255), nullable=is_nullable),
        Column('key_size', Integer),
        Column('provider', String(255), nullable=is_nullable),
        # NOTE(joel-coffman): The volume_type_id must be unique or else the
        # referenced volume type becomes ambiguous. That is, specifying the
        # volume type is not sufficient to identify a particular encryption
        # scheme unless each volume type is associated with at most one
        # encryption scheme.
        Column('volume_type_id', String(36), nullable=is_nullable),
        # NOTE (smcginnis): nullable=True triggers this to not set a default
        # value, but since it's a primary key the resulting schema will end up
        # still being NOT NULL. This is avoiding a case in MySQL where it will
        # otherwise set this to NOT NULL DEFAULT ''. May be harmless, but
        # inconsistent with previous schema.
        Column('encryption_id', String(36), primary_key=True, nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_admin_metadata = Table(
        'volume_admin_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_id', String(36), ForeignKey('volumes.id'),
               nullable=False),
        Column('key', String(255)),
        Column('value', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    initiator_data = Table(
        'driver_initiator_data', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('initiator', String(255), index=True, nullable=False),
        Column('namespace', String(255), nullable=False),
        Column('key', String(255), nullable=False),
        Column('value', String(255)),
        UniqueConstraint('initiator', 'namespace', 'key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    image_volume_cache = Table(
        'image_volume_cache_entries', meta,
        Column('image_updated_at', DateTime(timezone=False)),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(255), index=True, nullable=False),
        Column('image_id', String(36), index=True, nullable=False),
        Column('volume_id', String(36), nullable=False),
        Column('size', Integer, nullable=False),
        Column('last_used', DateTime, nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    return [consistencygroups,
            cgsnapshots,
            volumes,
            volume_attachment,
            snapshots,
            snapshot_metadata,
            quality_of_service_specs,
            volume_types,
            volume_type_projects,
            quotas,
            services,
            volume_metadata,
            volume_type_extra_specs,
            quota_classes,
            quota_usages,
            reservations,
            volume_glance_metadata,
            backups,
            transfers,
            encryption,
            volume_admin_metadata,
            initiator_data,
            image_volume_cache]


def upgrade(migrate_engine):
    meta = MetaData()
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

    # Set default quota class values
    quota_classes = Table('quota_classes', meta, autoload=True)
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
