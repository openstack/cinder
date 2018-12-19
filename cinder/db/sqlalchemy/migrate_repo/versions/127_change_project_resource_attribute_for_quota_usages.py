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

from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    """Increase the resource column size to the quota_usages table.

    The resource value is constructed from (prefix + volume_type_name),
    but the length of volume_type_name is limited to 255, if we add a
    prefix such as 'volumes_' or 'gigabytes_' to volume_type_name it
    will exceed the db length limit.
    """
    # On MariaDB, max length varies depending on the version and the InnoDB
    # page size [1], so it is possible to have error 1071 ('Specified key was
    # too long; max key length is 767 bytes").  Since this migration is to
    # resolve a corner case, deployments with those DB versions won't be
    # covered.
    # [1]: https://mariadb.com/kb/en/library/innodb-limitations/#page-sizes
    hide_failure = migrate_engine.name.startswith('mysql')
    meta = MetaData(bind=migrate_engine)

    quota_usages = Table('quota_usages', meta, autoload=True)
    try:
        quota_usages.c.resource.alter(type=String(300))
    except Exception:
        if not hide_failure:
            raise
