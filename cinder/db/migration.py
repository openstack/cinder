# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Database setup and migration commands."""

import os

from oslo_config import cfg
from oslo_db import options
from oslo_db.sqlalchemy import migration

from cinder.db.sqlalchemy import api as db_api

options.set_defaults(cfg.CONF)

INIT_VERSION = 134
MIGRATE_REPO_PATH = os.path.join(
    os.path.abspath(os.path.dirname(__file__)),
    'sqlalchemy',
    'migrate_repo',
)


def db_sync(version=None, engine=None):
    """Migrate the database to `version` or the most recent version."""

    if engine is None:
        engine = db_api.get_engine()

    return migration.db_sync(
        engine=engine,
        abs_path=MIGRATE_REPO_PATH,
        version=version,
        init_version=INIT_VERSION)
