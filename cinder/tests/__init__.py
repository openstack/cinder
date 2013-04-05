# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
:mod:`cinder.tests` -- Cinder Unittests
=====================================================

.. automodule:: cinder.tests
   :platform: Unix
.. moduleauthor:: Jesse Andrews <jesse@ansolabs.com>
.. moduleauthor:: Devin Carlen <devin.carlen@gmail.com>
.. moduleauthor:: Vishvananda Ishaya <vishvananda@gmail.com>
.. moduleauthor:: Joshua McKenty <joshua@cognition.ca>
.. moduleauthor:: Manish Singh <yosh@gimp.org>
.. moduleauthor:: Andy Smith <andy@anarkystic.com>
"""

import eventlet
eventlet.monkey_patch()

# See http://code.google.com/p/python-nose/issues/detail?id=373
# The code below enables nosetests to work with i18n _() blocks
import __builtin__
setattr(__builtin__, '_', lambda x: x)
import os
import shutil

from cinder.db.sqlalchemy.session import get_engine
from cinder import flags

FLAGS = flags.FLAGS

_DB = None


def reset_db():
    if FLAGS.sql_connection == "sqlite://":
        engine = get_engine()
        engine.dispose()
        conn = engine.connect()
        conn.connection.executescript(_DB)
    else:
        shutil.copyfile(os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db),
                        os.path.join(FLAGS.state_path, FLAGS.sqlite_db))


def setup():
    import mox  # Fail fast if you don't have mox. Workaround for bug 810424

    from cinder.db import migration
    from cinder.tests import fake_flags
    fake_flags.set_defaults(FLAGS)

    if FLAGS.sql_connection == "sqlite://":
        if migration.db_version() > 1:
            return
    else:
        testdb = os.path.join(FLAGS.state_path, FLAGS.sqlite_db)
        if os.path.exists(testdb):
            return
    migration.db_sync()

    if FLAGS.sql_connection == "sqlite://":
        global _DB
        engine = get_engine()
        conn = engine.connect()
        _DB = "".join(line for line in conn.connection.iterdump())
    else:
        cleandb = os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db)
        shutil.copyfile(testdb, cleandb)
