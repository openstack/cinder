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

import abc

from oslo_concurrency import processutils
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume.targets import driver
from cinder.volume import utils as vutils

LOG = logging.getLogger(__name__)


class ISCSITarget(driver.Target):
    """Target object for block storage devices.

    Base class for target object, where target
    is data transport mechanism (target) specific calls.
    This includes things like create targets, attach, detach
    etc.
    """

    def __init__(self, *args, **kwargs):
        super(ISCSITarget, self).__init__(*args, **kwargs)
        self.iscsi_target_prefix = \
            self.configuration.safe_get('target_prefix')
        self.iscsi_protocol = \
            self.configuration.safe_get('target_protocol')
        self.protocol = 'iSCSI'
        self.volumes_dir = self.configuration.safe_get('volumes_dir')

    def _get_iscsi_properties(self, volume, multipath=False):
        """Gets iscsi configuration

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in the
        future.

        The properties are:

        :target_discovered:    boolean indicating whether discovery was used

        :target_iqn:    the IQN of the iSCSI target

        :target_portal:    the portal of the iSCSI target

        :target_lun:    the lun of the iSCSI target

        :volume_id:    the uuid of the volume

        :auth_method:, :auth_username:, :auth_password:

            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.

        :discard:    boolean indicating if discard is supported

        In some of drivers that support multiple connections (for multipath
        and for single path with failover on connection failure), it returns
        :target_iqns, :target_portals, :target_luns, which contain lists of
        multiple values. The main portal information is also returned in
        :target_iqn, :target_portal, :target_lun for backward compatibility.

        Note that some of drivers don't return :target_portals even if they
        support multipath. Then the connector should use sendtargets discovery
        to find the other portals if it supports multipath.
        """

        properties = {}

        location = volume['provider_location']

        if location:
            # provider_location is the same format as iSCSI discovery output
            properties['target_discovered'] = False
        else:
            location = self._do_iscsi_discovery(volume)

            if not location:
                msg = (_("Could not find iSCSI export for volume %s") %
                        (volume['name']))
                raise exception.InvalidVolume(reason=msg)

            LOG.debug("ISCSI Discovery: Found %s", location)
            properties['target_discovered'] = True

        results = location.split(" ")
        portals = results[0].split(",")[0].split(";")
        iqn = results[1]
        nr_portals = len(portals)
        try:
            lun = int(results[2])
        except (IndexError, ValueError):
            # NOTE(jdg): The following is carried over from the existing
            # code.  The trick here is that different targets use different
            # default lun numbers, the base driver with tgtadm uses 1
            # others like LIO use 0.
            if (self.configuration.volume_driver ==
                    'cinder.volume.drivers.lvm.ThinLVMVolumeDriver' and
                    self.configuration.target_helper == 'tgtadm'):
                lun = 1
            else:
                lun = 0

        if nr_portals > 1 or multipath:
            properties['target_portals'] = portals
            properties['target_iqns'] = [iqn] * nr_portals
            properties['target_luns'] = [lun] * nr_portals
        properties['target_portal'] = portals[0]
        properties['target_iqn'] = iqn
        properties['target_lun'] = lun

        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        geometry = volume.get('provider_geometry', None)
        if geometry:
            (physical_block_size, logical_block_size) = geometry.split()
            properties['physical_block_size'] = physical_block_size
            properties['logical_block_size'] = logical_block_size

        encryption_key_id = volume.get('encryption_key_id', None)
        properties['encrypted'] = encryption_key_id is not None

        return properties

    def _iscsi_authentication(self, chap, name, password):
        return "%s %s %s" % (chap, name, password)

    def _do_iscsi_discovery(self, volume):
        # TODO(justinsb): Deprecate discovery and use stored info
        # NOTE(justinsb): Discovery won't work with CHAP-secured targets (?)
        LOG.warning("ISCSI provider_location not stored, using discovery")

        volume_id = volume['id']

        try:
            # NOTE(griff) We're doing the split straight away which should be
            # safe since using '@' in hostname is considered invalid

            (out, _err) = utils.execute('iscsiadm', '-m', 'discovery',
                                        '-t', 'sendtargets', '-p',
                                        volume['host'].split('@')[0],
                                        run_as_root=True)
        except processutils.ProcessExecutionError as ex:
            LOG.error("ISCSI discovery attempt failed for: %s",
                      volume['host'].split('@')[0])
            LOG.debug("Error from iscsiadm -m discovery: %s", ex.stderr)
            return None

        for target in out.splitlines():
            if (self.configuration.safe_get('target_ip_address') in target
                    and volume_id in target):
                return target
        return None

    def _get_portals_config(self):
        # Prepare portals configuration
        portals_ips = ([self.configuration.target_ip_address]
                       + self.configuration.iscsi_secondary_ip_addresses or [])

        return {'portals_ips': portals_ips,
                'portals_port': self.configuration.target_port}

    def create_export(self, context, volume, volume_path):
        """Creates an export for a logical volume."""
        # 'iscsi_name': 'iqn.2010-10.org.openstack:volume-00000001'
        iscsi_name = "%s%s" % (self.configuration.target_prefix,
                               volume['name'])
        iscsi_target, lun = self._get_target_and_lun(context, volume)

        # Verify we haven't setup a CHAP creds file already
        # if DNE no big deal, we'll just create it
        chap_auth = self._get_target_chap_auth(context, volume)
        if not chap_auth:
            chap_auth = (vutils.generate_username(),
                         vutils.generate_password())

        # Get portals ips and port
        portals_config = self._get_portals_config()

        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        tid = self.create_iscsi_target(iscsi_name,
                                       iscsi_target,
                                       lun,
                                       volume_path,
                                       chap_auth,
                                       **portals_config)
        data = {}
        data['location'] = self._iscsi_location(
            self.configuration.target_ip_address, tid, iscsi_name, lun,
            self.configuration.iscsi_secondary_ip_addresses)
        LOG.debug('Set provider_location to: %s', data['location'])
        data['auth'] = self._iscsi_authentication(
            'CHAP', *chap_auth)
        return data

    def remove_export(self, context, volume):
        try:
            iscsi_target, lun = self._get_target_and_lun(context, volume)
        except exception.NotFound:
            LOG.info("Skipping remove_export. No iscsi_target "
                     "provisioned for volume: %s", volume['id'])
            return
        try:

            # NOTE: provider_location may be unset if the volume hasn't
            # been exported
            location = volume['provider_location'].split(' ')
            iqn = location[1]

            # ietadm show will exit with an error
            # this export has already been removed
            self.show_target(iscsi_target, iqn=iqn)

        except Exception:
            LOG.info("Skipping remove_export. No iscsi_target "
                     "is presently exported for volume: %s", volume['id'])
            return

        # NOTE: For TgtAdm case volume['id'] is the ONLY param we need
        self.remove_iscsi_target(iscsi_target, lun, volume['id'],
                                 volume['name'])

    def ensure_export(self, context, volume, volume_path):
        """Recreates an export for a logical volume."""
        iscsi_name = "%s%s" % (self.configuration.target_prefix,
                               volume['name'])

        chap_auth = self._get_target_chap_auth(context, volume)

        # Get portals ips and port
        portals_config = self._get_portals_config()

        iscsi_target, lun = self._get_target_and_lun(context, volume)
        self.create_iscsi_target(
            iscsi_name, iscsi_target, lun, volume_path,
            chap_auth, check_exit_code=False,
            old_name=None, **portals_config)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': '9a0d35d0-175a-11e4-8c21-0800200c9a66',
                    'discard': False,
                }
            }
        """

        iscsi_properties = self._get_iscsi_properties(volume,
                                                      connector.get(
                                                          'multipath'))
        return {
            'driver_volume_type': self.iscsi_protocol,
            'data': iscsi_properties
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def validate_connector(self, connector):
        # NOTE(jdg): api passes in connector which is initiator info
        if 'initiator' not in connector:
            err_msg = ('The volume driver requires the iSCSI initiator '
                       'name in the connector.')
            LOG.error(err_msg)
            raise exception.InvalidConnectorException(missing='initiator')
        return True

    def _iscsi_location(self, ip, target, iqn, lun=None, ip_secondary=None):
        ip_secondary = ip_secondary or []
        port = self.configuration.target_port
        portals = map(lambda x: "%s:%s" % (vutils.sanitize_host(x), port),
                      [ip] + ip_secondary)
        return ("%(portals)s,%(target)s %(iqn)s %(lun)s"
                % ({'portals': ";".join(portals),
                    'target': target, 'iqn': iqn, 'lun': lun}))

    def show_target(self, iscsi_target, iqn, **kwargs):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.NotFound()

    def _get_target_chap_auth(self, context, volume):
        """Get the current chap auth username and password."""
        try:
            # Query DB to get latest state of volume
            volume_info = self.db.volume_get(context, volume['id'])
            # 'provider_auth': 'CHAP user_id password'
            if volume_info['provider_auth']:
                return tuple(volume_info['provider_auth'].split(' ', 3)[1:])
        except exception.NotFound:
            LOG.debug('Failed to get CHAP auth from DB for %s.', volume['id'])

    def extend_target(self, volume):
        """Reinitializes a target after the LV has been extended.

        Note: This will cause IO disruption in most cases.
        """
        iscsi_name = "%s%s" % (self.configuration.target_prefix,
                               volume['name'])

        if volume.volume_attachment:
            self._do_tgt_update(iscsi_name, force=True)

    @abc.abstractmethod
    def _get_target_and_lun(self, context, volume):
        """Get iscsi target and lun."""
        pass

    @abc.abstractmethod
    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth, **kwargs):
        pass

    @abc.abstractmethod
    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        pass

    @abc.abstractmethod
    def _get_iscsi_target(self, context, vol_id):
        pass

    @abc.abstractmethod
    def _get_target(self, iqn):
        pass

    def _do_tgt_update(self, name, force=False):
        pass


class SanISCSITarget(ISCSITarget):
    """iSCSI target for san devices.

    San devices are slightly different, they don't need to implement
    all of the same things that we need to implement locally fro LVM
    and local block devices when we create and manage our own targets.

    """
    @abc.abstractmethod
    def create_export(self, context, volume, volume_path):
        pass

    @abc.abstractmethod
    def remove_export(self, context, volume):
        pass

    @abc.abstractmethod
    def ensure_export(self, context, volume, volume_path):
        pass

    @abc.abstractmethod
    def terminate_connection(self, volume, connector, **kwargs):
        pass

    # NOTE(jdg): Items needed for local iSCSI target drivers,
    # but NOT sans Stub them out here to make abc happy

    # Use care when looking at these to make sure something
    # that's inheritted isn't dependent on one of
    # these.
    def _get_target_and_lun(self, context, volume):
        pass

    def _get_target_chap_auth(self, context, volume):
        pass

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth, **kwargs):
        pass

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        pass

    def _get_iscsi_target(self, context, vol_id):
        pass

    def _get_target(self, iqn):
        pass
