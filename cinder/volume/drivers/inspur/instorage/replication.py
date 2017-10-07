# Copyright 2017 Inspur Corp.
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
from cinder.i18n import _
from cinder.objects import fields
from cinder import ssh_utils
from cinder import utils as cinder_utils
from cinder.volume.drivers.inspur.instorage import instorage_const

LOG = logging.getLogger(__name__)


class InStorageMCSReplicationManager(object):

    def __init__(self, driver, replication_target=None, target_assistant=None):
        self.sshpool = None
        self.driver = driver
        self.target = replication_target
        self.target_assistant = target_assistant(self._run_ssh)
        self._local_assistant = self.driver._local_backend_assistant
        self.async_m = InStorageMCSReplicationAsyncCopy(
            self.driver, replication_target, self.target_assistant)
        self.sync_m = InStorageMCSReplicationSyncCopy(
            self.driver, replication_target, self.target_assistant)

    def _run_ssh(self, cmd_list, check_exit_code=True, attempts=1):
        cinder_utils.check_ssh_injection(cmd_list)
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
                        LOG.error(e)
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
                LOG.error("Error running SSH command: %s", command)

    def get_target_assistant(self):
        return self.target_assistant

    def get_replica_obj(self, rep_type):
        if rep_type == instorage_const.ASYNC:
            return self.async_m
        elif rep_type == instorage_const.SYNC:
            return self.sync_m
        else:
            return None

    def _partnership_validate_create(self, client, remote_name, remote_ip):
        try:
            partnership_info = client.get_partnership_info(remote_name)
            if not partnership_info:
                candidate_info = client.get_partnershipcandidate_info(
                    remote_name)
                if candidate_info:
                    client.mkfcpartnership(remote_name)
                else:
                    client.mkippartnership(remote_ip)
                partnership_info = client.get_partnership_info(remote_name)
            if partnership_info['partnership'] != 'fully_configured':
                client.chpartnership(partnership_info['id'])
        except Exception:
            msg = (_('Unable to establish the partnership with '
                     'the InStorage cluster %s.') % remote_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def establish_target_partnership(self):
        local_system_info = self._local_assistant.get_system_info()
        target_system_info = self.target_assistant.get_system_info()
        local_system_name = local_system_info['system_name']
        target_system_name = target_system_info['system_name']
        local_ip = self.driver.configuration.safe_get('san_ip')
        target_ip = self.target.get('san_ip')
        # Establish partnership only when the local system and the replication
        # target system is different.
        if target_system_name != local_system_name:
            self._partnership_validate_create(self._local_assistant,
                                              target_system_name, target_ip)
            self._partnership_validate_create(self.target_assistant,
                                              local_system_name, local_ip)


class InStorageMCSReplication(object):

    def __init__(self, asynccopy, driver,
                 replication_target=None, target_assistant=None):

        self.asynccopy = asynccopy
        self.driver = driver
        self.target = replication_target or {}
        self.target_assistant = target_assistant

    @cinder_utils.trace
    def volume_replication_setup(self, context, vref):
        target_vol_name = instorage_const.REPLICA_AUX_VOL_PREFIX + vref.name
        try:
            attr = self.target_assistant.get_vdisk_attributes(target_vol_name)
            if not attr:
                opts = self.driver._get_vdisk_params(vref.volume_type_id)
                pool = self.target.get('pool_name')
                src_attr = self.driver._assistant.get_vdisk_attributes(
                    vref.name)
                opts['iogrp'] = src_attr['IO_group_id']
                self.target_assistant.create_vdisk(target_vol_name,
                                                   six.text_type(vref['size']),
                                                   'gb', pool, opts)

            system_info = self.target_assistant.get_system_info()
            self.driver._assistant.create_relationship(
                vref.name, target_vol_name, system_info.get('system_name'),
                self.asynccopy)
        except Exception as e:
            msg = (_("Unable to set up copy mode replication for %(vol)s. "
                     "Exception: %(err)s.") % {'vol': vref.id, 'err': e})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    @cinder_utils.trace
    def failover_volume_host(self, context, vref):
        target_vol = instorage_const.REPLICA_AUX_VOL_PREFIX + vref.name

        try:
            rel_info = self.target_assistant.get_relationship_info(target_vol)
            # Reverse the role of the primary and secondary volumes
            self.target_assistant.switch_relationship(rel_info['name'])
            return {'replication_status': fields.ReplicationStatus.FAILED_OVER}
        except Exception as e:
            LOG.exception('Unable to fail-over the volume %(id)s to the '
                          'secondary back-end by switchrcrelationship '
                          'command.', {"id": vref.id})
            # If the switch command fail, try to make the aux volume
            # writeable again.
            try:
                self.target_assistant.stop_relationship(target_vol,
                                                        access=True)
                return {
                    'replication_status': fields.ReplicationStatus.FAILED_OVER}
            except Exception as e:
                msg = (_('Unable to fail-over the volume %(id)s to the '
                         'secondary back-end, error: %(error)s') %
                       {"id": vref.id, "error": six.text_type(e)})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

    def replication_failback(self, volume):
        tgt_volume = instorage_const.REPLICA_AUX_VOL_PREFIX + volume.name
        rel_info = self.target_assistant.get_relationship_info(tgt_volume)
        if rel_info:
            try:
                self.target_assistant.switch_relationship(rel_info['name'],
                                                          aux=False)
                return {'replication_status': fields.ReplicationStatus.ENABLED,
                        'status': 'available'}
            except Exception as e:
                msg = (_('Unable to fail-back the volume:%(vol)s to the '
                         'master back-end, error:%(error)s') %
                       {"vol": volume.name, "error": six.text_type(e)})
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)


class InStorageMCSReplicationAsyncCopy(InStorageMCSReplication):
    """Support for InStorage/MCS async copy mode replication.

    Async Copy establishes a Async Copy relationship between
    two volumes of equal size. The volumes in a Async Copy relationship
    are referred to as the master (source) volume and the auxiliary
    (target) volume. This mode is dedicated to the asynchronous volume
    replication.
    """

    def __init__(self, driver, replication_target=None, target_assistant=None):
        super(InStorageMCSReplicationAsyncCopy, self).__init__(
            True, driver, replication_target, target_assistant)


class InStorageMCSReplicationSyncCopy(InStorageMCSReplication):
    """Support for InStorage/MCS sync copy mode replication.

    Sync Copy establishes a Sync Copy relationship between
    two volumes of equal size. The volumes in a Sync Copy relationship
    are referred to as the master (source) volume and the auxiliary
    (target) volume.
    """

    def __init__(self, driver, replication_target=None, target_assistant=None):
        super(InStorageMCSReplicationSyncCopy, self).__init__(
            False, driver, replication_target, target_assistant)
