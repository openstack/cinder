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

import sqlalchemy as sa

from cinder import exception
from cinder.i18n import _


def upgrade(migrate_engine):
    """Make volume_type columns non-nullable"""

    meta = sa.MetaData(bind=migrate_engine)

    # Update volume_type columns in tables to not allow null value

    volumes = sa.Table('volumes', meta, autoload=True)

    try:
        volumes.c.volume_type_id.alter(nullable=False)
    except Exception:
        msg = (_('Migration cannot continue until all volumes have '
                 'been migrated to the `__DEFAULT__` volume type. Please '
                 'run `cinder-manage db online_data_migrations`. '
                 'There are still untyped volumes unmigrated.'))
        raise exception.ValidationError(msg)

    snapshots = sa.Table('snapshots', meta, autoload=True)

    try:
        snapshots.c.volume_type_id.alter(nullable=False)
    except Exception:
        msg = (_('Migration cannot continue until all snapshots have '
                 'been migrated to the `__DEFAULT__` volume type. Please '
                 'run `cinder-manage db online_data_migrations`.'
                 'There are still %(count)i untyped snapshots unmigrated.'))
        raise exception.ValidationError(msg)

    encryption = sa.Table('encryption', meta, autoload=True)
    # since volume_type is a mandatory arg when creating encryption
    # volume_type_id column won't contain any null values so we can directly
    # alter it
    encryption.c.volume_type_id.alter(nullable=False)
