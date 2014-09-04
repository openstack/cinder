
# Copyright 2012 OpenStack Foundation
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

import math

import mox
from oslo.config import cfg

from cinder.brick.initiator import connector
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import jsonutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import units
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import coraid
from cinder.volume import volume_types


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def to_coraid_kb(gb):
    return math.ceil(float(gb) * units.Gi / 1000)


def coraid_volume_size(gb):
    return '{0}K'.format(to_coraid_kb(gb))


fake_esm_ipaddress = "192.168.0.1"
fake_esm_username = "darmok"
fake_esm_group = "tanagra"
fake_esm_group_id = 1
fake_esm_password = "12345678"

fake_coraid_repository_key = 'repository_key'

fake_volume_name = "volume-12345678-1234-1234-1234-1234567890ab"
fake_clone_name = "volume-ffffffff-1234-1234-1234-1234567890ab"
fake_volume_size = 10
fake_repository_name = "A-B:C:D"
fake_pool_name = "FakePool"
fake_aoetarget = 4081
fake_shelf = 16
fake_lun = 241

fake_str_aoetarget = str(fake_aoetarget)
fake_lun_addr = {"shelf": fake_shelf, "lun": fake_lun}

fake_volume_type = {'id': 1}

fake_volume = {"id": fake_volume_name,
               "name": fake_volume_name,
               "size": fake_volume_size,
               "volume_type": fake_volume_type}

fake_clone_volume = {"name": fake_clone_name,
                     "size": fake_volume_size,
                     "volume_type": fake_volume_type}

fake_big_clone_volume = {"name": fake_clone_name,
                         "size": fake_volume_size + 1,
                         "volume_type": fake_volume_type}

fake_volume_info = {"pool": fake_pool_name,
                    "repo": fake_repository_name,
                    "vsxidx": fake_aoetarget,
                    "index": fake_lun,
                    "shelf": fake_shelf}

fake_lun_info = {"shelf": fake_shelf, "lun": fake_lun}

fake_snapshot_name = "snapshot-12345678-8888-8888-1234-1234567890ab"
fake_snapshot_id = "12345678-8888-8888-1234-1234567890ab"
fake_volume_id = "12345678-1234-1234-1234-1234567890ab"
fake_snapshot = {"id": fake_snapshot_id,
                 "name": fake_snapshot_name,
                 "volume_id": fake_volume_id,
                 "volume_name": fake_volume_name,
                 "volume_size": int(fake_volume_size) - 1,
                 "volume": fake_volume}

fake_configure_data = [{"addr": "cms", "data": "FAKE"}]

fake_esm_fetch = [[
    {"command": "super_fake_command"},
    {"reply": [
        {"lv":
            {"containingPool": fake_pool_name,
             "lunIndex": fake_aoetarget,
             "name": fake_volume_name,
             "lvStatus":
                {"exportedLun":
                    {"lun": fake_lun,
                     "shelf": fake_shelf}}
             },
         "repoName": fake_repository_name}]}]]

fake_esm_fetch_no_volume = [[
    {"command": "super_fake_command"},
    {"reply": []}]]

fake_esm_success = {"category": "provider",
                    "tracking": False,
                    "configState": "completedSuccessfully",
                    "heldPending": False,
                    "metaCROp": "noAction",
                    "message": None}

fake_group_fullpath = "admin group:%s" % (fake_esm_group)
fake_group_id = 4
fake_login_reply = {"values": [
                    {"fullPath": fake_group_fullpath,
                     "groupId": fake_group_id}],
                    "message": "",
                    "state": "adminSucceed",
                    "metaCROp": "noAction"}

fake_group_fail_fullpath = "fail group:%s" % (fake_esm_group)
fake_group_fail_id = 5
fake_login_reply_group_fail = {"values": [
                               {"fullPath": fake_group_fail_fullpath,
                                "groupId": fake_group_fail_id}],
                               "message": "",
                               "state": "adminSucceed",
                               "metaCROp": "noAction"}


def compare(a, b):
    if type(a) != type(b):
        return False
    if type(a) == list or type(a) == tuple:
        if len(a) != len(b):
            return False
        return all(map(lambda t: compare(t[0], t[1]), zip(a, b)))
    elif type(a) == dict:
        if len(a) != len(b):
            return False
        for k, v in a.items():
            if not compare(v, b[k]):
                return False
        return True
    else:
        return a == b


def pack_data(request):
    request['data'] = jsonutils.dumps(request['data'])


