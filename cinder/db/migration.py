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

from migrate import exceptions as migrate_exceptions
from migrate.versioning import api as migrate_api
from migrate.versioning import repository as migrate_repository
from oslo_config import cfg
from oslo_db import exception
from oslo_db import options
import sqlalchemy as sa

from cinder.db.sqlalchemy import api as db_api
from cinder.i18n import _

options.set_defaults(cfg.CONF)

INIT_VERSION = 134
LEGACY_MIGRATIONS_PATH = os.path.join(
    os.path.abspath(os.path.dirname(__file__)),
    'legacy_migrations',
)


def _find_migrate_repo(abs_path):
    """Get the project's change script repository

    :param abs_path: Absolute path to migrate repository
    """
    if not os.path.exists(abs_path):
        raise exception.DBMigrationError("Path %s not found" % abs_path)
    return migrate_repository.Repository(abs_path)


def _migrate_db_version_control(engine, abs_path, version=None):
    """Mark a database as under this repository's version control.

    Once a database is under version control, schema changes should
    only be done via change scripts in this repository.

    :param engine: SQLAlchemy engine instance for a given database
    :param abs_path: Absolute path to migrate repository
    :param version: Initial database version
    """
    repository = _find_migrate_repo(abs_path)

    try:
        migrate_api.version_control(engine, repository, version)
    except migrate_exceptions.InvalidVersionError as ex:
        raise exception.DBMigrationError("Invalid version : %s" % ex)
    except migrate_exceptions.DatabaseAlreadyControlledError:
        raise exception.DBMigrationError("Database is already controlled.")

    return version


def _migrate_db_version(engine, abs_path, init_version):
    """Show the current version of the repository.

    :param engine: SQLAlchemy engine instance for a given database
    :param abs_path: Absolute path to migrate repository
    :param init_version: Initial database version
    """
    repository = _find_migrate_repo(abs_path)
    try:
        return migrate_api.db_version(engine, repository)
    except migrate_exceptions.DatabaseNotControlledError:
        pass

    meta = sa.MetaData()
    meta.reflect(bind=engine)
    tables = meta.tables
    if (
        len(tables) == 0 or
        'alembic_version' in tables or
        'migrate_version' in tables
    ):
        _migrate_db_version_control(engine, abs_path, version=init_version)
        return migrate_api.db_version(engine, repository)

    msg = _(
        "The database is not under version control, but has tables. "
        "Please stamp the current version of the schema manually."
    )
    raise exception.DBMigrationError(msg)


def _migrate_db_sync(engine, abs_path, version=None, init_version=0):
    """Upgrade or downgrade a database.

    Function runs the upgrade() or downgrade() functions in change scripts.

    :param engine: SQLAlchemy engine instance for a given database
    :param abs_path: Absolute path to migrate repository.
    :param version: Database will upgrade/downgrade until this version.
        If None - database will update to the latest available version.
    :param init_version: Initial database version
    """

    if version is not None:
        try:
            version = int(version)
        except ValueError:
            raise exception.DBMigrationError(_("version should be an integer"))

    current_version = _migrate_db_version(engine, abs_path, init_version)
    repository = _find_migrate_repo(abs_path)

    if version is None or version > current_version:
        try:
            return migrate_api.upgrade(engine, repository, version)
        except Exception as ex:
            raise exception.DBMigrationError(ex)
    else:
        return migrate_api.downgrade(engine, repository, version)


def db_version():
    """Get database version."""
    return _migrate_db_version(
        db_api.get_engine(),
        LEGACY_MIGRATIONS_PATH,
        INIT_VERSION)


def db_sync(version=None, engine=None):
    """Migrate the database to `version` or the most recent version."""

    if engine is None:
        engine = db_api.get_engine()

    return _migrate_db_sync(
        engine=engine,
        abs_path=LEGACY_MIGRATIONS_PATH,
        version=version,
        init_version=INIT_VERSION)
