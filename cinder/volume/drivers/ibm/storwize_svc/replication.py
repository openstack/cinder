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

import random

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder import ssh_utils
from cinder import utils
from cinder.volume.drivers.ibm.storwize_svc import storwize_const
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
    """Support for Storwize/SVC stretched cluster mode replication.

    This stretched cluster mode implements volume replication in terms of
    adding a copy to an existing volume, which changes a nonmirrored volume
    into a mirrored volume.
    """

    def __init__(self, driver, replication_target=None):
        super(StorwizeSVCReplicationStretchedCluster, self).__init__(driver)
        self.target = replication_target or {}

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


class StorwizeSVCReplicationGlobalMirror(
        StorwizeSVCReplicationStretchedCluster):
    """Support for Storwize/SVC global mirror mode replication.

    Global Mirror establishes a Global Mirror relationship between
    two volumes of equal size. The volumes in a Global Mirror relationship
    are referred to as the master (source) volume and the auxiliary
    (target) volume. This mode is dedicated to the asynchronous volume
    replication.
    """

    asyncmirror = True

    def __init__(self, driver, replication_target=None, target_helpers=None):
        super(StorwizeSVCReplicationGlobalMirror, self).__init__(
            driver, replication_target)
        self.target_helpers = target_helpers

    def volume_replication_setup(self, context, vref):
        LOG.debug('enter: volume_replication_setup: volume %s', vref['name'])

        target_vol_name = storwize_const.REPLICA_AUX_VOL_PREFIX + vref['name']
        try:
            attr = self.target_helpers.get_vdisk_attributes(target_vol_name)
            if not attr:
                opts = self.driver._get_vdisk_params(vref['volume_type_id'])
                pool = self.target.get('pool_name')
                self.target_helpers.create_vdisk(target_vol_name,
                                                 six.text_type(vref['size']),
                                                 'gb', pool, opts)

            system_info = self.target_helpers.get_system_info()
            self.driver._helpers.create_relationship(
                vref['name'], target_vol_name, system_info.get('system_name'),
                self.asyncmirror)
        except Exception as e:
            msg = (_("Unable to set up mirror mode replication for %(vol)s. "
                     "Exception: %(err)s.") % {'vol': vref['id'],
                                               'err': e.message})
            LOG.exception(msg)
            raise exception.VolumeDriverException(message=msg)
        LOG.debug('leave: volume_replication_setup:volume %s', vref['name'])

    def failover_volume_host(self, context, vref):
        LOG.debug('enter: failover_volume_host: vref=%(vref)s',
                  {'vref': vref['name']})
        target_vol = storwize_const.REPLICA_AUX_VOL_PREFIX + vref['name']

        try:
            rel_info = self.target_helpers.get_relationship_info(target_vol)
            # Reverse the role of the primary and secondary volumes
            self.target_helpers.switch_relationship(rel_info['name'])
            return {'replication_status': 'failed-over'}
        except Exception as e:
            LOG.exception(_LE('Unable to fail-over the volume %(id)s to the '
                              'secondary back-end by switchrcrelationship '
                              'command, error: %(error)s'),
                          {"id": vref['id'], "error": e})
            # If the switch command fail, try to make the aux volume
            # writeable again.
            try:
                self.target_helpers.stop_relationship(target_vol,
                                                      access=True)
                return {'replication_status': 'failed-over'}
            except Exception as e:
                msg = (_('Unable to fail-over the volume %(id)s to the '
                         'secondary back-end, error: %(error)s') %
                       {"id": vref['id'], "error": e})
                LOG.exception(msg)
                raise exception.VolumeDriverException(message=msg)
        LOG.debug('leave: failover_volume_host: vref=%(vref)s',
                  {'vref': vref['name']})

    def replication_failback(self, volume):
        tgt_volume = storwize_const.REPLICA_AUX_VOL_PREFIX + volume['name']
        rel_info = self.target_helpers.get_relationship_info(tgt_volume)
        if rel_info:
            try:
                self.target_helpers.switch_relationship(rel_info['name'],
                                                        aux=False)
                return {'replication_status': 'enabled',
                        'status': 'available'}
            except Exception as e:
                msg = (_('Unable to fail-back the volume:%(vol)s to the '
                         'master back-end, error:%(error)s') %
                       {"vol": volume['name'], "error": e})
                LOG.exception(msg)
                raise exception.VolumeDriverException(message=msg)


