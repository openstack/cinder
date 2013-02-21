# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import MetaData, Integer, String, Table

from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New table
    backups = Table(
        'backups', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('volume_id', String(36), nullable=False),
        Column('user_id', String(length=255, convert_unicode=False,
                                 assert_unicode=None,
                                 unicode_error=None,
                                 _warn_on_bytestring=False)),
        Column('project_id', String(length=255, convert_unicode=False,
                                    assert_unicode=None,
                                    unicode_error=None,
                                    _warn_on_bytestring=False)),
        Column('host', String(length=255, convert_unicode=False,
                              assert_unicode=None,
                              unicode_error=None,
                              _warn_on_bytestring=False)),
        Column('availability_zone', String(length=255,
                                           convert_unicode=False,
                                           assert_unicode=None,
                                           unicode_error=None,
                                           _warn_on_bytestring=False)),
        Column('display_name', String(length=255, convert_unicode=False,
                                      assert_unicode=None,
                                      unicode_error=None,
                                      _warn_on_bytestring=False)),
        Column('display_description', String(length=255,
                                             convert_unicode=False,
                                             assert_unicode=None,
                                             unicode_error=None,
                                             _warn_on_bytestring=False)),
        Column('container', String(length=255, convert_unicode=False,
                                   assert_unicode=None,
                                   unicode_error=None,
                                   _warn_on_bytestring=False)),
        Column('status', String(length=255, convert_unicode=False,
                                assert_unicode=None,
                                unicode_error=None,
                                _warn_on_bytestring=False)),
        Column('fail_reason', String(length=255, convert_unicode=False,
                                     assert_unicode=None,
                                     unicode_error=None,
                                     _warn_on_bytestring=False)),
        Column('service_metadata', String(length=255, convert_unicode=False,
                                          assert_unicode=None,
                                          unicode_error=None,
                                          _warn_on_bytestring=False)),
        Column('service', String(length=255, convert_unicode=False,
                                 assert_unicode=None,
                                 unicode_error=None,
                                 _warn_on_bytestring=False)),
        Column('size', Integer()),
        Column('object_count', Integer()),
        mysql_engine='InnoDB'
    )

    try:
        backups.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(backups))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    backups = Table('backups', meta, autoload=True)
    try:
        backups.drop()
    except Exception:
        LOG.error(_("backups table not dropped"))
        raise