class FakeRpcBadRequest(Exception):
    pass


class FakeRpcIsNotCalled(Exception):
    def __init__(self, handle, url_params, data):
        self.handle = handle
        self.url_params = url_params
        self.data = data

    def __str__(self):
        return 'Fake Rpc handle for {0}/{1}/{2} not found'.format(
            self.handle, self.url_params, self.data)


class FakeRpcHandle(object):
    def __init__(self, handle, url_params, data, result):
        self.handle = handle
        self.url_params = url_params
        self.data = data
        self.result = result
        self._is_called = False

    def set_called(self):
        self._is_called = True

    def __call__(self, handle, url_params, data,
                 allow_empty_response=False):
        if handle != self.handle:
            raise FakeRpcBadRequest(
                'Unexpected handle name {0}. Expected {1}.'
                .format(handle, self.handle))
        if not compare(url_params, self.url_params):
            raise FakeRpcBadRequest('Unexpected url params: {0} / {1}'
                                    .format(url_params, self.url_params))
        if not compare(data, self.data):
            raise FakeRpcBadRequest('Unexpected data: {0}/{1}'
                                    .format(data, self.data))
        if callable(self.result):
            return self.result()
        else:
            return self.result


class FakeRpc(object):
    def __init__(self):
        self._handles = []

    def handle(self, handle, url_params, data, result):
        self._handles.append(FakeRpcHandle(handle, url_params, data, result))

    def __call__(self, handle_name, url_params, data,
                 allow_empty_response=False):
        for handle in self._handles:
            if (handle.handle == handle_name and
                compare(handle.url_params, url_params) and
                    compare(handle.data, handle.data)):
                handle.set_called()
                return handle(handle_name, url_params, data,
                              allow_empty_response)
        raise FakeRpcIsNotCalled(handle_name, url_params, data)


class CoraidDriverTestCase(test.TestCase):
    def setUp(self):
        super(CoraidDriverTestCase, self).setUp()
        configuration = mox.MockObject(conf.Configuration)
        configuration.append_config_values(mox.IgnoreArg())
        configuration.coraid_esm_address = fake_esm_ipaddress
        configuration.coraid_user = fake_esm_username
        configuration.coraid_group = fake_esm_group
        configuration.coraid_password = fake_esm_password
        configuration.volume_name_template = "volume-%s"
        configuration.snapshot_name_template = "snapshot-%s"
        configuration.coraid_repository_key = fake_coraid_repository_key
        configuration.use_multipath_for_image_xfer = False
        configuration.num_volume_device_scan_tries = 3
        configuration.volume_dd_blocksize = '1M'
        self.fake_rpc = FakeRpc()

        self.stubs.Set(coraid.CoraidRESTClient, 'rpc', self.fake_rpc)

        self.driver = coraid.CoraidDriver(configuration=configuration)
        self.driver.do_setup({})

    def mock_volume_types(self, repositories=None):
        if not repositories:
            repositories = [fake_repository_name]
        self.mox.StubOutWithMock(volume_types, 'get_volume_type_extra_specs')
        for repository in repositories:
            (volume_types
             .get_volume_type_extra_specs(fake_volume_type['id'],
                                          fake_coraid_repository_key)
             .AndReturn('<in> {0}'.format(repository)))


class CoraidDriverLoginSuccessTestCase(CoraidDriverTestCase):
    def setUp(self):
        super(CoraidDriverLoginSuccessTestCase, self).setUp()

        login_results = {'state': 'adminSucceed',
                         'values': [
                             {'fullPath':
                              'admin group:{0}'.format(fake_esm_group),
                              'groupId': fake_esm_group_id
                              }]}

        self.fake_rpc.handle('admin', {'op': 'login',
                                       'username': fake_esm_username,
                                       'password': fake_esm_password},
                             'Login', login_results)

        self.fake_rpc.handle('admin', {'op': 'setRbacGroup',
                                       'groupId': fake_esm_group_id},
                             'Group', {'state': 'adminSucceed'})


class CoraidDriverApplianceTestCase(CoraidDriverLoginSuccessTestCase):
    def test_resize_volume(self):
        new_volume_size = int(fake_volume_size) + 1

        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_volume_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        reply = {'configState': 'completedSuccessfully'}

        resize_volume_request = {'addr': 'cms',
                                 'data': {
                                     'lvName': fake_volume_name,
                                     'newLvName': fake_volume_name + '-resize',
                                     'size':
                                         coraid_volume_size(new_volume_size),
                                     'repoName': fake_repository_name},
                                 'op': 'orchStrLunMods',
                                 'args': 'resize'}
        pack_data(resize_volume_request)
        self.fake_rpc.handle('configure', {}, [resize_volume_request],
                             reply)

        real_reply = self.driver.appliance.resize_volume(fake_volume_name,
                                                         new_volume_size)

        self.assertEqual(reply['configState'], real_reply['configState'])


