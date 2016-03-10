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
import uuid

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder import ssh_utils
from cinder import utils
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
    UUID_LEN = 36

    def __init__(self, driver, replication_target=None, target_helpers=None):
        super(StorwizeSVCReplicationGlobalMirror, self).__init__(
            driver, replication_target)
        self.sshpool = None
        self.target_helpers = target_helpers(self._run_ssh)

    def _partnership_validate_create(self, client, remote_name, remote_ip):
        try:
            partnership_info = client.get_partnership_info(
                remote_name)
            if not partnership_info:
                candidate_info = client.get_partnershipcandidate_info(
                    remote_name)
                if not candidate_info:
                    client.mkippartnership(remote_ip)
                else:
                    client.mkfcpartnership(remote_name)
            elif partnership_info['partnership'] == (
                    'fully_configured_stopped'):
                client.startpartnership(partnership_info['id'])
        except Exception:
            msg = (_('Unable to establish the partnership with '
                     'the Storwize cluster %s.'), remote_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def establish_target_partnership(self):
        local_system_info = self.driver._helpers.get_system_info()
        target_system_info = self.target_helpers.get_system_info()
        local_system_name = local_system_info['system_name']
        target_system_name = target_system_info['system_name']
        local_ip = self.driver.configuration.safe_get('san_ip')
        target_ip = self.target.get('san_ip')
        self._partnership_validate_create(self.driver._helpers,
                                          target_system_name, target_ip)
        self._partnership_validate_create(self.target_helpers,
                                          local_system_name, local_ip)

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

    def volume_replication_setup(self, context, vref):
        target_vol_name = vref['name']
        try:
            attr = self.target_helpers.get_vdisk_attributes(target_vol_name)
            if attr:
                # If the volume name exists in the target pool, we need
                # to change to a different target name.
                vol_id = six.text_type(uuid.uuid4())
                prefix = vref['name'][0:len(vref['name']) - len(vol_id)]
                target_vol_name = prefix + vol_id

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
                     "Exception: %(err)s."), {'vol': vref['id'],
                                              'err': e})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def create_relationship(self, vref, target_vol_name):
        if not target_vol_name:
            return
        try:
            system_info = self.target_helpers.get_system_info()
            self.driver._helpers.create_relationship(
                vref['name'], target_vol_name, system_info.get('system_name'),
                self.asyncmirror)
        except Exception:
            msg = (_("Unable to create the relationship for %s."),
                   vref['name'])
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def extend_target_volume(self, target_vol_name, amount):
        if not target_vol_name:
            return
        self.target_helpers.extend_vdisk(target_vol_name, amount)

    def delete_target_volume(self, vref):
        try:
            rel_info = self.driver._helpers.get_relationship_info(vref)
        except Exception as e:
            msg = (_('Failed to get remote copy information for %(volume)s '
                     'due to %(err)s.'), {'volume': vref['id'], 'err': e})
            LOG.error(msg)
            raise exception.VolumeDriverException(data=msg)

        if rel_info and rel_info.get('aux_vdisk_name', None):
            try:
                self.driver._helpers.delete_relationship(vref['name'])
                self.driver._helpers.delete_vdisk(
                    rel_info['aux_vdisk_name'], False)
            except Exception as e:
                msg = (_('Unable to delete the target volume for '
                         'volume %(vol)s. Exception: %(err)s.'),
                       {'vol': vref['id'], 'err': e})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

    def get_relationship_status(self, volume):
        rel_info = {}
        try:
            rel_info = self.target_helpers.get_relationship_info(volume)
        except Exception:
            msg = (_LE('Unable to access the Storwize back-end '
                       'for volume %s.'), volume['id'])
            LOG.error(msg)

        return rel_info.get('state') if rel_info else None

    def failover_volume_host(self, context, vref, secondary):
        if not self.target or self.target.get('backend_id') != secondary:
            msg = _LE("A valid secondary target MUST be specified in order "
                      "to failover.")
            LOG.error(msg)
            # If the admin does not provide a valid secondary, the failover
            # will fail, but it is not severe enough to throw an exception.
            # The admin can still issue another failover request. That is
            # why we tentatively put return None instead of raising an
            # exception.
            return

        try:
            rel_info = self.target_helpers.get_relationship_info(vref)
        except Exception:
            msg = (_('Unable to access the Storwize back-end for volume %s.'),
                   vref['id'])
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if not rel_info:
            msg = (_('Unable to get the replication relationship for volume '
                     '%s.'),
                   vref['id'])
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        else:
            try:
                # Reverse the role of the primary and secondary volumes,
                # because the secondary volume becomes the primary in the
                # fail-over status.
                self.target_helpers.switch_relationship(
                    rel_info.get('name'))
            except Exception as e:
                msg = (_('Unable to fail-over the volume %(id)s to the '
                         'secondary back-end, because the replication '
                         'relationship is unable to switch: %(error)s'),
                       {"id": vref['id'], "error": e})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

    def replication_failback(self, volume):
        rel_info = self.target_helpers.get_relationship_info(volume)
        if rel_info:
            self.target_helpers.switch_relationship(rel_info.get('name'),
                                                    aux=False)


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
