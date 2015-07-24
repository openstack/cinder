# (c) Copyright 2012-2014 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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

import six
from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import ForeignKey, MetaData, String, Table

CREATED_AT = datetime.datetime.now()  # noqa


def upgrade(migrate_engine):
    """Add volume multi attachment table."""
    meta = MetaData()
    meta.bind = migrate_engine

    # add the multiattach flag to the volumes table.
    volumes = Table('volumes', meta, autoload=True)
    multiattach = Column('multiattach', Boolean)
    volumes.create_column(multiattach)
    volumes.update().values(multiattach=False).execute()

    # The new volume_attachment table
    volume_attachment = Table(
        'volume_attachment', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=36), primary_key=True, nullable=False),
        Column('volume_id', String(length=36), ForeignKey('volumes.id'),
               nullable=False),
        Column('attached_host', String(length=255)),
        Column('instance_uuid', String(length=36)),
        Column('mountpoint', String(length=255)),
        Column('attach_time', DateTime),
        Column('detach_time', DateTime),
        Column('attach_mode', String(length=36)),
        Column('attach_status', String(length=255)),
        mysql_engine='InnoDB'
    )

    volume_attachment.create()

    # now migrate existing volume attachment info into the
    # new volume_attachment table
    volumes_list = list(volumes.select().execute())
    for volume in volumes_list:
        if volume.attach_status == 'attached':
            attachment = volume_attachment.insert()
            values = {'id': six.text_type(uuid.uuid4()),
                      'created_at': CREATED_AT,
                      'deleted_at': None,
                      'deleted': False,
                      'volume_id': volume.id,
                      'attached_host': volume.host,
                      'instance_uuid': volume.instance_uuid,
                      'mountpoint': volume.mountpoint,
                      'attach_time': volume.attach_time,
                      'attach_mode': 'rw',
                      'attach_status': 'attached',
                      }
            attachment.execute(values)

    # we have no reason to keep the columns that now
    # exist in the volume_attachment table
    mountpoint = volumes.columns.mountpoint
    volumes.drop_column(mountpoint)
    instance_uuid = volumes.columns.instance_uuid
    volumes.drop_column(instance_uuid)
    attach_time = volumes.columns.attach_time
    volumes.drop_column(attach_time)
    attached_host = volumes.columns.attached_host
    volumes.drop_column(attached_host)


def downgrade(migrate_engine):
    """Remove volume_attachment table."""
    meta = MetaData()
    meta.bind = migrate_engine

    # Put the needed volumes table columns back
    volumes = Table('volumes', meta, autoload=True)
    multiattach = volumes.columns.multiattach
    volumes.drop_column(multiattach)

    attached_host = Column('attached_host', String(length=255))
    volumes.create_column(attached_host)
    volumes.update().values(attached_host=None).execute()

    attach_time = Column('attach_time', String(length=255))
    volumes.create_column(attach_time)
    volumes.update().values(attach_time=None).execute()

    instance_uuid = Column('instance_uuid', String(length=36))
    volumes.create_column(instance_uuid)
    volumes.update().values(instance_uuid=None).execute()

    mountpoint = Column('mountpoint', String(length=255))
    volumes.create_column(mountpoint)
    volumes.update().values(mountpoint=None).execute()

    volume_attachment = Table('volume_attachment', meta, autoload=True)
    attachments = list(volume_attachment.select().execute())
    for attachment in attachments:
        # we are going to lose data here for
        # multiple attaches.  We'll migrate and the
        # last update wins.

        if not attachment.deleted_at:
            volume_id = attachment.volume_id
            volumes.update().\
                where(volumes.c.id == volume_id).\
                values(mountpoint=attachment.mountpoint,
                       attached_host=attachment.attached_host,
                       attach_time=attachment.attach_time,
                       instance_uuid=attachment.instance_uuid).\
                execute()
    volume_attachment.drop()
