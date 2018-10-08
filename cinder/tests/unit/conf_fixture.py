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

import os

from oslo_config import cfg

from cinder.volume import configuration

CONF = cfg.CONF

CONF.import_opt('policy_file', 'cinder.policy', group='oslo_policy')
CONF.import_opt('volume_driver', 'cinder.volume.manager',
                group=configuration.SHARED_CONF_GROUP)
CONF.import_opt('backup_driver', 'cinder.backup.manager')
CONF.import_opt('backend', 'cinder.keymgr', group='key_manager')
CONF.import_opt('scheduler_driver', 'cinder.scheduler.manager')

def_vol_type = 'fake_vol_type'


def set_defaults(conf):
    conf.set_default('default_volume_type', def_vol_type)
    conf.set_default('volume_driver',
                     'cinder.tests.fake_driver.FakeLoggingVolumeDriver',
                     group=configuration.SHARED_CONF_GROUP)
    conf.set_default('target_helper', 'fake')
    conf.set_default('transport_url', 'fake:/')
    conf.set_default('connection', 'sqlite://', group='database')
    conf.set_default('sqlite_synchronous', False, group='database')
    conf.set_default('policy_file', 'cinder.tests.unit/policy.json',
                     group='oslo_policy')
    conf.set_default('backup_driver',
                     'cinder.tests.unit.backup.fake_service.FakeBackupService')
    conf.set_default('backend',
                     'castellan.tests.unit.key_manager.mock_key_manager.'
                     'MockKeyManager',
                     group='key_manager')
    conf.set_default('scheduler_driver',
                     'cinder.scheduler.filter_scheduler.FilterScheduler')
    conf.set_default('state_path', os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', '..')))
    conf.set_default('policy_dirs', [], group='oslo_policy')
    # This is where we don't authenticate
    conf.set_default('auth_strategy', 'noauth')
    conf.set_default('auth_url', 'fake', 'keystone_authtoken')
