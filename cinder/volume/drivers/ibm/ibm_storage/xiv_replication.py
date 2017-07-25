#  Copyright (c) 2017 IBM Corporation
#  All Rights Reserved.
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
import six

from oslo_log import log as logging
from oslo_utils import importutils

pyxcli = importutils.try_import("pyxcli")
if pyxcli:
    from pyxcli import errors
    from pyxcli.mirroring import cg_recovery_manager
    from pyxcli.mirroring import errors as m_errors
    from pyxcli.mirroring import volume_recovery_manager

from cinder.i18n import _
from cinder.volume.drivers.ibm.ibm_storage import strings

SYNC = 'sync'
ASYNC = 'async'

LOG = logging.getLogger(__name__)


class Rate(object):

    def __init__(self, rpo, schedule):
        self.rpo = rpo
        self.schedule = schedule
        self.schedule_name = self._schedule_name_from_schedule(self.schedule)

    def _schedule_name_from_schedule(self, schedule):
        if schedule == '00:00:20':
            return 'min_interval'
        return ("cinder_%(sched)s" %
                {'sched': schedule.replace(':', '_')})


class Replication(object):

    async_rates = (
        Rate(rpo=120, schedule='00:01:00'),
        Rate(rpo=300, schedule='00:02:00'),
        Rate(rpo=600, schedule='00:05:00'),
        Rate(rpo=1200, schedule='00:10:00'),
    )

    def __init__(self, proxy):
        self.proxy = proxy

    @staticmethod
    def get_schedule_from_rpo(rpo):
        schedule = [rate for rate in Replication.async_rates
                    if rate.rpo == rpo][0].schedule_name
        if schedule:
            LOG.debug('schedule %(sched)s: for rpo %(rpo)s',
                      {'sched': schedule, 'rpo': rpo})
        else:
            LOG.error('Failed to find schedule for rpo %(rpo)s',
                      {'rpo': rpo})
        return schedule

    @staticmethod
    def get_supported_rpo():
        return [rate.rpo for rate in Replication.async_rates]

    def get_recovery_mgr(self):
        # Recovery manager is set in derived classes
        raise NotImplementedError

    def get_remote_recovery_mgr(self):
        # Recovery manager is set in derived classes
        raise NotImplementedError

    def replication_create_mirror(self, resource, replication_info,
                                  target, pool):
        raise NotImplementedError

    @staticmethod
    def extract_replication_info_from_specs(specs):
        info = {'enabled': False, 'mode': None, 'rpo': 0}
        msg = ""
        if specs:
            LOG.debug('extract_replication_info_from_specs: specs %(specs)s',
                      {'specs': specs})

            info['enabled'] = (
                specs.get('replication_enabled', '').upper() in
                (u'TRUE', strings.METADATA_IS_TRUE) or
                specs.get('group_replication_enabled', '').upper() in
                (u'TRUE', strings.METADATA_IS_TRUE))

            replication_type = specs.get('replication_type', SYNC).lower()
            if replication_type in (u'sync', u'<is> sync'):
                info['mode'] = SYNC
            elif replication_type in (u'async', u'<is> async'):
                info['mode'] = ASYNC
            else:
                msg = (_("Unsupported replication mode %(mode)s")
                       % {'mode': replication_type})
                return None, msg
            info['rpo'] = int(specs.get('rpo', u'<is> 0')[5:])
            supported_rpos = Replication.get_supported_rpo()
            if info['rpo'] and info['rpo'] not in supported_rpos:
                msg = (_("Unsupported replication RPO %(rpo)s"),
                       {'rpo': info['rpo']})
                return None, msg

            LOG.debug('extract_replication_info_from_specs: info %(info)s',
                      {'info': info})
        return info, msg

    def failover(self, resource, failback):
        raise NotImplementedError

    def create_replication(self, resource_name, replication_info):
        LOG.debug('Replication::create_replication replication_info %(rep)s',
                  {'rep': replication_info})

        target, params = self.proxy._get_replication_target_params()
        LOG.info('Target %(target)s: %(params)s',
                 {'target': target, 'params': six.text_type(params)})

        try:
            pool = params['san_clustername']
        except Exception:
            msg = (_("Missing pool information for target '%(target)s'") %
                   {'target': target})
            LOG.error(msg)
            raise self.proxy.meta['exception'].VolumeBackendAPIException(
                data=msg)

        self.replication_create_mirror(resource_name, replication_info,
                                       target, pool)

    def delete_replication(self, resource_name, replication_info):
        LOG.debug('Replication::delete_replication replication_info %(rep)s',
                  {'rep': replication_info})

        recovery_mgr = self.get_recovery_mgr()

        try:
            recovery_mgr.deactivate_mirror(resource_id=resource_name)
        except Exception as e:
            details = self.proxy._get_code_and_status_or_message(e)
            msg = (_("Failed ending replication for %(resource)s: "
                     "'%(details)s'") % {'resource': resource_name,
                                         'details': details})
            LOG.error(msg)
            raise self.proxy.meta['exception'].VolumeBackendAPIException(
                data=msg)
        try:
            recovery_mgr.delete_mirror(resource_id=resource_name)
        except Exception as e:
            details = self.proxy._get_code_and_status_or_message(e)
            msg = (_("Failed deleting replica for %(resource)s: "
                     "'%(details)s'") % {'resource': resource_name,
                                         'details': details})
            LOG.error(msg)
            raise self.proxy.meta['exception'].VolumeBackendAPIException(
                data=msg)

    def _failover_resource(self, resource, recovery_mgr, failover_rep_mgr,
                           rep_type, failback):
        # check if mirror is defined and active
        LOG.debug('Check if mirroring is active on %(res)s',
                  {'res': resource['name']})
        try:
            active = recovery_mgr.is_mirror_active(
                resource_id=resource['name'])
        except Exception:
            active = False
        state = 'active' if active else 'inactive'
        LOG.debug('Mirroring is %(state)s', {'state': state})

        # In case of failback, mirroring must be active
        # In case of failover we attempt to move in any condition
        if failback and not active:
            msg = ("%(rep_type)s %(res)s: no active mirroring and can not "
                   "failback" % {'rep_type': rep_type,
                                 'res': resource['name']})
            LOG.error(msg)
            return False, msg

        try:
            if rep_type == 'cg':
                resource['name'] = self.proxy._cg_name_from_group(resource)
            recovery_mgr.switch_roles(resource_id=resource['name'])
            return True, None
        except Exception as e:
            # failed attempt to switch_roles from the master
            details = self.proxy._get_code_and_status_or_message(e)
            LOG.warning('Failed to perform switch_roles on'
                        ' %(res)s: %(err)s. '
                        'Continue to change_role',
                        {'res': resource['name'], 'err': details})
        try:
            # this is the ugly stage we come to brute force
            if failback:
                role = 'Slave'
            else:
                role = 'Master'
            LOG.warning('Attempt to change_role to %(role)s', {'role': role})
            failover_rep_mgr.change_role(resource_id=resource['name'],
                                         new_role=role)
            return True, None
        except m_errors.NoMirrorDefinedError as e:
            details = self.proxy._get_code_and_status_or_message(e)
            msg = ("%(rep_type)s %(res)s no replication defined: %(err)s" %
                   {'rep_type': rep_type, 'res': resource['name'],
                    'err': details})
            LOG.error(msg)
            return False, msg
        except Exception as e:
            details = self.proxy._get_code_and_status_or_message(e)
            msg = ('%(rep_type)s %(res)s change_role failed: %(err)s' %
                   {'rep_type': rep_type, 'res': resource['name'],
                    'err': details})
            LOG.error(msg)
            return False, msg


