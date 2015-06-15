#    Copyright 2013 IBM Corp.
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
from sqlalchemy import MetaData, Table

# Get default values via config.  The defaults will either
# come from the default values set in the quota option
# configuration or via cinder.conf if the user has configured
# default values for quotas there.
CONF = cfg.CONF
CONF.import_opt('quota_volumes', 'cinder.quota')
CONF.import_opt('quota_snapshots', 'cinder.quota')
CONF.import_opt('quota_gigabytes', 'cinder.quota')

CLASS_NAME = 'default'
CREATED_AT = datetime.datetime.now()  # noqa


def upgrade(migrate_engine):
    """Add default quota class data into DB."""
    meta = MetaData()
    meta.bind = migrate_engine

    quota_classes = Table('quota_classes', meta, autoload=True)

    rows = quota_classes.count().\
        where(quota_classes.c.class_name == 'default').execute().scalar()

    # Do not add entries if there are already 'default' entries.  We don't
    # want to write over something the user added.
    if rows:
        return

    # Set default volumes
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


def downgrade(migrate_engine):
    """Don't delete the 'default' entries at downgrade time.

    We don't know if the user had default entries when we started.
    If they did, we wouldn't want to remove them.  So, the safest
    thing to do is just leave the 'default' entries at downgrade time.
    """
    pass