class StorwizeSVCReplicationMetroMirror(
        StorwizeSVCReplicationGlobalMirror):
    """Support for Storwize/SVC metro mirror mode replication.

    Metro Mirror establishes a Metro Mirror relationship between
    two volumes of equal size. The volumes in a Metro Mirror relationship
    are referred to as the master (source) volume and the auxiliary
    (target) volume.
    """

    asyncmirror = False

    def __init__(self, driver, replication_target=None, target_helpers=None):
        super(StorwizeSVCReplicationMetroMirror, self).__init__(
            driver, replication_target, target_helpers)


class StorwizeSVCReplicationManager(object):

    def __init__(self, driver, replication_target=None, target_helpers=None):
        self.sshpool = None
        self.driver = driver
        self.target = replication_target
        self.target_helpers = target_helpers(self._run_ssh)
        self._master_helpers = self.driver._master_backend_helpers
        self.global_m = StorwizeSVCReplicationGlobalMirror(
            self.driver, replication_target, self.target_helpers)
        self.metro_m = StorwizeSVCReplicationMetroMirror(
            self.driver, replication_target, self.target_helpers)

    def _run_ssh(self, cmd_list, check_exit_code=True, attempts=1):
        utils.check_ssh_injection(cmd_list)
        # TODO(vhou): We'll have a common method in ssh_utils to take
        # care of this _run_ssh method.
        command = ' '. join(cmd_list)

        if not self.sshpool:
            self.sshpool = ssh_utils.SSHPool(
                self.target.get('san_ip'),
                self.target.get('san_ssh_port', 22),
                self.target.get('ssh_conn_timeout', 30),
                self.target.get('san_login'),
                password=self.target.get('san_password'),
                privatekey=self.target.get('san_private_key', ''),
                min_size=self.target.get('ssh_min_pool_conn', 1),
                max_size=self.target.get('ssh_max_pool_conn', 5),)
        last_exception = None
        try:
            with self.sshpool.item() as ssh:
                while attempts > 0:
                    attempts -= 1
                    try:
                        return processutils.ssh_execute(
                            ssh, command, check_exit_code=check_exit_code)
                    except Exception as e:
                        LOG.error(six.text_type(e))
                        last_exception = e
                        greenthread.sleep(random.randint(20, 500) / 100.0)
                try:
                    raise processutils.ProcessExecutionError(
                        exit_code=last_exception.exit_code,
                        stdout=last_exception.stdout,
                        stderr=last_exception.stderr,
                        cmd=last_exception.cmd)
                except AttributeError:
                    raise processutils.ProcessExecutionError(
                        exit_code=-1, stdout="",
                        stderr="Error running SSH command",
                        cmd=command)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error running SSH command: %s"), command)

    def get_target_helpers(self):
        return self.target_helpers

    def get_replica_obj(self, rep_type):
        if rep_type == storwize_const.GLOBAL:
            return self.global_m
        elif rep_type == storwize_const.METRO:
            return self.metro_m
        else:
            return None

    def _partnership_validate_create(self, client, remote_name, remote_ip):
        try:
            partnership_info = client.get_partnership_info(
                remote_name)
            if not partnership_info:
                candidate_info = client.get_partnershipcandidate_info(
                    remote_name)
                if candidate_info:
                    client.mkfcpartnership(remote_name)
                else:
                    client.mkippartnership(remote_ip)
            if partnership_info['partnership'] != 'fully_configured':
                client.chpartnership(partnership_info['id'])
        except Exception:
            msg = (_('Unable to establish the partnership with '
                     'the Storwize cluster %s.'), remote_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def establish_target_partnership(self):
        local_system_info = self._master_helpers.get_system_info()
        target_system_info = self.target_helpers.get_system_info()
        local_system_name = local_system_info['system_name']
        target_system_name = target_system_info['system_name']
        local_ip = self.driver.configuration.safe_get('san_ip')
        target_ip = self.target.get('san_ip')
        self._partnership_validate_create(self._master_helpers,
                                          target_system_name, target_ip)
        self._partnership_validate_create(self.target_helpers,
                                          local_system_name, local_ip)
