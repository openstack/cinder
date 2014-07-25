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

from sqlalchemy import Index, MetaData, Table
from sqlalchemy.exc import OperationalError

from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    reservations = Table('reservations', meta, autoload=True)

    # Based on expire_reservations query
    # from: cinder/db/sqlalchemy/api.py
    index = Index('reservations_deleted_expire_idx',
                  reservations.c.deleted, reservations.c.expire)
    try:
        index.create(migrate_engine)
    except OperationalError:
        LOG.info(_('Skipped adding reservations_deleted_expire_idx '
                   'because an equivalent index already exists.'))


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    reservations = Table('reservations', meta, autoload=True)

    index = Index('reservations_deleted_expire_idx',
                  reservations.c.deleted, reservations.c.expire)
    try:
        index.drop(migrate_engine)
    except OperationalError:
        LOG.info(_('Skipped removing reservations_deleted_expire_idx '
                   'because index does not exist.'))
