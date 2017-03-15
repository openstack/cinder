#  Copyright (c) 2016 IBM Corporation
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
import datetime
import six
import socket

from oslo_log import log as logging
from oslo_utils import importutils

pyxcli = importutils.try_import("pyxcli")
if pyxcli:
    from pyxcli import client
    from pyxcli import errors
    from pyxcli.events import events
    from pyxcli.mirroring import errors as m_errors
    from pyxcli.mirroring import volume_recovery_manager
    from pyxcli import transports

from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.i18n import _, _LE, _LW, _LI
from cinder import context
from cinder import objects
from cinder import volume as c_volume
import cinder.volume.drivers.ibm.ibm_storage as storage
from cinder.volume.drivers.ibm.ibm_storage import certificate
from cinder.volume.drivers.ibm.ibm_storage import cryptish
from cinder.volume.drivers.ibm.ibm_storage import proxy
from cinder.volume.drivers.ibm.ibm_storage import strings

OPENSTACK_PRODUCT_NAME = "OpenStack"
PERF_CLASS_NAME_PREFIX = "cinder-qos"
HOST_BAD_NAME = "HOST_BAD_NAME"
VOLUME_IS_MAPPED = "VOLUME_IS_MAPPED"
CONNECTIONS_PER_MODULE = 2
MIN_LUNID = 1
MAX_LUNID = 511
SYNC = 'sync'
ASYNC = 'async'
SYNC_TIMEOUT = 300
SYNCHED_STATES = ['synchronized', 'rpo ok']

LOG = logging.getLogger(__name__)

# performance class strings - used in exceptions
PERF_CLASS_ERROR = _("Unable to create or get performance class: %(details)s")
PERF_CLASS_ADD_ERROR = _("Unable to add volume to performance class: "
                         "%(details)s")
PERF_CLASS_VALUES_ERROR = _("A performance class with the same name but "
                            "different values exists:  %(details)s")

# setup strings - used in exceptions
SETUP_BASE_ERROR = _("Unable to connect to %(title)s: %(details)s")
SETUP_INVALID_ADDRESS = _("Unable to connect to the storage system "
                          "at '%(address)s', invalid address.")

# create volume strings - used in exceptions
CREATE_VOLUME_BASE_ERROR = _("Unable to create volume: %(details)s")

# initialize connection strings - used in exceptions
CONNECTIVITY_FC_NO_TARGETS = _("Unable to detect FC connection between the "
                               "compute host and the storage, please ensure "
                               "that zoning is set up correctly.")

# terminate connection strings - used in logging
TERMINATE_CONNECTION_BASE_ERROR = _LE("Unable to terminate the connection "
                                      "for volume '%(volume)s': %(error)s.")
TERMINATE_CONNECTION_HOST_ERROR = _LE("Terminate connection for volume "
                                      "'%(volume)s': for volume '%(volume)s': "
                                      "%(host)s %(error)s.")

# delete volume strings - used in logging
DELETE_VOLUME_BASE_ERROR = _LE("Unable to delete volume '%(volume)s': "
                               "%(error)s.")

# manage volume strings - used in exceptions
MANAGE_VOLUME_BASE_ERROR = _("Unable to manage the volume '%(volume)s': "
                             "%(error)s.")


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