class CoraidDriverIntegrationalTestCase(CoraidDriverLoginSuccessTestCase):
    def setUp(self):
        super(CoraidDriverIntegrationalTestCase, self).setUp()
        self.appliance = self.driver.appliance
        # NOTE(nsobolevsky) prevent re-creation esm appliance
        self.stubs.Set(coraid.CoraidDriver, 'appliance', self.appliance)

    def test_create_volume(self):
        self.mock_volume_types()

        create_volume_request = {'addr': 'cms',
                                 'data': {
                                     'servers': [],
                                     'size':
                                         coraid_volume_size(fake_volume_size),
                                     'repoName': fake_repository_name,
                                     'lvName': fake_volume_name},
                                 'op': 'orchStrLun',
                                 'args': 'add'}
        pack_data(create_volume_request)

        self.fake_rpc.handle('configure', {}, [create_volume_request],
                             {'configState': 'completedSuccessfully',
                              'firstParam': 'fake_first_param'})

        self.mox.ReplayAll()

        self.driver.create_volume(fake_volume)

        self.mox.VerifyAll()

    def test_delete_volume(self):
        delete_volume_request = {'addr': 'cms',
                                 'data': {
                                     'repoName': fake_repository_name,
                                     'lvName': fake_volume_name},
                                 'op': 'orchStrLun/verified',
                                 'args': 'delete'}
        pack_data(delete_volume_request)

        self.fake_rpc.handle('configure', {}, [delete_volume_request],
                             {'configState': 'completedSuccessfully'})

        self.fake_rpc.handle('fetch', {'orchStrRepo': '',
                                       'shelf': 'cms',
                                       'lv': fake_volume_name},
                             None,
                             fake_esm_fetch)

        self.mox.ReplayAll()

        self.driver.delete_volume(fake_volume)

        self.mox.VerifyAll()

    def test_ping_ok(self):
        self.fake_rpc.handle('fetch', {}, None, '')

        self.mox.ReplayAll()

        self.driver.appliance.ping()

        self.mox.VerifyAll()

    def test_ping_failed(self):
        def rpc(handle, url_params, data,
                allow_empty_response=True):
            raise test.TestingException("Some exception")

        self.stubs.Set(self.driver.appliance, 'rpc', rpc)
        self.mox.ReplayAll()

        self.assertRaises(exception.CoraidESMNotAvailable,
                          self.driver.appliance.ping)

        self.mox.VerifyAll()

    def test_delete_not_existing_lun(self):
        delete_volume_request = {'addr': 'cms',
                                 'data': {
                                     'repoName': fake_repository_name,
                                     'lvName': fake_volume_name},
                                 'op': 'orchStrLun/verified',
                                 'args': 'delete'}
        pack_data(delete_volume_request)

        self.fake_rpc.handle('configure', {}, [delete_volume_request],
                             {'configState': 'completedSuccessfully'})

        self.fake_rpc.handle('fetch', {'orchStrRepo': '',
                                       'shelf': 'cms',
                                       'lv': fake_volume_name},
                             None,
                             fake_esm_fetch_no_volume)

        self.mox.ReplayAll()

        self.assertRaises(
            exception.VolumeNotFound,
            self.driver.appliance.delete_lun,
            fake_volume['name'])

        self.mox.VerifyAll()

    def test_delete_not_existing_volumeappliance_is_ok(self):
        def delete_lun(volume_name):
            raise exception.VolumeNotFound(volume_id=fake_volume['name'])

        self.stubs.Set(self.driver.appliance, 'delete_lun', delete_lun)

        def ping():
            pass

        self.stubs.Set(self.driver.appliance, 'ping', ping)

        self.mox.ReplayAll()

        self.driver.delete_volume(fake_volume)

        self.mox.VerifyAll()

    def test_delete_not_existing_volume_sleepingappliance(self):
        def delete_lun(volume_name):
            raise exception.VolumeNotFound(volume_id=fake_volume['name'])

        self.stubs.Set(self.driver.appliance, 'delete_lun', delete_lun)

        def ping():
            raise exception.CoraidESMNotAvailable(reason="Any reason")

        self.stubs.Set(self.driver.appliance, 'ping', ping)

        self.driver.appliance.ping = ping

        self.mox.ReplayAll()

        self.assertRaises(exception.CoraidESMNotAvailable,
                          self.driver.delete_volume,
                          fake_volume)

        self.mox.VerifyAll()

    def test_create_snapshot(self):
        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_volume_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        create_snapshot_request = {'addr': 'cms',
                                   'data': {
                                       'repoName': fake_repository_name,
                                       'lvName': fake_volume_name,
                                       'newLvName': fake_snapshot_name},
                                   'op': 'orchStrLunMods',
                                   'args': 'addClSnap'}
        pack_data(create_snapshot_request)
        self.fake_rpc.handle('configure', {}, [create_snapshot_request],
                             {'configState': 'completedSuccessfully'})

        self.mox.ReplayAll()

        self.driver.create_snapshot(fake_snapshot)

        self.mox.VerifyAll()

    def test_delete_snapshot(self):
        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_snapshot_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        delete_snapshot_request = {'addr': 'cms',
                                   'data': {
                                       'repoName': fake_repository_name,
                                       'lvName': fake_snapshot_name,
                                       'newLvName': 'noop'},
                                   'op': 'orchStrLunMods',
                                   'args': 'delClSnap'}
        pack_data(delete_snapshot_request)
        self.fake_rpc.handle('configure', {}, [delete_snapshot_request],
                             {'configState': 'completedSuccessfully'})

        self.mox.ReplayAll()

        self.driver.delete_snapshot(fake_snapshot)

        self.mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        self.mock_volume_types()

        self.mox.StubOutWithMock(self.driver.appliance, 'resize_volume')
        self.driver.appliance.resize_volume(fake_volume_name,
                                            fake_volume['size'])\
            .AndReturn(None)

        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_snapshot_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        create_clone_request = {'addr': 'cms',
                                'data': {
                                    'lvName': fake_snapshot_name,
                                    'repoName': fake_repository_name,
                                    'newLvName': fake_volume_name,
                                    'newRepoName': fake_repository_name},
                                'op': 'orchStrLunMods',
                                'args': 'addClone'}
        pack_data(create_clone_request)
        self.fake_rpc.handle('configure', {}, [create_clone_request],
                             {'configState': 'completedSuccessfully'})

        self.mox.ReplayAll()

        self.driver.create_volume_from_snapshot(fake_volume, fake_snapshot)

        self.mox.VerifyAll()

    def test_initialize_connection(self):
        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_volume_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        self.mox.ReplayAll()

        connection = self.driver.initialize_connection(fake_volume, {})

        self.mox.VerifyAll()

        self.assertEqual(connection['driver_volume_type'], 'aoe')
        self.assertEqual(connection['data']['target_shelf'], fake_shelf)
        self.assertEqual(connection['data']['target_lun'], fake_lun)

    def test_get_repository_capabilities(self):
        reply = [[{}, {'reply': [
            {'name': 'repo1',
             'profile':
                {'fullName': 'Bronze-Bronze:Profile1'}},
            {'name': 'repo2',
             'profile':
                {'fullName': 'Bronze-Bronze:Profile2'}}]}]]

        self.fake_rpc.handle('fetch', {'orchStrRepo': ''}, None,
                             reply)

        self.mox.ReplayAll()

        capabilities = self.driver.get_volume_stats(refresh=True)

        self.mox.VerifyAll()

        self.assertEqual(
            capabilities[fake_coraid_repository_key],
            'Bronze-Bronze:Profile1:repo1 Bronze-Bronze:Profile2:repo2')

    def test_create_cloned_volume(self):
        self.mock_volume_types([fake_repository_name])

        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_volume_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        shelf_lun = '{0}.{1}'.format(fake_shelf, fake_lun)
        create_clone_request = {'addr': 'cms',
                                'data': {
                                    'shelfLun': shelf_lun,
                                    'lvName': fake_volume_name,
                                    'repoName': fake_repository_name,
                                    'newLvName': fake_clone_name,
                                    'newRepoName': fake_repository_name},
                                'op': 'orchStrLunMods',
                                'args': 'addClone'}
        pack_data(create_clone_request)
        self.fake_rpc.handle('configure', {}, [create_clone_request],
                             {'configState': 'completedSuccessfully'})

        self.mox.ReplayAll()

        self.driver.create_cloned_volume(fake_clone_volume, fake_volume)

        self.mox.VerifyAll()

    def test_create_cloned_volume_with_resize(self):
        self.mock_volume_types([fake_repository_name])

        self.mox.StubOutWithMock(self.driver.appliance, 'resize_volume')
        self.driver.appliance.resize_volume(fake_big_clone_volume['name'],
                                            fake_big_clone_volume['size'])\
            .AndReturn(None)

        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_volume_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        shelf_lun = '{0}.{1}'.format(fake_shelf, fake_lun)
        create_clone_request = {'addr': 'cms',
                                'data': {
                                    'shelfLun': shelf_lun,
                                    'lvName': fake_volume_name,
                                    'repoName': fake_repository_name,
                                    'newLvName': fake_clone_name,
                                    'newRepoName': fake_repository_name},
                                'op': 'orchStrLunMods',
                                'args': 'addClone'}
        pack_data(create_clone_request)
        self.fake_rpc.handle('configure', {}, [create_clone_request],
                             {'configState': 'completedSuccessfully'})

        self.mox.ReplayAll()

        self.driver.create_cloned_volume(fake_big_clone_volume, fake_volume)

        self.mox.VerifyAll()

    def test_create_cloned_volume_in_different_repository(self):
        self.mock_volume_types([fake_repository_name + '_another'])

        fetch_request = {'shelf': 'cms',
                         'orchStrRepo': '',
                         'lv': fake_volume_name}
        self.fake_rpc.handle('fetch', fetch_request, None,
                             fake_esm_fetch)

        self.mox.ReplayAll()

        self.assertRaises(
            exception.CoraidException,
            self.driver.create_cloned_volume,
            fake_clone_volume,
            fake_volume)

        self.mox.VerifyAll()

    def test_extend_volume(self):
        self.mox.StubOutWithMock(self.driver.appliance, 'resize_volume')
        self.driver.appliance.resize_volume(fake_volume_name, 10)\
            .AndReturn(None)

        self.mox.ReplayAll()

        self.driver.extend_volume(fake_volume, 10)

        self.mox.VerifyAll()


