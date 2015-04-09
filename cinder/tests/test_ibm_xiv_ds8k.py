# Copyright 2013 IBM Corp.
# Copyright (c) 2013 OpenStack Foundation
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
#
# Authors:
#   Erik Zaadi <erikz@il.ibm.com>
#   Avishay Traeger <avishay@il.ibm.com>


import copy

import mox
from oslo_config import cfg

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm import xiv_ds8k
from cinder.volume import volume_types

FAKE = "fake"
CANNOT_DELETE = "Can not delete"
TOO_BIG_VOLUME_SIZE = 12000
POOL_SIZE = 100
CONSISTGROUP_ID = 1
VOLUME = {'size': 16,
          'name': FAKE,
          'id': 1,
          'consistencygroup_id': CONSISTGROUP_ID,
          'status': 'available'}

MANAGED_FAKE = "managed_fake"
MANAGED_VOLUME = {'size': 16,
                  'name': MANAGED_FAKE,
                  'id': 2}

REPLICA_FAKE = "repicated_fake"
REPLICATED_VOLUME = {'size': 64,
                     'name': REPLICA_FAKE,
                     'id': 2}

CONTEXT = {}

CONSISTGROUP = {'id': CONSISTGROUP_ID, }
CG_SNAPSHOT_ID = 1
CG_SNAPSHOT = {'id': CG_SNAPSHOT_ID,
               'consistencygroup_id': CONSISTGROUP_ID}

CONNECTOR = {'initiator': "iqn.2012-07.org.fake:01:948f189c4695", }

CONF = cfg.CONF


