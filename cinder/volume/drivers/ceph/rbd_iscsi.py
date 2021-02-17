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
"""RADOS Block Device iSCSI Driver"""

from distutils import version

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import netutils

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration
from cinder.volume.drivers import rbd
from cinder.volume import volume_utils

try:
    import rbd_iscsi_client
    from rbd_iscsi_client import client
    from rbd_iscsi_client import exceptions as client_exceptions
except ImportError:
    rbd_iscsi_client = None
    client = None
    client_exceptions = None

LOG = logging.getLogger(__name__)

RBD_ISCSI_OPTS = [
    cfg.StrOpt('rbd_iscsi_api_user',
               default='',
               help='The username for the rbd_target_api service'),
    cfg.StrOpt('rbd_iscsi_api_password',
               default='',
               secret=True,
               help='The username for the rbd_target_api service'),
    cfg.StrOpt('rbd_iscsi_api_url',
               default='',
               help='The url to the rbd_target_api service'),
    cfg.BoolOpt('rbd_iscsi_api_debug',
                default=False,
                help='Enable client request debugging.'),
    cfg.StrOpt('rbd_iscsi_target_iqn',
               default=None,
               help='The preconfigured target_iqn on the iscsi gateway.'),
]

CONF = cfg.CONF
CONF.register_opts(RBD_ISCSI_OPTS, group=configuration.SHARED_CONF_GROUP)


MIN_CLIENT_VERSION = "0.1.8"


