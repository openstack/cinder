#    Copyright (c) 2020 Open-E, Inc.
#    All Rights Reserved.
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

"""iSCSI volume driver for JovianDSS driver."""
import math
import string

from oslo_log import log as logging
from oslo_utils import units as o_units

from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.open_e.jovian_common import driver as jdriver
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import jdss_common as jcom
from cinder.volume.drivers.open_e.jovian_common import rest
from cinder.volume.drivers.open_e import options
from cinder.volume.drivers.san import san
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)


@interface.volumedriver
class JovianISCSIDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Open-E JovianDSS.

    Version history:

    .. code-block:: none

        1.0.0 - Open-E JovianDSS driver with basic functionality
        1.0.1 - Added certificate support
                Added revert to snapshot support
        1.0.2 - Added multi-attach support
                Added 16K block support
        1.0.3 - Driver rework and optimisation
                Abandon recursive volume deletion
                Removed revert to snapshot support
 """

    # Third-party Systems wiki page
    CI_WIKI_NAME = "Open-E_JovianDSS_CI"
    VERSION = "1.0.3"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._stats = None
        self.jovian_iscsi_target_portal_port = "3260"
        self.jovian_target_prefix = 'iqn.2020-04.com.open-e.cinder:'
        self.jovian_chap_pass_len = 12
        self.jovian_sparse = False
        self.jovian_ignore_tpath = None
        self.jovian_hosts = None
        self._pool = 'Pool-0'
        self.ra = None
        self.driver = None

    @property
    def backend_name(self):
        """Return backend name."""
        backend_name = None
        if self.configuration:
            backend_name = self.configuration.get('volume_backend_name',
                                                  'Open-EJovianDSS')
        if not backend_name:
            backend_name = self.__class__.__name__
        return backend_name

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self.configuration.append_config_values(
            options.jdss_connection_opts)
        self.configuration.append_config_values(
            options.jdss_iscsi_opts)
        self.configuration.append_config_values(
            options.jdss_volume_opts)
        self.configuration.append_config_values(san.san_opts)

        self.jovian_target_prefix = self.configuration.get(
            'target_prefix',
            'iqn.2020-04.com.open-e.cinder:')
        self.jovian_chap_pass_len = self.configuration.get(
            'chap_password_len', 12)
        self.block_size = (
            self.configuration.get('jovian_block_size', '64K'))
        self.jovian_sparse = (
            self.configuration.get('san_thin_provision', True))
        self.jovian_ignore_tpath = self.configuration.get(
            'jovian_ignore_tpath', None)
        self.jovian_hosts = self.configuration.get(
            'san_hosts', [])

        self.ra = rest.JovianRESTAPI(self.configuration)
        self.driver = jdriver.JovianDSSDriver(self.configuration)

    def check_for_setup_error(self):
        """Check for setup error."""
        if len(self.jovian_hosts) == 0:
            msg = _("No hosts provided in configuration")
            raise exception.VolumeDriverException(msg)

        if not self.driver.rest_config_is_ok():
            msg = (_("Unable to identify pool %s") % self._pool)
            raise exception.VolumeDriverException(msg)

        valid_bsize = ['16K', '32K', '64K', '128K', '256K', '512K', '1M']
        if self.block_size not in valid_bsize:
            raise exception.InvalidConfigurationValue(
                value=self.block_size,
                option='jovian_block_size')

    def _get_target_name(self, volume_name):
        """Return iSCSI target name to access volume."""
        return f'{self.jovian_target_prefix}{volume_name}'

    def _get_active_ifaces(self):
        """Return list of ip addresses for iSCSI connection"""

        return self.jovian_hosts

    def create_volume(self, volume):
        """Create a volume.

        :param volume: volume reference
        :return: model update dict for volume reference
        """
        LOG.debug('creating volume %s.', volume.id)

        try:
            self.driver.create_volume(volume.id,
                                      volume.size,
                                      sparse=self.jovian_sparse,
                                      block_size=self.block_size)

        except jexc.JDSSException as jerr:
            LOG.error("Create volume error. Because %(err)s",
                      {"err": jerr})
            raise exception.VolumeBackendAPIException(
                _('Failed to create volume %s.') % volume.id) from jerr

        return self._get_provider_info(volume.id)

    def delete_volume(self, volume, cascade=False):
        """Delete volume

        :param volume: volume reference
        :param cascade: remove snapshots of a volume as well
        """

        try:
            self.driver.delete_volume(volume.id, cascade=cascade)
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: volume reference
        :param new_size: volume new size in GB
        """

        try:
            self.driver.resize_volume(volume.id, new_size)
        except jexc.JDSSException as jerr:
            msg = _('Failed to extend volume %s.')
            raise exception.VolumeBackendAPIException(
                data=msg % volume.id) from jerr

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume.

        :param volume: new volume reference
        :param src_vref: source volume reference
        """

        try:
            self.driver.create_cloned_volume(volume.id,
                                             src_vref.id,
                                             volume.size,
                                             sparse=self.jovian_sparse)
        except jexc.JDSSException as jerr:
            msg = _("Fail to clone volume %(vol)s to %(clone)s because of "
                    "error %(err)s.") % {
                'vol': src_vref.id,
                'clone': volume.id,
                'err': jerr}
            raise exception.VolumeBackendAPIException(msg) from jerr

        return self._get_provider_info(volume.id)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        """
        LOG.debug('create volume %(vol)s from snapshot %(snap)s', {
            'vol': volume.id,
            'snap': snapshot.id})

        try:
            self.driver.create_cloned_volume(volume.id,
                                             snapshot.volume_id,
                                             volume.size,
                                             snapshot_name=snapshot.id)
        except jexc.JDSSResourceExistsException as jerr:
            raise exception.Duplicate() from jerr
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(
                _("Failed to create clone %(clone)s from snapshot %(snap)s "
                  "of volume %(vol)s because of error %(err)s.") % {
                    'vol': snapshot.volume_id,
                    'clone': volume.id,
                    'snap': snapshot.id,
                    'err': jerr}) from jerr

        return self._get_provider_info(volume.id)

    def create_snapshot(self, snapshot):
        """Create snapshot of existing volume.

        :param snapshot: snapshot object
        """
        LOG.debug('create snapshot %(snap)s for volume %(vol)s', {
            'snap': snapshot.id,
            'vol': snapshot.volume_id})

        try:
            self.driver.create_snapshot(snapshot.id, snapshot.volume_id)
        except jexc.JDSSSnapshotExistsException as jexistserr:
            raise exception.Duplicate() from jexistserr
        except jexc.JDSSResourceNotFoundException as jerrnotfound:
            raise exception.VolumeNotFound(
                volume_id=jcom.idname(snapshot.volume_id)) from jerrnotfound
        except jexc.JDSSException as jerr:
            args = {'snapshot': snapshot.id,
                    'object': snapshot.volume_id,
                    'err': jerr}
            msg = (_('Failed to create tmp snapshot %(snapshot)s '
                     'for object %(object)s: %(err)s') % args)
            raise exception.VolumeBackendAPIException(msg) from jerr

        return self._get_provider_info(snapshot.id)

    def delete_snapshot(self, snapshot):
        """Delete snapshot of existing volume.

        :param snapshot: snapshot reference
        """

        try:
            self.driver.delete_snapshot(snapshot.volume_id, snapshot.id)
        except jexc.JDSSResourceNotFoundException:
            return
        except jexc.JDSSException as jerr:
            raise exception.VolumeBackendAPIException(jerr)

    def _get_provider_info(self, vid):
        '''returns provider info dict

        :param vid: volume id
        '''

        info = {}
        try:
            info['provider_location'] = self.driver.get_provider_location(vid)
        except jexc.JDSSException as jerr:
            msg = _("Fail to identify critical properties of "
                    "new volume %s.") % vid
            raise exception.VolumeBackendAPIException(data=msg) from jerr

        info['provider_auth'] = self._get_provider_auth()

        return info

    def _get_provider_auth(self):
        """Get provider authentication for the volume.

        :return: string of auth method and credentials
        """
        chap_user = volume_utils.generate_password(
            length=8,
            symbolgroups=(string.ascii_lowercase +
                          string.ascii_uppercase))

        chap_password = volume_utils.generate_password(
            length=self.jovian_chap_pass_len,
            symbolgroups=(string.ascii_lowercase +
                          string.ascii_uppercase + string.digits))

        return 'CHAP %(user)s %(passwd)s' % {
            'user': chap_user, 'passwd': chap_password}

    def create_export(self, _ctx, volume, connector):
        """Create new export for zvol.

        :param volume: reference of volume to be exported
        :return: iscsiadm-formatted provider location string
        """
        LOG.debug("create export for volume: %s.", volume.id)

        provider_auth = volume.provider_auth
        ret = dict()

        if provider_auth is None:
            provider_auth = self._get_provider_auth()
            ret['provider_auth'] = provider_auth

        try:
            self.driver.ensure_export(volume.id, provider_auth)
            location = self.driver.get_provider_location(volume.id)
            ret['provider_location'] = location
        except jexc.JDSSException as jerr:
            raise exception.VolumeDriverException from jerr

        return ret

    def ensure_export(self, _ctx, volume):
        """Recreate parts of export if necessary.

        :param volume: reference of volume to be exported
        """
        LOG.debug("ensure export for volume: %s.", volume.id)
        provider_auth = volume.provider_auth
        ret = dict()

        if provider_auth is None:
            provider_auth = self._get_provider_auth()
            ret['provider_auth'] = provider_auth
        try:
            self.driver.ensure_export(volume.id, provider_auth)
            location = self.driver.get_provider_location(volume.id)
            ret['provider_location'] = location
        except jexc.JDSSException as jerr:
            raise exception.VolumeDriverException from jerr
        return ret

    def create_export_snapshot(self, context, snapshot, connector):
        provider_auth = snapshot.provider_auth
        ret = dict()

        if provider_auth is None:
            provider_auth = self._get_provider_auth()
            ret['provider_auth'] = provider_auth
        try:
            ret = self.driver.create_export_snapshot(snapshot.id,
                                                     snapshot.volume_id,
                                                     provider_auth)
        except jexc.JDSSResourceExistsException as jres_err:
            raise exception.Duplicate() from jres_err
        except jexc.JDSSException as jerr:
            raise exception.VolumeDriverException from jerr
        return ret

    def remove_export(self, _ctx, volume):
        """Destroy all resources created to export zvol.

        :param volume: reference of volume to be unexposed
        """
        LOG.debug("remove_export for volume: %s.", volume.id)

        try:
            self.driver.remove_export(volume.id)
        except jexc.JDSSException as jerr:
            raise exception.VolumeDriverException from jerr

    def remove_export_snapshot(self, context, snapshot):
        try:
            self.driver.remove_export_snapshot(snapshot.id,
                                               snapshot.volume_id)
        except jexc.JDSSException as jerr:
            raise exception.VolumeDriverException from jerr

    def _update_volume_stats(self):
        """Retrieve stats info."""
        LOG.debug('Updating volume stats')

        pool_stats = self.ra.get_pool_stats()
        total_capacity = math.floor(int(pool_stats["size"]) / o_units.Gi)
        free_capacity = math.floor(int(pool_stats["available"]) / o_units.Gi)

        reserved_percentage = (
            self.configuration.get('reserved_percentage', 0))

        if total_capacity is None:
            total_capacity = 'unknown'
        if free_capacity is None:
            free_capacity = 'unknown'

        location_info = '%(driver)s:%(host)s:%(volume)s' % {
            'driver': self.__class__.__name__,
            'host': self.ra.get_active_host(),
            'volume': self._pool
        }

        self._stats = {
            'vendor_name': 'Open-E',
            'driver_version': self.VERSION,
            'storage_protocol': constants.ISCSI,
            'total_capacity_gb': total_capacity,
            'free_capacity_gb': free_capacity,
            'reserved_percentage': int(reserved_percentage),
            'volume_backend_name': self.backend_name,
            'QoS_support': False,
            'location_info': location_info,
            'multiattach': True
        }

        LOG.debug('Total capacity: %d, '
                  'Free %d.',
                  self._stats['total_capacity_gb'],
                  self._stats['free_capacity_gb'])

    def _get_iscsi_properties(self, volume_id, provider_auth,
                              multipath=False):
        """Return dict according to cinder/driver.py implementation.

        :param volume_id: openstack volume UUID
        :param str provider_auth: space-separated triple
              '<auth method> <auth username> <auth password>'
        :param bool multipath: use multipath flag
        :return:
        """
        tname = self.jovian_target_prefix + volume_id
        iface_info = []
        if multipath:
            iface_info = self._get_active_ifaces()
            if not iface_info:
                raise exception.InvalidConfigurationValue(
                    _('No available interfaces '
                      'or config excludes them'))

        iscsi_properties = {}

        if multipath:
            iscsi_properties['target_iqns'] = []
            iscsi_properties['target_portals'] = []
            iscsi_properties['target_luns'] = []
            LOG.debug('tpaths %s.', iface_info)
            for iface in iface_info:
                iscsi_properties['target_iqns'].append(
                    self.jovian_target_prefix +
                    volume_id)
                iscsi_properties['target_portals'].append(
                    iface +
                    ":" +
                    str(self.jovian_iscsi_target_portal_port))
                iscsi_properties['target_luns'].append(0)
        else:
            iscsi_properties['target_iqn'] = tname
            iscsi_properties['target_portal'] = (
                self.ra.get_active_host() +
                ":" +
                str(self.jovian_iscsi_target_portal_port))

        iscsi_properties['target_discovered'] = False

        if provider_auth is None:
            provider_auth = self._get_provider_auth()

        (auth_method, auth_username, auth_secret) = provider_auth.split()

        iscsi_properties['auth_method'] = auth_method
        iscsi_properties['auth_username'] = auth_username
        iscsi_properties['auth_password'] = auth_secret

        iscsi_properties['target_lun'] = 0
        return iscsi_properties

    def initialize_connection(self, volume, connector):
        """Initialize the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        Format of the driver data is defined in _get_iscsi_properties.
        Example return value:
        .. code-block:: json
            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': '12345678-1234-1234-1234-123456789012',
                }
            }
        """
        multipath = connector.get("multipath", False)

        provider_auth = volume.provider_auth

        ret = {
            'driver_volume_type': 'iscsi',
            'data': None,
        }

        try:
            self.driver.initialize_connection(volume.id,
                                              provider_auth,
                                              multipath=multipath)
            ret['data'] = self._get_iscsi_properties(volume.id,
                                                     provider_auth,
                                                     multipath=multipath)
        except jexc.JDSSException as jerr:
            raise exception.VolumeDriverException from jerr
        return ret

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """terminate_connection

        """

        LOG.debug("terminate connection for %(volume)s ",
                  {'volume': volume.id})

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        multipath = connector.get("multipath", False)

        provider_auth = snapshot.provider_auth

        ret = {
            'driver_volume_type': 'iscsi',
            'data': None,
        }

        try:
            self.driver.initialize_connection(snapshot.volume_id,
                                              provider_auth,
                                              snapshot_id=snapshot.id,
                                              multipath=multipath)
            ret['data'] = self._get_iscsi_properties(snapshot.id,
                                                     provider_auth,
                                                     multipath=multipath)
        except jexc.JDSSException as jerr:
            raise exception.VolumeDriverException from jerr

        return ret

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        pass