class VolumeReplication(Replication):

    def __init__(self, proxy):
        super(VolumeReplication, self).__init__(proxy)

    def get_recovery_mgr(self):
        return volume_recovery_manager.VolumeRecoveryManager(
            False, self.proxy.ibm_storage_cli)

    def get_remote_recovery_mgr(self):
        return volume_recovery_manager.VolumeRecoveryManager(
            True, self.proxy.ibm_storage_remote_cli)

    def replication_create_mirror(self, resource_name, replication_info,
                                  target, pool):
        LOG.debug('VolumeReplication::replication_create_mirror')

        schedule = None
        if replication_info['rpo']:
            schedule = Replication.get_schedule_from_rpo(
                replication_info['rpo'])
        try:
            recovery_mgr = self.get_recovery_mgr()
            recovery_mgr.create_mirror(
                resource_name=resource_name,
                target_name=target,
                mirror_type=replication_info['mode'],
                slave_resource_name=resource_name,
                create_slave='yes',
                remote_pool=pool,
                rpo=replication_info['rpo'],
                schedule=schedule,
                activate_mirror='yes')
        except errors.RemoteVolumeExists:
            # if volume exists (same ID), don't create slave
            # This only happens when vol is a part of a cg
            recovery_mgr.create_mirror(
                resource_name=resource_name,
                target_name=target,
                mirror_type=replication_info['mode'],
                slave_resource_name=resource_name,
                create_slave='no',
                remote_pool=pool,
                rpo=replication_info['rpo'],
                schedule=schedule,
                activate_mirror='yes')
        except errors.VolumeMasterError:
            LOG.debug('Volume %(vol)s has been already mirrored',
                      {'vol': resource_name})
        except Exception as e:
            details = self.proxy._get_code_and_status_or_message(e)
            msg = (_("Failed replication for %(resource)s: '%(details)s'") %
                   {'resource': resource_name, 'details': details})
            LOG.error(msg)
            raise self.proxy.meta['exception'].VolumeBackendAPIException(
                data=msg)

    def failover(self, resource, failback):
        """Failover a single volume.

        Attempts to failover a single volume
        Sequence:
        1. attempt to switch roles from master
        2. attempt to change role to master on secondary

        returns (success, failure_reason)
        """
        LOG.debug("VolumeReplication::failover %(vol)s",
                  {'vol': resource['name']})

        recovery_mgr = self.get_recovery_mgr()
        remote_recovery_mgr = self.get_remote_recovery_mgr()
        return self._failover_resource(resource, recovery_mgr,
                                       remote_recovery_mgr, 'vol', failback)


