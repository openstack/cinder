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

from alembic import command as alembic_api
from alembic import config as alembic_config
from alembic import migration as alembic_migration
from migrate import exceptions as migrate_exceptions
from migrate.versioning import api as migrate_api
from migrate.versioning import repository as migrate_repo
from oslo_config import cfg
from oslo_db import options
from oslo_log import log as logging

from cinder.db.sqlalchemy import api as db_api

options.set_defaults(cfg.CONF)

LOG = logging.getLogger(__name__)

MIGRATE_INIT_VERSION = 134
MIGRATE_MIGRATIONS_PATH = ALEMBIC_INIT_VERSION = '921e1a36b076'


def _find_migrate_repo():
    """Get the project's change script repository

    :returns: An instance of ``migrate.versioning.repository.Repository``
    """
    path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), 'legacy_migrations',
    )
    return migrate_repo.Repository(path)


def _find_alembic_conf():
    """Get the project's alembic configuration

    :returns: An instance of ``alembic.config.Config``
    """
    path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), 'alembic.ini')

    config = alembic_config.Config(os.path.abspath(path))
    # we don't want to use the logger configuration from the file, which is
    # only really intended for the CLI
    # https://stackoverflow.com/a/42691781/613428
    config.attributes['configure_logger'] = False

    return config


def _is_database_under_migrate_control(engine, repository):
    try:
        migrate_api.db_version(engine, repository)
        return True
    except migrate_exceptions.DatabaseNotControlledError:
        return False


def _is_database_under_alembic_control(engine):
    with engine.connect() as conn:
        context = alembic_migration.MigrationContext.configure(conn)
        return bool(context.get_current_revision())


def _init_alembic_on_legacy_database(engine, repository, config):
    """Init alembic in an existing environment with sqlalchemy-migrate."""
    LOG.info(
        'The database is still under sqlalchemy-migrate control; '
        'applying any remaining sqlalchemy-migrate-based migrations '
        'and fake applying the initial alembic migration'
    )
    migrate_api.upgrade(engine, repository)

    # re-use the connection rather than creating a new one
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        alembic_api.stamp(config, ALEMBIC_INIT_VERSION)


def _upgrade_alembic(engine, config, version):
    # re-use the connection rather than creating a new one
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        alembic_api.upgrade(config, version or 'head')


def db_version():
    """Get database version."""
    repository = _find_migrate_repo()
    engine = db_api.get_engine()

    migrate_version = None
    if _is_database_under_migrate_control(engine, repository):
        migrate_version = migrate_api.db_version(engine, repository)

    alembic_version = None
    if _is_database_under_alembic_control(engine):
        with engine.connect() as conn:
            m_context = alembic_migration.MigrationContext.configure(conn)
            alembic_version = m_context.get_current_revision()

    return alembic_version or migrate_version


def db_sync(version=None, engine=None):
    """Migrate the database to `version` or the most recent version.

    We're currently straddling two migration systems, sqlalchemy-migrate and
    alembic. This handles both by ensuring we switch from one to the other at
    the appropriate moment.
    """

    # if the user requested a specific version, check if it's an integer: if
    # so, we're almost certainly in sqlalchemy-migrate land and won't support
    # that
    if version is not None and version.isdigit():
        raise ValueError(
            'You requested an sqlalchemy-migrate database version; this is '
            'no longer supported'
        )

    if engine is None:
        engine = db_api.get_engine()

    repository = _find_migrate_repo()
    config = _find_alembic_conf()

    # discard the URL encoded in alembic.ini in favour of the URL configured
    # for the engine by the database fixtures, casting from
    # 'sqlalchemy.engine.url.URL' to str in the process. This returns a
    # RFC-1738 quoted URL, which means that a password like "foo@" will be
    # turned into "foo%40". This in turns causes a problem for
    # set_main_option() because that uses ConfigParser.set, which (by design)
    # uses *python* interpolation to write the string out ... where "%" is the
    # special python interpolation character! Avoid this mismatch by quoting
    # all %'s for the set below.
    engine_url = str(engine.url).replace('%', '%%')
    config.set_main_option('sqlalchemy.url', str(engine_url))

    # if we're in a deployment where sqlalchemy-migrate is already present,
    # then apply all the updates for that and fake apply the initial alembic
    # migration; if we're not then 'upgrade' will take care of everything
    # this should be a one-time operation
    if (
        _is_database_under_migrate_control(engine, repository) and
        not _is_database_under_alembic_control(engine)
    ):
        _init_alembic_on_legacy_database(engine, repository, config)

    # apply anything later
    LOG.info('Applying migration(s)')
    _upgrade_alembic(engine, config, version)
    LOG.info('Migration(s) applied')
