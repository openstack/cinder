# Copyright 2015 CloudFounders NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Mock basic unit tests for the OVS Cinder Plugin
"""
import mock

from cinder import test
import cinder.volume.drivers.openvstorage as ovsvd


# MOCKUPS
MOCK_hostname = 'test-hostname'
MOCK_mountpoint = '/mnt/test'
MOCK_vdisk_guid = '0000'
MOCK_vdisk_guid2 = '1111'
MOCK_vdisk_guid3 = '2222'
MOCK_vdisk_devicename = 'volume-test.raw'
MOCK_vdisk_devicename2 = 'volume-test-clone.raw'
MOCK_vdisk_devicename3 = 'volume-test-template.raw'
MOCK_vdisk_disk_info = {'object_type': 'DISK'}
MOCK_vdisk_disk_info_template = {'object_type': 'TEMPLATE'}
MOCK_volume_name = 'volume-test'
MOCK_volume_name2 = 'volume-test-clone'
MOCK_volume_name3 = 'volume-test-template'
MOCK_volume_size = 10
MOCK_volume_size_extend = 20
MOCK_volume_type_id = 'RANDOM'
MOCK_volume_id = '0'
MOCK_volume_id2 = '1'
MOCK_volume_id3 = '3'
MOCK_volume_provider_location = '{0}/{1}'.format(
    MOCK_mountpoint, MOCK_vdisk_devicename)
MOCK_volume_provider_location2 = '{0}/{1}'.format(
    MOCK_mountpoint, MOCK_vdisk_devicename2)
MOCK_volume_provider_location3 = '{0}/{1}'.format(
    MOCK_mountpoint, MOCK_vdisk_devicename3)
MOCK_snapshot_id = '1234'
MOCK_snapshot_display_name = 'test-snapshot'
MOCK_pmachine_guid = '1111'
MOCK_image_id = '9999'
CALLED = {}


class MockVDiskController(object):

    def create_volume(self, location, size):
        CALLED['create_volume'] = {'location': location, 'size': size}

    def delete_volume(self, location):
        CALLED['delete_volume'] = {'location': location}

    def extend_volume(self, location, size):
        CALLED['extend_volume'] = {'location': location, 'size': size}

    def clone(self, diskguid, snapshotid, devicename, pmachineguid,
              machinename, machineguid):
        CALLED['clone_volume'] = diskguid
        return {'backingdevice': '/%s.raw' % devicename,
                'diskguid': diskguid}

    def create_snapshot(self, diskguid, metadata, snapshotid):
        CALLED['create_snapshot'] = diskguid

    def delete_snapshot(self, diskguid, snapshotid):
        CALLED['delete_snapshot'] = diskguid

    def create_from_template(self, diskguid, machinename, devicename,
                             pmachineguid, machineguid, storagedriver_guid):
        CALLED['create_from_template'] = diskguid
        return {'backingdevice': '/%s.raw' % devicename,
                'diskguid': diskguid}


class MockStorageRouter(object):
    name = MOCK_hostname


class MockStorageDriver(object):
    storagerouter = MockStorageRouter()
    mountpoint = MOCK_mountpoint


class MockVPool(object):
    storagedrivers = [MockStorageDriver()]


class MockVDisk(object):
    vpool = MockVPool()
    cinder_id = None
    snapshots = []
    vmachine_guid = None

    def __init__(self, guid = MOCK_vdisk_guid,
                 devicename = None,
                 info = MOCK_vdisk_disk_info):
        self.guid = guid
        self.devicename = devicename
        self.info = info
        if guid == MOCK_vdisk_guid and not devicename:
            self.devicename = MOCK_vdisk_devicename
        elif guid == MOCK_vdisk_guid2 and not devicename:
            self.devicename = MOCK_vdisk_devicename2
        elif guid == MOCK_vdisk_guid3 and not devicename:
            self.devicename = MOCK_vdisk_devicename3
            self.info = {'object_type': 'TEMPLATE'}

    def save(self):
        pass


class MockPMachine(object):
    guid = MOCK_pmachine_guid
    storagerouters = [MockStorageRouter()]

    def __init__(self):
        pass


class MockVPoolList(object):

    def get_vpool_by_name(self, name):
        return MockVPool()


class MockVDiskList(object):

    def __init__(self, vdisks = None):
        self.vdisks = vdisks
        if not vdisks:
            self.vdisks = [MockVDisk()]

    def get_vdisks(self):
        return self.vdisks


class MockPMachineList(object):

    def get_pmachines(self):
        return [MockPMachine()]


class MOCK_log(object):

    def debug(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class MOCK_Context(object):
    pass


class MOCK_ImageService(object):
    pass


class MOCK_ImageUtils(object):
    def fetch_to_raw(self, context, image_service, image_id, destination_path,
                     block_size, size, run_as_root=False):
        CALLED['ImageUtils_fetch_to_raw'] = (destination_path, size)


class MOCK_volume(object):
    host = MOCK_hostname
    size = MOCK_volume_size
    volume_type_id = MOCK_volume_type_id

    def __init__(self, display_name = MOCK_volume_name, id = MOCK_volume_id,
                 provider_location = None):
        self.display_name = display_name
        self.id = id
        self.provider_location = provider_location
        if self.id == MOCK_volume_id:
            self.provider_location = MOCK_volume_provider_location
        elif self.id == MOCK_volume_id2:
            self.provider_location = MOCK_volume_provider_location2
        elif self.id == MOCK_volume_id3:
            self.provider_location = MOCK_volume_provider_location3

    def __setitem__(self, attribute, value):
        setattr(self, attribute, value)

    def __getitem__(self, attribute):
        return getattr(self, attribute)


class MOCK_snapshot(object):
    volume = MOCK_volume()
    display_name = MOCK_snapshot_display_name
    id = MOCK_snapshot_id


# Fake Modules
class vdiskhybrid(object):
    VDisk = MockVDisk


class pmachinelist(object):
    PMachineList = MockPMachineList()


class vdisklist(object):
    def __init__(self, vdisks):
        self.VDiskList = MockVDiskList(vdisks)


class vpoollist(object):
    VPoolList = MockVPoolList()


class vdisklib(object):
    VDiskController = MockVDiskController()


class OVSPluginBaseTestCase(test.TestCase):
    """Basic tests - mocked
    """

    def setUp(self):
        vdisk1 = MockVDisk(MOCK_vdisk_guid, MOCK_vdisk_devicename)
        vdisk2 = MockVDisk(MOCK_vdisk_guid2, MOCK_vdisk_devicename2)
        vdisk3 = MockVDisk(MOCK_vdisk_guid3, MOCK_vdisk_devicename3)
        super(OVSPluginBaseTestCase, self).setUp()
        ovsvd.vdiskhybrid = vdiskhybrid()
        ovsvd.vpoollist = vpoollist()
        ovsvd.vdisklist = vdisklist([vdisk1, vdisk2, vdisk3])
        ovsvd.vdisklib = vdisklib()
        ovsvd.pmachinelist = pmachinelist()
        ovsvd.LOG = MOCK_log()
        ovsvd.image_utils = MOCK_ImageUtils()
        self.driver = ovsvd.OVSVolumeDriver(configuration = mock.Mock())

    def tearDown(self):
        super(OVSPluginBaseTestCase, self).tearDown()

    def test__get_hostname_mountpoint(self):
        mountpoint = self.driver._get_hostname_mountpoint(MOCK_hostname)
        self.assertTrue(mountpoint == MOCK_mountpoint, 'Wrong mountpoint')

    def test__find_ovs_model_disk_by_location(self):
        location = '{0}/{1}'.format(MOCK_mountpoint, MOCK_vdisk_devicename)
        vdisk = self.driver._find_ovs_model_disk_by_location(location,
                                                             MOCK_hostname)
        self.assertTrue(vdisk.devicename == MOCK_vdisk_devicename,
                        'Wrong devicename')

    def test_create_volume_mock(self):
        result = self.driver.create_volume(MOCK_volume())
        self.assertTrue(result['provider_location'] == '{0}/{1}.raw'.format(
            MOCK_mountpoint, MOCK_volume_name), 'Wrong location')
        self.assertTrue(CALLED['create_volume'] ==
                        {'location': MOCK_volume_provider_location,
                         'size': MOCK_volume_size},
                        'Wrong params')

    def test_delete_volume_mock(self):
        self.driver.delete_volume(MOCK_volume())
        self.assertTrue(CALLED['delete_volume'] ==
                        {'location': MOCK_volume_provider_location},
                        'Wrong params')

    def test_extend_volume(self):
        self.driver.extend_volume(MOCK_volume(), MOCK_volume_size_extend)
        self.assertTrue(CALLED['extend_volume'] ==
                        {'location': MOCK_volume_provider_location,
                         'size': MOCK_volume_size_extend},
                        'Wrong params')

    def test_copy_image_to_volume(self):
        self.driver.copy_image_to_volume(MOCK_Context(), MOCK_volume(),
                                         MOCK_ImageService(), MOCK_image_id)
        self.assertTrue(CALLED['delete_volume'] ==
                        {'location': MOCK_volume_provider_location},
                        'Wrong params')
        self.assertTrue(CALLED['ImageUtils_fetch_to_raw'] ==
                        (MOCK_volume_provider_location, MOCK_volume_size),
                        'Wrong params')
        self.assertTrue(CALLED['extend_volume'] ==
                        {'location': MOCK_volume_provider_location,
                         'size': MOCK_volume_size},
                        'Wrong params')

    # Test_copy_volume_to_image actually tests the standard behaviour of
    # the super class, not our own specific code

    def test_create_cloned_volume_template(self):
        target_volume = MOCK_volume(MOCK_volume_name2, MOCK_volume_id2,
                                    MOCK_volume_provider_location2)
        source_volume = MOCK_volume(MOCK_volume_name3, MOCK_volume_id3,
                                    MOCK_volume_provider_location3)
        result = self.driver.create_cloned_volume(target_volume,
                                                  source_volume)
        self.assertTrue(CALLED['create_from_template'] ==
                        MOCK_vdisk_guid3,
                        'Wrong params')
        self.assertTrue(result['provider_location'] ==
                        MOCK_volume_provider_location2,
                        'Wrong result %s' % result['provider_location'])

    def test_create_cloned_volume_volume(self):
        target_volume = MOCK_volume(MOCK_volume_name2, MOCK_volume_id2,
                                    MOCK_volume_provider_location2)
        source_volume = MOCK_volume(MOCK_volume_name, MOCK_volume_id,
                                    MOCK_volume_provider_location)
        result = self.driver.create_cloned_volume(target_volume,
                                                  source_volume)
        self.assertTrue(CALLED['create_snapshot'] ==
                        MOCK_vdisk_guid,
                        'Wrong params')
        self.assertTrue(CALLED['clone_volume'] ==
                        MOCK_vdisk_guid,
                        'Wrong params')
        self.assertTrue(result['provider_location'] ==
                        MOCK_volume_provider_location2,
                        'Wrong result %s' % result['provider_location'])

    def test_create_snapshot(self):
        snapshot = MOCK_snapshot()
        self.driver.create_snapshot(snapshot)
        self.assertTrue(CALLED['create_snapshot'] == MOCK_vdisk_guid,
                        'Wrong params')

    def test_delete_snapshot(self):
        snapshot = MOCK_snapshot()
        self.driver.delete_snapshot(snapshot)
        self.assertTrue(CALLED['delete_snapshot'] == MOCK_vdisk_guid,
                        'Wrong params')

    def create_volume_from_snapshot(self):
        new_volume = MOCK_volume(MOCK_volume_name2, MOCK_volume_id2,
                                 MOCK_volume_provider_location2)
        snapshot = MOCK_snapshot()
        result = self.driver.create_volume_from_snapshot(new_volume, snapshot)
        self.assertTrue(CALLED['clone_volume'] ==
                        MOCK_vdisk_guid,
                        'Wrong params')
        self.assertTrue(result['provider_location'] ==
                        MOCK_volume_provider_location2,
                        'Wrong result %s' % result['provider_location'])
