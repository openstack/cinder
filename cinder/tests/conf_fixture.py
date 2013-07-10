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


from oslo.config import cfg


CONF = cfg.CONF

CONF.import_opt('iscsi_num_targets', 'cinder.volume.drivers.lvm')
CONF.import_opt('policy_file', 'cinder.policy')
CONF.import_opt('volume_driver', 'cinder.volume.manager')
CONF.import_opt('xiv_proxy', 'cinder.volume.drivers.xiv')
CONF.import_opt('backup_driver', 'cinder.backup.manager')

def_vol_type = 'fake_vol_type'


def set_defaults(conf):
    conf.set_default('default_volume_type', def_vol_type)
    conf.set_default('volume_driver',
                     'cinder.tests.fake_driver.FakeISCSIDriver')
    conf.set_default('iscsi_helper', 'fake')
    conf.set_default('connection_type', 'fake')
    conf.set_default('fake_rabbit', True)
    conf.set_default('rpc_backend', 'cinder.openstack.common.rpc.impl_fake')
    conf.set_default('iscsi_num_targets', 8)
    conf.set_default('verbose', True)
    conf.set_default('connection', 'sqlite://', group='database')
    conf.set_default('sqlite_synchronous', False)
    conf.set_default('policy_file', 'cinder/tests/policy.json')
    conf.set_default('xiv_proxy', 'cinder.tests.test_xiv.XIVFakeProxyDriver')
    conf.set_default('backup_driver', 'cinder.tests.backup.fake_service')
