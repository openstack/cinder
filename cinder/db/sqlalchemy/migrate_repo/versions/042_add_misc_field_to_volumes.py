
from oslo_log import log as logging
from sqlalchemy import Column, MetaData, String, Table

from cinder.i18n import _LE


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    volumes = Table('volumes', meta, autoload=True)
    misc = Column('miscellaneous', String(256))
    try:
        volumes.create_column(misc)
    except Exception:
        LOG.error(_LE("Adding miscellaneous column to volumes table failed."))
        raise
