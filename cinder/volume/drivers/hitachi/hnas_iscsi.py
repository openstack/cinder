# Copyright (c) 2014 Hitachi Data Systems, Inc.
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

"""
iSCSI Cinder Volume driver for Hitachi Unified Storage (HUS-HNAS) platform.
"""

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder import interface

from cinder import utils as cinder_utils
from cinder.volume import driver
from cinder.volume.drivers.hitachi import hnas_backend
from cinder.volume.drivers.hitachi import hnas_utils
from cinder.volume import utils


HNAS_ISCSI_VERSION = '5.0.0'

LOG = logging.getLogger(__name__)

iSCSI_OPTS = [
    cfg.StrOpt('hds_hnas_iscsi_config_file',
               default='/opt/hds/hnas/cinder_iscsi_conf.xml',
               help='Legacy configuration file for HNAS iSCSI Cinder '
                    'plugin. This is not needed if you fill all '
                    'configuration on cinder.conf',
               deprecated_for_removal=True),
    cfg.BoolOpt('hnas_chap_enabled',
                default=True,
                help='Whether the chap authentication is enabled in the '
                     'iSCSI target or not.'),
    cfg.IPOpt('hnas_svc0_iscsi_ip',
              help='Service 0 iSCSI IP'),
    cfg.IPOpt('hnas_svc1_iscsi_ip',
              help='Service 1 iSCSI IP'),
    cfg.IPOpt('hnas_svc2_iscsi_ip',
              help='Service 2 iSCSI IP'),
    cfg.IPOpt('hnas_svc3_iscsi_ip',
              help='Service 3 iSCSI IP')
]


CONF = cfg.CONF
CONF.register_opts(iSCSI_OPTS)

HNAS_DEFAULT_CONFIG = {'ssc_cmd': 'ssc',
                       'chap_enabled': True,
                       'ssh_port': 22}
MAX_HNAS_ISCSI_TARGETS = 32
MAX_HNAS_LUS_PER_TARGET = 32