class AutoReloginCoraidTestCase(test.TestCase):
    def setUp(self):
        super(AutoReloginCoraidTestCase, self).setUp()
        self.rest_client = coraid.CoraidRESTClient('https://fake')
        self.appliance = coraid.CoraidAppliance(self.rest_client,
                                                'fake_username',
                                                'fake_password',
                                                'fake_group')

    def _test_auto_relogin_fail(self, state):
        self.mox.StubOutWithMock(self.rest_client, 'rpc')

        self.rest_client.rpc('fake_handle', {}, None, False).\
            AndReturn({'state': state,
                       'metaCROp': 'reboot'})

        self.rest_client.rpc('fake_handle', {}, None, False).\
            AndReturn({'state': state,
                       'metaCROp': 'reboot'})

        self.rest_client.rpc('fake_handle', {}, None, False).\
            AndReturn({'state': state,
                       'metaCROp': 'reboot'})

        self.mox.StubOutWithMock(self.appliance, '_ensure_session')
        self.appliance._ensure_session().AndReturn(None)

        self.mox.StubOutWithMock(self.appliance, '_relogin')
        self.appliance._relogin().AndReturn(None)
        self.appliance._relogin().AndReturn(None)

        self.mox.ReplayAll()

        self.assertRaises(exception.CoraidESMReloginFailed,
                          self.appliance.rpc,
                          'fake_handle', {}, None, False)

        self.mox.VerifyAll()

    def test_auto_relogin_fail_admin(self):
        self._test_auto_relogin_fail('GeneralAdminFailure')

    def test_auto_relogin_fail_inactivity(self):
        self._test_auto_relogin_fail('passwordInactivityTimeout')

    def test_auto_relogin_fail_absolute(self):
        self._test_auto_relogin_fail('passwordAbsoluteTimeout')

    def test_auto_relogin_success(self):
        self.mox.StubOutWithMock(self.rest_client, 'rpc')

        self.rest_client.rpc('fake_handle', {}, None, False).\
            AndReturn({'state': 'GeneralAdminFailure',
                       'metaCROp': 'reboot'})

        self.rest_client.rpc('fake_handle', {}, None, False).\
            AndReturn({'state': 'ok'})

        self.mox.StubOutWithMock(self.appliance, '_ensure_session')
        self.appliance._ensure_session().AndReturn(None)

        self.mox.StubOutWithMock(self.appliance, '_relogin')
        self.appliance._relogin().AndReturn(None)

        self.mox.ReplayAll()

        reply = self.appliance.rpc('fake_handle', {}, None, False)

        self.mox.VerifyAll()

        self.assertEqual(reply['state'], 'ok')


