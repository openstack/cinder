#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

import os

from oslo.config import cfg

from cinder.openstack.common import gettextutils
gettextutils.install('cinder', lazy=False)

from cinder.db.sqlalchemy import migrate_repo
import cinder.openstack.common.db.sqlalchemy.session
from cinder import version

from migrate.versioning.shell import main

CONF = cfg.CONF

if __name__ == '__main__':
    CONF([], project='cinder', version=version.version_string())
    main(debug='False', url=CONF.database.connection,
         repository=os.path.abspath(os.path.dirname(migrate_repo.__file__)))