@interface.volumedriver
class HNASISCSIDriver(driver.ISCSIDriver):
    """HNAS iSCSI volume driver.

    Version history:

        code-block:: none

        Version 1.0.0: Initial driver version
        Version 2.2.0: Added support to SSH authentication
        Version 3.2.0: Added pool aware scheduling
                       Fixed concurrency errors
        Version 3.3.0: Fixed iSCSI target limitation error
        Version 4.0.0: Added manage/unmanage features
        Version 4.1.0: Fixed XML parser checks on blank options
        Version 4.2.0: Fixed SSH and cluster_admin_ip0 verification
        Version 4.3.0: Fixed attachment with os-brick 1.0.0
        Version 5.0.0: Code cleaning up
                       New communication interface between the driver and HNAS
                       Removed the option to use local SSC (ssh_enabled=False)
                       Updated to use versioned objects
                       Changed the class name to HNASISCSIDriver
                       Deprecated XML config file
                       Fixed driver stats reporting
"""

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Hitachi_HNAS_CI"
    VERSION = HNAS_ISCSI_VERSION

    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        """Initializes and reads different config parameters."""
        super(HNASISCSIDriver, self).__init__(*args, **kwargs)
        msg = _("The Hitachi NAS iSCSI  driver is deprecated and will be "
                "removed in a future release.")
        versionutils.report_deprecated_feature(LOG, msg)
        self.configuration = kwargs.get('configuration', None)
        self.context = {}
        self.config = {}

        service_parameters = ['volume_type', 'hdp', 'iscsi_ip']
        optional_parameters = ['ssc_cmd', 'cluster_admin_ip0',
                               'chap_enabled']

        if self.configuration:
            self.configuration.append_config_values(
                hnas_utils.drivers_common_opts)
            self.configuration.append_config_values(iSCSI_OPTS)

            # Trying to get HNAS configuration from cinder.conf
            self.config = hnas_utils.read_cinder_conf(
                self.configuration, 'iscsi')

            # If HNAS configuration are not set on cinder.conf, tries to use
            # the deprecated XML configuration file
            if not self.config:
                self.config = hnas_utils.read_xml_config(
                    self.configuration.hds_hnas_iscsi_config_file,
                    service_parameters,
                    optional_parameters)

            self.reserved_percentage = (
                self.configuration.safe_get('reserved_percentage'))
            self.max_osr = (
                self.configuration.safe_get('max_over_subscription_ratio'))

        self.backend = hnas_backend.HNASSSHBackend(self.config)

    def _get_service(self, volume):
        """Gets the available service parameters.

        Get the available service parameters for a given volume using its
        type.

        :param volume: dictionary volume reference
        :returns: HDP (file system) related to the service or error if no
        configuration is found.
        :raises: ParameterNotFound
        """
        LOG.debug("Available services: %(svc)s.",
                  {'svc': self.config['services'].keys()})
        label = utils.extract_host(volume.host, level='pool')

        if label in self.config['services'].keys():
            svc = self.config['services'][label]
            LOG.info(_LI("Using service label: %(lbl)s."), {'lbl': label})
            return svc['hdp']
        else:
            LOG.error(_LE("No configuration found for service: %(lbl)s."),
                      {'lbl': label})
            raise exception.ParameterNotFound(param=label)

    def _get_service_target(self, volume):
        """Gets the available service parameters

        Gets the available service parameters for a given volume using its
        type.
        :param volume: dictionary volume reference
        :returns: service target information or raises error
        :raises: NoMoreTargets
        """
        fs_label = self._get_service(volume)
        evs_id = self.backend.get_evs(fs_label)

        svc_label = utils.extract_host(volume.host, level='pool')
        svc = self.config['services'][svc_label]

        lu_info = self.backend.check_lu(volume.name, fs_label)

        # The volume is already mapped to a LU, so no need to create any
        # targets
        if lu_info['mapped']:
            service = (
                svc['iscsi_ip'], svc['iscsi_port'], svc['evs'], svc['port'],
                fs_label, lu_info['tgt']['alias'], lu_info['tgt']['secret'])
            LOG.info(_LI("Volume %(vol_name)s already mapped on target "
                         "%(tgt)s to LUN %(lunid)s."),
                     {'vol_name': volume.name, 'tgt': lu_info['tgt']['alias'],
                      'lunid': lu_info['id']})
            return service

        # Each EVS can have up to 32 targets. Each target can have up to 32
        # LUs attached and have the name format 'evs<id>-tgt<0-N>'. We run
        # from the first 'evs1-tgt0' until we find a target that is not already
        # created in the BE or is created but have slots to place new LUs.
        tgt_alias = ''
        for i in range(0, MAX_HNAS_ISCSI_TARGETS):
            tgt_alias = 'evs' + evs_id + '-tgt' + six.text_type(i)
            tgt = self.backend.check_target(fs_label, tgt_alias)

            if (tgt['found'] and
                    len(tgt['tgt']['lus']) < MAX_HNAS_LUS_PER_TARGET or
                    not tgt['found']):
                # Target exists and has free space or, target does not exist
                # yet. Proceed and use the target or create a target using this
                # name.
                break
        else:
            # If we've got here, we run out of targets, raise and go away.
            LOG.error(_LE("No more targets available."))
            raise exception.NoMoreTargets(param=tgt_alias)

        LOG.info(_LI("Using target label: %(tgt)s."), {'tgt': tgt_alias})

        # Check if we have a secret stored for this target so we don't have to
        # go to BE on every query
        if 'targets' not in self.config.keys():
            self.config['targets'] = {}

        if tgt_alias not in self.config['targets'].keys():
            self.config['targets'][tgt_alias] = {}

        tgt_info = self.config['targets'][tgt_alias]

        # HNAS - one time lookup
        # see if the client supports CHAP authentication and if
        # iscsi_secret has already been set, retrieve the secret if
        # available, otherwise generate and store
        if self.config['chap_enabled']:
            # CHAP support is enabled. Tries to get the target secret.
            if 'iscsi_secret' not in tgt_info.keys():
                LOG.info(_LI("Retrieving secret for service: %(tgt)s."),
                         {'tgt': tgt_alias})
                out = self.backend.get_target_secret(tgt_alias, fs_label)
                tgt_info['iscsi_secret'] = out

                # CHAP supported and the target has no secret yet. So, the
                # secret is created for the target
                if tgt_info['iscsi_secret'] == "":
                    random_secret = utils.generate_password()[0:15]
                    tgt_info['iscsi_secret'] = random_secret

                    LOG.info(_LI("Set tgt CHAP secret for service: %(tgt)s."),
                             {'tgt': tgt_alias})
        else:
            # We set blank password when the client does not
            # support CHAP. Later on, if the client tries to create a new
            # target that does not exist in the backend, we check for this
            # value and use a temporary dummy password.
            if 'iscsi_secret' not in tgt_info.keys():
                # Warns in the first time
                LOG.info(_LI("CHAP authentication disabled."))

            tgt_info['iscsi_secret'] = "''"

        # If the target does not exist, it should be created
        if not tgt['found']:
            self.backend.create_target(tgt_alias, fs_label,
                                       tgt_info['iscsi_secret'])
        elif (tgt['tgt']['secret'] == "" and
                self.config['chap_enabled']):
            # The target exists, has no secret and chap is enabled
            self.backend.set_target_secret(tgt_alias, fs_label,
                                           tgt_info['iscsi_secret'])

        if 'tgt_iqn' not in tgt_info:
            LOG.info(_LI("Retrieving IQN for service: %(tgt)s."),
                     {'tgt': tgt_alias})

            out = self.backend.get_target_iqn(tgt_alias, fs_label)
            tgt_info['tgt_iqn'] = out

        self.config['targets'][tgt_alias] = tgt_info

        service = (svc['iscsi_ip'], svc['iscsi_port'], svc['evs'], svc['port'],
                   fs_label, tgt_alias, tgt_info['iscsi_secret'])

        return service

    def _get_stats(self):
        """Get FS stats from HNAS.

        :returns: dictionary with the stats from HNAS
        _stats['pools'] = {
            'total_capacity_gb': total size of the pool,
            'free_capacity_gb': the available size,
            'QoS_support': bool to indicate if QoS is supported,
            'reserved_percentage': percentage of size reserved,
            'max_over_subscription_ratio': oversubscription rate,
            'thin_provisioning_support': thin support (True),
            'reserved_percentage': reserved percentage
            }
        """
        hnas_stat = {}
        be_name = self.configuration.safe_get('volume_backend_name')
        hnas_stat["volume_backend_name"] = be_name or 'HNASISCSIDriver'
        hnas_stat["vendor_name"] = 'Hitachi'
        hnas_stat["driver_version"] = HNAS_ISCSI_VERSION
        hnas_stat["storage_protocol"] = 'iSCSI'

        for pool in self.pools:
            fs_info = self.backend.get_fs_info(pool['fs'])
            pool['provisioned_capacity_gb'] = fs_info['provisioned_capacity']
            pool['total_capacity_gb'] = (float(fs_info['total_size']))
            pool['free_capacity_gb'] = (
                float(fs_info['total_size']) - float(fs_info['used_size']))
            pool['QoS_support'] = 'False'
            pool['reserved_percentage'] = self.reserved_percentage
            pool['max_over_subscription_ratio'] = self.max_osr
            pool['thin_provisioning_support'] = True

        hnas_stat['pools'] = self.pools

        LOG.debug("stats: %(stat)s.", {'stat': hnas_stat})
        return hnas_stat

    def _check_fs_list(self):
        """Verifies the FSs list in HNAS.

        Verify that all FSs specified in the configuration files actually
        exists on the storage.
        """
        fs_list = self.config['fs'].keys()

        for fs in fs_list:
            if not self.backend.get_fs_info(fs):
                msg = (_("File system not found or not mounted: %(fs)s") %
                       {'fs': fs})
                LOG.error(msg)
                raise exception.ParameterNotFound(param=msg)

    def _check_pool_and_fs(self, volume, fs_label):
        """Validates pool and file system of a volume being managed.

        Checks if the file system for the volume-type chosen matches the
        one passed in the volume reference. Also, checks if the pool
        for the volume type matches the pool for the host passed.

        :param volume: Reference to the volume.
        :param fs_label: Label of the file system.
        :raises: ManageExistingVolumeTypeMismatch
        """
        pool_from_vol_type = hnas_utils.get_pool(self.config, volume)

        if (pool_from_vol_type == 'default' and
                'default' not in self.config['services']):
            msg = (_("Failed to manage existing volume %(volume)s because the "
                     "chosen volume type %(vol_type)s does not have a "
                     "service_label configured in its extra-specs and there "
                     "is no pool configured with hnas_svcX_volume_type as "
                     "'default' in cinder.conf.") %
                   {'volume': volume.id,
                    'vol_type': getattr(volume.volume_type, 'id', None)})
            LOG.error(msg)
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        pool = self.config['services'][pool_from_vol_type]['hdp']
        if pool != fs_label:
            msg = (_("Failed to manage existing volume because the "
                     "pool %(pool)s of the volume type chosen does not "
                     "match the file system %(fs_label)s passed in the "
                     "volume reference.")
                   % {'pool': pool, 'fs_label': fs_label})
            LOG.error(msg)
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

        pool_from_host = utils.extract_host(volume.host, level='pool')

        if pool_from_host != pool_from_vol_type:
            msg = (_("Failed to manage existing volume because the pool "
                     "%(pool)s of the volume type chosen does not match the "
                     "pool %(pool_host)s of the host.") %
                   {'pool': pool_from_vol_type, 'pool_host': pool_from_host})
            LOG.error(msg)
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)

    def _get_info_from_vol_ref(self, vol_ref):
        """Gets information from the volume reference.

        Returns the information (File system and volume name) taken from
        the volume reference.

        :param vol_ref: existing volume to take under management
        :returns: the file system label and the volume name or raises error
        :raises: ManageExistingInvalidReference
        """
        vol_info = vol_ref.strip().split('/')

        if len(vol_info) == 2 and '' not in vol_info:
            fs_label = vol_info[0]
            vol_name = vol_info[1]

            return fs_label, vol_name
        else:
            msg = _("The reference to the volume in the backend should have "
                    "the format file_system/volume_name (volume_name cannot "
                    "contain '/')")
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=vol_ref, reason=msg)

    def check_for_setup_error(self):
        pass

    def do_setup(self, context):
        """Sets up and verify Hitachi HNAS storage connection."""
        self.context = context
        self._check_fs_list()

        version_info = self.backend.get_version()
        LOG.info(_LI("HNAS iSCSI driver."))
        LOG.info(_LI("HNAS model: %(mdl)s"), {'mdl': version_info['model']})
        LOG.info(_LI("HNAS version: %(version)s"),
                 {'version': version_info['version']})
        LOG.info(_LI("HNAS hardware: %(hw)s"),
                 {'hw': version_info['hardware']})
        LOG.info(_LI("HNAS S/N: %(sn)s"), {'sn': version_info['serial']})
        service_list = self.config['services'].keys()
        for svc in service_list:
            svc = self.config['services'][svc]
            pool = {}
            pool['pool_name'] = svc['pool_name']
            pool['service_label'] = svc['pool_name']
            pool['fs'] = svc['hdp']

            self.pools.append(pool)

        LOG.debug("Configured pools: %(pool)s", {'pool': self.pools})

        evs_info = self.backend.get_evs_info()
        LOG.info(_LI("Configured EVSs: %(evs)s"), {'evs': evs_info})

        for svc in self.config['services'].keys():
            svc_ip = self.config['services'][svc]['iscsi_ip']
            if svc_ip in evs_info.keys():
                LOG.info(_LI("iSCSI portal found for service: %(svc_ip)s"),
                         {'svc_ip': svc_ip})
                self.config['services'][svc]['evs'] = (
                    evs_info[svc_ip]['evs_number'])
                self.config['services'][svc]['iscsi_port'] = '3260'
                self.config['services'][svc]['port'] = '0'
            else:
                LOG.error(_LE("iSCSI portal not found "
                              "for service: %(svc)s"), {'svc': svc_ip})
                raise exception.InvalidParameterValue(err=svc_ip)
        LOG.info(_LI("HNAS iSCSI Driver loaded successfully."))

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    @cinder_utils.trace
    def create_volume(self, volume):
        """Creates a LU on HNAS.

        :param volume: dictionary volume reference
        :returns: the volume provider location
        """
        fs = self._get_service(volume)
        size = six.text_type(volume.size)

        self.backend.create_lu(fs, size, volume.name)

        return {'provider_location': self._get_provider_location(volume)}

    @cinder_utils.trace
    def create_cloned_volume(self, dst, src):
        """Creates a clone of a volume.

        :param dst: dictionary destination volume reference
        :param src: dictionary source volume reference
        :returns: the provider location of the extended volume
        """
        fs_label = self._get_service(dst)

        self.backend.create_cloned_lu(src.name, fs_label, dst.name)

        if src.size < dst.size:
            LOG.debug("Increasing dest size from %(old_size)s to "
                      "%(new_size)s",
                      {'old_size': src.size, 'new_size': dst.size})
            self.extend_volume(dst, dst.size)

        return {'provider_location': self._get_provider_location(dst)}

    @cinder_utils.trace
    def extend_volume(self, volume, new_size):
        """Extends an existing volume.

       :param volume: dictionary volume reference
       :param new_size: int size in GB to extend
       """
        fs = self._get_service(volume)
        self.backend.extend_lu(fs, new_size, volume.name)

    @cinder_utils.trace
    def delete_volume(self, volume):
        """Deletes the volume on HNAS.

        :param volume: dictionary volume reference
        """
        fs = self._get_service(volume)
        self.backend.delete_lu(fs, volume.name)

    @cinder_utils.synchronized('volume_mapping')
    @cinder_utils.trace
    def initialize_connection(self, volume, connector):
        """Maps the created volume to connector['initiator'].

        :param volume: dictionary volume reference
        :param connector: dictionary connector reference
        :returns: The connection information
        :raises: ISCSITargetAttachFailed
        """
        service_info = self._get_service_target(volume)
        (ip, ipp, evs, port, _fs, tgtalias, secret) = service_info

        try:
            conn = self.backend.add_iscsi_conn(volume.name, _fs, port,
                                               tgtalias,
                                               connector['initiator'])

        except processutils.ProcessExecutionError:
            msg = (_("Error attaching volume %(vol)s. "
                     "Target limit might be reached!") % {'vol': volume.id})
            LOG.error(msg)
            raise exception.ISCSITargetAttachFailed(volume_id=volume.id)

        hnas_portal = ip + ':' + ipp
        lu_id = six.text_type(conn['lu_id'])
        fulliqn = conn['iqn']
        tgt = (hnas_portal + ',' + tgtalias + ',' +
               volume.provider_location + ',' + evs + ',' +
               port + ',' + lu_id)

        LOG.info(_LI("initiate: connection %(tgt)s"), {'tgt': tgt})

        properties = {}
        properties['provider_location'] = tgt
        properties['target_discovered'] = False
        properties['target_portal'] = hnas_portal
        properties['target_iqn'] = fulliqn
        properties['target_lu'] = int(lu_id)
        properties['volume_id'] = volume.id
        properties['auth_username'] = connector['initiator']

        if self.config['chap_enabled']:
            properties['auth_method'] = 'CHAP'
            properties['auth_password'] = secret

        conn_info = {'driver_volume_type': 'iscsi', 'data': properties}

        return conn_info

    @cinder_utils.synchronized('volume_mapping')
    @cinder_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate a connection to a volume.

        :param volume: dictionary volume reference
        :param connector: dictionary connector reference
        """
        service_info = self._get_service_target(volume)
        (ip, ipp, evs, port, fs, tgtalias, secret) = service_info
        lu_info = self.backend.check_lu(volume.name, fs)

        self.backend.del_iscsi_conn(evs, tgtalias, lu_info['id'])

    @cinder_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: dictionary volume reference
        :param snapshot: dictionary snapshot reference
        :returns: the provider location of the snapshot
        """
        fs = self._get_service(volume)

        self.backend.create_cloned_lu(snapshot.name, fs, volume.name)

        return {'provider_location': self._get_provider_location(snapshot)}

    @cinder_utils.trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: dictionary snapshot reference
        :returns: the provider location of the snapshot
        """
        fs = self._get_service(snapshot.volume)

        self.backend.create_cloned_lu(snapshot.volume_name, fs, snapshot.name)

        return {'provider_location': self._get_provider_location(snapshot)}

    @cinder_utils.trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

       :param snapshot: dictionary snapshot reference
       """
        fs = self._get_service(snapshot.volume)
        self.backend.delete_lu(fs, snapshot.name)

    def get_volume_stats(self, refresh=False):
        """Gets the volume driver stats.

        :param refresh: if refresh is True, the driver_stats is updated
        :returns: the driver stats
        """
        if refresh:
            self.driver_stats = self._get_stats()

        return self.driver_stats

    @cinder_utils.trace
    def manage_existing_get_size(self, volume, existing_vol_ref):
        """Gets the size to manage_existing.

        Returns the size of volume to be managed by manage_existing.

        :param volume: cinder volume to manage
        :param existing_vol_ref: existing volume to take under management
        :returns: the size of the volume to be managed or raises error
        :raises: ManageExistingInvalidReference
        """
        # Check if the reference is valid.
        if 'source-name' not in existing_vol_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_vol_ref, reason=reason)

        fs_label, vol_name = (
            self._get_info_from_vol_ref(existing_vol_ref['source-name']))

        LOG.debug("File System: %(fs_label)s "
                  "Volume name: %(vol_name)s.",
                  {'fs_label': fs_label, 'vol_name': vol_name})

        if utils.check_already_managed_volume(vol_name):
            raise exception.ManageExistingAlreadyManaged(volume_ref=vol_name)

        lu_info = self.backend.get_existing_lu_info(vol_name, fs_label)

        if lu_info != {}:
            return lu_info['size']
        else:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_vol_ref,
                reason=_('Volume not found on configured storage backend. '
                         'If your volume name contains "/", please rename it '
                         'and try to manage again.'))

    @cinder_utils.trace
    def manage_existing(self, volume, existing_vol_ref):
        """Manages an existing volume.

        The specified Cinder volume is to be taken into Cinder management.
        The driver will verify its existence and then rename it to the
        new Cinder volume name. It is expected that the existing volume
        reference is a File System and some volume_name;
        e.g., openstack/vol_to_manage

        :param volume:           cinder volume to manage
        :param existing_vol_ref: driver specific information used to identify a
                                 volume
        :returns: the provider location of the volume managed
        """
        LOG.info(_LI("Asked to manage ISCSI volume %(vol)s, with vol "
                     "ref %(ref)s."), {'vol': volume.id,
                                       'ref': existing_vol_ref['source-name']})

        fs_label, vol_name = (
            self._get_info_from_vol_ref(existing_vol_ref['source-name']))

        if volume.volume_type is not None:
            self._check_pool_and_fs(volume, fs_label)

        self.backend.rename_existing_lu(fs_label, vol_name, volume.name)

        LOG.info(_LI("Set newly managed Cinder volume name to %(name)s."),
                 {'name': volume.name})

        return {'provider_location': self._get_provider_location(volume)}

    @cinder_utils.trace
    def unmanage(self, volume):
        """Unmanages a volume from cinder.

        Removes the specified volume from Cinder management.
        Does not delete the underlying backend storage object. A log entry
        will be made to notify the admin that the volume is no longer being
        managed.

        :param volume: cinder volume to unmanage
        """
        fslabel = self._get_service(volume)
        new_name = 'unmanage-' + volume.name
        vol_path = fslabel + '/' + volume.name

        self.backend.rename_existing_lu(fslabel, volume.name, new_name)

        LOG.info(_LI("The volume with path %(old)s is no longer being managed "
                     "by Cinder. However, it was not deleted and can be found "
                     "with the new name %(cr)s on backend."),
                 {'old': vol_path, 'cr': new_name})

    def _get_provider_location(self, volume):
        """Gets the provider location of a given volume

        :param volume: dictionary volume reference
        :returns: the provider_location related to the volume
        """
        return self.backend.get_version()['mac'] + '.' + volume.name