class XIVProxy(proxy.IBMStorageProxy):
    """Proxy between the Cinder Volume and Spectrum Accelerate Storage.

    Supports IBM XIV, Spectrum Accelerate, A9000, A9000R
    """
    async_rates = (
        Rate(rpo=30, schedule='00:00:20'),
        Rate(rpo=60, schedule='00:00:20'),
        Rate(rpo=300, schedule='00:02:00'),
        Rate(rpo=600, schedule='00:05:00'),
        Rate(rpo=3600, schedule='00:15:00'),
        Rate(rpo=7200, schedule='00:30:00'),
        Rate(rpo=14400, schedule='01:00:00'),
        Rate(rpo=43200, schedule='03:00:00'),
    )

    def __init__(self, storage_info, logger, exception,
                 driver=None, active_backend_id=None):
        """Initialize Proxy."""
        if not active_backend_id:
            active_backend_id = strings.PRIMARY_BACKEND_ID
        proxy.IBMStorageProxy.__init__(
            self, storage_info, logger, exception, driver, active_backend_id)
        LOG.info(_LI("__init__: storage_info: %(keys)s"),
                 {'keys': self.storage_info})
        if active_backend_id:
            LOG.info(_LI("__init__: active_backend_id: %(id)s"),
                     {'id': active_backend_id})
        self.ibm_storage_cli = None
        self.meta['ibm_storage_portal'] = None
        self.meta['ibm_storage_iqn'] = None
        self.ibm_storage_remote_cli = None
        self.meta['ibm_storage_fc_targets'] = []
        self.meta['storage_version'] = None
        self.system_id = None

    @proxy._trace_time
    def setup(self, context):
        """Connect ssl client."""
        LOG.info(_LI("Setting up connection to %(title)s...\n"
                 "Active backend_id: '%(id)s'."),
                 {'title': strings.TITLE,
                  'id': self.active_backend_id})

        self.ibm_storage_cli = self._init_xcli(self.active_backend_id)

        if self._get_connection_type() == storage.XIV_CONNECTION_TYPE_ISCSI:
            self.meta['ibm_storage_iqn'] = (
                self._call_xiv_xcli("config_get").
                as_dict('name')['iscsi_name'].value)

            portals = storage.get_online_iscsi_ports(self.ibm_storage_cli)
            if len(portals) == 0:
                msg = (SETUP_BASE_ERROR,
                       {'title': strings.TITLE,
                        'details': "No iSCSI portals available on the Storage."
                        })
                raise self._get_exception()(
                    _("%(prefix)s %(portals)s") %
                    {'prefix': storage.XIV_LOG_PREFIX,
                     'portals': msg})

            self.meta['ibm_storage_portal'] = "%s:3260" % portals[:1][0]

        remote_id = self._get_secondary_backend_id()
        if remote_id:
            self.ibm_storage_remote_cli = self._init_xcli(remote_id)
        self._event_service_start()
        self._update_stats()
        self._update_system_id()
        if remote_id:
            self._update_active_schedule_objects()
            self._update_remote_schedule_objects()
        LOG.info(_LI("Connection to the IBM storage "
                     "system established successfully."))

    def _get_schedule_from_rpo(self, rpo):
        return [rate for rate in self.async_rates
                if rate.rpo == rpo][0].schedule_name

    def _get_supported_rpo(self):
        return [rate.rpo for rate in self.async_rates]

    @proxy._trace_time
    def _update_active_schedule_objects(self):
        """Set schedule objects on active backend.

        The value 00:20:00 is covered in XIV by a pre-defined object named
        min_interval.
        """
        schedules = self._call_xiv_xcli("schedule_list").as_dict('name')
        for rate in self.async_rates:
            if rate.schedule == '00:00:20':
                continue
            name = rate.schedule_name
            schedule = schedules.get(name, None)
            if schedule:
                LOG.debug('Exists on local backend %(sch)s', {'sch': name})
                interval = schedule.get('interval', '')
                if interval != rate.schedule:
                    msg = (_("Schedule %(sch)s exists with incorrect "
                             "value %(int)s")
                           % {'sch': name, 'int': interval})
                    LOG.error(msg)
                    raise self.meta['exception'].VolumeBackendAPIException(
                        data=msg)
            else:
                LOG.debug('create %(sch)s', {'sch': name})
                self._call_xiv_xcli("schedule_create",
                                    schedule=name, type='interval',
                                    interval=rate.schedule)

    @proxy._trace_time
    def _update_remote_schedule_objects(self):
        """Set schedule objects on remote backend.

        The value 00:20:00 is covered in XIV by a pre-defined object named
        min_interval.
        """
        schedules = self._call_remote_xiv_xcli("schedule_list").as_dict('name')
        for rate in self.async_rates:
            if rate.schedule == '00:00:20':
                continue
            name = rate.schedule_name
            if schedules.get(name, None):
                LOG.debug('Exists on remote backend %(sch)s', {'sch': name})
                interval = schedules.get(name, None)['interval']
                if interval != rate.schedule:
                    msg = (_("Schedule %(sch)s exists with incorrect "
                             "value %(int)s")
                           % {'sch': name, 'int': interval})
                    LOG.error(msg)
                    raise self.meta['exception'].VolumeBackendAPIException(
                        data=msg)
            else:
                self._call_remote_xiv_xcli("schedule_create",
                                           schedule=name, type='interval',
                                           interval=rate.schedule)

    def _get_extra_specs(self, type_id):
        """get extra specs to match the type_id

        type_id can derive from volume or from consistency_group
        """
        if type_id is None:
            return {}
        return c_volume.volume_types.get_volume_type_extra_specs(type_id)

    def _update_system_id(self):
        if self.system_id:
            return
        local_ibm_storage_cli = self._init_xcli(strings.PRIMARY_BACKEND_ID)
        if not local_ibm_storage_cli:
            LOG.error(_LE('Failed to connect to main backend. '
                          'Cannot retrieve main backend system_id'))
            return
        system_id = local_ibm_storage_cli.cmd.config_get().as_dict(
            'name')['system_id'].value
        LOG.debug('system_id: %(id)s', {'id': system_id})
        self.system_id = system_id

    @proxy._trace_time
    def _get_qos_specs(self, type_id):
        """Gets the qos specs from cinder."""
        ctxt = context.get_admin_context()
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        if not volume_type:
            return None
        qos_specs_id = volume_type.get('qos_specs_id', None)
        if qos_specs_id:
            return qos_specs.get_qos_specs(
                ctxt, qos_specs_id).get('specs', None)
        return None

    @proxy._trace_time
    def _qos_create_kwargs_for_xcli(self, specs):
        args = {}
        for key in specs:
            if key == 'bw':
                args['max_bw_rate'] = specs[key]
            if key == 'iops':
                args['max_io_rate'] = specs[key]
        return args

    def _qos_remove_vol(self, volume):
        try:
            self._call_xiv_xcli("perf_class_remove_vol",
                                vol=volume['name'])

        except errors.VolumeNotConnectedToPerfClassError as e:
            details = self._get_code_and_status_or_message(e)
            LOG.debug(details)
            return True
        except errors.XCLIError as e:
            details = self._get_code_and_status_or_message(e)
            msg_data = (_("Unable to add volume to performance "
                          "class: %(details)s") % {'details': details})
            LOG.error(msg_data)
            raise self.meta['exception'].VolumeBackendAPIException(
                data=msg_data)
        return True

    def _qos_add_vol(self, volume, perf_class_name):
        try:
            self._call_xiv_xcli("perf_class_add_vol",
                                vol=volume['name'],
                                perf_class=perf_class_name)
        except errors.VolumeAlreadyInPerfClassError as e:
            details = self._get_code_and_status_or_message(e)
            LOG.debug(details)
            return True
        except errors.XCLIError as e:
            details = self._get_code_and_status_or_message(e)
            msg = PERF_CLASS_ADD_ERROR % {'details': details}
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)
        return True

    def _check_perf_class_on_backend(self, specs):
        """Checking if class exists on backend. if not - create it."""
        perf_class_name = PERF_CLASS_NAME_PREFIX
        if specs is None or specs == {}:
            return ''

        for key, value in specs.items():
            perf_class_name += '_' + key + '_' + value

        try:
            classes_list = self._call_xiv_xcli("perf_class_list",
                                               perf_class=perf_class_name
                                               ).as_list

            # list is not empty, check if class has the right values
            for perf_class in classes_list:
                if (not perf_class.max_iops == specs.get('iops', '0') or
                        not perf_class.max_bw == specs.get('bw', '0')):
                    raise self.meta['exception'].VolumeBackendAPIException(
                        data=PERF_CLASS_VALUES_ERROR %
                        {'details': perf_class_name})
        except errors.XCLIError as e:
            details = self._get_code_and_status_or_message(e)
            msg = PERF_CLASS_ERROR % {'details': details}
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

            # class does not exist, create it
        if not classes_list:
            self._create_qos_class(perf_class_name, specs)
        return perf_class_name

    def _create_qos_class(self, perf_class_name, specs):
        """Create the qos class on the backend."""
        try:
            self._call_xiv_xcli("perf_class_create",
                                perf_class=perf_class_name)

        except errors.XCLIError as e:
            details = self._get_code_and_status_or_message(e)
            msg = PERF_CLASS_ERROR % {'details': details}
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

        try:
            args = self._qos_create_kwargs_for_xcli(specs)
            self._call_xiv_xcli("perf_class_set_rate",
                                perf_class=perf_class_name,
                                **args)
            return perf_class_name
        except errors.XCLIError as e:
            details = self._get_code_and_status_or_message(e)
            # attempt to clean up
            self._call_xiv_xcli("perf_class_delete",
                                perf_class=perf_class_name)
            msg = PERF_CLASS_ERROR % {'details': details}
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

    def _qos_specs_from_volume(self, volume):
        """Returns qos_specs of volume.

        checks if there is a type on the volume
        if so, checks if it has been associated with a qos class
        returns the name of that class
        """
        type_id = volume.get('volume_type_id', None)
        if not type_id:
            return None
        return self._get_qos_specs(type_id)

    def _get_replication_info(self, specs):
        info = {'enabled': False, 'mode': None, 'rpo': 0}
        if specs:
            LOG.debug('_get_replication_info: specs %(specs)s',
                      {'specs': specs})
            info['enabled'] = (
                specs.get('replication_enabled', '').upper() in
                (u'TRUE', strings.METADATA_IS_TRUE))
            replication_type = specs.get('replication_type', SYNC).lower()
            if replication_type in (u'sync', u'<is> sync'):
                info['mode'] = SYNC
            elif replication_type in (u'async', u'<is> async'):
                info['mode'] = ASYNC
            else:
                msg = (_("Unsupported replication mode %(mode)s"),
                       {'mode': replication_type})
                LOG.error(msg)
                raise self._get_exception()(message=msg)
            info['rpo'] = int(specs.get('rpo', u'<is> 0')[5:])
            if info['rpo'] and info['rpo'] not in self._get_supported_rpo():
                msg = (_("Unsupported replication RPO %(rpo)s"),
                       {'rpo': info['rpo']})
                LOG.error(msg)
                raise self._get_exception()(message=msg)
            LOG.debug('_get_replication_info: info %(info)s', {'info': info})
        return info

    @proxy._trace_time
    def _create_volume(self, volume):
        """Internal implementation to create a volume."""
        size = storage.gigabytes_to_blocks(float(volume['size']))
        pool = self.storage_info[storage.FLAG_KEYS['storage_pool']]
        try:
            self._call_xiv_xcli(
                "vol_create", vol=volume['name'], size_blocks=size, pool=pool)
        except errors.SystemOutOfSpaceError:
            msg = _("Unable to create volume: System is out of space.")
            LOG.error(msg)
            raise self._get_exception()(msg)
        except errors.PoolOutOfSpaceError:
            msg = (_("Unable to create volume: pool '%(pool)s' is "
                     "out of space."),
                   {'pool': pool})
            LOG.error(msg)
            raise self._get_exception()(msg)
        except errors.XCLIError as e:
            details = self._get_code_and_status_or_message(e)
            msg = (CREATE_VOLUME_BASE_ERROR, {'details': details})
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

    @proxy._trace_time
    def create_volume(self, volume):
        """Creates a volume."""
        # read CG information
        cg = self._cg_name_from_volume(volume)
        # read replication information
        specs = self._get_extra_specs(volume.get('volume_type_id', None))
        replication_info = self._get_replication_info(specs)

        if cg and replication_info['enabled']:
            # An unsupported illegal configuration
            msg = _("Unable to create volume: "
                    "Replication of consistency group is not supported")
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

        self._create_volume(volume)
        return self.handle_created_vol_properties(cg,
                                                  replication_info,
                                                  volume)

    def handle_created_vol_properties(self, cg, replication_info, volume):
        volume_update = {}
        if cg:
            volume_update['consistencygroup_id'] = (
                volume.get('consistencygroup_id', None))
            try:
                self._call_xiv_xcli(
                    "cg_add_vol", vol=volume['name'], cg=cg)
            except errors.XCLIError as e:
                details = self._get_code_and_status_or_message(e)
                self._silent_delete_volume(volume=volume)
                msg = (CREATE_VOLUME_BASE_ERROR, {'details': details})
                LOG.error(msg)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)

        perf_class_name = None
        specs = self._qos_specs_from_volume(volume)
        if specs:
            try:
                perf_class_name = self._check_perf_class_on_backend(specs)
                if perf_class_name:
                    self._call_xiv_xcli("perf_class_add_vol",
                                        vol=volume['name'],
                                        perf_class=perf_class_name)
            except errors.XCLIError as e:
                details = self._get_code_and_status_or_message(e)
                if cg:
                    self._silent_delete_volume_from_cg(volume, cg)
                self._silent_delete_volume(volume=volume)
                msg = PERF_CLASS_ADD_ERROR % {'details': details}
                LOG.error(msg)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)

        LOG.debug('checking replication_info %(rep)s',
                  {'rep': replication_info})
        volume_update['replication_status'] = 'disabled'
        if replication_info['enabled']:
            try:
                self._replication_create(volume, replication_info)
            except Exception as e:
                details = self._get_code_and_status_or_message(e)
                msg = (_LE('Failed _replication_create for '
                           'volume %(vol)s: %(err)s'),
                       {'vol': volume['name'], 'err': details})
                LOG.error(msg)
                if cg:
                    self._silent_delete_volume_from_cg(volume, cg)
                self._silent_delete_volume(volume=volume)
                raise
            volume_update['replication_status'] = 'enabled'

        return volume_update

    def _get_replication_target_params(self):
        LOG.debug('_get_replication_target_params.')
        targets = self._get_targets()
        if not targets:
            msg = _("No targets available for replication")
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)
        no_of_targets = len(targets)
        if no_of_targets > 1:
            msg = _("Too many targets configured. Only one is supported")
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

        LOG.debug('_get_replication_target_params selecting target...')
        target = self._get_target()
        if not target:
            msg = _("No targets available for replication.")
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)
        params = self._get_target_params(target)
        if not params:
            msg = (_("Missing target information for target '%(target)s'"),
                   {'target': target})
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)
        return target, params

    def _replication_create(self, volume, replication_info):
        LOG.debug('_replication_create replication_info %(rep)s',
                  {'rep': replication_info})

        target, params = self._get_replication_target_params()
        LOG.info(_LI('Target %(target)s: %(params)s'),
                 {'target': target, 'params': six.text_type(params)})

        try:
            pool = params['san_clustername']
        except Exception:
            msg = (_("Missing pool information for target '%(target)s'"),
                   {'target': target})
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

        volume_replication_mgr = volume_recovery_manager.VolumeRecoveryManager(
            False, self.ibm_storage_cli)

        self._replication_create_mirror(volume, replication_info,
                                        target, pool, volume_replication_mgr)

    def _replication_create_mirror(self, volume, replication_info,
                                   target, pool, volume_replication_mgr):
        LOG.debug('_replication_create_mirror')
        schedule = None
        if replication_info['rpo']:
            schedule = self._get_schedule_from_rpo(replication_info['rpo'])
            if schedule:
                LOG.debug('schedule %(sched)s: for rpo %(rpo)s',
                          {'sched': schedule, 'rpo': replication_info['rpo']})
            else:
                LOG.error(_LE('Failed to find schedule for rpo %(rpo)s'),
                          {'rpo': replication_info['rpo']})
                # will fail in the next step
        try:
            volume_replication_mgr.create_mirror(
                resource_name=volume['name'],
                target_name=target,
                mirror_type=replication_info['mode'],
                slave_resource_name=volume['name'],
                create_slave='yes',
                remote_pool=pool,
                rpo=replication_info['rpo'],
                schedule=schedule,
                activate_mirror='yes')
        # TBD - what exceptions will we get here?
        except Exception as e:
            details = self._get_code_and_status_or_message(e)
            msg = (_("Failed replication for %(vol)s: '%(details)s'"),
                   {'vol': volume['name'], 'details': details})
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

    def _replication_delete(self, volume, replication_info):
        LOG.debug('_replication_delete replication_info %(rep)s',
                  {'rep': replication_info})
        targets = self._get_targets()
        if not targets:
            LOG.debug('No targets defined for replication')

        volume_replication_mgr = volume_recovery_manager.VolumeRecoveryManager(
            False, self.ibm_storage_cli)
        try:
            volume_replication_mgr.deactivate_mirror(
                resource_id=volume['name'])
        except Exception as e:
            details = self._get_code_and_status_or_message(e)
            msg = (_("Failed ending replication for %(vol)s: '%(details)s'"),
                   {'vol': volume['name'], 'details': details})
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

        try:
            volume_replication_mgr.delete_mirror(
                resource_id=volume['name'])
        except Exception as e:
            details = self._get_code_and_status_or_message(e)
            msg = (_("Failed deleting replica for %(vol)s: '%(details)s'"),
                   {'vol': volume['name'], 'details': details})
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)

    def _delete_volume(self, vol_name):
        """Deletes a volume on the Storage."""
        LOG.debug("_delete_volume: %(volume)s",
                  {'volume': vol_name})
        try:
            self._call_xiv_xcli("vol_delete", vol=vol_name)
        except errors.VolumeBadNameError:
            # Don't throw error here, allow the cinder volume manager
            # to set the volume as deleted if it's not available
            # on the XIV box
            LOG.info(_LI("Volume '%(volume)s' not found on storage"),
                     {'volume': vol_name})

    def _silent_delete_volume(self, volume):
        """Silently delete a volume.

        silently delete a volume in case of an immediate failure
        within a function that created it.
        """
        try:
            self._delete_volume(vol_name=volume['name'])
        except errors.XCLIError as e:
            error = self._get_code_and_status_or_message(e)
            LOG.error(DELETE_VOLUME_BASE_ERROR,
                      {'volume': volume['name'], 'error': error})

    def _silent_delete_volume_from_cg(self, volume, cgname):
        """Silently delete a volume from CG.

        silently delete a volume in case of an immediate failure
        within a function that created it.
        """
        try:
            self._call_xiv_xcli(
                "cg_remove_vol", vol=volume['name'])
        except errors.XCLIError as e:
            LOG.error(_LE("Failed removing volume %(vol)s from "
                          "consistency group %(cg)s: %(err)s"),
                      {'vol': volume['name'],
                       'cg': cgname,
                       'err': self._get_code_and_status_or_message(e)})
        self._silent_delete_volume(volume=volume)

    @proxy._trace_time
    def delete_volume(self, volume):
        """Deletes a volume on the Storage machine."""
        LOG.debug("delete_volume: %(volume)s",
                  {'volume': volume['name']})
        # read replication information
        specs = self._get_extra_specs(volume.get('volume_type_id', None))
        replication_info = self._get_replication_info(specs)
        if replication_info['enabled']:
            try:
                self._replication_delete(volume, replication_info)
            except Exception as e:
                error = self._get_code_and_status_or_message(e)
                LOG.error(DELETE_VOLUME_BASE_ERROR,
                          {'volume': volume['name'], 'error': error})
                # continue even if failed

            # attempt to delete volume at target
            target = None
            try:
                target, params = self._get_replication_target_params()
                LOG.info(_LI('Target %(target)s: %(params)s'),
                         {'target': target, 'params': six.text_type(params)})
            except Exception as e:
                LOG.error(_LE("Unable to delete replicated volume "
                              "'%(volume)s': %(error)s."),
                          {'error': self._get_code_and_status_or_message(e),
                           'volume': volume['name']})
            if target:
                try:
                    self._call_remote_xiv_xcli(
                        "vol_delete", vol=volume['name'])
                except errors.XCLIError as e:
                    LOG.error(
                        _LE("Unable to delete replicated volume "
                            "'%(volume)s': %(error)s."),
                        {'error': self._get_code_and_status_or_message(e),
                         'volume': volume['name']})

        try:
            self._delete_volume(volume['name'])
        except errors.XCLIError as e:
            LOG.error(DELETE_VOLUME_BASE_ERROR,
                      {'volume': volume['name'],
                       'error': self._get_code_and_status_or_message(e)})

    @proxy._trace_time
    def initialize_connection(self, volume, connector):
        """Initialize connection to instance.

        Maps the created volume to the nova volume node,
        and returns the iSCSI target to be used in the instance
        """

        connection_type = self._get_connection_type()
        LOG.debug("initialize_connection: %(volume)s %(connector)s"
                  " connection_type: %(connection_type)s",
                  {'volume': volume['name'], 'connector': connector,
                   'connection_type': connection_type})

        # This call does all the work..
        fc_targets, host = self._get_host_and_fc_targets(
            volume, connector)

        lun_id = self._vol_map_and_get_lun_id(
            volume, connector, host)

        meta = {
            'driver_volume_type': connection_type,
            'data': {
                'target_discovered': True,
                'target_lun': lun_id,
                'volume_id': volume['id'],
            },
        }
        if connection_type == storage.XIV_CONNECTION_TYPE_ISCSI:
            meta['data']['target_portal'] = self.meta['ibm_storage_portal']
            meta['data']['target_iqn'] = self.meta['ibm_storage_iqn']
            meta['data']['provider_location'] = "%s,1 %s %s" % (
                self.meta['ibm_storage_portal'],
                self.meta['ibm_storage_iqn'], lun_id)

            chap_type = self._get_chap_type()
            LOG.debug("initialize_connection: %(volume)s."
                      " chap_type:%(chap_type)s",
                      {'volume': volume['name'],
                       'chap_type': chap_type})

            if chap_type == storage.CHAP_ENABLED:
                chap = self._create_chap(host)
                meta['data']['auth_method'] = 'CHAP'
                meta['data']['auth_username'] = chap[0]
                meta['data']['auth_password'] = chap[1]
        else:
            all_storage_wwpns = self._get_fc_targets(None)
            meta['data']['all_storage_wwpns'] = all_storage_wwpns
            modules = set()
            for wwpn in fc_targets:
                modules.add(wwpn[-2])
            meta['data']['recommended_connections'] = (
                len(modules) * CONNECTIONS_PER_MODULE)
            meta['data']['target_wwn'] = fc_targets
            if fc_targets == []:
                fc_targets = all_storage_wwpns
            meta['data']['initiator_target_map'] = (
                self._build_initiator_target_map(fc_targets, connector))

        LOG.debug(six.text_type(meta))
        return meta

    @proxy._trace_time
    def terminate_connection(self, volume, connector):
        """Terminate connection.

        Unmaps volume. If this is the last connection from the host, undefines
        the host from the storage.
        """

        LOG.debug("terminate_connection: %(volume)s %(connector)s",
                  {'volume': volume['name'], 'connector': connector})

        host = self._get_host(connector)
        if host is None:
            LOG.error(TERMINATE_CONNECTION_BASE_ERROR,
                      {'volume': volume['name'],
                       'error': "Host not found."})
            return

        fc_targets = {}
        if self._get_connection_type() == storage.XIV_CONNECTION_TYPE_FC:
            fc_targets = self._get_fc_targets(host)

        try:
            self._call_xiv_xcli(
                "unmap_vol",
                vol=volume['name'],
                host=host.get('name'))
        except errors.VolumeBadNameError:
            LOG.error(TERMINATE_CONNECTION_BASE_ERROR,
                      {'volume': volume['name'],
                       'error': "Volume not found."})
        except errors.XCLIError as err:
            details = self._get_code_and_status_or_message(err)
            LOG.error(TERMINATE_CONNECTION_BASE_ERROR,
                      {'volume': volume['name'],
                       'error': details})

        # check if there are still mapped volumes or we can
        # remove this host
        host_mappings = []
        try:
            host_mappings = self._call_xiv_xcli(
                "mapping_list",
                host=host.get('name')).as_list
            if len(host_mappings) == 0:
                LOG.info(_LI("Terminate connection for volume '%(volume)s': "
                             "%(host)s %(info)s."),
                         {'volume': volume['name'],
                          'host': host.get('name'),
                          'info': "will be deleted"})
                if not self._is_iscsi():
                    # The following meta data is provided so that zoning can
                    # be cleared

                    meta = {
                        'driver_volume_type': self._get_connection_type(),
                        'data': {'volume_id': volume['id'], },
                    }
                    meta['data']['target_wwn'] = fc_targets
                    meta['data']['initiator_target_map'] = (
                        self._build_initiator_target_map(fc_targets,
                                                         connector))
                self._call_xiv_xcli("host_delete", host=host.get('name'))
                if not self._is_iscsi():
                    return meta
                return None
            else:
                LOG.debug(("Host '%(host)s' has additional mapped "
                           "volumes %(mappings)s"),
                          {'host': host.get('name'),
                           'mappings': host_mappings})

        except errors.HostBadNameError:
            LOG.error(TERMINATE_CONNECTION_HOST_ERROR,
                      {'volume': volume['name'],
                       'host': host.get('name'),
                       'error': "Host not found."})
        except errors.XCLIError as err:
            details = self._get_code_and_status_or_message(err)
            LOG.error(TERMINATE_CONNECTION_HOST_ERROR,
                      {'volume': volume['name'],
                       'host': host.get('name'),
                       'error': details})

    def _create_volume_from_snapshot(self, volume,
                                     snapshot_name, snapshot_size):
        """Create volume from snapshot internal implementation.

        used for regular snapshot and cgsnapshot
        """
        LOG.debug("_create_volume_from_snapshot: %(volume)s from %(name)s",
                  {'volume': volume['name'], 'name': snapshot_name})

        # TODO(alonma): Refactor common validation
        volume_size = float(volume['size'])
        if volume_size < snapshot_size:
            error = (_("Volume size (%(vol_size)sGB) cannot be smaller than "
                       "the snapshot size (%(snap_size)sGB).."),
                     {'vol_size': volume_size,
                      'snap_size': snapshot_size})
            LOG.error(error)
            raise self._get_exception()(error)
        self.create_volume(volume)
        try:
            self._call_xiv_xcli(
                "vol_copy", vol_src=snapshot_name, vol_trg=volume['name'])
        except errors.XCLIError as e:
            error = (_("Fatal error in copying volume: %(details)s"),
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            self._silent_delete_volume(volume)
            raise self._get_exception()(error)
        # A side effect of vol_copy is the resizing of the destination volume
        # to the size of the source volume. If the size is different we need
        # to get it back to the desired size
        if snapshot_size == volume_size:
            return
        size = storage.gigabytes_to_blocks(volume_size)
        try:
            self._call_xiv_xcli(
                "vol_resize", vol=volume['name'], size_blocks=size)
        except errors.XCLIError as e:
            error = (_("Fatal error in resize volume: %(details)s"),
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            self._silent_delete_volume(volume)
            raise self._get_exception()(error)

    @proxy._trace_time
    def create_volume_from_snapshot(self, volume, snapshot):
        """create volume from snapshot."""

        snapshot_size = float(snapshot['volume_size'])
        snapshot_name = snapshot['name']
        self._create_volume_from_snapshot(
            volume, snapshot_name, snapshot_size)

    @proxy._trace_time
    def create_snapshot(self, snapshot):
        """create snapshot."""

        try:
            self._call_xiv_xcli(
                "snapshot_create", vol=snapshot['volume_name'],
                name=snapshot['name'])
        except errors.XCLIError as e:
            error = (_("Fatal error in snapshot_create: %(details)s"),
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

    @proxy._trace_time
    def delete_snapshot(self, snapshot):
        """delete snapshot."""

        try:
            self._call_xiv_xcli(
                "snapshot_delete", snapshot=snapshot['name'])
        except errors.XCLIError as e:
            error = (_("Fatal error in snapshot_delete: %(details)s"),
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

    @proxy._trace_time
    def extend_volume(self, volume, new_size):
        """Resize volume."""
        volume_size = float(volume['size'])
        wanted_size = float(new_size)
        if wanted_size == volume_size:
            return
        shrink = 'yes' if wanted_size < volume_size else 'no'
        size = storage.gigabytes_to_blocks(wanted_size)
        try:
            self._call_xiv_xcli(
                "vol_resize", vol=volume['name'],
                size_blocks=size, shrink_volume=shrink)
        except errors.XCLIError as e:
            error = (_("Fatal error in vol_resize: %(details)s"),
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

    @proxy._trace_time
    def migrate_volume(self, context, volume, host):
        """Migrate volume to another backend.

        Optimize the migration if the destination is on the same server.

        If the specified host is another back-end on the same server, and
        the volume is not attached, we can do the migration locally without
        going through iSCSI.

        Storage-assisted migration...
        """

        false_ret = (False, None)
        if 'location_info' not in host['capabilities']:
            return false_ret
        info = host['capabilities']['location_info']
        try:
            dest, dest_host, dest_pool = info.split(':')
        except ValueError:
            return false_ret
        volume_host = volume.host.split('_')[1]
        if dest != strings.XIV_BACKEND_PREFIX or dest_host != volume_host:
            return false_ret

        if volume.attach_status == 'attached':
            LOG.info(_LI("Storage-assisted volume migration: Volume "
                         "%(volume)s is attached"),
                     {'volume': volume.id})

        try:
            self._call_xiv_xcli(
                "vol_move", vol=volume.name,
                pool=dest_pool)
        except errors.XCLIError as e:
            error = (_("Fatal error in vol_move: %(details)s"),
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

        return (True, None)

    @proxy._trace_time
    def manage_volume(self, volume, reference):
        """Brings an existing backend storage object under Cinder management.

        reference value is passed straight from the get_volume_list helper
        function. it is up to the driver how this should be interpreted.
        It should be sufficient to identify a storage object that the driver
        should somehow associate with the newly-created cinder volume
        structure.
        There are two ways to do this:

        1. Rename the backend storage object so that it matches the,
           volume['name'] which is how drivers traditionally map between a
           cinder volume and the associated backend storage object.

        2. Place some metadata on the volume, or somewhere in the backend, that
           allows other driver requests (e.g. delete, clone, attach, detach...)
           to locate the backend storage object when required.

        If the reference doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        The volume may have a volume_type, and the driver can inspect that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch, specifying a reason for the failure.
        """

        existing_volume = reference['source-name']
        LOG.debug("manage_volume: %(volume)s", {'volume': existing_volume})
        # check that volume exists
        try:
            volumes = self._call_xiv_xcli(
                "vol_list", vol=existing_volume).as_list
        except errors.XCLIError as e:
            error = (MANAGE_VOLUME_BASE_ERROR,
                     {'volume': existing_volume,
                      'error': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

        if len(volumes) != 1:
            error = (MANAGE_VOLUME_BASE_ERROR,
                     {'volume': existing_volume,
                      'error': 'Volume does not exist'})
            LOG.error(error)
            raise self._get_exception()(error)

        volume['size'] = float(volumes[0]['size'])

        # option 1:
        # rename volume to volume['name']
        try:
            self._call_xiv_xcli(
                "vol_rename",
                vol=existing_volume,
                new_name=volume['name'])
        except errors.XCLIError as e:
            error = (MANAGE_VOLUME_BASE_ERROR,
                     {'volume': existing_volume,
                      'error': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

        # option 2:
        # return volume name as admin metadata
        # update the admin metadata DB

        # Need to do the ~same in create data. use the metadata instead of the
        # volume name

        return {}

    @proxy._trace_time
    def manage_volume_get_size(self, volume, reference):
        """Return size of volume to be managed by manage_volume.

        When calculating the size, round up to the next GB.
        """
        existing_volume = reference['source-name']

        # check that volume exists
        try:
            volumes = self._call_xiv_xcli(
                "vol_list", vol=existing_volume).as_list
        except errors.XCLIError as e:
            error = (_("Fatal error in vol_list: %(details)s"),
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

        if len(volumes) != 1:
            error = (_("Volume %(volume)s is not available on storage") %
                     {'volume': existing_volume})
            LOG.error(error)
            raise self._get_exception()(error)

        return float(volumes[0]['size'])

    @proxy._trace_time
    def unmanage_volume(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.
        """
        pass

    @proxy._trace_time
    def get_replication_status(self, context, volume):
        """Return replication status."""
        pass

    def freeze_backend(self, context):
        """Notify the backend that it's frozen."""
        # go over volumes in backend that are replicated and lock them

        pass

    def thaw_backend(self, context):
        """Notify the backend that it's unfrozen/thawed."""

        # go over volumes in backend that are replicated and unlock them
        pass

    def _using_default_backend(self):
        return ((self.active_backend_id is None) or
                (self.active_backend_id == strings.PRIMARY_BACKEND_ID))

    def _is_vol_split_brain(self, xcli_master, xcli_slave, vol):
        mirror_master = xcli_master.cmd.mirror_list(vol=vol).as_list
        mirror_slave = xcli_slave.cmd.mirror_list(vol=vol).as_list
        if (len(mirror_master) == 1 and len(mirror_slave) == 1 and
            mirror_master[0].current_role == 'Master' and
            mirror_slave[0].current_role == 'Slave' and
                mirror_master[0].sync_state.lower() in SYNCHED_STATES):
            return False
        else:
            return True

    def _potential_split_brain(self, xcli_master, xcli_slave,
                               volumes, pool_master, pool_slave):
        potential_split_brain = []
        if xcli_master is None or xcli_slave is None:
            return potential_split_brain
        try:
            vols_master = xcli_master.cmd.vol_list(
                pool=pool_master).as_dict('name')
        except Exception:
            msg = "Failed getting information from the active storage."
            LOG.debug(msg)
            return potential_split_brain
        try:
            vols_slave = xcli_slave.cmd.vol_list(
                pool=pool_slave).as_dict('name')
        except Exception:
            msg = "Failed getting information from the target storage."
            LOG.debug(msg)
            return potential_split_brain

        vols_requested = set(vol['name'] for vol in volumes)
        common_vols = set(vols_master).intersection(
            set(vols_slave)).intersection(set(vols_requested))
        for name in common_vols:
            if self._is_vol_split_brain(xcli_master=xcli_master,
                                        xcli_slave=xcli_slave, vol=name):
                potential_split_brain.append(name)
        return potential_split_brain

    def _failover_vol(self, volume, volume_replication_mgr,
                      failover_volume_replication_mgr,
                      replication_info, failback):
        """Failover a single volume.

        Attempts to failover a single volume
        Sequence:
        1. attempt to switch roles from master
        2. attempt to change role to master on slave

        returns (success, failure_reason)
        """
        LOG.debug("_failover_vol %(vol)s", {'vol': volume['name']})

        # check if mirror is defined and active
        try:
            LOG.debug('Check if mirroring is active on %(vol)s.',
                      {'vol': volume['name']})
            active = volume_replication_mgr.is_mirror_active(
                resource_id=volume['name'])
        except Exception:
            active = False
        state = 'active' if active else 'inactive'
        LOG.debug('Mirroring is %(state)s', {'state': state})

        # In case of failback, mirroring must be active
        # In case of failover we attempt to move in any condition
        if failback and not active:
            msg = (_LE("Volume %(vol)s: no active mirroring and can not "
                       "failback"),
                   {'vol': volume['name']})
            LOG.error(msg)
            return False, msg

        try:
            volume_replication_mgr.switch_roles(resource_id=volume['name'])
            return True, None
        except Exception as e:
            # failed attempt to switch_roles from the master
            details = self._get_code_and_status_or_message(e)
            LOG.warning(_LW('Failed to perform switch_roles on'
                            ' %(vol)s: %(err)s. '
                            'Continue to change_role'),
                        {'vol': volume['name'], 'err': details})

        try:
            # this is the ugly stage we come to brute force
            LOG.warning(_LW('Attempt to change_role to master'))
            failover_volume_replication_mgr.failover_by_id(
                resource_id=volume['name'])
            return True, None
        except m_errors.NoMirrorDefinedError as e:
            details = self._get_code_and_status_or_message(e)
            msg = (_LW("Volume %(vol)s no replication defined: %(err)s"),
                   {'vol': volume['name'], 'err': details})
            LOG.error(msg)
            return False, msg
        except Exception as e:
            details = self._get_code_and_status_or_message(e)
            msg = (_LE('Volume %(vol)s change_role failed: %(err)s'),
                   {'vol': volume['name'], 'err': details})
            LOG.error(msg)
            return False, msg

        return False, None

    @proxy._trace_time
    def failover_host(self, context, volumes, secondary_id):
        """Failover a full backend.

        Fails over the volume back and forth, if secondary_id is 'default',
        volumes will be failed back, otherwize failed over.

        Note that the resulting status depends on the direction:
        in case of failover it will be 'failed-over' and in case of
        failback it will be 'available'
        """
        volume_update_list = []

        LOG.info(_LI("failover_host: from %(active)s to %(id)s"),
                 {'active': self.active_backend_id, 'id': secondary_id})
        # special cases to handle
        if secondary_id == strings.PRIMARY_BACKEND_ID:
            # case: already failed back
            if self._using_default_backend():
                msg = _LI("Host has been failed back. No need "
                          "to fail back again.")
                LOG.info(msg)
                return self.active_backend_id, volume_update_list
            pool_slave = self.storage_info[storage.FLAG_KEYS['storage_pool']]
            pool_master = self._get_target_params(
                self.active_backend_id)['san_clustername']
            goal_status = 'available'
        else:
            if not self._using_default_backend():
                msg = _LI("Already failed over. No need to failover again.")
                LOG.info(msg)
                return self.active_backend_id, volume_update_list
            # case: need to select a target
            if secondary_id is None:
                secondary_id = self._get_target()
            # still no targets..
            if secondary_id is None:
                msg = _("No targets defined. Can't perform failover")
                LOG.error(msg)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)
            pool_master = self.storage_info[storage.FLAG_KEYS['storage_pool']]
            try:
                pool_slave = self._get_target_params(
                    secondary_id)['san_clustername']
            except Exception:
                msg = _("Invalid target information. Can't perform failover")
                LOG.error(msg)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)
            pool_master = self.storage_info[storage.FLAG_KEYS['storage_pool']]
            goal_status = objects.fields.ReplicationStatus.FAILED_OVER

        # connnect xcli to secondary storage according to backend_id by
        #  calling _init_xcli with secondary_id
        self.ibm_storage_remote_cli = self._init_xcli(secondary_id)

        # Create volume manager for both master and remote
        volume_replication_mgr = volume_recovery_manager.VolumeRecoveryManager(
            False, self.ibm_storage_cli)
        failover_volume_replication_mgr = (
            volume_recovery_manager.VolumeRecoveryManager(
                True, self.ibm_storage_remote_cli))

        # get replication_info for all volumes at once
        if len(volumes):
            # check for split brain situations
            # check for files that are available on both volumes
            # and are not in an active mirroring relation
            split_brain = self._potential_split_brain(
                self.ibm_storage_cli,
                self.ibm_storage_remote_cli,
                volumes, pool_master,
                pool_slave)
            if len(split_brain):
                # if such a situation exists stop and raise an exception!
                msg = (_("A potential split brain condition has been found "
                         "with the following volumes: \n'%(volumes)s.'"),
                       {'volumes': split_brain})
                LOG.error(msg)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)
            specs = self._get_extra_specs(
                volumes[0].get('volume_type_id', None))
            replication_info = self._get_replication_info(specs)

        # loop over volumes and attempt failover
        for volume in volumes:
            LOG.debug("Attempting to failover '%(vol)s'",
                      {'vol': volume['name']})
            result, details = self._failover_vol(
                volume,
                volume_replication_mgr,
                failover_volume_replication_mgr,
                replication_info,
                failback=(secondary_id == strings.PRIMARY_BACKEND_ID))
            if result:
                status = goal_status
            else:
                status = 'error'

            updates = {'status': status}
            if status == 'error':
                updates['replication_extended_status'] = details
            volume_update_list.append({
                'volume_id': volume['id'],
                'updates': updates
            })

        # set active xcli to secondary xcli
        temp_ibm_storage_cli = self.ibm_storage_cli
        self.ibm_storage_cli = self.ibm_storage_remote_cli
        self.ibm_storage_remote_cli = temp_ibm_storage_cli
        # set active backend id to secondary id
        self.active_backend_id = secondary_id

        return secondary_id, volume_update_list

    @proxy._trace_time
    def retype(self, ctxt, volume, new_type, diff, host):
        """Change volume type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities
        """
        LOG.debug("retype: volume = %(vol)s type = %(ntype)s",
                  {'vol': volume.get('display_name'),
                   'ntype': new_type['name']})

        if 'location_info' not in host['capabilities']:
            return False
        info = host['capabilities']['location_info']
        try:
            (dest, dest_host, dest_pool) = info.split(':')
        except ValueError:
            return False
        volume_host = volume.get('host').split('_')[1]
        if (dest != strings.XIV_BACKEND_PREFIX or dest_host != volume_host):
            return False

        pool_name = self.storage_info[storage.FLAG_KEYS['storage_pool']]

        # if pool is different. else - we're on the same pool and retype is ok.
        if (pool_name != dest_pool):
            # The input host and pool are already "linked" to the new_type,
            # otherwise the scheduler does not assign them as candidates for
            # the retype thus we just need to migrate the volume to the new
            # pool
            LOG.debug("retype: migrate volume %(vol)s to "
                      "host=%(host)s, pool=%(pool)s",
                      {'vol': volume.get('display_name'),
                       'host': dest_host, 'pool': dest_pool})
            (mig_result, model) = self.migrate_volume(
                context=ctxt, volume=volume, host=host)

            if not mig_result:
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=PERF_CLASS_ADD_ERROR)

        # Migration occurred, retype has finished.
        # We need to check for type and QoS.
        # getting the old specs
        old_specs = self._qos_specs_from_volume(volume)
        new_specs = self._get_qos_specs(new_type.get('id', None))
        if not new_specs:
            if old_specs:
                LOG.debug("qos: removing qos class for %(vol)s.",
                          {'vol': volume.display_name})
                self._qos_remove_vol(volume)
            return True

        perf_class_name_old = self._check_perf_class_on_backend(old_specs)
        perf_class_name_new = self._check_perf_class_on_backend(new_specs)
        if perf_class_name_new != perf_class_name_old:
            # add new qos to vol. (removed from old qos automatically)
            self._qos_add_vol(volume, perf_class_name_new)
        return True

    @proxy._trace_time
    def _check_storage_version_for_qos_support(self):
        if self.meta['storage_version'] is None:
            self.meta['storage_version'] = self._call_xiv_xcli(
                "version_get").as_single_element.system_version

        if int(self.meta['storage_version'][0:2]) >= 12:
            return 'True'
        return 'False'

    @proxy._trace_time
    def _update_stats(self):
        """fetch and update stats."""

        LOG.debug("Entered XIVProxy::_update_stats:")

        self.meta['stat'] = {}
        connection_type = self._get_connection_type()
        backend_name = None
        if self.driver:
            backend_name = self.driver.configuration.safe_get(
                'volume_backend_name')
        self.meta['stat']["volume_backend_name"] = (
            backend_name or '%s_%s_%s_%s' % (
                strings.XIV_BACKEND_PREFIX,
                self.storage_info[storage.FLAG_KEYS['address']],
                self.storage_info[storage.FLAG_KEYS['storage_pool']],
                connection_type))
        self.meta['stat']["vendor_name"] = 'IBM'
        self.meta['stat']["driver_version"] = self.full_version
        self.meta['stat']["storage_protocol"] = connection_type
        self.meta['stat']['multiattach'] = True  # XIV xupports multiattach
        self.meta['stat']['QoS_support'] = (
            self._check_storage_version_for_qos_support())

        self.meta['stat']['location_info'] = (
            ('%(destination)s:%(hostname)s:%(pool)s' %
             {'destination': strings.XIV_BACKEND_PREFIX,
              'hostname': self.storage_info[storage.FLAG_KEYS['address']],
              'pool': self.storage_info[storage.FLAG_KEYS['storage_pool']]
              }))

        pools = self._call_xiv_xcli(
            "pool_list",
            pool=self.storage_info[storage.FLAG_KEYS['storage_pool']]).as_list
        if len(pools) != 1:
            LOG.error(
                _LE("_update_stats: Pool %(pool)s not available on storage"),
                {'pool': self.storage_info[storage.FLAG_KEYS['storage_pool']]})
            return
        pool = pools[0]

        # handle different fields in pool_list between Gen3 and BR
        soft_size = pool.get('soft_size')
        if soft_size is None:
            soft_size = pool.get('size')
            hard_size = 0
        else:
            hard_size = pool.hard_size
        self.meta['stat']['total_capacity_gb'] = int(soft_size)
        self.meta['stat']['free_capacity_gb'] = int(
            pool.get('empty_space_soft', pool.get('empty_space')))
        self.meta['stat']['reserved_percentage'] = (
            self.driver.configuration.safe_get('reserved_percentage'))
        self.meta['stat']['consistencygroup_support'] = True

        # thin/thick provision
        self.meta['stat']['thin_provision'] = ('True' if soft_size > hard_size
                                               else 'False')

        targets = self._get_targets()
        if targets:
            self.meta['stat']['replication_enabled'] = True
            # TBD - replication_type should be according to type
            self.meta['stat']['replication_type'] = [SYNC, ASYNC]
            self.meta['stat']['rpo'] = self._get_supported_rpo()
            self.meta['stat']['replication_count'] = len(targets)
            self.meta['stat']['replication_targets'] = [target for target in
                                                        six.iterkeys(targets)]

        self.meta['stat']['timestamp'] = datetime.datetime.utcnow()

        LOG.debug("Exiting XIVProxy::_update_stats: %(stat)s",
                  {'stat': self.meta['stat']})

    @proxy._trace_time
    def create_cloned_volume(self, volume, src_vref):
        """Create cloned volume."""
        cg = self._cg_name_from_volume(volume)
        # read replication information
        specs = self._get_extra_specs(volume.get('volume_type_id', None))
        replication_info = self._get_replication_info(specs)

        # TODO(alonma): Refactor to use more common code
        src_vref_size = float(src_vref['size'])
        volume_size = float(volume['size'])
        if volume_size < src_vref_size:
            error = (_("New volume size (%(vol_size)s GB) cannot be less"
                       "than the source volume size (%(src_size)s GB).."),
                     {'vol_size': volume_size, 'src_size': src_vref_size})
            LOG.error(error)
            raise self._get_exception()(error)

        self._create_volume(volume)
        try:
            self._call_xiv_xcli(
                "vol_copy",
                vol_src=src_vref['name'],
                vol_trg=volume['name'])
        except errors.XCLIError as e:
            error = (_("Failed to copy from '%(src)s' to '%(vol)s': "
                       "%(details)s"),
                     {'src': src_vref.get('name', ''),
                      'vol': volume.get('name', ''),
                      'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            self._silent_delete_volume(volume=volume)
            raise self._get_exception()(error)
        # A side effect of vol_copy is the resizing of the destination volume
        # to the size of the source volume. If the size is different we need
        # to get it back to the desired size
        if src_vref_size != volume_size:
            size = storage.gigabytes_to_blocks(volume_size)
            try:
                self._call_xiv_xcli(
                    "vol_resize",
                    vol=volume['name'],
                    size_blocks=size)
            except errors.XCLIError as e:
                error = (_("Fatal error in vol_resize: %(details)s"),
                         {'details': self._get_code_and_status_or_message(e)})
                LOG.error(error)
                self._silent_delete_volume(volume=volume)
                raise self._get_exception()(error)
        self.handle_created_vol_properties(cg, replication_info, volume)

    @proxy._trace_time
    def volume_exists(self, volume):
        """Checks if a volume exists on xiv."""

        return len(self._call_xiv_xcli(
            "vol_list", vol=volume['name']).as_list) > 0

    def _cg_name_from_id(self, id):
        '''Get storage CG name from id.

        A utility method to translate from id
        to CG name on the storage
        '''
        return "cg_%(id)s" % {'id': id}

    def _group_name_from_id(self, id):
        '''Get storage group name from id.

        A utility method to translate from id
        to Snapshot Group name on the storage
        '''
        return "cgs_%(id)s" % {'id': id}

    def _cg_name_from_volume(self, volume):
        '''Get storage CG name from volume.

        A utility method to translate from openstack volume
        to CG name on the storage
        '''
        LOG.debug("_cg_name_from_volume: %(vol)s",
                  {'vol': volume['name']})
        cg_id = volume.get('consistencygroup_id', None)
        if cg_id:
            cg_name = self._cg_name_from_id(cg_id)
            LOG.debug("Volume %(vol)s is in CG %(cg)s",
                      {'vol': volume['name'], 'cg': cg_name})
            return cg_name
        else:
            LOG.debug("Volume %(vol)s not in CG",
                      {'vol': volume['name']})
            return None

    def _cg_name_from_group(self, group):
        '''Get storage CG name from group.

        A utility method to translate from openstack group
        to CG name on the storage
        '''
        return self._cg_name_from_id(group['id'])

    def _cg_name_from_cgsnapshot(self, cgsnapshot):
        '''Get storage CG name from snapshot.

        A utility method to translate from openstack cgsnapshot
        to CG name on the storage
        '''
        return self._cg_name_from_id(cgsnapshot['consistencygroup_id'])

    def _group_name_from_cgsnapshot(self, cgsnapshot):
        '''Get storage Snaphost Group name from snapshot.

        A utility method to translate from openstack cgsnapshot
        to Snapshot Group name on the storage
        '''
        return self._group_name_from_id(cgsnapshot['id'])

    def _volume_name_from_cg_snapshot(self, cgs, vol):
        # Note: The string is limited by the storage to 63 characters
        return ('%(cgs)s.%(vol)s' % {'cgs': cgs, 'vol': vol})[0:62]

    @proxy._trace_time
    def create_consistencygroup(self, context, group):
        """Creates a consistency group."""

        cgname = self._cg_name_from_group(group)
        LOG.info(_LI("Creating consistency group %(name)s."),
                 {'name': cgname})
        if isinstance(group, objects.Group):
            volume_type_ids = group.volume_type_ids
        elif isinstance(group, objects.ConsistencyGroup):
            volume_type_ids = filter(None, group.volume_type_id.split(","))
        else:
            msg = (_("Consistency group %(group)s has no volume_type_ids") %
                   {'group': cgname})
            LOG.error(msg)
            raise self.meta['exception'].VolumeBackendAPIException(data=msg)
        LOG.debug("volume_type_ids: %s", volume_type_ids)
        for volume_type_id in volume_type_ids:
            specs = self._get_extra_specs(volume_type_id)
            replication_info = self._get_replication_info(specs)

            if replication_info.get('enabled'):
                # An unsupported illegal configuration
                msg = _("Unable to create consistency group: "
                        "Replication of consistency group is not supported")
                LOG.error(msg)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)

        # call XCLI
        try:
            self._call_xiv_xcli(
                "cg_create", cg=cgname,
                pool=self.storage_info[
                    storage.FLAG_KEYS['storage_pool']]).as_list
        except errors.CgNameExistsError as e:
            error = (_("consistency group %s already exists on backend") %
                     cgname)
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.CgLimitReachedError as e:
            error = _("Reached Maximum number of consistency groups")
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.XCLIError as e:
            error = (_("Fatal error in cg_create: %(details)s") %
                     {'details': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)
        model_update = {'status': 'available'}
        return model_update

    def _silent_cleanup_consistencygroup_from_src(self, context, group,
                                                  volumes, cgname):
        """Silent cleanup of volumes from CG.

        Silently cleanup volumes and created consistency-group from
        storage. This function is called after a failure already occured
        and just logs errors, but does not raise exceptions
        """
        for volume in volumes:
            self._silent_delete_volume_from_cg(volume=volume, cgname=cgname)
        try:
            self.delete_consistencygroup(context, group, [])
        except Exception as e:
            details = self._get_code_and_status_or_message(e)
            LOG.error(_LE('Failed to cleanup CG %(details)s'),
                      {'details': details})

    @proxy._trace_time
    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot, snapshots,
                                         source_cg, sorted_source_vols):
        """Creates a consistencygroup from source.

        Source can be a cgsnapshot with the relevant list of snapshots,
        or another CG with its list of volumes.
        """
        cgname = self._cg_name_from_group(group)
        LOG.info(_LI("Creating consistency group %(cg)s from src."),
                 {'cg': cgname})

        volumes_model_update = []
        if cgsnapshot and snapshots:
            LOG.debug("Creating from cgsnapshot %(cg)s",
                      {'cg': self._cg_name_from_group(cgsnapshot)})
            try:
                self.create_consistencygroup(context, group)
            except Exception as e:
                LOG.error(
                    _LE("Creating CG from cgsnapshot failed: %(details)s"),
                    {'details': self._get_code_and_status_or_message(e)})
                raise
            created_volumes = []
            try:
                groupname = self._group_name_from_cgsnapshot(cgsnapshot)
                for volume, source in zip(volumes, snapshots):
                    vol_name = source.volume_name
                    LOG.debug("Original volume: %(vol_name)s",
                              {'vol_name': vol_name})
                    snapshot_name = self._volume_name_from_cg_snapshot(
                        groupname, vol_name)
                    LOG.debug("create volume (vol)s from snapshot %(snap)s",
                              {'vol': vol_name,
                               'snap': snapshot_name})

                    snapshot_size = float(source['volume_size'])
                    self._create_volume_from_snapshot(
                        volume, snapshot_name, snapshot_size)
                    created_volumes.append(volume)
                    volumes_model_update.append(
                        {
                            'id': volume['id'],
                            'status': 'available',
                            'size': snapshot_size,
                        })
            except Exception as e:
                details = self._get_code_and_status_or_message(e)
                msg = (CREATE_VOLUME_BASE_ERROR % {'details': details})
                LOG.error(msg)
                # cleanup and then raise exception
                self._silent_cleanup_consistencygroup_from_src(
                    context, group, created_volumes, cgname)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)

        elif source_cg and sorted_source_vols:
            LOG.debug("Creating from CG %(cg)s .",
                      {'cg': self._cg_name_from_group(source_cg)})
            LOG.debug("Creating from CG %(cg)s .", {'cg': source_cg['id']})
            try:
                self.create_consistencygroup(context, group)
            except Exception as e:
                LOG.error(_LE("Creating CG from CG failed: %(details)s"),
                          {'details': self._get_code_and_status_or_message(e)})
                raise
            created_volumes = []
            try:
                for volume, source in zip(volumes, sorted_source_vols):
                    self.create_cloned_volume(volume, source)
                    created_volumes.append(volume)
                    volumes_model_update.append(
                        {
                            'id': volume['id'],
                            'status': 'available',
                            'size': source['size'],
                        })
            except Exception as e:
                details = self._get_code_and_status_or_message(e)
                msg = (CREATE_VOLUME_BASE_ERROR, {'details': details})
                LOG.error(msg)
                # cleanup and then raise exception
                self._silent_cleanup_consistencygroup_from_src(
                    context, group, created_volumes, cgname)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)

        else:
            error = 'create_consistencygroup_from_src called without a source'
            raise self._get_exception()(error)

        model_update = {'status': 'available'}
        return model_update, volumes_model_update

    @proxy._trace_time
    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""

        cgname = self._cg_name_from_group(group)
        LOG.info(_LI("Deleting consistency group %(name)s."),
                 {'name': cgname})
        model_update = {}
        model_update['status'] = group.get('status', 'deleting')

        # clean up volumes
        volumes_model_update = []
        for volume in volumes:
            try:
                self._call_xiv_xcli(
                    "cg_remove_vol", vol=volume['name'])
            except errors.XCLIError as e:
                LOG.error(_LE("Failed removing volume %(vol)s from "
                              "consistency group %(cg)s: %(err)s"),
                          {'vol': volume['name'],
                           'cg': cgname,
                           'err': self._get_code_and_status_or_message(e)})
                # continue in spite of error

            try:
                self._delete_volume(volume['name'])
                # size and volume_type_id are required in liberty code
                # they are maintained here for backwards compatability
                volumes_model_update.append(
                    {
                        'id': volume['id'],
                        'status': 'deleted',
                    })
            except errors.XCLIError as e:
                LOG.error(DELETE_VOLUME_BASE_ERROR,
                          {'volume': volume['name'],
                           'error': self._get_code_and_status_or_message(e)})
                model_update['status'] = 'error_deleting'
                # size and volume_type_id are required in liberty code
                # they are maintained here for backwards compatability
                volumes_model_update.append(
                    {
                        'id': volume['id'],
                        'status': 'error_deleting',
                    })

        # delete CG from cinder.volume.drivers.ibm.ibm_storage
        if model_update['status'] != 'error_deleting':
            try:
                self._call_xiv_xcli(
                    "cg_delete", cg=cgname).as_list
                model_update['status'] = 'deleted'
            except (errors.CgDoesNotExistError, errors.CgBadNameError):
                error = (_LW("consistency group %(cgname)s does not "
                             "exist on backend") %
                         {'cgname': cgname})
                LOG.warning(error)
                # if the object was already deleted on the backend, we can
                # continue and delete the openstack object
                model_update['status'] = 'deleted'
            except errors.CgHasMirrorError:
                error = (_("consistency group %s is being mirrored") % cgname)
                LOG.error(error)
                raise self._get_exception()(error)
            except errors.CgNotEmptyError:
                error = (_("consistency group %s is not empty") % cgname)
                LOG.error(error)
                raise self._get_exception()(error)
            except errors.XCLIError as e:
                error = (_("Fatal: %(code)s. CG: %(cgname)s") %
                         {'code': self._get_code_and_status_or_message(e),
                          'cgname': cgname})
                LOG.error(error)
                raise self._get_exception()(error)
        return model_update, volumes_model_update

    @proxy._trace_time
    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group."""

        cgname = self._cg_name_from_group(group)
        LOG.info(_LI("Updating consistency group %(name)s."), {'name': cgname})
        model_update = {'status': 'available'}

        add_volumes_update = []
        if add_volumes:
            for volume in add_volumes:
                try:
                    self._call_xiv_xcli(
                        "cg_add_vol", vol=volume['name'], cg=cgname)
                except errors.XCLIError as e:
                    error = (_("Failed adding volume %(vol)s to "
                               "consistency group %(cg)s: %(err)s"),
                             {'vol': volume['name'],
                              'cg': cgname,
                              'err': self._get_code_and_status_or_message(e)})
                    LOG.error(error)
                    self._cleanup_consistencygroup_update(
                        context, group, add_volumes_update, None)
                    raise self._get_exception()(error)
                add_volumes_update.append({'name': volume['name']})

        remove_volumes_update = []
        if remove_volumes:
            for volume in remove_volumes:
                try:
                    self._call_xiv_xcli(
                        "cg_remove_vol", vol=volume['name'])
                except errors.XCLIError as e:
                    error = (_("Failed removing volume %(vol)s from "
                               "consistency group %(cg)s: %(err)s"),
                             {'vol': volume['name'],
                              'cg': cgname,
                              'err': self._get_code_and_status_or_message(e)})
                    LOG.error(error)
                    self._cleanup_consistencygroup_update(
                        context, group, add_volumes_update,
                        remove_volumes_update)
                    raise self._get_exception()(error)
                remove_volumes_update.append({'name': volume['name']})

        return model_update, None, None

    def _cleanup_consistencygroup_update(self, context, group,
                                         add_volumes, remove_volumes):
        if add_volumes:
            for volume in add_volumes:
                try:
                    self._call_xiv_xcli(
                        "cg_remove_vol", vol=volume['name'])
                except Exception:
                    LOG.debug("cg_remove_vol(%s) failed", volume['name'])

        if remove_volumes:
            cgname = self._cg_name_from_group(group)
            for volume in remove_volumes:
                try:
                    self._call_xiv_xcli(
                        "cg_add_vol", vol=volume['name'], cg=cgname)
                except Exception:
                    LOG.debug("cg_add_vol(%(name)s, %(cgname)s) failed",
                              {'name': volume['name'], 'cgname': cgname})

    @proxy._trace_time
    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a CG snapshot."""
        model_update = {'status': 'available'}

        cgname = self._cg_name_from_cgsnapshot(cgsnapshot)
        groupname = self._group_name_from_cgsnapshot(cgsnapshot)
        LOG.info(_LI("Creating snapshot %(group)s for CG %(cg)s."),
                 {'group': groupname, 'cg': cgname})

        # call XCLI
        try:
            self._call_xiv_xcli(
                "cg_snapshots_create", cg=cgname,
                snap_group=groupname).as_list
        except errors.CgDoesNotExistError as e:
            error = (_("Consistency group %s does not exist on backend") %
                     cgname)
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.CgBadNameError as e:
            error = (_("Consistency group %s has an illegal name") % cgname)
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.SnapshotGroupDoesNotExistError as e:
            error = (_("Snapshot group %s has an illegal name") % cgname)
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.PoolSnapshotLimitReachedError as e:
            error = _("Reached maximum snapshots allocation size")
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.CgEmptyError as e:
            error = (_("Consistency group %s is empty") % cgname)
            LOG.error(error)
            raise self._get_exception()(error)
        except (errors.MaxVolumesReachedError,
                errors.DomainMaxVolumesReachedError) as e:
            error = _("Reached Maximum number of volumes")
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.SnapshotGroupIsReservedError as e:
            error = (_("Consistency group %s name is reserved") % cgname)
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.SnapshotGroupAlreadyExistsError as e:
            error = (_("Snapshot group %s already exists") % groupname)
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.XCLIError as e:
            error = (_("Fatal: CG %(cg)s, Group %(group)s. %(err)s") %
                     {'cg': cgname,
                      'group': groupname,
                      'err': self._get_code_and_status_or_message(e)})
            LOG.error(error)
            raise self._get_exception()(error)

        snapshots_model_update = []
        for snapshot in snapshots:
            snapshots_model_update.append(
                {
                    'id': snapshot['id'],
                    'status': 'available',
                })
        return model_update, snapshots_model_update

    @proxy._trace_time
    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a CG snapshot."""

        cgname = self._cg_name_from_cgsnapshot(cgsnapshot)
        groupname = self._group_name_from_cgsnapshot(cgsnapshot)
        LOG.info(_LI("Deleting snapshot %(group)s for CG %(cg)s."),
                 {'group': groupname, 'cg': cgname})

        # call XCLI
        try:
            self._call_xiv_xcli(
                "snap_group_delete", snap_group=groupname).as_list
        except errors.CgDoesNotExistError:
            error = (_("consistency group %s not found on backend"), cgname)
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.PoolSnapshotLimitReachedError:
            error = _("Reached Maximum size allocated for snapshots")
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.CgEmptyError:
            error = _("Consistency group %s is empty") % cgname
            LOG.error(error)
            raise self._get_exception()(error)
        except errors.XCLIError as e:
            error = _("Fatal: CG %(cg)s, Group %(group)s. %(err)s") % {
                'cg': cgname,
                'group': groupname,
                'err': self._get_code_and_status_or_message(e)
            }
            LOG.error(error)
            raise self._get_exception()(error)

        snapshots_model_update = []
        for snapshot in snapshots:
            snapshots_model_update.append(
                {
                    'id': snapshot['id'],
                    'status': 'deleted',
                })
        model_update = {'status': 'deleted'}
        return model_update, snapshots_model_update

    def _generate_chap_secret(self, chap_name):
        """Returns chap secret generated according to chap_name

        chap secret must be between 12-16 chaqnracters
        """
        name = chap_name
        chap_secret = ""
        while len(chap_secret) < 12:
            chap_secret = cryptish.encrypt(name)[:16]
            name = name + '_'
        LOG.debug("_generate_chap_secret: %(secret)s",
                  {'secret': chap_secret})
        return chap_secret

    @proxy._trace_time
    def _create_chap(self, host=None):
        """Get CHAP name and secret

        returns chap name and secret
        chap_name and chap_secret must be 12-16 characters long
        """

        if host:
            if host['chap']:
                chap_name = host['chap'][0]
                LOG.debug("_create_chap: %(chap_name)s ",
                          {'chap_name': chap_name})
            else:
                chap_name = host['name']
        else:
            LOG.info(_LI("_create_chap: host missing!!!"))
            chap_name = "12345678901234"
        chap_secret = self._generate_chap_secret(chap_name)
        LOG.debug("_create_chap (new): %(chap_name)s ",
                  {'chap_name': chap_name})
        return (chap_name, chap_secret)

    @proxy._trace_time
    def _get_host(self, connector):
        """Returns a host looked up via initiator."""

        try:
            host_bunch = self._get_bunch_from_host(connector)
        except Exception as e:
            details = self._get_code_and_status_or_message(e)
            msg = (_("%(prefix)s. Invalid connector: '%(details)s.'") %
                   {'prefix': storage.XIV_LOG_PREFIX, 'details': details})
            raise self._get_exception()(msg)
        host = []
        chap = None
        all_hosts = self._call_xiv_xcli("host_list").as_list
        if self._get_connection_type() == storage.XIV_CONNECTION_TYPE_ISCSI:
            host = [host_obj for host_obj in all_hosts
                    if host_bunch['initiator']
                    in host_obj.iscsi_ports.split(',')]
        else:
            if 'wwpns' in connector:
                if len(host_bunch['wwpns']) > 0:
                    wwpn_set = set([wwpn.lower() for wwpn
                                    in host_bunch['wwpns']])
                    host = [host_obj for host_obj in all_hosts if
                            len(wwpn_set.intersection(host_obj.get(
                                'fc_ports', '').lower().split(','))) > 0]
            else:  # fake connector created by nova
                host = [host_obj for host_obj in all_hosts
                        if host_obj.get('name', '') == connector['host']]
        if len(host) == 1:
            if self._is_iscsi() and host[0].iscsi_chap_name:
                chap = (host[0].iscsi_chap_name,
                        self._generate_chap_secret(host[0].iscsi_chap_name))
                LOG.debug("_get_host: chap_name %(chap_name)s ",
                          {'chap_name': host[0].iscsi_chap_name})
            return self._get_bunch_from_host(
                connector, host[0].id, host[0].name, chap)

        LOG.debug("_get_host: returns None")
        return None

    @proxy._trace_time
    def _call_host_define(self, host,
                          chap_name=None, chap_secret=None, domain_name=None):
        """Call host_define using XCLI."""
        LOG.debug("host_define with domain: %s)" % domain_name)
        if domain_name:
            if chap_name:
                return self._call_xiv_xcli(
                    "host_define",
                    host=host,
                    iscsi_chap_name=chap_name,
                    iscsi_chap_secret=chap_secret,
                    domain=domain_name
                ).as_list[0]
            else:
                return self._call_xiv_xcli(
                    "host_define",
                    host=host,
                    domain=domain_name
                ).as_list[0]
        else:
            # No domain
            if chap_name:
                return self._call_xiv_xcli(
                    "host_define",
                    host=host,
                    iscsi_chap_name=chap_name,
                    iscsi_chap_secret=chap_secret
                ).as_list[0]
            else:
                return self._call_xiv_xcli(
                    "host_define",
                    host=host
                ).as_list[0]

    @proxy._trace_time
    def _define_host_according_to_chap(self, host, in_domain):
        """Check on chap state and define host accordingly."""
        chap_name = None
        chap_secret = None
        if (self._get_connection_type() ==
                storage.XIV_CONNECTION_TYPE_ISCSI and
                self._get_chap_type() == storage.CHAP_ENABLED):
            host_bunch = {'name': host, 'chap': None, }
            chap = self._create_chap(host=host_bunch)
            chap_name = chap[0]
            chap_secret = chap[1]
            LOG.debug("_define_host_according_to_chap: "
                      "%(name)s : %(secret)s",
                      {'name': chap_name, 'secret': chap_secret})
        return self._call_host_define(
            host=host,
            chap_name=chap_name,
            chap_secret=chap_secret,
            domain_name=in_domain)

    def _define_ports(self, host_bunch):
        """Defines ports in XIV."""
        fc_targets = []
        LOG.debug(host_bunch.get('name'))
        if self._get_connection_type() == storage.XIV_CONNECTION_TYPE_ISCSI:
            self._define_iscsi(host_bunch)
        else:
            fc_targets = self._define_fc(host_bunch)
            fc_targets = list(set(fc_targets))
            fc_targets.sort(key=self._sort_last_digit)
        return fc_targets

    def _get_pool_domain(self, connector):
        pool_name = self.storage_info[storage.FLAG_KEYS['storage_pool']]
        LOG.debug("pool name from configuration: %s" % pool_name)
        domain = None
        try:
            domain = self._call_xiv_xcli(
                "pool_list", pool=pool_name).as_list[0].get('domain')
            LOG.debug("Pool's domain: %s", domain)
        except AttributeError:
            pass
        return domain

    @proxy._trace_time
    def _define_host(self, connector):
        """Defines a host in XIV."""
        domain = self._get_pool_domain(connector)
        host_bunch = self._get_bunch_from_host(connector)
        host = self._call_xiv_xcli(
            "host_list", host=host_bunch['name']).as_list
        connection_type = self._get_connection_type()
        if len(host) == 0:
            LOG.debug("Non existing host, defining")
            host = self._define_host_according_to_chap(
                host=host_bunch['name'], in_domain=domain)
            host_bunch = self._get_bunch_from_host(connector,
                                                   host.get('id'))
        else:
            host_bunch = self._get_bunch_from_host(connector,
                                                   host[0].get('id'))
            LOG.debug("Generating hostname for connector %(conn)s",
                      {'conn': connector})
            generated_hostname = storage.get_host_or_create_from_iqn(
                connector, connection=connection_type)
            generated_host = self._call_xiv_xcli(
                "host_list",
                host=generated_hostname).as_list
            if len(generated_host) == 0:
                host = self._define_host_according_to_chap(
                    host=generated_hostname,
                    in_domain=domain)
            else:
                host = generated_host[0]
            host_bunch = self._get_bunch_from_host(
                connector, host.get('id'), host_name=generated_hostname)
        LOG.debug("The host_bunch: %s", host_bunch)
        return host_bunch

    @proxy._trace_time
    def _define_fc(self, host_bunch):
        """Define FC Connectivity."""

        fc_targets = []
        if len(host_bunch.get('wwpns')) > 0:
            connected_wwpns = []
            for wwpn in host_bunch.get('wwpns'):
                component_ids = list(set(
                    [p.component_id for p in
                     self._call_xiv_xcli(
                         "fc_connectivity_list",
                         wwpn=wwpn.replace(":", ""))]))
                wwpn_fc_target_lists = []
                for component in component_ids:
                    wwpn_fc_target_lists += [fc_p.wwpn for fc_p in
                                             self._call_xiv_xcli(
                                                 "fc_port_list",
                                                 fcport=component)]
                LOG.debug("got %(tgts)s fc targets for wwpn %(wwpn)s",
                          {'tgts': wwpn_fc_target_lists, 'wwpn': wwpn})
                if len(wwpn_fc_target_lists) > 0:
                    connected_wwpns += [wwpn]
                    fc_targets += wwpn_fc_target_lists
                LOG.debug("adding fc port %s", wwpn)
                self._call_xiv_xcli(
                    "host_add_port", host=host_bunch.get('name'),
                    fcaddress=wwpn)
            if len(connected_wwpns) == 0:
                LOG.error(CONNECTIVITY_FC_NO_TARGETS)
                raise self._get_exception()(CONNECTIVITY_FC_NO_TARGETS)
        else:
            msg = _("No Fibre Channel HBA's are defined on the host.")
            LOG.error(msg)
            raise self._get_exception()(msg)

        return fc_targets

    @proxy._trace_time
    def _define_iscsi(self, host_bunch):
        """Add iscsi ports."""
        if host_bunch.get('initiator'):
            LOG.debug("adding iscsi")
            self._call_xiv_xcli(
                "host_add_port", host=host_bunch.get('name'),
                iscsi_name=host_bunch.get('initiator'))
        else:
            msg = _("No iSCSI initiator found!")
            LOG.error(msg)
            raise self._get_exception()(msg)

    @proxy._trace_time
    def _event_service_start(self):
        """Send an event when cinder service starts."""
        LOG.debug("send event SERVICE_STARTED")
        service_start_evnt_prop = {
            "openstack_version": self.meta['openstack_version'],
            "pool_name": self.storage_info[storage.FLAG_KEYS['storage_pool']]}
        ev_mgr = events.EventsManager(self.ibm_storage_cli,
                                      OPENSTACK_PRODUCT_NAME,
                                      self.full_version)
        ev_mgr.send_event('SERVICE_STARTED', service_start_evnt_prop)

    @proxy._trace_time
    def _event_volume_attached(self):
        """Send an event when volume is attached to host."""
        LOG.debug("send event VOLUME_ATTACHED")
        compute_host_name = socket.getfqdn()
        vol_attach_evnt_prop = {
            "openstack_version": self.meta['openstack_version'],
            "pool_name": self.storage_info[storage.FLAG_KEYS['storage_pool']],
            "compute_hostname": compute_host_name}

        ev_mgr = events.EventsManager(self.ibm_storage_cli,
                                      OPENSTACK_PRODUCT_NAME,
                                      self.full_version)
        ev_mgr.send_event('VOLUME_ATTACHED', vol_attach_evnt_prop)

    @proxy._trace_time
    def _build_initiator_target_map(self, fc_targets, connector):
        """Build the target_wwns and the initiator target map."""
        init_targ_map = {}
        wwpns = connector.get('wwpns', [])
        for initiator in wwpns:
            init_targ_map[initiator] = fc_targets

        LOG.debug("_build_initiator_target_map: %(init_targ_map)s",
                  {'init_targ_map': init_targ_map})
        return init_targ_map

    @proxy._trace_time
    def _get_host_and_fc_targets(self, volume, connector):
        """Returns the host and its FC targets."""

        LOG.debug("_get_host_and_fc_targets %(volume)s",
                  {'volume': volume['name']})

        fc_targets = []
        host = self._get_host(connector)
        if not host:
            host = self._define_host(connector)
            fc_targets = self._define_ports(host)
        elif self._get_connection_type() == storage.XIV_CONNECTION_TYPE_FC:
            fc_targets = self._get_fc_targets(host)
            if len(fc_targets) == 0:
                LOG.error(CONNECTIVITY_FC_NO_TARGETS)
                raise self._get_exception()(CONNECTIVITY_FC_NO_TARGETS)

        return (fc_targets, host)

    def _vol_map_and_get_lun_id(self, volume, connector, host):
        """Maps volume to instance.

        Maps a volume to the nova volume node as host,
        and return the created lun id
        """
        vol_name = volume['name']
        LOG.debug("_vol_map_and_get_lun_id %(volume)s",
                  {'volume': vol_name})

        try:
            mapped_vols = self._call_xiv_xcli(
                "vol_mapping_list",
                vol=vol_name).as_dict('host')
            if host['name'] in mapped_vols:
                LOG.info(_LI("Volume '%(volume)s' was already attached to "
                             "the host '%(host)s'."),
                         {'host': host['name'],
                          'volume': volume['name']})
                return int(mapped_vols[host['name']].lun)
        except errors.VolumeBadNameError:
            LOG.error(_LE("%(error)s '%(volume)s"),
                      {'error': "Volume not found.",
                       'volume': volume['name']})
            raise self.meta['exception'].VolumeNotFound(volume_id=volume['id'])
        used_luns = [int(mapped.get('lun')) for mapped in
                     self._call_xiv_xcli(
                         "mapping_list",
                         host=host['name']).as_list]
        luns = six.moves.xrange(MIN_LUNID, MAX_LUNID)  # pylint: disable=E1101
        for lun_id in luns:
            if lun_id not in used_luns:
                self._call_xiv_xcli(
                    "map_vol",
                    lun=lun_id,
                    host=host['name'],
                    vol=vol_name)
                self._event_volume_attached()
                return lun_id
        msg = _("All free LUN IDs were already mapped.")
        LOG.error(msg)
        raise self._get_exception()(msg)

    @proxy._trace_time
    def _get_fc_targets(self, host):
        """Get FC targets

        :host: host bunch
        :returns: array of FC target WWPNs
        """
        target_wwpns = []
        target_wwpns += (
            [t.get('wwpn') for t in
                self._call_xiv_xcli("fc_port_list") if
                t.get('wwpn') != '0000000000000000' and
                t.get('role') == 'Target' and
                t.get('port_state') == 'Online'])
        fc_targets = list(set(target_wwpns))
        fc_targets.sort(key=self._sort_last_digit)
        LOG.debug("fc_targets : %s" % fc_targets)
        return fc_targets

    def _sort_last_digit(self, a):
        return a[-1:]

    @proxy._trace_time
    def _get_xcli(self, xcli, backend_id):
        """Wrapper around XCLI to ensure that connection is up."""
        if self.meta['bypass_connection_check']:
            LOG.debug("_get_xcli(bypass mode)")
        else:
            if not xcli.is_connected():
                xcli = self._init_xcli(backend_id)
        return xcli

    @proxy._trace_time
    def _call_xiv_xcli(self, method, *args, **kwargs):
        """Wrapper around XCLI to call active storage."""
        self.ibm_storage_cli = self._get_xcli(
            self.ibm_storage_cli, self.active_backend_id)

        if self.ibm_storage_cli:
            LOG.info(_LI("_call_xiv_xcli #1: %s"), method)
        else:
            LOG.debug("_call_xiv_xcli #2: %s", method)
        return getattr(self.ibm_storage_cli.cmd, method)(*args, **kwargs)

    @proxy._trace_time
    def _call_remote_xiv_xcli(self, method, *args, **kwargs):
        """Wrapper around XCLI to call remote storage."""
        remote_id = self._get_secondary_backend_id()
        if not remote_id:
            raise self._get_exception()(_("No remote backend found."))
        self.ibm_storage_remote_cli = self._get_xcli(
            self.ibm_storage_remote_cli, remote_id)

        LOG.debug("_call_remote_xiv_xcli: %s", method)
        return getattr(self.ibm_storage_remote_cli.cmd, method)(
            *args,
            **kwargs)

    def _verify_xiv_flags(self, address, user, password):
        """Verify that the XIV flags were passed."""
        if not user or not password:
            raise self._get_exception()(_("No credentials found."))

        if not address:
            raise self._get_exception()(_("No host found."))

    def _get_connection_params(self, backend_id=strings.PRIMARY_BACKEND_ID):
        """Get connection parameters.

        returns a tuple containing address list, user, password,
        according to backend_id
        """
        if not backend_id or backend_id == strings.PRIMARY_BACKEND_ID:
            if self._get_management_ips():
                address = [e.strip(" ") for e in self.storage_info[
                    storage.FLAG_KEYS['management_ips']].split(",")]
            else:
                address = self.storage_info[storage.FLAG_KEYS['address']]
            user = self.storage_info[storage.FLAG_KEYS['user']]
            password = self.storage_info[storage.FLAG_KEYS['password']]
        else:
            params = self._get_target_params(backend_id)
            if not params:
                msg = (_("Missing target information for target '%(target)s'"),
                       {'target': backend_id})
                LOG.error(msg)
                raise self.meta['exception'].VolumeBackendAPIException(
                    data=msg)
            if params.get('management_ips', None):
                address = [e.strip(" ") for e in
                           params['management_ips'].split(",")]
            else:
                address = params['san_ip']
            user = params['san_login']
            password = params['san_password']

        return (address, user, password)

    @proxy._trace_time
    def _init_xcli(self, backend_id=strings.PRIMARY_BACKEND_ID):
        """Initilize XCLI connection.

        returns an XCLIClient object
        """

        try:
            address, user, password = self._get_connection_params(backend_id)
        except Exception as e:
            details = self._get_code_and_status_or_message(e)
            ex_details = (SETUP_BASE_ERROR,
                          {'title': strings.TITLE, 'details': details})
            LOG.error(ex_details)
            raise self.meta['exception'].InvalidParameterValue(
                (_("%(prefix)s %(ex_details)s") %
                 {'prefix': storage.XIV_LOG_PREFIX,
                  'ex_details': ex_details}))

        self._verify_xiv_flags(address, user, password)

        try:
            clear_pass = cryptish.decrypt(password)
        except TypeError:
            ex_details = (SETUP_BASE_ERROR,
                          {'title': strings.TITLE,
                           'details': "Invalid password."})
            LOG.error(ex_details)
            raise self.meta['exception'].InvalidParameterValue(
                (_("%(prefix)s %(ex_details)s") %
                 {'prefix': storage.XIV_LOG_PREFIX,
                  'ex_details': ex_details}))

        certs = certificate.CertificateCollector()
        path = certs.collect_certificate()
        try:
            LOG.debug('connect_multiendpoint_ssl with: %s' % address)
            xcli = client.XCLIClient.connect_multiendpoint_ssl(
                user,
                clear_pass,
                address,
                ca_certs=path)
        except errors.CredentialsError:
            LOG.error(SETUP_BASE_ERROR,
                      {'title': strings.TITLE,
                       'details': "Invalid credentials."})
            raise self.meta['exception'].NotAuthorized()
        except (errors.ConnectionError, transports.ClosedTransportError):
            err_msg = (SETUP_INVALID_ADDRESS, {'address': address})
            LOG.error(err_msg)
            raise self.meta['exception'].HostNotFound(host=err_msg)
        except Exception as er:
            err_msg = (SETUP_BASE_ERROR,
                       {'title': strings.TITLE, 'details': er})
            LOG.error(err_msg)
            raise self._get_exception()(err_msg)
        finally:
            certs.free_certificate()

        return xcli