class CoraidDriverImageTestCases(CoraidDriverTestCase):
    def setUp(self):
        super(CoraidDriverImageTestCases, self).setUp()

        self.fake_dev_path = '/dev/ether/fake_dev'

        self.fake_connection = {'driver_volume_type': 'aoe',
                                'data': {'target_shelf': fake_shelf,
                                         'target_lun': fake_lun}}

        self.fake_volume_info = {
            'shelf': self.fake_connection['data']['target_shelf'],
            'lun': self.fake_connection['data']['target_lun']}

        self.mox.StubOutWithMock(self.driver, 'initialize_connection')
        self.driver.initialize_connection(fake_volume, {})\
            .AndReturn(self.fake_connection)

        self.mox.StubOutWithMock(self.driver, 'terminate_connection')
        self.driver.terminate_connection(fake_volume, mox.IgnoreArg(),
                                         force=False).AndReturn(None)

        root_helper = 'sudo cinder-rootwrap /etc/cinder/rootwrap.conf'

        self.mox.StubOutWithMock(connector, 'get_connector_properties')
        connector.get_connector_properties(root_helper,
                                           CONF.my_ip).\
            AndReturn({})

        self.mox.StubOutWithMock(utils, 'brick_get_connector')

        aoe_initiator = self.mox.CreateMockAnything()

        utils.brick_get_connector('aoe',
                                  device_scan_attempts=3,
                                  use_multipath=False,
                                  conn=mox.IgnoreArg()).\
            AndReturn(aoe_initiator)

        aoe_initiator\
            .connect_volume(self.fake_connection['data'])\
            .AndReturn({'path': self.fake_dev_path})

        aoe_initiator.check_valid_device(self.fake_dev_path)\
            .AndReturn(True)

        aoe_initiator.disconnect_volume(
            {'target_shelf': self.fake_volume_info['shelf'],
             'target_lun': self.fake_volume_info['lun']}, mox.IgnoreArg())

    def test_copy_volume_to_image(self):
        fake_image_service = 'fake-image-service'
        fake_image_meta = 'fake-image-meta'

        self.mox.StubOutWithMock(image_utils, 'upload_volume')
        image_utils.upload_volume({},
                                  fake_image_service,
                                  fake_image_meta,
                                  self.fake_dev_path)

        self.mox.ReplayAll()
        self.driver.copy_volume_to_image({},
                                         fake_volume,
                                         fake_image_service,
                                         fake_image_meta)

        self.mox.VerifyAll()

    def test_copy_image_to_volume(self):
        fake_image_service = 'fake-image-service'
        fake_image_id = 'fake-image-id;'

        self.mox.StubOutWithMock(image_utils, 'fetch_to_raw')
        image_utils.fetch_to_raw({},
                                 fake_image_service,
                                 fake_image_id,
                                 self.fake_dev_path,
                                 mox.IgnoreArg(),
                                 size=fake_volume_size)

        self.mox.ReplayAll()

        self.driver.copy_image_to_volume({},
                                         fake_volume,
                                         fake_image_service,
                                         fake_image_id)

        self.mox.VerifyAll()


class CoraidResetConnectionTestCase(CoraidDriverTestCase):
    def test_create_new_appliance_for_every_request(self):
        self.mox.StubOutWithMock(coraid, 'CoraidRESTClient')
        self.mox.StubOutWithMock(coraid, 'CoraidAppliance')

        coraid.CoraidRESTClient(mox.IgnoreArg())
        coraid.CoraidRESTClient(mox.IgnoreArg())

        coraid.CoraidAppliance(mox.IgnoreArg(),
                               mox.IgnoreArg(),
                               mox.IgnoreArg(),
                               mox.IgnoreArg()).AndReturn('fake_app1')
        coraid.CoraidAppliance(mox.IgnoreArg(),
                               mox.IgnoreArg(),
                               mox.IgnoreArg(),
                               mox.IgnoreArg()).AndReturn('fake_app2')
        self.mox.ReplayAll()

        self.assertEqual(self.driver.appliance, 'fake_app1')
        self.assertEqual(self.driver.appliance, 'fake_app2')

        self.mox.VerifyAll()
