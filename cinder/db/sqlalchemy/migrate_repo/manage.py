#!/usr/bin/env python

import os

from oslo.config import cfg

from cinder.openstack.common import gettextutils
gettextutils.install('cinder', lazy=True)

from cinder.db.sqlalchemy import migrate_repo
from cinder.openstack.common.db.sqlalchemy import session
from cinder import version

from migrate.versioning.shell import main

CONF = cfg.CONF

if __name__ == '__main__':
    CONF([], project='cinder', version=version.version_string())
    main(debug='False', url=CONF.database.connection,
         repository=os.path.abspath(os.path.dirname(migrate_repo.__file__)))
