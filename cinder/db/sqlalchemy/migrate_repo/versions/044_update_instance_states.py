# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from sqlalchemy import MetaData, Table, Column, String


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_table = Table('instances', meta, autoload=True)

    c_state = instance_table.c.state
    c_state.alter(name='power_state')

    c_vm_state = instance_table.c.state_description
    c_vm_state.alter(name='vm_state')

    c_task_state = Column('task_state',
                          String(length=255, convert_unicode=False,
                                 assert_unicode=None, unicode_error=None,
                                 _warn_on_bytestring=False),
                          nullable=True)
    instance_table.create_column(c_task_state)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_table = Table('instances', meta, autoload=True)

    c_state = instance_table.c.power_state
    c_state.alter(name='state')

    c_vm_state = instance_table.c.vm_state
    c_vm_state.alter(name='state_description')

    instance_table.drop_column('task_state')
