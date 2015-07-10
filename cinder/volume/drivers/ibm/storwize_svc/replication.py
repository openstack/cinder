# Copyright 2014 IBM Corp.
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

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


class StorwizeSVCReplication(object):
    def __init__(self, driver):
        self.driver = driver

    @staticmethod
    def factory(driver):
        """Use replication methods for the requested mode."""
        stretch = driver.configuration.storwize_svc_stretched_cluster_partner
        if stretch:
            return StorwizeSVCReplicationStretchedCluster(driver)

    def create_replica(self, ctxt, volume):
        return (None, None)

    def is_replicated(self, volume):
        return False

    def promote_replica(self, volume):
        pass

    def test_replica(self, tgt_volume, src_volume):
        pass

    def get_replication_status(self, volume):
        return None

    def get_replication_info(self):
        return {}

    def reenable_replication(self, volume):
        """Enable the replication between the primary and secondary volumes.

        This is not implemented in the StorwizeSVCReplicationStretchedCluster,
        as the Storwize backend is responsible for automatically resuming
        mirroring when stopped.
        """
        pass


class StorwizeSVCReplicationStretchedCluster(StorwizeSVCReplication):
    """Support for Storwize/SVC stretched cluster mode replication."""

    def __init__(self, driver):
        super(StorwizeSVCReplicationStretchedCluster, self).__init__(driver)

    def create_replica(self, ctxt, volume, vol_type = None):
        # if vol_type is None, use the source volume type
        if vol_type is None:
            vol_type = volume['volume_type_id']
            vol_type = volume_types.get_volume_type(ctxt, vol_type)
        conf = self.driver.configuration
        dest_pool = conf.storwize_svc_stretched_cluster_partner

        self.driver.add_vdisk_copy(volume['name'], dest_pool, vol_type)
        vol_update = {'replication_status': 'copying'}
        return vol_update

    def delete_replica(self, volume):
        vdisk = volume['name']
        copies = self.driver._helpers.get_vdisk_copies(vdisk)
        secondary = copies['secondary']

        if secondary:
            self.driver._helpers.rm_vdisk_copy(volume['name'],
                                               secondary['copy_id'])
        else:
            LOG.info(_LI('Could not find replica to delete of'
                         ' volume %(vol)s.'), {'vol': vdisk})

    def test_replica(self, tgt_volume, src_volume):
        vdisk = src_volume['name']
        opts = self.driver._get_vdisk_params(tgt_volume['volume_type_id'])
        copies = self.driver._helpers.get_vdisk_copies(vdisk)

        if copies['secondary']:
            dest_pool = copies['secondary']['mdisk_grp_name']
            self.driver._helpers.create_copy(src_volume['name'],
                                             tgt_volume['name'],
                                             src_volume['id'],
                                             self.driver.configuration,
                                             opts,
                                             True,
                                             pool=dest_pool)
        else:
            msg = (_('Unable to create replica clone for volume %s.'), vdisk)
            raise exception.VolumeDriverException(message=msg)

    def promote_replica(self, volume):
        vdisk = volume['name']
        copies = self.driver._helpers.get_vdisk_copies(vdisk)
        if copies['secondary']:
            copy_id = copies['secondary']['copy_id']
            self.driver._helpers.change_vdisk_primary_copy(volume['name'],
                                                           copy_id)
        else:
            msg = (_('Unable to promote replica to primary for volume %s.'
                     ' No secondary copy available.'),
                   volume['id'])
            raise exception.VolumeDriverException(message=msg)

    def get_replication_status(self, volume):
        # Make sure volume is replicated, otherwise ignore
        if volume['replication_status'] == 'disabled':
            return None

        vdisk = volume['name']
        orig = (volume['replication_status'],
                volume['replication_extended_status'])
        copies = self.driver._helpers.get_vdisk_copies(vdisk)

        primary = copies.get('primary', None)
        secondary = copies.get('secondary', None)

        # Check status of primary copy, set status 'error' as default
        status = 'error'
        if not primary:
            primary = {'status': 'not found',
                       'sync': 'no'}
        else:
            if primary['status'] == 'online':
                status = 'active'

        extended1 = (_('Primary copy status: %(status)s'
                       ' and synchronized: %(sync)s.') %
                     {'status': primary['status'],
                      'sync': primary['sync']})

        # Check status of secondary copy
        if not secondary:
            secondary = {'status': 'not found',
                         'sync': 'no',
                         'sync_progress': '0'}
            status = 'error'
        else:
            if secondary['status'] != 'online':
                status = 'error'
            else:
                if secondary['sync'] == 'yes':
                    secondary['sync_progress'] = '100'
                    # Only change the status if not in error state
                    if status != 'error':
                        status = 'active'
                    else:
                        # Primary offline, secondary online, data consistent,
                        # stop copying
                        status = 'active-stop'
                else:
                    # Primary and secondary both online, the status is copying
                    if status != 'error':
                        status = 'copying'

        extended2 = (_('Secondary copy status: %(status)s'
                       ' and synchronized: %(sync)s,'
                       ' sync progress is: %(progress)s%%.') %
                     {'status': secondary['status'],
                      'sync': secondary['sync'],
                      'progress': secondary['sync_progress']})

        extended = '%s. %s' % (extended1, extended2)

        if (status, extended) != orig:
            return {'replication_status': status,
                    'replication_extended_status': extended}
        else:
            return None

    def get_replication_info(self):
        data = {}
        data['replication'] = True
        return data