class XIVDS8KFakeProxyDriver(object):
    """Fake IBM XIV and DS8K Proxy Driver."""

    def __init__(self, xiv_ds8k_info, logger, expt, driver=None):
        """Initialize Proxy."""

        self.xiv_ds8k_info = xiv_ds8k_info
        self.logger = logger
        self.exception = expt
        self.xiv_ds8k_portal = \
            self.xiv_ds8k_iqn = FAKE

        self.volumes = {}
        self.snapshots = {}
        self.driver = driver

    def setup(self, context):
        if self.xiv_ds8k_info['xiv_ds8k_user'] != self.driver\
                .configuration.san_login:
            raise self.exception.NotAuthorized()

        if self.xiv_ds8k_info['xiv_ds8k_address'] != self.driver\
                .configuration.san_ip:
            raise self.exception.HostNotFound(host='fake')

    def create_volume(self, volume):
        if volume['size'] > POOL_SIZE:
            raise self.exception.VolumeBackendAPIException(data='blah')
        self.volumes[volume['name']] = volume

    def volume_exists(self, volume):
        return self.volumes.get(volume['name'], None) is not None

    def delete_volume(self, volume):
        if self.volumes.get(volume['name'], None) is not None:
            del self.volumes[volume['name']]

    def manage_volume_get_size(self, volume, existing_ref):
        if self.volumes.get(existing_ref['source-name'], None) is None:
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        return self.volumes[existing_ref['source-name']]['size']

    def manage_volume(self, volume, existing_ref):
        if self.volumes.get(existing_ref['source-name'], None) is None:
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        volume['size'] = MANAGED_VOLUME['size']
        return {}

    def unmanage_volume(self, volume):
        pass

    def initialize_connection(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        lun_id = volume['id']

        self.volumes[volume['name']]['attached'] = connector

        return {'driver_volume_type': 'iscsi',
                'data': {'target_discovered': True,
                         'target_discovered': True,
                         'target_portal': self.xiv_ds8k_portal,
                         'target_iqn': self.xiv_ds8k_iqn,
                         'target_lun': lun_id,
                         'volume_id': volume['id'],
                         'multipath': True,
                         'provider_location': "%s,1 %s %s" % (
                             self.xiv_ds8k_portal,
                             self.xiv_ds8k_iqn,
                             lun_id), },
                }

    def terminate_connection(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        if not self.is_volume_attached(volume, connector):
            raise self.exception.NotFound(_('Volume not found for '
                                            'instance %(instance_id)s.')
                                          % {'instance_id': 'fake'})
        del self.volumes[volume['name']]['attached']

    def is_volume_attached(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])

        return (self.volumes[volume['name']].get('attached', None)
                == connector)

    def reenable_replication(self, context, volume):
        model_update = {}
        if volume['replication_status'] == 'inactive':
            model_update['replication_status'] = 'active'
        elif volume['replication_status'] == 'invalid_status_val':
            raise exception.CinderException()
        model_update['replication_extended_status'] = 'some_status'
        model_update['replication_driver_data'] = 'some_data'
        return model_update

    def get_replication_status(self, context, volume):
        if volume['replication_status'] == 'invalid_status_val':
            raise exception.CinderException()
        return {'replication_status': 'active'}

    def promote_replica(self, context, volume):
        if volume['replication_status'] == 'invalid_status_val':
            raise exception.CinderException()
        return {'replication_status': 'inactive'}

    def create_replica_test_volume(self, volume, src_vref):
        if volume['size'] != src_vref['size']:
            raise exception.InvalidVolume(
                reason="Target and source volumes have different size.")
        return

    def retype(self, ctxt, volume, new_type, diff, host):
        volume['easytier'] = new_type['extra_specs']['easytier']
        return True, volume

    def create_consistencygroup(self, ctxt, group):

        volumes = [volume for k, volume in self.volumes.iteritems()
                   if volume['consistencygroup_id'] == group['id']]

        if volumes:
            raise exception.CinderException(
                message='The consistency group id of volume may be wrong.')

        return {'status': 'available'}

    def delete_consistencygroup(self, ctxt, group):
        volumes = []
        for volume in self.volumes.values():
            if (group.get('id', None)
                    == volume.get('consistencygroup_id', None)):
                if volume['name'] == CANNOT_DELETE:
                    raise exception.VolumeBackendAPIException(
                        message='Volume can not be deleted')
                else:
                    volume['status'] = 'deleted'
                    volumes.append(volume)

        # Delete snapshots in consistency group
        self.snapshots = {k: snap for k, snap in self.snapshots.iteritems()
                          if not(snap.get('consistencygroup_id', None)
                                 == group.get('id', None))}

        # Delete volume in consistency group
        self.volumes = {k: vol for k, vol in self.volumes.iteritems()
                        if not(vol.get('consistencygroup_id', None)
                               == group.get('id', None))}

        return {'status': 'deleted'}, volumes

    def create_cgsnapshot(self, ctxt, cgsnapshot):
        snapshots = []
        for volume in self.volumes.values():
            if (cgsnapshot.get('consistencygroup_id', None)
                    == volume.get('consistencygroup_id', None)):

                if volume['size'] > POOL_SIZE / 2:
                    raise self.exception.VolumeBackendAPIException(data='blah')

                snapshot = copy.deepcopy(volume)
                snapshot['name'] = CANNOT_DELETE \
                    if snapshot['name'] == CANNOT_DELETE \
                    else snapshot['name'] + 'Snapshot'
                snapshot['status'] = 'available'
                snapshot['cgsnapshot_id'] = cgsnapshot.get('id', None)
                snapshot['consistencygroup_id'] = \
                    cgsnapshot.get('consistencygroup_id', None)
                self.snapshots[snapshot['name']] = snapshot
                snapshots.append(snapshot)

        return {'status': 'available'}, snapshots

    def delete_cgsnapshot(self, ctxt, cgsnapshot):
        snapshots = []
        for snapshot in self.snapshots.values():
            if (cgsnapshot.get('id', None)
                    == snapshot.get('cgsnapshot_id', None)):

                if snapshot['name'] == CANNOT_DELETE:
                    raise exception.VolumeBackendAPIException(
                        message='Snapshot can not be deleted')
                else:
                    snapshot['status'] = 'deleted'
                    snapshots.append(snapshot)

        # Delete snapshots in consistency group
        self.snapshots = {k: snap for k, snap in self.snapshots.iteritems()
                          if not(snap.get('consistencygroup_id', None)
                                 == cgsnapshot.get('cgsnapshot_id', None))}

        return {'status': 'deleted'}, snapshots


class XIVDS8KVolumeDriverTest(test.TestCase):
    """Test IBM XIV and DS8K volume driver."""

    def setUp(self):
        """Initialize IBM XIV and DS8K Driver."""
        super(XIVDS8KVolumeDriverTest, self).setUp()

        configuration = mox.MockObject(conf.Configuration)
        configuration.san_is_local = False
        configuration.xiv_ds8k_proxy = \
            'cinder.tests.test_ibm_xiv_ds8k.XIVDS8KFakeProxyDriver'
        configuration.xiv_ds8k_connection_type = 'iscsi'
        configuration.xiv_chap = 'disabled'
        configuration.san_ip = FAKE
        configuration.san_login = FAKE
        configuration.san_clustername = FAKE
        configuration.san_password = FAKE
        configuration.append_config_values(mox.IgnoreArg())

        self.driver = xiv_ds8k.XIVDS8KDriver(
            configuration=configuration)

    def test_initialized_should_set_xiv_ds8k_info(self):
        """Test that the san flags are passed to the IBM proxy."""

        self.assertEqual(
            self.driver.xiv_ds8k_proxy.xiv_ds8k_info['xiv_ds8k_user'],
            self.driver.configuration.san_login)
        self.assertEqual(
            self.driver.xiv_ds8k_proxy.xiv_ds8k_info['xiv_ds8k_pass'],
            self.driver.configuration.san_password)
        self.assertEqual(
            self.driver.xiv_ds8k_proxy.xiv_ds8k_info['xiv_ds8k_address'],
            self.driver.configuration.san_ip)
        self.assertEqual(
            self.driver.xiv_ds8k_proxy.xiv_ds8k_info['xiv_ds8k_vol_pool'],
            self.driver.configuration.san_clustername)

    def test_setup_should_fail_if_credentials_are_invalid(self):
        """Test that the xiv_ds8k_proxy validates credentials."""

        self.driver.xiv_ds8k_proxy.xiv_ds8k_info['xiv_ds8k_user'] = 'invalid'
        self.assertRaises(exception.NotAuthorized, self.driver.do_setup, None)

    def test_setup_should_fail_if_connection_is_invalid(self):
        """Test that the xiv_ds8k_proxy validates connection."""

        self.driver.xiv_ds8k_proxy.xiv_ds8k_info['xiv_ds8k_address'] = \
            'invalid'
        self.assertRaises(exception.HostNotFound, self.driver.do_setup, None)

    def test_create_volume(self):
        """Test creating a volume."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        has_volume = self.driver.xiv_ds8k_proxy.volume_exists(VOLUME)
        self.assertTrue(has_volume)
        self.driver.delete_volume(VOLUME)

    def test_volume_exists(self):
        """Test the volume exist method with a volume that doesn't exist."""

        self.driver.do_setup(None)

        self.assertFalse(
            self.driver.xiv_ds8k_proxy.volume_exists({'name': FAKE})
        )

    def test_delete_volume(self):
        """Verify that a volume is deleted."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.delete_volume(VOLUME)
        has_volume = self.driver.xiv_ds8k_proxy.volume_exists(VOLUME)
        self.assertFalse(has_volume)

    def test_delete_volume_should_fail_for_not_existing_volume(self):
        """Verify that deleting a non-existing volume is OK."""

        self.driver.do_setup(None)
        self.driver.delete_volume(VOLUME)

    def test_create_volume_should_fail_if_no_pool_space_left(self):
        """Vertify that the xiv_ds8k_proxy validates volume pool space."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          {'name': FAKE,
                           'id': 1,
                           'size': TOO_BIG_VOLUME_SIZE})

    def test_initialize_connection(self):
        """Test that inititialize connection attaches volume to host."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.initialize_connection(VOLUME, CONNECTOR)

        self.assertTrue(
            self.driver.xiv_ds8k_proxy.is_volume_attached(VOLUME, CONNECTOR))

        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.driver.delete_volume(VOLUME)

    def test_initialize_connection_should_fail_for_non_existing_volume(self):
        """Verify that initialize won't work for non-existing volume."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.initialize_connection,
                          VOLUME,
                          CONNECTOR)

    def test_terminate_connection(self):
        """Test terminating a connection."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.initialize_connection(VOLUME, CONNECTOR)
        self.driver.terminate_connection(VOLUME, CONNECTOR)

        self.assertFalse(self.driver.xiv_ds8k_proxy.is_volume_attached(
            VOLUME,
            CONNECTOR))

        self.driver.delete_volume(VOLUME)

    def test_terminate_connection_should_fail_on_non_existing_volume(self):
        """Test that terminate won't work for non-existing volumes."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.terminate_connection,
                          VOLUME,
                          CONNECTOR)

    def test_manage_existing_get_size(self):
        """Test that manage_existing_get_size returns the expected size. """

        self.driver.do_setup(None)
        self.driver.create_volume(MANAGED_VOLUME)
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        return_size = self.driver.manage_existing_get_size(
            VOLUME,
            existing_ref)
        self.assertEqual(return_size, MANAGED_VOLUME['size'])

        # cover both case, whether driver renames the volume or not
        self.driver.delete_volume(VOLUME)
        self.driver.delete_volume(MANAGED_VOLUME)

    def test_manage_existing_get_size_should_fail_on_non_existing_volume(self):
        """Test that manage_existing_get_size fails on non existing volume. """

        self.driver.do_setup(None)
        # on purpose - do NOT create managed volume
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.manage_existing_get_size,
                          VOLUME,
                          existing_ref)

    def test_manage_existing(self):
        """Test that manage_existing returns successfully. """

        self.driver.do_setup(None)
        self.driver.create_volume(MANAGED_VOLUME)
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        self.driver.manage_existing(VOLUME, existing_ref)
        self.assertEqual(VOLUME['size'], MANAGED_VOLUME['size'])

        # cover both case, whether driver renames the volume or not
        self.driver.delete_volume(VOLUME)
        self.driver.delete_volume(MANAGED_VOLUME)

    def test_manage_existing_should_fail_on_non_existing_volume(self):
        """Test that manage_existing fails on non existing volume. """

        self.driver.do_setup(None)
        # on purpose - do NOT create managed volume
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.manage_existing,
                          VOLUME,
                          existing_ref)

    def test_reenable_replication(self):
        """Test that reenable_replication returns successfully. """

        self.driver.do_setup(None)
        # assume the replicated volume is inactive
        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        replicated_volume['replication_status'] = 'inactive'
        model_update = self.driver.reenable_replication(
            CONTEXT,
            replicated_volume
        )
        self.assertEqual(
            model_update['replication_status'],
            'active'
        )
        self.assertTrue('replication_extended_status' in model_update)
        self.assertTrue('replication_driver_data' in model_update)

    def test_reenable_replication_fail_on_cinder_exception(self):
        """Test that reenable_replication fails on driver raising exception."""

        self.driver.do_setup(None)

        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        # on purpose - set invalid value to replication_status
        # expect an exception.
        replicated_volume['replication_status'] = 'invalid_status_val'
        self.assertRaises(
            exception.CinderException,
            self.driver.reenable_replication,
            CONTEXT,
            replicated_volume
        )

    def test_get_replication_status(self):
        """Test that get_replication_status return successfully. """

        self.driver.do_setup(None)

        # assume the replicated volume is inactive
        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        replicated_volume['replication_status'] = 'inactive'
        model_update = self.driver.get_replication_status(
            CONTEXT,
            replicated_volume
        )
        self.assertEqual(
            model_update['replication_status'],
            'active'
        )

    def test_get_replication_status_fail_on_exception(self):
        """Test that get_replication_status fails on exception"""

        self.driver.do_setup(None)

        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        # on purpose - set invalid value to replication_status
        # expect an exception.
        replicated_volume['replication_status'] = 'invalid_status_val'
        self.assertRaises(
            exception.CinderException,
            self.driver.get_replication_status,
            CONTEXT,
            replicated_volume
        )

    def test_promote_replica(self):
        """Test that promote_replica returns successfully. """

        self.driver.do_setup(None)

        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        # assume the replication_status should be active
        replicated_volume['replication_status'] = 'active'
        model_update = self.driver.promote_replica(
            CONTEXT,
            replicated_volume
        )
        # after promoting, replication_status should be inactive
        self.assertEqual(
            model_update['replication_status'],
            'inactive'
        )

    def test_promote_replica_fail_on_cinder_exception(self):
        """Test that promote_replica fails on CinderException. """

        self.driver.do_setup(None)

        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        # on purpose - set invalid value to replication_status
        # expect an exception.
        replicated_volume['replication_status'] = 'invalid_status_val'
        self.assertRaises(
            exception.CinderException,
            self.driver.promote_replica,
            CONTEXT,
            replicated_volume
        )

    def test_create_replica_test_volume(self):
        """Test that create_replica_test_volume returns successfully."""

        self.driver.do_setup(None)
        tgt_volume = copy.deepcopy(VOLUME)
        src_volume = copy.deepcopy(REPLICATED_VOLUME)
        tgt_volume['size'] = src_volume['size']
        model_update = self.driver.create_replica_test_volume(
            tgt_volume,
            src_volume
        )
        self.assertTrue(model_update is None)

    def test_create_replica_test_volume_fail_on_diff_size(self):
        """Test that create_replica_test_volume fails on diff size."""

        self.driver.do_setup(None)
        tgt_volume = copy.deepcopy(VOLUME)
        src_volume = copy.deepcopy(REPLICATED_VOLUME)
        self.assertRaises(
            exception.InvalidVolume,
            self.driver.create_replica_test_volume,
            tgt_volume,
            src_volume
        )

    def test_retype(self):
        """Test that retype returns successfully."""

        self.driver.do_setup(None)

        # prepare parameters
        ctxt = context.get_admin_context()

        host = {
            'host': 'foo',
            'capabilities': {
                'location_info': 'xiv_ds8k_fake_1',
                'extent_size': '1024'
            }
        }

        key_specs_old = {'easytier': False, 'warning': 2, 'autoexpand': True}
        key_specs_new = {'easytier': True, 'warning': 5, 'autoexpand': False}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, equal = volume_types.volume_types_diff(
            ctxt,
            old_type_ref['id'],
            new_type_ref['id'],
        )

        volume = copy.deepcopy(VOLUME)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.create_volume(volume)
        ret = self.driver.retype(ctxt, volume, new_type, diff, host)
        self.assertTrue(ret)
        self.assertTrue(volume['easytier'])

    def test_retype_fail_on_exception(self):
        """Test that retype fails on exception."""

        self.driver.do_setup(None)

        # prepare parameters
        ctxt = context.get_admin_context()

        host = {
            'host': 'foo',
            'capabilities': {
                'location_info': 'xiv_ds8k_fake_1',
                'extent_size': '1024'
            }
        }

        key_specs_old = {'easytier': False, 'warning': 2, 'autoexpand': True}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new')

        diff, equal = volume_types.volume_types_diff(
            ctxt,
            old_type_ref['id'],
            new_type_ref['id'],
        )

        volume = copy.deepcopy(VOLUME)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.create_volume(volume)
        self.assertRaises(
            KeyError,
            self.driver.retype,
            ctxt, volume, new_type, diff, host
        )

    def test_create_consistencygroup(self):
        """Test that create_consistencygroup return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create consistency group
        model_update = self.driver.create_consistencygroup(ctxt, CONSISTGROUP)

        self.assertEqual('available',
                         model_update['status'],
                         "Consistency Group created failed")

    def test_create_consistencygroup_fail_on_cg_not_empty(self):
        """Test that create_consistencygroup fail
        when consistency group is not empty.
        """

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create volumes
        # And add the volumes into the consistency group before creating cg
        self.driver.create_volume(VOLUME)

        self.assertRaises(exception.CinderException,
                          self.driver.create_consistencygroup,
                          ctxt, CONSISTGROUP)

    def test_delete_consistencygroup(self):
        """Test that delete_consistencygroup return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create consistency group
        self.driver.create_consistencygroup(ctxt, CONSISTGROUP)

        # Create volumes and add them to consistency group
        self.driver.create_volume(VOLUME)

        # Delete consistency group
        model_update, volumes = \
            self.driver.delete_consistencygroup(ctxt, CONSISTGROUP)

        # Verify the result
        self.assertEqual('deleted',
                         model_update['status'],
                         'Consistency Group deleted failed')
        for volume in volumes:
            self.assertEqual('deleted',
                             volume['status'],
                             'Consistency Group deleted failed')

    def test_delete_consistencygroup_fail_on_volume_not_delete(self):
        """Test that delete_consistencygroup return fail
        when the volume can not be deleted.
        """

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create consistency group
        self.driver.create_consistencygroup(ctxt, CONSISTGROUP)

        # Set the volume not to be deleted
        volume = copy.deepcopy(VOLUME)
        volume['name'] = CANNOT_DELETE

        # Create volumes and add them to consistency group
        self.driver.create_volume(volume)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_consistencygroup,
                          ctxt, CONSISTGROUP)

    def test_create_cgsnapshot(self):
        """Test that create_cgsnapshot return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create consistency group
        self.driver.create_consistencygroup(ctxt, CONSISTGROUP)

        # Create volumes and add them to consistency group
        self.driver.create_volume(VOLUME)

        # Create consistency group snapshot
        model_update, snapshots = \
            self.driver.create_cgsnapshot(ctxt, CG_SNAPSHOT)

        # Verify the result
        self.assertEqual('available',
                         model_update['status'],
                         'Consistency Group Snapshot created failed')
        for snap in snapshots:
            self.assertEqual('available',
                             snap['status'])

        # Clean the environment
        self.driver.delete_cgsnapshot(ctxt, CG_SNAPSHOT)
        self.driver.delete_consistencygroup(ctxt, CONSISTGROUP)

    def test_create_cgsnapshot_fail_on_no_pool_space_left(self):
        """Test that create_cgsnapshot return fail when no pool space left."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create consistency group
        self.driver.create_consistencygroup(ctxt, CONSISTGROUP)

        # Set the volume size
        volume = copy.deepcopy(VOLUME)
        volume['size'] = POOL_SIZE / 2 + 1

        # Create volumes and add them to consistency group
        self.driver.create_volume(volume)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cgsnapshot,
                          ctxt, CG_SNAPSHOT)

        # Clean the environment
        self.driver.volumes = None
        self.driver.delete_consistencygroup(ctxt, CONSISTGROUP)

    def test_delete_cgsnapshot(self):
        """Test that delete_cgsnapshot return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create consistency group
        self.driver.create_consistencygroup(ctxt, CONSISTGROUP)

        # Create volumes and add them to consistency group
        self.driver.create_volume(VOLUME)

        # Create consistency group snapshot
        self.driver.create_cgsnapshot(ctxt, CG_SNAPSHOT)

        # Delete consistency group snapshot
        model_update, snapshots = \
            self.driver.delete_cgsnapshot(ctxt, CG_SNAPSHOT)

        # Verify the result
        self.assertEqual('deleted',
                         model_update['status'],
                         'Consistency Group Snapshot deleted failed')
        for snap in snapshots:
            self.assertEqual('deleted',
                             snap['status'])

        # Clean the environment
        self.driver.delete_consistencygroup(ctxt, CONSISTGROUP)

    def test_delete_cgsnapshot_fail_on_snapshot_not_delete(self):
        """Test that delete_cgsnapshot return fail
        when the snapshot can not be deleted.
        """

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create consistency group
        self.driver.create_consistencygroup(ctxt, CONSISTGROUP)

        # Set the snapshot not to be deleted
        volume = copy.deepcopy(VOLUME)
        volume['name'] = CANNOT_DELETE

        # Create volumes and add them to consistency group
        self.driver.create_volume(volume)

        # Create consistency group snapshot
        self.driver.create_cgsnapshot(ctxt, CG_SNAPSHOT)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_cgsnapshot,
                          ctxt, CG_SNAPSHOT)