@interface.volumedriver
class RBDISCSIDriver(rbd.RBDDriver):
    """Implements RADOS block device (RBD) iSCSI volume commands."""

    VERSION = '1.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Cinder_Jenkins"

    SUPPORTS_ACTIVE_ACTIVE = True

    STORAGE_PROTOCOL = 'iSCSI'
    CHAP_LENGTH = 16

    # The target IQN to use for creating all exports
    # we map all the targets for OpenStack attaches to this.
    target_iqn = None

    def __init__(self, active_backend_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configuration.append_config_values(RBD_ISCSI_OPTS)

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'replication_device', 'reserved_percentage',
            'max_over_subscription_ratio', 'volume_dd_blocksize',
            'driver_ssl_cert_verify', 'suppress_requests_ssl_warnings')
        return rbd.RBD_OPTS + RBD_ISCSI_OPTS + additional_opts

    def _create_client(self):
        client_version = rbd_iscsi_client.version
        if (version.StrictVersion(client_version) <
                version.StrictVersion(MIN_CLIENT_VERSION)):
            ex_msg = (_('Invalid rbd_iscsi_client version found (%(found)s). '
                        'Version %(min)s or greater required. Run "pip'
                        ' install --upgrade rbd-iscsi-client" to upgrade'
                        ' the client.')
                      % {'found': client_version,
                         'min': MIN_CLIENT_VERSION})
            LOG.error(ex_msg)
            raise exception.InvalidInput(reason=ex_msg)

        config = self.configuration
        ssl_warn = config.safe_get('suppress_requests_ssl_warnings')
        cl = client.RBDISCSIClient(
            config.safe_get('rbd_iscsi_api_user'),
            config.safe_get('rbd_iscsi_api_password'),
            config.safe_get('rbd_iscsi_api_url'),
            secure=config.safe_get('driver_ssl_cert_verify'),
            suppress_ssl_warnings=ssl_warn
        )

        return cl

    def _is_status_200(self, response):
        return (response and 'status' in response and
                response['status'] == '200')

    def do_setup(self, context):
        """Perform initialization steps that could raise exceptions."""
        super(RBDISCSIDriver, self).do_setup(context)
        if client is None:
            msg = _("You must install rbd-iscsi-client python package "
                    "before using this driver.")
            raise exception.VolumeDriverException(data=msg)

        # Make sure we have the basic settings we need to talk to the
        # iscsi api service
        config = self.configuration
        self.client = self._create_client()
        self.client.set_debug_flag(config.safe_get('rbd_iscsi_api_debug'))
        resp, body = self.client.get_api()
        if not self._is_status_200(resp):
            # failed to fetch the open api url
            raise exception.InvalidConfigurationValue(
                option='rbd_iscsi_api_url',
                value='Could not talk to the rbd-target-api')

        # The admin had to have setup a target_iqn in the iscsi gateway
        # already in order for the gateways to work properly
        self.target_iqn = self.configuration.safe_get('rbd_iscsi_target_iqn')
        LOG.info("Using target_iqn '%s'", self.target_iqn)

    def check_for_setup_error(self):
        """Return an error if prerequisites aren't met."""
        super(RBDISCSIDriver, self).check_for_setup_error()

        required_options = ['rbd_iscsi_api_user',
                            'rbd_iscsi_api_password',
                            'rbd_iscsi_api_url',
                            'rbd_iscsi_target_iqn']

        for attr in required_options:
            val = getattr(self.configuration, attr)
            if not val:
                raise exception.InvalidConfigurationValue(option=attr,
                                                          value=val)

    def _get_clients(self):
        # make sure we have
        resp, body = self.client.get_clients(self.target_iqn)
        if not self._is_status_200(resp):
            msg = _("Failed to get_clients() from rbd-target-api")
            raise exception.VolumeBackendAPIException(data=msg)
        return body

    def _get_config(self):
        resp, body = self.client.get_config()
        if not self._is_status_200(resp):
            msg = _("Failed to get_config() from rbd-target-api")
            raise exception.VolumeBackendAPIException(data=msg)
        return body

    def _get_disks(self):
        resp, disks = self.client.get_disks()
        if not self._is_status_200(resp):
            msg = _("Failed to get_disks() from rbd-target-api")
            raise exception.VolumeBackendAPIException(data=msg)
        return disks

    def create_client(self, initiator_iqn):
        """Create a client iqn on the gateway if it doesn't exist."""
        client = self._get_target_client(initiator_iqn)
        if not client:
            try:
                self.client.create_client(self.target_iqn,
                                          initiator_iqn)
            except client_exceptions.ClientException as ex:
                raise exception.VolumeBackendAPIException(
                    data=ex.get_description())

    def _get_target_client(self, initiator_iqn):
        """Get the config information for a client defined to a target."""
        config = self._get_config()
        target_config = config['targets'][self.target_iqn]
        if initiator_iqn in target_config['clients']:
            return target_config['clients'][initiator_iqn]

    def _get_auth_for_client(self, initiator_iqn):
        initiator_config = self._get_target_client(initiator_iqn)
        if initiator_config:
            auth = initiator_config['auth']
            return auth

    def _set_chap_for_client(self, initiator_iqn, username, password):
        """Save the CHAP creds in the client on the gateway."""
        # username is 8-64 chars
        # Password has to be 12-16 chars
        LOG.debug("Setting chap creds to %(user)s : %(pass)s",
                  {'user': username, 'pass': password})
        try:
            self.client.set_client_auth(self.target_iqn,
                                        initiator_iqn,
                                        username,
                                        password)
        except client_exceptions.ClientException as ex:
            raise exception.VolumeBackendAPIException(
                data=ex.get_description())

    def _get_lun(self, iscsi_config, lun_name, initiator_iqn):
        lun = None
        target_info = iscsi_config['targets'][self.target_iqn]
        luns = target_info['clients'][initiator_iqn]['luns']
        if lun_name in luns:
            lun = {'name': lun_name,
                   'id': luns[lun_name]['lun_id']}

        return lun

    def _lun_name(self, volume_name):
        """Build the iscsi gateway lun name."""
        return ("%(pool)s/%(volume_name)s" %
                {'pool': self.configuration.rbd_pool,
                 'volume_name': volume_name})

    def get_existing_disks(self):
        """Get the existing list of registered volumes on the gateway."""
        resp, disks = self.client.get_disks()
        return disks['disks']

    @volume_utils.trace
    def create_disk(self, volume_name):
        """Register the volume with the iscsi gateways.

        We have to register the volume with the iscsi gateway.
        Exporting the volume won't work unless the gateway knows
        about it.
        """
        try:
            self.client.find_disk(self.configuration.rbd_pool,
                                  volume_name)
        except client_exceptions.HTTPNotFound:
            try:
                # disk isn't known by the gateways, so lets add it.
                self.client.create_disk(self.configuration.rbd_pool,
                                        volume_name)
            except client_exceptions.ClientException as ex:
                LOG.exception("Couldn't create the disk entry to "
                              "export the volume.")
                raise exception.VolumeBackendAPIException(
                    data=ex.get_description())

    @volume_utils.trace
    def register_disk(self, target_iqn, volume_name):
        """Register the disk with the target_iqn."""
        lun_name = self._lun_name(volume_name)
        try:
            self.client.register_disk(target_iqn, lun_name)
        except client_exceptions.HTTPBadRequest as ex:
            desc = ex.get_description()
            search_str = ('is already mapped on target %(target_iqn)s' %
                          {'target_iqn': self.target_iqn})
            if desc.find(search_str):
                # The volume is already registered
                return
            else:
                LOG.error("Couldn't register the volume to the target_iqn")
                raise exception.VolumeBackendAPIException(
                    data=ex.get_description())
        except client_exceptions.ClientException as ex:
            LOG.exception("Couldn't register the volume to the target_iqn",
                          ex)
            raise exception.VolumeBackendAPIException(
                data=ex.get_description())

    @volume_utils.trace
    def unregister_disk(self, target_iqn, volume_name):
        """Unregister the volume from the gateway."""
        lun_name = self._lun_name(volume_name)
        try:
            self.client.unregister_disk(target_iqn, lun_name)
        except client_exceptions.ClientException as ex:
            LOG.exception("Couldn't unregister the volume to the target_iqn",
                          ex)
            raise exception.VolumeBackendAPIException(
                data=ex.get_description())

    @volume_utils.trace
    def export_disk(self, initiator_iqn, volume_name, iscsi_config):
        """Export a volume to an initiator."""
        lun_name = self._lun_name(volume_name)
        LOG.debug("Export lun %(lun)s", {'lun': lun_name})
        lun = self._get_lun(iscsi_config, lun_name, initiator_iqn)
        if lun:
            LOG.debug("Found existing lun export.")
            return lun

        try:
            LOG.debug("Creating new lun export for %(lun)s",
                      {'lun': lun_name})
            self.client.export_disk(self.target_iqn, initiator_iqn,
                                    self.configuration.rbd_pool,
                                    volume_name)

            resp, iscsi_config = self.client.get_config()
            return self._get_lun(iscsi_config, lun_name, initiator_iqn)
        except client_exceptions.ClientException as ex:
            raise exception.VolumeBackendAPIException(
                data=ex.get_description())

    @volume_utils.trace
    def unexport_disk(self, initiator_iqn, volume_name, iscsi_config):
        """Remove a volume from an initiator."""
        lun_name = self._lun_name(volume_name)
        LOG.debug("unexport lun %(lun)s", {'lun': lun_name})
        lun = self._get_lun(iscsi_config, lun_name, initiator_iqn)
        if not lun:
            LOG.debug("Didn't find LUN on gateway.")
            return

        try:
            LOG.debug("unexporting %(lun)s", {'lun': lun_name})
            self.client.unexport_disk(self.target_iqn, initiator_iqn,
                                      self.configuration.rbd_pool,
                                      volume_name)
        except client_exceptions.ClientException as ex:
            LOG.exception(ex)
            raise exception.VolumeBackendAPIException(
                data=ex.get_description())

    def find_client_luns(self, target_iqn, client_iqn, iscsi_config):
        """Find luns already exported to an initiator."""
        if 'targets' in iscsi_config:
            if target_iqn in iscsi_config['targets']:
                target_info = iscsi_config['targets'][target_iqn]
                if 'clients' in target_info:
                    clients = target_info['clients']
                    client = clients[client_iqn]
                    luns = client['luns']
                    return luns

    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        """Export a volume to a host."""
        # create client
        initiator_iqn = connector['initiator']
        self.create_client(initiator_iqn)
        auth = self._get_auth_for_client(initiator_iqn)
        username = initiator_iqn
        if not auth['password']:
            password = volume_utils.generate_password(length=self.CHAP_LENGTH)
            self._set_chap_for_client(initiator_iqn, username, password)
        else:
            LOG.debug("using existing CHAP password")
            password = auth['password']

        # add disk for export
        iscsi_config = self._get_config()

        # First have to ensure that the disk is registered with
        # the gateways.
        self.create_disk(volume.name)
        self.register_disk(self.target_iqn, volume.name)

        iscsi_config = self._get_config()
        # Now export the disk to the initiator
        lun = self.export_disk(initiator_iqn, volume.name, iscsi_config)

        # fetch the updated config so we can get the lun id
        iscsi_config = self._get_config()
        target_info = iscsi_config['targets'][self.target_iqn]
        ips = target_info['ip_list']

        target_portal = ips[0]
        if netutils.is_valid_ipv6(target_portal):
            target_portal = "[%s]:3260" % target_portal
        else:
            target_portal = "%s:3260" % target_portal

        data = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': self.target_iqn,
                'target_portal': target_portal,
                'target_lun': lun['id'],
                'auth_method': 'CHAP',
                'auth_username': username,
                'auth_password': password,
            }
        }
        return data

    def _delete_disk(self, volume):
        """Remove the defined disk from the gateway."""

        # We only do this when we know it's not exported
        # anywhere in the gateway
        lun_name = self._lun_name(volume.name)
        config = self._get_config()

        # Now look for the disk on any exported target
        found = False
        for target_iqn in config['targets']:
            # Do we have the volume we are looking for?
            target = config['targets'][target_iqn]
            for client_iqn in target['clients'].keys():
                if lun_name in target['clients'][client_iqn]['luns']:
                    found = True

        if not found:
            # we can delete the disk definition
            LOG.info("Deleting volume definition in iscsi gateway for %s",
                     lun_name)
            self.client.delete_disk(self.configuration.rbd_pool, volume.name,
                                    preserve_image=True)

    def _terminate_connection(self, volume, initiator_iqn, target_iqn,
                              iscsi_config):
        # remove the disk from the client.
        self.unexport_disk(initiator_iqn, volume.name, iscsi_config)

        # Try to unregister the disk, since nobody is using it.
        self.unregister_disk(self.target_iqn, volume.name)

        config = self._get_config()

        # If there are no more luns exported to this initiator
        # then delete the initiator
        luns = self.find_client_luns(target_iqn, initiator_iqn, config)
        if not luns:
            LOG.debug("There aren't any more LUNs attached to %(iqn)s."
                      "So we unregister the volume and delete "
                      "the client entry",
                      {'iqn': initiator_iqn})

            try:
                self.client.delete_client(target_iqn, initiator_iqn)
            except client_exceptions.ClientException:
                LOG.warning("Tried to delete initiator %(iqn)s, but delete "
                            "failed.", {'iqns': initiator_iqn})

    def _terminate_all(self, volume, iscsi_config):
        """Find all exports of this volume for our target_iqn and detach."""
        disks = self._get_disks()
        lun_name = self._lun_name(volume.name)
        if lun_name not in disks['disks']:
            LOG.debug("Volume %s not attached anywhere.", lun_name)
            return

        for target_iqn_tmp in iscsi_config['targets']:
            if self.target_iqn != target_iqn_tmp:
                # We don't touch exports for targets
                # we aren't configured to manage.
                continue

            target = iscsi_config['targets'][self.target_iqn]
            for client_iqn in target['clients'].keys():
                if lun_name in target['clients'][client_iqn]['luns']:
                    self._terminate_connection(volume, client_iqn,
                                               self.target_iqn,
                                               iscsi_config)

        self._delete_disk(volume)

    @volume_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Unexport the volume from the gateway."""
        iscsi_config = self._get_config()

        if not connector:
            # No connector was passed in, so this is a force detach
            # we need to detach the volume from the configured target_iqn.
            self._terminate_all(volume, iscsi_config)

        initiator_iqn = connector['initiator']
        self._terminate_connection(volume, initiator_iqn, self.target_iqn,
                                   iscsi_config)
        self._delete_disk(volume)