class GroupReplication(Replication):

    def __init__(self, proxy):
        super(GroupReplication, self).__init__(proxy)

    def get_recovery_mgr(self):
        return cg_recovery_manager.CGRecoveryManager(
            False, self.proxy.ibm_storage_cli)

    def get_remote_recovery_mgr(self):
        return cg_recovery_manager.CGRecoveryManager(
            True, self.proxy.ibm_storage_remote_cli)

    def replication_create_mirror(self, resource_name, replication_info,
                                  target, pool):
        LOG.debug('GroupReplication::replication_create_mirror')
        schedule = None
        if replication_info['rpo']:
            schedule = Replication.get_schedule_from_rpo(
                replication_info['rpo'])
        try:
            recovery_mgr = self.get_recovery_mgr()
            recovery_mgr.create_mirror(
                resource_name=resource_name,
                target_name=target,
                mirror_type=replication_info['mode'],
                slave_resource_name=resource_name,
                rpo=replication_info['rpo'],
                schedule=schedule,
                activate_mirror='yes')
        except Exception as e:
            details = self.proxy._get_code_and_status_or_message(e)
            msg = (_("Failed replication for %(resource)s: '%(details)s'"),
                   {'resource': resource_name, 'details': details})
            LOG.error(msg)
            raise self.proxy.meta['exception'].VolumeBackendAPIException(
                data=msg)

    def failover(self, resource, failback):
        LOG.debug("GroupReplication::failover %(cg)s",
                  {'cg': resource['name']})

        recovery_mgr = self.get_recovery_mgr()
        remote_recovery_mgr = self.get_remote_recovery_mgr()

        return self._failover_resource(resource, recovery_mgr,
                                       remote_recovery_mgr, 'cg', failback)
