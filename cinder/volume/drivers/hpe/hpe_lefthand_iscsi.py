#    (c) Copyright 2014-2016 Hewlett Packard Enterprise Development LP
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
#
"""HPE LeftHand SAN ISCSI REST Proxy.

Volume driver for HPE LeftHand Storage array.
This driver requires 11.5 or greater firmware on the LeftHand array, using
the 2.0 or greater version of the hpelefthandclient.

You will need to install the python hpelefthandclient module.
sudo pip install python-lefthandclient

Set the following in the cinder.conf file to enable the
LeftHand iSCSI REST Driver along with the required flags:

volume_driver=cinder.volume.drivers.hpe.hpe_lefthand_iscsi.
    HPELeftHandISCSIDriver

It also requires the setting of hpelefthand_api_url, hpelefthand_username,
hpelefthand_password for credentials to talk to the REST service on the
LeftHand array.

"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import units

from cinder import context
from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.objects import fields
from cinder import utils as cinder_utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import utils
from cinder.volume import volume_types

import math
import re
import six

LOG = logging.getLogger(__name__)

hpelefthandclient = importutils.try_import("hpelefthandclient")
if hpelefthandclient:
    from hpelefthandclient import client as hpe_lh_client
    from hpelefthandclient import exceptions as hpeexceptions

hpelefthand_opts = [
    cfg.URIOpt('hpelefthand_api_url',
               default=None,
               help="HPE LeftHand WSAPI Server Url like "
                    "https://<LeftHand ip>:8081/lhos",
               deprecated_name='hplefthand_api_url'),
    cfg.StrOpt('hpelefthand_username',
               default=None,
               help="HPE LeftHand Super user username",
               deprecated_name='hplefthand_username'),
    cfg.StrOpt('hpelefthand_password',
               default=None,
               help="HPE LeftHand Super user password",
               secret=True,
               deprecated_name='hplefthand_password'),
    cfg.StrOpt('hpelefthand_clustername',
               default=None,
               help="HPE LeftHand cluster name",
               deprecated_name='hplefthand_clustername'),
    cfg.BoolOpt('hpelefthand_iscsi_chap_enabled',
                default=False,
                help='Configure CHAP authentication for iSCSI connections '
                '(Default: Disabled)',
                deprecated_name='hplefthand_iscsi_chap_enabled'),
    cfg.BoolOpt('hpelefthand_debug',
                default=False,
                help="Enable HTTP debugging to LeftHand",
                deprecated_name='hplefthand_debug'),
    cfg.PortOpt('hpelefthand_ssh_port',
                default=16022,
                help="Port number of SSH service."),

]

CONF = cfg.CONF
CONF.register_opts(hpelefthand_opts, group=configuration.SHARED_CONF_GROUP)

MIN_API_VERSION = "1.1"
MIN_CLIENT_VERSION = '2.1.0'

# map the extra spec key to the REST client option key
extra_specs_key_map = {
    'hpelh:provisioning': 'isThinProvisioned',
    'hpelh:ao': 'isAdaptiveOptimizationEnabled',
    'hpelh:data_pl': 'dataProtectionLevel',
    'hplh:provisioning': 'isThinProvisioned',
    'hplh:ao': 'isAdaptiveOptimizationEnabled',
    'hplh:data_pl': 'dataProtectionLevel',
}

# map the extra spec value to the REST client option value
extra_specs_value_map = {
    'isThinProvisioned': {'thin': True, 'full': False},
    'isAdaptiveOptimizationEnabled': {'true': True, 'false': False},
    'dataProtectionLevel': {
        'r-0': 0, 'r-5': 1, 'r-10-2': 2, 'r-10-3': 3, 'r-10-4': 4, 'r-6': 5}
}

extra_specs_default_key_value_map = {
    'hpelh:provisioning': 'thin',
    'hpelh:ao': 'true',
    'hpelh:data_pl': 'r-0'
}


@interface.volumedriver
class HPELeftHandISCSIDriver(driver.ISCSIDriver):
    """Executes REST commands relating to HPE/LeftHand SAN ISCSI volumes.

    Version history:

    .. code-block:: none

        1.0.0 - Initial REST iSCSI proxy
        1.0.1 - Added support for retype
        1.0.2 - Added support for volume migrate
        1.0.3 - Fixed bug #1285829, HP LeftHand backend assisted migration
                should check for snapshots
        1.0.4 - Fixed bug #1285925, LeftHand AO volume create performance
                improvement
        1.0.5 - Fixed bug #1311350, Live-migration of an instance when
                attached to a volume was causing an error.
        1.0.6 - Removing locks bug #1395953
        1.0.7 - Fixed bug #1353137, Server was not removed from the HP
                Lefthand backend after the last volume was detached.
        1.0.8 - Fixed bug #1418201, A cloned volume fails to attach.
        1.0.9 - Adding support for manage/unmanage.
        1.0.10 - Add stats for goodness_function and filter_function
        1.0.11 - Add over subscription support
        1.0.12 - Adds consistency group support
        1.0.13 - Added update_migrated_volume #1493546
        1.0.14 - Removed the old CLIQ based driver
        2.0.0 - Rebranded HP to HPE
        2.0.1 - Remove db access for consistency groups
        2.0.2 - Adds v2 managed replication support
        2.0.3 - Adds v2 unmanaged replication support
        2.0.4 - Add manage/unmanage snapshot support
        2.0.5 - Changed minimum client version to be 2.1.0
        2.0.6 - Update replication to version 2.1
        2.0.7 - Fixed bug #1554746, Create clone volume with new size.
        2.0.8 - Add defaults for creating a replication client, bug #1556331
        2.0.9 - Fix terminate connection on failover
        2.0.10 - Add entry point tracing
        2.0.11 - Fix extend volume if larger than snapshot bug #1560654
        2.0.12 - add CG capability to generic volume groups.
        2.0.13 - Fix cloning operation related to provisioning, bug #1688243
        2.0.14 - Fixed bug #1710072, Volume doesn't show expected parameters
                 after Retype
        2.0.15 - Fixed bug #1710098, Managed volume, does not pick up the extra
                 specs/capabilities of the selected volume type.
        2.0.16 - Handled concurrent attachment requests. bug #1779654
    """

    VERSION = "2.0.16"

    CI_WIKI_NAME = "HPE_Storage_CI"

    device_stats = {}

    # v2 replication constants
    EXTRA_SPEC_REP_SYNC_PERIOD = "replication:sync_period"
    EXTRA_SPEC_REP_RETENTION_COUNT = "replication:retention_count"
    EXTRA_SPEC_REP_REMOTE_RETENTION_COUNT = (
        "replication:remote_retention_count")
    MIN_REP_SYNC_PERIOD = 1800
    DEFAULT_RETENTION_COUNT = 5
    MAX_RETENTION_COUNT = 50
    DEFAULT_REMOTE_RETENTION_COUNT = 5
    MAX_REMOTE_RETENTION_COUNT = 50
    REP_SNAPSHOT_SUFFIX = "_SS"
    REP_SCHEDULE_SUFFIX = "_SCHED"
    FAILBACK_VALUE = 'default'

    def __init__(self, *args, **kwargs):
        super(HPELeftHandISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(hpelefthand_opts)
        self.configuration.append_config_values(san.san_opts)
        if not self.configuration.hpelefthand_api_url:
            raise exception.NotFound(_("HPELeftHand url not found"))

        # blank is the only invalid character for cluster names
        # so we need to use it as a separator
        self.DRIVER_LOCATION = self.__class__.__name__ + ' %(cluster)s %(vip)s'
        self._client_conf = {}
        self._replication_targets = []
        self._replication_enabled = False
        self._active_backend_id = kwargs.get('active_backend_id', None)

    def _login(self, timeout=None):
        conf = self._get_lefthand_config()
        if conf:
            self._client_conf['hpelefthand_username'] = (
                conf['hpelefthand_username'])
            self._client_conf['hpelefthand_password'] = (
                conf['hpelefthand_password'])
            self._client_conf['hpelefthand_clustername'] = (
                conf['hpelefthand_clustername'])
            self._client_conf['hpelefthand_api_url'] = (
                conf['hpelefthand_api_url'])
            self._client_conf['hpelefthand_ssh_port'] = (
                conf['hpelefthand_ssh_port'])
            self._client_conf['hpelefthand_iscsi_chap_enabled'] = (
                conf['hpelefthand_iscsi_chap_enabled'])
            self._client_conf['ssh_conn_timeout'] = conf['ssh_conn_timeout']
            self._client_conf['san_private_key'] = conf['san_private_key']
        else:
            self._client_conf['hpelefthand_username'] = (
                self.configuration.hpelefthand_username)
            self._client_conf['hpelefthand_password'] = (
                self.configuration.hpelefthand_password)
            self._client_conf['hpelefthand_clustername'] = (
                self.configuration.hpelefthand_clustername)
            self._client_conf['hpelefthand_api_url'] = (
                self.configuration.hpelefthand_api_url)
            self._client_conf['hpelefthand_ssh_port'] = (
                self.configuration.hpelefthand_ssh_port)
            self._client_conf['hpelefthand_iscsi_chap_enabled'] = (
                self.configuration.hpelefthand_iscsi_chap_enabled)
            self._client_conf['ssh_conn_timeout'] = (
                self.configuration.ssh_conn_timeout)
            self._client_conf['san_private_key'] = (
                self.configuration.san_private_key)

        client = self._create_client(timeout=timeout)
        try:
            if self.configuration.hpelefthand_debug:
                client.debug_rest(True)

            client.login(
                self._client_conf['hpelefthand_username'],
                self._client_conf['hpelefthand_password'])

            cluster_info = client.getClusterByName(
                self._client_conf['hpelefthand_clustername'])
            self.cluster_id = cluster_info['id']
            virtual_ips = cluster_info['virtualIPAddresses']
            self.cluster_vip = virtual_ips[0]['ipV4Address']

            # Extract IP address from API URL
            ssh_ip = self._extract_ip_from_url(
                self._client_conf['hpelefthand_api_url'])
            known_hosts_file = CONF.ssh_hosts_key_file
            policy = "AutoAddPolicy"
            if CONF.strict_ssh_host_key_policy:
                policy = "RejectPolicy"
            client.setSSHOptions(
                ssh_ip,
                self._client_conf['hpelefthand_username'],
                self._client_conf['hpelefthand_password'],
                port=self._client_conf['hpelefthand_ssh_port'],
                conn_timeout=self._client_conf['ssh_conn_timeout'],
                privatekey=self._client_conf['san_private_key'],
                missing_key_policy=policy,
                known_hosts_file=known_hosts_file)

            return client
        except hpeexceptions.HTTPNotFound:
            raise exception.DriverNotInitialized(
                _('LeftHand cluster not found'))
        except Exception as ex:
            raise exception.DriverNotInitialized(ex)

    def _logout(self, client):
        if client is not None:
            client.logout()

    def _create_client(self, timeout=None):
        # Timeout is only supported in version 2.0.1 and greater of the
        # python-lefthandclient.
        hpelefthand_api_url = self._client_conf['hpelefthand_api_url']
        client = hpe_lh_client.HPELeftHandClient(
            hpelefthand_api_url, timeout=timeout)
        return client

    def _create_replication_client(self, remote_array):
        cl = hpe_lh_client.HPELeftHandClient(
            remote_array['hpelefthand_api_url'])
        try:
            cl.login(
                remote_array['hpelefthand_username'],
                remote_array['hpelefthand_password'])

            ssh_conn_timeout = remote_array.get('ssh_conn_timeout', 30)
            san_private_key = remote_array.get('san_private_key', '')

            # Extract IP address from API URL
            ssh_ip = self._extract_ip_from_url(
                remote_array['hpelefthand_api_url'])
            known_hosts_file = CONF.ssh_hosts_key_file
            policy = "AutoAddPolicy"
            if CONF.strict_ssh_host_key_policy:
                policy = "RejectPolicy"
            cl.setSSHOptions(
                ssh_ip,
                remote_array['hpelefthand_username'],
                remote_array['hpelefthand_password'],
                port=remote_array['hpelefthand_ssh_port'],
                conn_timeout=ssh_conn_timeout,
                privatekey=san_private_key,
                missing_key_policy=policy,
                known_hosts_file=known_hosts_file)

            return cl
        except hpeexceptions.HTTPNotFound:
            raise exception.DriverNotInitialized(
                _('LeftHand cluster not found'))
        except Exception as ex:
            raise exception.DriverNotInitialized(ex)

    def _destroy_replication_client(self, client):
        if client is not None:
            client.logout()

    def _extract_ip_from_url(self, url):
        result = re.search("://(.*):", url)
        ip = result.group(1)
        return ip

    def do_setup(self, context):
        """Set up LeftHand client."""
        if not hpelefthandclient:
            # Checks if client was successfully imported
            ex_msg = _("HPELeftHand client is not installed. Please"
                       " install using 'pip install "
                       "python-lefthandclient'.")
            LOG.error(ex_msg)
            raise exception.VolumeDriverException(ex_msg)

        if hpelefthandclient.version < MIN_CLIENT_VERSION:
            ex_msg = (_("Invalid hpelefthandclient version found ("
                        "%(found)s). Version %(minimum)s or greater "
                        "required. Run 'pip install --upgrade "
                        "python-lefthandclient' to upgrade the "
                        "hpelefthandclient.")
                      % {'found': hpelefthandclient.version,
                         'minimum': MIN_CLIENT_VERSION})
            LOG.error(ex_msg)
            raise exception.InvalidInput(reason=ex_msg)

        self._do_replication_setup()

    def check_for_setup_error(self):
        """Checks for incorrect LeftHand API being used on backend."""
        client = self._login()
        try:
            self.api_version = client.getApiVersion()

            LOG.info("HPELeftHand API version %s", self.api_version)

            if self.api_version < MIN_API_VERSION:
                LOG.warning("HPELeftHand API is version %(current)s. "
                            "A minimum version of %(min)s is needed for "
                            "manage/unmanage support.",
                            {'current': self.api_version,
                             'min': MIN_API_VERSION})
        finally:
            self._logout(client)

    def check_replication_flags(self, options, required_flags):
        for flag in required_flags:
            if not options.get(flag, None):
                msg = _('%s is not set and is required for the replication '
                        'device to be valid.') % flag
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

    def get_version_string(self):
        return (_('REST %(proxy_ver)s hpelefthandclient %(rest_ver)s') % {
            'proxy_ver': self.VERSION,
            'rest_ver': hpelefthandclient.get_version_string()})

    @cinder_utils.trace
    def create_volume(self, volume):
        """Creates a volume."""
        client = self._login()
        try:
            # get the extra specs of interest from this volume's volume type
            volume_extra_specs = self._get_volume_extra_specs(volume)
            extra_specs = self._get_lh_extra_specs(
                volume_extra_specs,
                extra_specs_key_map.keys())

            # map the extra specs key/value pairs to key/value pairs
            # used as optional configuration values by the LeftHand backend
            optional = self._map_extra_specs(extra_specs)

            # if provisioning is not set, default to thin
            if 'isThinProvisioned' not in optional:
                optional['isThinProvisioned'] = True

            # AdaptiveOptimization defaults to 'true' if you don't specify the
            # value on a create, and that is the most efficient way to create
            # a volume. If you pass in 'false' or 'true' for AO, it will result
            # in an update operation following the create operation to set this
            # value, so it is best to not specify the value and let it default
            # to 'true'.
            if optional.get('isAdaptiveOptimizationEnabled'):
                del optional['isAdaptiveOptimizationEnabled']

            clusterName = self._client_conf['hpelefthand_clustername']
            optional['clusterName'] = clusterName

            volume_info = client.createVolume(
                volume['name'], self.cluster_id,
                volume['size'] * units.Gi,
                optional)

            model_update = self._update_provider(volume_info)

            # v2 replication check
            if self._volume_of_replicated_type(volume) and (
               self._do_volume_replication_setup(volume, client, optional)):
                model_update['replication_status'] = 'enabled'
                model_update['replication_driver_data'] = (json.dumps(
                    {'location': self._client_conf['hpelefthand_api_url']}))

            return model_update
        except Exception as ex:
            raise exception.VolumeBackendAPIException(data=ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def delete_volume(self, volume):
        """Deletes a volume."""
        client = self._login()
        # v2 replication check
        # If the volume type is replication enabled, we want to call our own
        # method of deconstructing the volume and its dependencies
        if self._volume_of_replicated_type(volume):
            self._do_volume_replication_destroy(volume, client)
            return

        try:
            volume_info = client.getVolumeByName(volume['name'])
            client.deleteVolume(volume_info['id'])
        except hpeexceptions.HTTPNotFound:
            LOG.error("Volume did not exist. It will not be deleted")
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def extend_volume(self, volume, new_size):
        """Extend the size of an existing volume."""
        client = self._login()
        try:
            volume_info = client.getVolumeByName(volume['name'])

            # convert GB to bytes
            options = {'size': int(new_size) * units.Gi}
            client.modifyVolume(volume_info['id'], options)
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def create_group(self, context, group):
        """Creates a group."""
        LOG.debug("Creating group.")
        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        for vol_type_id in group.volume_type_ids:
            replication_type = self._volume_of_replicated_type(
                None, vol_type_id)
            if replication_type:
                # An unsupported configuration
                LOG.error('Unable to create group: create group with '
                          'replication volume type is not supported.')
                model_update = {'status': fields.GroupStatus.ERROR}
                return model_update

        return {'status': fields.GroupStatus.AVAILABLE}

    @cinder_utils.trace
    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from a source"""
        msg = _("Creating a group from a source is not "
                "supported when consistent_group_snapshot_enabled to true.")
        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        else:
            raise exception.VolumeBackendAPIException(data=msg)

    @cinder_utils.trace
    def delete_group(self, context, group, volumes):
        """Deletes a group."""
        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        volume_model_updates = []
        for volume in volumes:
            volume_update = {'id': volume.id}
            try:
                self.delete_volume(volume)
                volume_update['status'] = 'deleted'
            except Exception as ex:
                LOG.error("There was an error deleting volume %(id)s: "
                          "%(error)s.",
                          {'id': volume.id,
                           'error': ex})
                volume_update['status'] = 'error'
            volume_model_updates.append(volume_update)

        model_update = {'status': group.status}

        return model_update, volume_model_updates

    @cinder_utils.trace
    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        """Updates a group.

        Because the backend has no concept of volume grouping, cinder will
        maintain all volume/group relationships. Because of this
        functionality, there is no need to make any client calls; instead
        simply returning out of this function allows cinder to properly
        add/remove volumes from the group.
        """
        LOG.debug("Updating group.")
        if not utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        return None, None, None

    @cinder_utils.trace
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group snapshot."""
        if not utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        client = self._login()
        try:
            snap_set = []
            snapshot_base_name = "snapshot-" + group_snapshot.id
            snapshot_model_updates = []
            for i, snapshot in enumerate(snapshots):
                volume = snapshot.volume
                volume_name = volume['name']
                try:
                    volume_info = client.getVolumeByName(volume_name)
                except Exception as ex:
                    error = six.text_type(ex)
                    LOG.error("Could not find volume with name %(name)s. "
                              "Error: %(error)s",
                              {'name': volume_name,
                               'error': error})
                    raise exception.VolumeBackendAPIException(data=error)

                volume_id = volume_info['id']
                snapshot_name = snapshot_base_name + "-" + six.text_type(i)
                snap_set_member = {'volumeName': volume_name,
                                   'volumeId': volume_id,
                                   'snapshotName': snapshot_name}
                snap_set.append(snap_set_member)
                snapshot_update = {'id': snapshot['id'],
                                   'status': fields.SnapshotStatus.AVAILABLE}
                snapshot_model_updates.append(snapshot_update)

            source_volume_id = snap_set[0]['volumeId']
            optional = {'inheritAccess': True}
            description = group_snapshot.description
            if description:
                optional['description'] = description

            try:
                client.createSnapshotSet(source_volume_id, snap_set, optional)
            except Exception as ex:
                error = six.text_type(ex)
                LOG.error("Could not create snapshot set. Error: '%s'",
                          error)
                raise exception.VolumeBackendAPIException(
                    data=error)

        except Exception as ex:
            raise exception.VolumeBackendAPIException(data=six.text_type(ex))
        finally:
            self._logout(client)

        model_update = {'status': 'available'}

        return model_update, snapshot_model_updates

    @cinder_utils.trace
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group snapshot."""
        if not utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        client = self._login()
        snap_name_base = "snapshot-" + group_snapshot.id

        snapshot_model_updates = []
        for i, snapshot in enumerate(snapshots):
            snapshot_update = {'id': snapshot['id']}
            try:
                snap_name = snap_name_base + "-" + six.text_type(i)
                snap_info = client.getSnapshotByName(snap_name)
                client.deleteSnapshot(snap_info['id'])
                snapshot_update['status'] = fields.SnapshotStatus.DELETED
            except hpeexceptions.HTTPServerError as ex:
                in_use_msg = ('cannot be deleted because it is a clone '
                              'point')
                if in_use_msg in ex.get_description():
                    LOG.error("The snapshot cannot be deleted because "
                              "it is a clone point.")
                snapshot_update['status'] = fields.SnapshotStatus.ERROR
            except Exception as ex:
                LOG.error("There was an error deleting snapshot %(id)s: "
                          "%(error)s.",
                          {'id': snapshot['id'],
                           'error': six.text_type(ex)})
                snapshot_update['status'] = fields.SnapshotStatus.ERROR
            snapshot_model_updates.append(snapshot_update)

        self._logout(client)

        model_update = {'status': group_snapshot.status}

        return model_update, snapshot_model_updates

    @cinder_utils.trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        client = self._login()
        try:
            volume_info = client.getVolumeByName(snapshot['volume_name'])

            option = {'inheritAccess': True}
            client.createSnapshot(snapshot['name'],
                                  volume_info['id'],
                                  option)
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        client = self._login()
        try:
            snap_info = client.getSnapshotByName(snapshot['name'])
            client.deleteSnapshot(snap_info['id'])
        except hpeexceptions.HTTPNotFound:
            LOG.error("Snapshot did not exist. It will not be deleted")
        except hpeexceptions.HTTPServerError as ex:
            in_use_msg = 'cannot be deleted because it is a clone point'
            if in_use_msg in ex.get_description():
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])

            raise exception.VolumeBackendAPIException(ex)

        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def get_volume_stats(self, refresh=False):
        """Gets volume stats."""
        client = self._login()
        try:
            if refresh:
                self._update_backend_status(client)

            return self.device_stats
        finally:
            self._logout(client)

    def _update_backend_status(self, client):
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['driver_version'] = self.VERSION
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['reserved_percentage'] = (
            self.configuration.safe_get('reserved_percentage'))
        data['storage_protocol'] = 'iSCSI'
        data['vendor_name'] = 'Hewlett Packard Enterprise'
        data['location_info'] = (self.DRIVER_LOCATION % {
            'cluster': self._client_conf['hpelefthand_clustername'],
            'vip': self.cluster_vip})
        data['thin_provisioning_support'] = True
        data['thick_provisioning_support'] = True
        data['max_over_subscription_ratio'] = (
            self.configuration.safe_get('max_over_subscription_ratio'))

        cluster_info = client.getCluster(self.cluster_id)

        total_capacity = cluster_info['spaceTotal']
        free_capacity = cluster_info['spaceAvailable']

        # convert to GB
        data['total_capacity_gb'] = int(total_capacity) / units.Gi
        data['free_capacity_gb'] = int(free_capacity) / units.Gi

        # Collect some stats
        capacity_utilization = (
            (float(total_capacity - free_capacity) /
             float(total_capacity)) * 100)
        # Don't have a better way to get the total number volumes
        # so try to limit the size of data for now. Once new lefthand API is
        # available, replace this call.
        total_volumes = 0
        provisioned_size = 0
        volumes = client.getVolumes(
            cluster=self._client_conf['hpelefthand_clustername'],
            fields=['members[id]', 'members[clusterName]', 'members[size]'])
        if volumes:
            total_volumes = volumes['total']
            provisioned_size = sum(
                members['size'] for members in volumes['members'])
        data['provisioned_capacity_gb'] = int(provisioned_size) / units.Gi
        data['capacity_utilization'] = capacity_utilization
        data['total_volumes'] = total_volumes
        data['filter_function'] = self.get_filter_function()
        data['goodness_function'] = self.get_goodness_function()
        data['consistent_group_snapshot_enabled'] = True
        data['replication_enabled'] = self._replication_enabled
        data['replication_type'] = ['periodic']
        data['replication_count'] = len(self._replication_targets)
        data['replication_targets'] = self._get_replication_targets()

        self.device_stats = data

    @cinder_utils.trace
    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Assign any created volume to a compute node/host so that it can be
        used from that host. HPE VSA requires a volume to be assigned
        to a server.
        """
        client = self._login()
        try:
            server_info = self._create_server(connector, client)
            volume_info = client.getVolumeByName(volume['name'])

            access_already_enabled = False
            if volume_info['iscsiSessions'] is not None:
                # Extract the server id for each session to check if the
                # new server already has access permissions enabled.
                for session in volume_info['iscsiSessions']:
                    server_id = int(session['server']['uri'].split('/')[3])
                    if server_id == server_info['id']:
                        access_already_enabled = True
                        break

            if not access_already_enabled:
                client.addServerAccess(
                    volume_info['id'],
                    server_info['id'])

            iscsi_properties = self._get_iscsi_properties(volume)

            if ('chapAuthenticationRequired' in server_info and
                    server_info['chapAuthenticationRequired']):
                iscsi_properties['auth_method'] = 'CHAP'
                iscsi_properties['auth_username'] = connector['initiator']
                iscsi_properties['auth_password'] = (
                    server_info['chapTargetSecret'])

            return {'driver_volume_type': 'iscsi', 'data': iscsi_properties}
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Unassign the volume from the host."""
        client = self._login()
        try:
            volume_info = client.getVolumeByName(volume['name'])
            server_info = client.getServerByName(connector['host'])
            volume_list = client.findServerVolumes(server_info['name'])

            removeServer = True
            for entry in volume_list:
                if entry['id'] != volume_info['id']:
                    removeServer = False
                    break

            client.removeServerAccess(
                volume_info['id'],
                server_info['id'])

            if removeServer:
                client.deleteServer(server_info['id'])
        except hpeexceptions.HTTPNotFound as ex:
            # If a host is failed-over, we want to allow the detach to
            # to 'succeed' when it cannot find the host. We can simply
            # return out of the terminate connection in order for things
            # to be updated correctly.
            if self._active_backend_id:
                LOG.warning("Because the host is currently in a "
                            "failed-over state, the volume will not "
                            "be properly detached from the primary "
                            "array. The detach will be considered a "
                            "success as far as Cinder is concerned. "
                            "The volume can now be attached to the "
                            "secondary target.")
                return
            else:
                raise exception.VolumeBackendAPIException(ex)
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        client = self._login()
        try:
            snap_info = client.getSnapshotByName(snapshot['name'])
            volume_info = client.cloneSnapshot(
                volume['name'],
                snap_info['id'])

            # Extend volume
            if volume['size'] > snapshot['volume_size']:
                LOG.debug("Resize the new volume to %s.", volume['size'])
                self.extend_volume(volume, volume['size'])

            model_update = self._update_provider(volume_info)

            # v2 replication check
            if self._volume_of_replicated_type(volume) and (
               self._do_volume_replication_setup(volume, client)):
                model_update['replication_status'] = 'enabled'
                model_update['replication_driver_data'] = (json.dumps(
                    {'location': self._client_conf['hpelefthand_api_url']}))

            return model_update
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    @cinder_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        client = self._login()
        try:
            volume_info = client.getVolumeByName(src_vref['name'])
            clone_info = client.cloneVolume(volume['name'], volume_info['id'])

            # Extend volume
            if volume['size'] > src_vref['size']:
                LOG.debug("Resize the new volume to %s.", volume['size'])
                self.extend_volume(volume, volume['size'])
            # TODO(kushal) : we will use volume.volume_types when we re-write
            # the design for unit tests to use objects instead of dicts.
            # Get the extra specs of interest from this volume's volume type
            volume_extra_specs = self._get_volume_extra_specs(src_vref)
            extra_specs = self._get_lh_extra_specs(
                volume_extra_specs,
                extra_specs_key_map.keys())

            # Check provisioning type of source volume. If it's full then need
            # to change provisioning of clone volume to full as lefthand
            # creates clone volume only with thin provisioning type.
            if extra_specs.get('hpelh:provisioning') == 'full':
                options = {'isThinProvisioned': False}
                clone_volume_info = client.getVolumeByName(volume['name'])
                client.modifyVolume(clone_volume_info['id'], options)

            model_update = self._update_provider(clone_info)

            # v2 replication check
            if self._volume_of_replicated_type(volume) and (
               self._do_volume_replication_setup(volume, client)):
                model_update['replication_status'] = 'enabled'
                model_update['replication_driver_data'] = (json.dumps(
                    {'location': self._client_conf['hpelefthand_api_url']}))

            return model_update
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)
        finally:
            self._logout(client)

    def _get_volume_extra_specs(self, volume):
        """Get extra specs from a volume."""
        extra_specs = {}
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            extra_specs = volume_type.get('extra_specs')
        return extra_specs

    def _get_lh_extra_specs(self, extra_specs, valid_keys):
        """Get LeftHand extra_specs (valid_keys only)."""
        extra_specs_of_interest = {}
        for key, value in extra_specs.items():
            if key in valid_keys:
                prefix = key.split(":")
                if prefix[0] == "hplh":
                    LOG.warning("The 'hplh' prefix is deprecated. Use "
                                "'hpelh' instead.")
                extra_specs_of_interest[key] = value
        return extra_specs_of_interest

    def _map_extra_specs(self, extra_specs):
        """Map the extra spec key/values to LeftHand key/values."""
        client_options = {}
        for key, value in extra_specs.items():
            # map extra spec key to lh client option key
            client_key = extra_specs_key_map[key]
            # map extra spect value to lh client option value
            try:
                value_map = extra_specs_value_map[client_key]
                # an invalid value will throw KeyError
                client_value = value_map[value]
                client_options[client_key] = client_value
            except KeyError:
                LOG.error("'%(value)s' is an invalid value "
                          "for extra spec '%(key)s'",
                          {'value': value, 'key': key})
        return client_options

    def _update_provider(self, volume_info, cluster_vip=None):
        if not cluster_vip:
            cluster_vip = self.cluster_vip
        # TODO(justinsb): Is this always 1? Does it matter?
        cluster_interface = '1'
        iscsi_portal = cluster_vip + ":3260," + cluster_interface

        return {'provider_location': (
            "%s %s %s" % (iscsi_portal, volume_info['iscsiIqn'], 0))}

    @coordination.synchronized('VSA-{connector[host]}')
    def _create_server(self, connector, client):
        server_info = None
        chap_enabled = self._client_conf.get('hpelefthand_iscsi_chap_enabled')
        try:
            server_info = client.getServerByName(connector['host'])
            chap_secret = server_info['chapTargetSecret']
            if not chap_enabled and chap_secret:
                LOG.warning('CHAP secret exists for host %s but CHAP is '
                            'disabled', connector['host'])
            if chap_enabled and chap_secret is None:
                LOG.warning('CHAP is enabled, but server secret not '
                            'configured on server %s', connector['host'])
            return server_info
        except hpeexceptions.HTTPNotFound:
            # server does not exist, so create one
            pass

        optional = None
        if chap_enabled:
            chap_secret = utils.generate_password()
            optional = {'chapName': connector['initiator'],
                        'chapTargetSecret': chap_secret,
                        'chapAuthenticationRequired': True
                        }

        server_info = client.createServer(connector['host'],
                                          connector['initiator'],
                                          optional)
        return server_info

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    @cinder_utils.trace
    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to retype
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('enter: retype: id=%(id)s, new_type=%(new_type)s,'
                  'diff=%(diff)s, host=%(host)s', {'id': volume['id'],
                                                   'new_type': new_type,
                                                   'diff': diff,
                                                   'host': host})
        client = self._login()
        try:
            volume_info = client.getVolumeByName(volume['name'])

            # pick out the LH extra specs
            new_extra_specs = dict(new_type).get('extra_specs')

            # in the absence of LH capability in diff,
            # True should be return as retype is not needed
            if not list(filter((lambda key: extra_specs_key_map.get(key)),
                               diff['extra_specs'].keys())):
                return True

            # add capability of LH, which are absent in new type,
            # so default value gets set for those capability
            for key, value in extra_specs_default_key_value_map.items():
                if key not in new_extra_specs.keys():
                    new_extra_specs[key] = value

            lh_extra_specs = self._get_lh_extra_specs(
                new_extra_specs,
                extra_specs_key_map.keys())

            LOG.debug('LH specs=%(specs)s', {'specs': lh_extra_specs})

            # only set the ones that have changed
            changed_extra_specs = {}
            for key, value in lh_extra_specs.items():
                try:
                    (old, new) = diff['extra_specs'][key]
                    if old != new:
                        changed_extra_specs[key] = value
                except KeyError:
                    changed_extra_specs[key] = value

            # map extra specs to LeftHand options
            options = self._map_extra_specs(changed_extra_specs)
            if len(options) > 0:
                client.modifyVolume(volume_info['id'], options)
            return True
        except hpeexceptions.HTTPNotFound:
            raise exception.VolumeNotFound(volume_id=volume['id'])
        except Exception as ex:
            LOG.warning("%s", ex)
        finally:
            self._logout(client)

        return False

    @cinder_utils.trace
    def migrate_volume(self, ctxt, volume, host):
        """Migrate the volume to the specified host.

        Backend assisted volume migration will occur if and only if;

        1. Same LeftHand backend
        2. Volume cannot be attached
        3. Volumes with snapshots cannot be migrated
        4. Source and Destination clusters must be in the same management group

        Volume re-type is not supported.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        false_ret = (False, None)
        if 'location_info' not in host['capabilities']:
            return false_ret

        host_location = host['capabilities']['location_info']
        (driver, cluster, vip) = host_location.split(' ')
        client = self._login()
        LOG.debug('enter: migrate_volume: id=%(id)s, host=%(host)s, '
                  'cluster=%(cluster)s', {
                      'id': volume['id'],
                      'host': host,
                      'cluster': self._client_conf['hpelefthand_clustername']})
        try:
            # get the cluster info, if it exists and compare
            cluster_info = client.getClusterByName(cluster)
            LOG.debug('Cluster info: %s', cluster_info)
            virtual_ips = cluster_info['virtualIPAddresses']

            if driver != self.__class__.__name__:
                LOG.info("Cannot provide backend assisted migration for "
                         "volume: %s because volume is from a different "
                         "backend.", volume['name'])
                return false_ret
            if vip != virtual_ips[0]['ipV4Address']:
                LOG.info("Cannot provide backend assisted migration for "
                         "volume: %s because cluster exists in different "
                         "management group.", volume['name'])
                return false_ret

        except hpeexceptions.HTTPNotFound:
            LOG.info("Cannot provide backend assisted migration for "
                     "volume: %s because cluster exists in different "
                     "management group.", volume['name'])
            return false_ret
        finally:
            self._logout(client)

        client = self._login()
        try:
            volume_info = client.getVolumeByName(volume['name'])
            LOG.debug('Volume info: %s', volume_info)

            # can't migrate if server is attached
            if volume_info['iscsiSessions'] is not None:
                LOG.info("Cannot provide backend assisted migration "
                         "for volume: %s because the volume has been "
                         "exported.", volume['name'])
                return false_ret

            # can't migrate if volume has snapshots
            snap_info = client.getVolume(
                volume_info['id'],
                'fields=snapshots,snapshots[resource[members[name]]]')
            LOG.debug('Snapshot info: %s', snap_info)
            if snap_info['snapshots']['resource'] is not None:
                LOG.info("Cannot provide backend assisted migration "
                         "for volume: %s because the volume has "
                         "snapshots.", volume['name'])
                return false_ret

            options = {'clusterName': cluster}
            client.modifyVolume(volume_info['id'], options)
        except hpeexceptions.HTTPNotFound:
            LOG.info("Cannot provide backend assisted migration for "
                     "volume: %s because volume does not exist in this "
                     "management group.", volume['name'])
            return false_ret
        except hpeexceptions.HTTPServerError as ex:
            LOG.error("Exception: %s", ex)
            return false_ret
        finally:
            self._logout(client)

        return (True, None)

    @cinder_utils.trace
    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        """Rename the new (temp) volume to it's original name.


        This method tries to rename the new volume to it's original
        name after the migration has completed.

        """
        LOG.debug("Update volume name for %(id)s.", {'id': new_volume['id']})
        name_id = None
        provider_location = None
        if original_volume_status == 'available':
            # volume isn't attached and can be updated
            original_name = CONF.volume_name_template % volume['id']
            current_name = CONF.volume_name_template % new_volume['id']
            client = self._login()
            try:
                volume_info = client.getVolumeByName(current_name)
                volumeMods = {'name': original_name}
                client.modifyVolume(volume_info['id'], volumeMods)
                LOG.info("Volume name changed from %(tmp)s to %(orig)s.",
                         {'tmp': current_name, 'orig': original_name})
            except Exception as e:
                LOG.error("Changing the volume name from %(tmp)s to "
                          "%(orig)s failed because %(reason)s.",
                          {'tmp': current_name, 'orig': original_name,
                           'reason': e})
                name_id = new_volume['_name_id'] or new_volume['id']
                provider_location = new_volume['provider_location']
            finally:
                self._logout(client)
        else:
            # the backend can't change the name.
            name_id = new_volume['_name_id'] or new_volume['id']
            provider_location = new_volume['provider_location']

        return {'_name_id': name_id, 'provider_location': provider_location}

    @cinder_utils.trace
    def manage_existing(self, volume, existing_ref):
        """Manage an existing LeftHand volume.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the virtual volume>}
        """
        # Check API Version
        self._check_api_version()

        target_vol_name = self._get_existing_volume_ref_name(existing_ref)

        # Check for the existence of the virtual volume.
        client = self._login()
        try:
            volume_info = client.getVolumeByName(target_vol_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Virtual volume '%s' doesn't exist on array.") %
                   target_vol_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)
        finally:
            self._logout(client)

        # Generate the new volume information based on the new ID.
        new_vol_name = 'volume-' + volume['id']

        volume_type = None
        if volume['volume_type_id']:
            try:
                volume_type = self._get_volume_type(volume['volume_type_id'])
            except Exception:
                reason = (_("Volume type ID '%s' is invalid.") %
                          volume['volume_type_id'])
                raise exception.ManageExistingVolumeTypeMismatch(reason=reason)

        new_vals = {"name": new_vol_name}

        client = self._login()
        try:
            # Update the existing volume with the new name.
            client.modifyVolume(volume_info['id'], new_vals)
        finally:
            self._logout(client)

        LOG.info("Virtual volume '%(ref)s' renamed to '%(new)s'.",
                 {'ref': existing_ref['source-name'], 'new': new_vol_name})

        display_name = None
        if volume['display_name']:
            display_name = volume['display_name']

        if volume_type:
            LOG.info("Virtual volume %(disp)s '%(new)s' is being retyped.",
                     {'disp': display_name, 'new': new_vol_name})

            # Creates a diff as it needed for retype operation.
            diff = {}
            diff['extra_specs'] = {key: (None, value) for key, value
                                   in volume_type['extra_specs'].items()}
            try:
                self.retype(None,
                            volume,
                            volume_type,
                            diff,
                            volume['host'])
                LOG.info("Virtual volume %(disp)s successfully retyped to "
                         "%(new_type)s.",
                         {'disp': display_name,
                          'new_type': volume_type.get('name')})
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.warning("Failed to manage virtual volume %(disp)s "
                                "due to error during retype.",
                                {'disp': display_name})
                    # Try to undo the rename and clear the new comment.
                    client = self._login()
                    try:
                        client.modifyVolume(
                            volume_info['id'],
                            {'name': target_vol_name})
                    finally:
                        self._logout(client)

        updates = {'display_name': display_name}

        LOG.info("Virtual volume %(disp)s '%(new)s' is now being managed.",
                 {'disp': display_name, 'new': new_vol_name})

        # Return display name to update the name displayed in the GUI and
        # any model updates from retype.
        return updates

    @cinder_utils.trace
    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage an existing LeftHand snapshot.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the snapshot>}
        """
        # Check API Version
        self._check_api_version()

        # Potential parent volume for the snapshot
        volume = snapshot['volume']

        if volume.get('replication_status') == 'failed-over':
            err = (_("Managing of snapshots to failed-over volumes is "
                     "not allowed."))
            raise exception.InvalidInput(reason=err)

        target_snap_name = self._get_existing_volume_ref_name(existing_ref)

        # Check for the existence of the virtual volume.
        client = self._login()
        try:
            updates = self._manage_snapshot(client,
                                            volume,
                                            snapshot,
                                            target_snap_name,
                                            existing_ref)
        finally:
            self._logout(client)

        # Return display name to update the name displayed in the GUI and
        # any model updates from retype.
        return updates

    def _manage_snapshot(self, client, volume, snapshot, target_snap_name,
                         existing_ref):
        # Check for the existence of the virtual volume.
        try:
            snapshot_info = client.getSnapshotByName(target_snap_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Snapshot '%s' doesn't exist on array.") %
                   target_snap_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        # Make sure the snapshot is being associated with the correct volume.
        try:
            parent_vol = client.getSnapshotParentVolume(target_snap_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Could not find the parent volume for Snapshot '%s' on "
                     "array.") % target_snap_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        parent_vol_name = 'volume-' + snapshot['volume_id']
        if parent_vol_name != parent_vol['name']:
            err = (_("The provided snapshot '%s' is not a snapshot of "
                     "the provided volume.") % target_snap_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        # Generate the new snapshot information based on the new ID.
        new_snap_name = 'snapshot-' + snapshot['id']

        new_vals = {"name": new_snap_name}

        try:
            # Update the existing snapshot with the new name.
            client.modifySnapshot(snapshot_info['id'], new_vals)
        except hpeexceptions.HTTPServerError:
            err = (_("An error occurred while attempting to modify "
                     "Snapshot '%s'.") % snapshot_info['id'])
            LOG.error(err)

        LOG.info("Snapshot '%(ref)s' renamed to '%(new)s'.",
                 {'ref': existing_ref['source-name'], 'new': new_snap_name})

        display_name = None
        if snapshot['display_name']:
            display_name = snapshot['display_name']

        updates = {'display_name': display_name}

        LOG.info("Snapshot %(disp)s '%(new)s' is now being managed.",
                 {'disp': display_name, 'new': new_snap_name})

        return updates

    @cinder_utils.trace
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the virtual volume>}
        """
        # Check API version.
        self._check_api_version()

        target_vol_name = self._get_existing_volume_ref_name(existing_ref)

        # Make sure the reference is not in use.
        if re.match('volume-*|snapshot-*', target_vol_name):
            reason = _("Reference must be the volume name of an unmanaged "
                       "virtual volume.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=target_vol_name,
                reason=reason)

        # Check for the existence of the virtual volume.
        client = self._login()
        try:
            volume_info = client.getVolumeByName(target_vol_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Virtual volume '%s' doesn't exist on array.") %
                   target_vol_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)
        finally:
            self._logout(client)

        return int(math.ceil(float(volume_info['size']) / units.Gi))

    @cinder_utils.trace
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of volume to be managed by manage_existing.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the virtual volume>}
        """
        # Check API version.
        self._check_api_version()

        target_snap_name = self._get_existing_volume_ref_name(existing_ref)

        # Make sure the reference is not in use.
        if re.match('volume-*|snapshot-*|unm-*', target_snap_name):
            reason = _("Reference must be the name of an unmanaged "
                       "snapshot.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=target_snap_name,
                reason=reason)

        # Check for the existence of the virtual volume.
        client = self._login()
        try:
            snapshot_info = client.getSnapshotByName(target_snap_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Snapshot '%s' doesn't exist on array.") %
                   target_snap_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)
        finally:
            self._logout(client)

        return int(math.ceil(float(snapshot_info['size']) / units.Gi))

    @cinder_utils.trace
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""
        # Check API version.
        self._check_api_version()

        # Rename the volume's name to unm-* format so that it can be
        # easily found later.
        client = self._login()
        try:
            volume_info = client.getVolumeByName(volume['name'])
            new_vol_name = 'unm-' + six.text_type(volume['id'])
            options = {'name': new_vol_name}
            client.modifyVolume(volume_info['id'], options)
        finally:
            self._logout(client)

        LOG.info("Virtual volume %(disp)s '%(vol)s' is no longer managed. "
                 "Volume renamed to '%(new)s'.",
                 {'disp': volume['display_name'],
                  'vol': volume['name'],
                  'new': new_vol_name})

    @cinder_utils.trace
    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management."""
        # Check API version.
        self._check_api_version()

        # Potential parent volume for the snapshot
        volume = snapshot['volume']

        if volume.get('replication_status') == 'failed-over':
            err = (_("Unmanaging of snapshots from 'failed-over' volumes is "
                     "not allowed."))
            LOG.error(err)
            # TODO(leeantho) Change this exception to Invalid when the volume
            # manager supports handling that.
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['id'])

        # Rename the snapshots's name to ums-* format so that it can be
        # easily found later.
        client = self._login()
        try:
            snapshot_info = client.getSnapshotByName(snapshot['name'])
            new_snap_name = 'ums-' + six.text_type(snapshot['id'])
            options = {'name': new_snap_name}
            client.modifySnapshot(snapshot_info['id'], options)
            LOG.info("Snapshot %(disp)s '%(vol)s' is no longer managed. "
                     "Snapshot renamed to '%(new)s'.",
                     {'disp': snapshot['display_name'],
                      'vol': snapshot['name'],
                      'new': new_snap_name})
        finally:
            self._logout(client)

    def _get_existing_volume_ref_name(self, existing_ref):
        """Returns the volume name of an existing reference.

        Checks if an existing volume reference has a source-name element.
        If source-name is not present an error will be thrown.
        """
        if 'source-name' not in existing_ref:
            reason = _("Reference must contain source-name.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason)

        return existing_ref['source-name']

    def _check_api_version(self):
        """Checks that the API version is correct."""
        if (self.api_version < MIN_API_VERSION):
            ex_msg = (_('Invalid HPELeftHand API version found: %(found)s. '
                        'Version %(minimum)s or greater required for '
                        'manage/unmanage support.')
                      % {'found': self.api_version,
                         'minimum': MIN_API_VERSION})
            LOG.error(ex_msg)
            raise exception.InvalidInput(reason=ex_msg)

    def _get_volume_type(self, type_id):
        ctxt = context.get_admin_context()
        return volume_types.get_volume_type(ctxt, type_id)

    # v2 replication methods
    @cinder_utils.trace
    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Force failover to a secondary replication target."""
        if secondary_id and secondary_id == self.FAILBACK_VALUE:
            volume_update_list = self._replication_failback(volumes)
            target_id = None
        else:
            failover_target = None
            for target in self._replication_targets:
                if target['backend_id'] == secondary_id:
                    failover_target = target
                    break
            if not failover_target:
                msg = _("A valid secondary target MUST be specified in order "
                        "to failover.")
                LOG.error(msg)
                raise exception.InvalidReplicationTarget(reason=msg)

            target_id = failover_target['backend_id']
            volume_update_list = []
            for volume in volumes:
                if self._volume_of_replicated_type(volume):
                    # Try and stop the remote snapshot schedule. If the primary
                    # array is down, we will continue with the failover.
                    client = None
                    try:
                        client = self._login(timeout=30)
                        name = volume['name'] + self.REP_SCHEDULE_SUFFIX + (
                            "_Pri")
                        client.stopRemoteSnapshotSchedule(name)
                    except Exception:
                        LOG.warning("The primary array is currently "
                                    "offline, remote copy has been "
                                    "automatically paused.")
                    finally:
                        self._logout(client)

                    # Update provider location to the new array.
                    cl = None
                    try:
                        cl = self._create_replication_client(failover_target)
                        # Stop snapshot schedule
                        try:
                            name = volume['name'] + (
                                self.REP_SCHEDULE_SUFFIX + "_Rmt")
                            cl.stopRemoteSnapshotSchedule(name)
                        except Exception:
                            pass
                        # Make the volume primary so it can be attached after a
                        # fail-over.
                        cl.makeVolumePrimary(volume['name'])

                        # Update the provider info for a proper fail-over.
                        volume_info = cl.getVolumeByName(volume['name'])
                        prov_location = self._update_provider(
                            volume_info,
                            cluster_vip=failover_target['cluster_vip'])
                        volume_update_list.append(
                            {'volume_id': volume['id'],
                             'updates': {'replication_status': 'failed-over',
                                         'provider_location':
                                         prov_location['provider_location']}})
                    except Exception as ex:
                        LOG.error("There was a problem with the failover "
                                  "(%(error)s) and it was unsuccessful. "
                                  "Volume '%(volume)s will not be available "
                                  "on the failed over target.",
                                  {'error': six.text_type(ex),
                                   'volume': volume['id']})
                        volume_update_list.append(
                            {'volume_id': volume['id'],
                             'updates': {'replication_status': 'error'}})
                    finally:
                        self._destroy_replication_client(cl)
                else:
                    # If the volume is not of replicated type, we need to
                    # force the status into error state so a user knows they
                    # do not have access to the volume.
                    volume_update_list.append(
                        {'volume_id': volume['id'],
                         'updates': {'status': 'error'}})

            self._active_backend_id = target_id

        return target_id, volume_update_list, []

    def _do_replication_setup(self):
        default_san_ssh_port = self.configuration.hpelefthand_ssh_port
        default_ssh_conn_timeout = self.configuration.ssh_conn_timeout
        default_san_private_key = self.configuration.san_private_key

        replication_targets = []
        replication_devices = self.configuration.replication_device
        if replication_devices:
            # We do not want to fail if we cannot log into the client here
            # as a failover can still occur, so we need out replication
            # devices to exist.
            for dev in replication_devices:
                remote_array = dict(dev.items())
                # Override and set defaults for certain entries
                remote_array['managed_backend_name'] = (
                    dev.get('managed_backend_name'))
                remote_array['hpelefthand_ssh_port'] = (
                    dev.get('hpelefthand_ssh_port', default_san_ssh_port))
                remote_array['ssh_conn_timeout'] = (
                    dev.get('ssh_conn_timeout', default_ssh_conn_timeout))
                remote_array['san_private_key'] = (
                    dev.get('san_private_key', default_san_private_key))
                # Format hpe3par_iscsi_chap_enabled as a bool
                remote_array['hpelefthand_iscsi_chap_enabled'] = (
                    dev.get('hpelefthand_iscsi_chap_enabled') == 'True')
                remote_array['cluster_id'] = None
                remote_array['cluster_vip'] = None
                array_name = remote_array['backend_id']

                # Make sure we can log into the array, that it has been
                # correctly configured, and its API version meets the
                # minimum requirement.
                cl = None
                try:
                    cl = self._create_replication_client(remote_array)
                    api_version = cl.getApiVersion()
                    cluster_info = cl.getClusterByName(
                        remote_array['hpelefthand_clustername'])
                    remote_array['cluster_id'] = cluster_info['id']
                    virtual_ips = cluster_info['virtualIPAddresses']
                    remote_array['cluster_vip'] = virtual_ips[0]['ipV4Address']

                    if api_version < MIN_API_VERSION:
                        LOG.warning("The secondary array must have an API "
                                    "version of %(min_ver)s or higher. "
                                    "Array '%(target)s' is on %(target_ver)s, "
                                    "therefore it will not be added as a "
                                    "valid replication target.",
                                    {'min_ver': MIN_API_VERSION,
                                     'target': array_name,
                                     'target_ver': api_version})
                    elif not self._is_valid_replication_array(remote_array):
                        LOG.warning("'%s' is not a valid replication array. "
                                    "In order to be valid, backend_id, "
                                    "hpelefthand_api_url, "
                                    "hpelefthand_username, "
                                    "hpelefthand_password, and "
                                    "hpelefthand_clustername, "
                                    "must be specified. If the target is "
                                    "managed, managed_backend_name must be "
                                    "set as well.", array_name)
                    else:
                        replication_targets.append(remote_array)
                except Exception:
                    LOG.error("Could not log in to LeftHand array (%s) with "
                              "the provided credentials.", array_name)
                finally:
                    self._destroy_replication_client(cl)

            self._replication_targets = replication_targets
            if self._is_replication_configured_correct():
                self._replication_enabled = True

    def _replication_failback(self, volumes):
        array_config = {'hpelefthand_api_url':
                        self.configuration.hpelefthand_api_url,
                        'hpelefthand_username':
                        self.configuration.hpelefthand_username,
                        'hpelefthand_password':
                        self.configuration.hpelefthand_password,
                        'hpelefthand_ssh_port':
                        self.configuration.hpelefthand_ssh_port}

        # Make sure the proper steps on the backend have been completed before
        # we allow a failback.
        if not self._is_host_ready_for_failback(volumes, array_config):
            msg = _("The host is not ready to be failed back. Please "
                    "resynchronize the volumes and resume replication on the "
                    "LeftHand backends.")
            LOG.error(msg)
            raise exception.InvalidReplicationTarget(reason=msg)

        cl = None
        volume_update_list = []
        for volume in volumes:
            if self._volume_of_replicated_type(volume):
                try:
                    cl = self._create_replication_client(array_config)
                    # Update the provider info for a proper fail-back.
                    volume_info = cl.getVolumeByName(volume['name'])
                    cluster_info = cl.getClusterByName(
                        self.configuration.hpelefthand_clustername)
                    virtual_ips = cluster_info['virtualIPAddresses']
                    cluster_vip = virtual_ips[0]['ipV4Address']
                    provider_location = self._update_provider(
                        volume_info, cluster_vip=cluster_vip)
                    volume_update_list.append(
                        {'volume_id': volume['id'],
                         'updates': {'replication_status': 'available',
                                     'provider_location':
                                     provider_location['provider_location']}})
                except Exception as ex:
                    # The secondary array was not able to execute the fail-back
                    # properly. The replication status is now in an unknown
                    # state, so we will treat it as an error.
                    LOG.error("There was a problem with the failover "
                              "(%(error)s) and it was unsuccessful. "
                              "Volume '%(volume)s will not be available "
                              "on the failed over target.",
                              {'error': ex,
                               'volume': volume['id']})
                    volume_update_list.append(
                        {'volume_id': volume['id'],
                         'updates': {'replication_status': 'error'}})
                finally:
                    self._destroy_replication_client(cl)
            else:
                # Upon failing back, we can move the non-replicated volumes
                # back into available state.
                volume_update_list.append(
                    {'volume_id': volume['id'],
                     'updates': {'status': 'available'}})

        return volume_update_list

    def _is_host_ready_for_failback(self, volumes, array_config):
        """Checks to make sure the volumes have been synchronized

        This entails ensuring the remote snapshot schedule has been resumed
        on the backends and the secondary volume's data has been copied back
        to the primary.
        """
        is_ready = True
        cl = None
        try:
            for volume in volumes:
                if self._volume_of_replicated_type(volume):
                    schedule_name = volume['name'] + (
                        self.REP_SCHEDULE_SUFFIX + "_Pri")
                    cl = self._create_replication_client(array_config)
                    schedule = cl.getRemoteSnapshotSchedule(schedule_name)
                    schedule = ''.join(schedule)
                    # We need to check the status of the schedule to make sure
                    # it is not paused.
                    result = re.search(r".*paused\s+(\w+)", schedule)
                    is_schedule_active = result.group(1) == 'false'

                    volume_info = cl.getVolumeByName(volume['name'])
                    if not volume_info['isPrimary'] or not is_schedule_active:
                        is_ready = False
                        break
        except Exception as ex:
            LOG.error("There was a problem when trying to determine if "
                      "the volume can be failed-back: %s", ex)
            is_ready = False
        finally:
            self._destroy_replication_client(cl)

        return is_ready

    def _get_replication_targets(self):
        replication_targets = []
        for target in self._replication_targets:
            replication_targets.append(target['backend_id'])

        return replication_targets

    def _is_valid_replication_array(self, target):
        required_flags = ['hpelefthand_api_url', 'hpelefthand_username',
                          'hpelefthand_password', 'backend_id',
                          'hpelefthand_clustername']
        try:
            self.check_replication_flags(target, required_flags)
            return True
        except Exception:
            return False

    def _is_replication_configured_correct(self):
        rep_flag = True
        # Make sure there is at least one replication target.
        if len(self._replication_targets) < 1:
            LOG.error("There must be at least one valid replication "
                      "device configured.")
            rep_flag = False
        return rep_flag

    def _volume_of_replicated_type(self, volume, vol_type_id=None):
        # TODO(kushal) : we will use volume.volume_types when we re-write
        # the design for unit tests to use objects instead of dicts.
        replicated_type = False
        volume_type_id = vol_type_id if vol_type_id else volume.get(
            'volume_type_id')
        if volume_type_id:
            volume_type = self._get_volume_type(volume_type_id)

            extra_specs = volume_type.get('extra_specs')
            if extra_specs and 'replication_enabled' in extra_specs:
                rep_val = extra_specs['replication_enabled']
                replicated_type = (rep_val == "<is> True")

        return replicated_type

    def _does_snapshot_schedule_exist(self, schedule_name, client):
        try:
            exists = client.doesRemoteSnapshotScheduleExist(schedule_name)
        except Exception:
            exists = False
        return exists

    def _get_lefthand_config(self):
        conf = None
        for target in self._replication_targets:
            if target['backend_id'] == self._active_backend_id:
                conf = target
                break

        return conf

    def _do_volume_replication_setup(self, volume, client, optional=None):
        """This function will do or ensure the following:

        -Create volume on main array (already done in create_volume)
        -Create volume on secondary array
        -Make volume remote on secondary array
        -Create the snapshot schedule

        If anything here fails, we will need to clean everything up in
        reverse order, including the original volume.
        """
        schedule_name = volume['name'] + self.REP_SCHEDULE_SUFFIX
        # If there is already a snapshot schedule, the volume is setup
        # for replication on the backend. Start the schedule and return
        # success.
        if self._does_snapshot_schedule_exist(schedule_name + "_Pri", client):
            try:
                client.startRemoteSnapshotSchedule(schedule_name + "_Pri")
            except Exception:
                pass
            return True

        # Grab the extra_spec entries for replication and make sure they
        # are set correctly.
        volume_type = self._get_volume_type(volume["volume_type_id"])
        extra_specs = volume_type.get("extra_specs")

        # Get and check replication sync period
        replication_sync_period = extra_specs.get(
            self.EXTRA_SPEC_REP_SYNC_PERIOD)
        if replication_sync_period:
            replication_sync_period = int(replication_sync_period)
            if replication_sync_period < self.MIN_REP_SYNC_PERIOD:
                msg = (_("The replication sync period must be at least %s "
                         "seconds.") % self.MIN_REP_SYNC_PERIOD)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            # If there is no extra_spec value for replication sync period, we
            # will default it to the required minimum and log a warning.
            replication_sync_period = self.MIN_REP_SYNC_PERIOD
            LOG.warning("There was no extra_spec value for %(spec_name)s, "
                        "so the default value of %(def_val)s will be "
                        "used. To overwrite this, set this value in the "
                        "volume type extra_specs.",
                        {'spec_name': self.EXTRA_SPEC_REP_SYNC_PERIOD,
                         'def_val': self.MIN_REP_SYNC_PERIOD})

        # Get and check retention count
        retention_count = extra_specs.get(
            self.EXTRA_SPEC_REP_RETENTION_COUNT)
        if retention_count:
            retention_count = int(retention_count)
            if retention_count > self.MAX_RETENTION_COUNT:
                msg = (_("The retention count must be %s or less.") %
                       self.MAX_RETENTION_COUNT)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            # If there is no extra_spec value for retention count, we
            # will default it and log a warning.
            retention_count = self.DEFAULT_RETENTION_COUNT
            LOG.warning("There was no extra_spec value for %(spec_name)s, "
                        "so the default value of %(def_val)s will be "
                        "used. To overwrite this, set this value in the "
                        "volume type extra_specs.",
                        {'spec_name': self.EXTRA_SPEC_REP_RETENTION_COUNT,
                         'def_val': self.DEFAULT_RETENTION_COUNT})

        # Get and checkout remote retention count
        remote_retention_count = extra_specs.get(
            self.EXTRA_SPEC_REP_REMOTE_RETENTION_COUNT)
        if remote_retention_count:
            remote_retention_count = int(remote_retention_count)
            if remote_retention_count > self.MAX_REMOTE_RETENTION_COUNT:
                msg = (_("The remote retention count must be %s or less.") %
                       self.MAX_REMOTE_RETENTION_COUNT)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            # If there is no extra_spec value for remote retention count, we
            # will default it and log a warning.
            remote_retention_count = self.DEFAULT_REMOTE_RETENTION_COUNT
            spec_name = self.EXTRA_SPEC_REP_REMOTE_RETENTION_COUNT
            LOG.warning("There was no extra_spec value for %(spec_name)s, "
                        "so the default value of %(def_val)s will be "
                        "used. To overwrite this, set this value in the "
                        "volume type extra_specs.",
                        {'spec_name': spec_name,
                         'def_val': self.DEFAULT_REMOTE_RETENTION_COUNT})

        cl = None
        try:
            # Create volume on secondary system
            for remote_target in self._replication_targets:
                cl = self._create_replication_client(remote_target)

                if optional:
                    optional['clusterName'] = (
                        remote_target['hpelefthand_clustername'])
                cl.createVolume(volume['name'],
                                remote_target['cluster_id'],
                                volume['size'] * units.Gi,
                                optional)

                # Make secondary volume a remote volume
                # NOTE: The snapshot created when making a volume remote is
                # not managed by cinder. This snapshot will be removed when
                # _do_volume_replication_destroy is called.
                snap_name = volume['name'] + self.REP_SNAPSHOT_SUFFIX
                cl.makeVolumeRemote(volume['name'], snap_name)

                # A remote IP address is needed from the cluster in order to
                # create the snapshot schedule.
                remote_ip = cl.getIPFromCluster(
                    remote_target['hpelefthand_clustername'])

                # Destroy remote client
                self._destroy_replication_client(cl)

                # Create remote snapshot schedule on the primary system.
                # We want to start the remote snapshot schedule instantly; a
                # date in the past will do that. We will use the Linux epoch
                # date formatted to ISO 8601 (YYYY-MM-DDTHH:MM:SSZ).
                start_date = "1970-01-01T00:00:00Z"
                remote_vol_name = volume['name']

                client.createRemoteSnapshotSchedule(
                    volume['name'],
                    schedule_name,
                    replication_sync_period,
                    start_date,
                    retention_count,
                    remote_target['hpelefthand_clustername'],
                    remote_retention_count,
                    remote_vol_name,
                    remote_ip,
                    remote_target['hpelefthand_username'],
                    remote_target['hpelefthand_password'])

            return True
        except Exception as ex:
            # Destroy the replication client that was created
            self._destroy_replication_client(cl)
            # Deconstruct what we tried to create
            self._do_volume_replication_destroy(volume, client)
            msg = (_("There was an error setting up a remote schedule "
                     "on the LeftHand arrays: ('%s'). The volume will not be "
                     "recognized as replication type.") %
                   six.text_type(ex))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _do_volume_replication_destroy(self, volume, client):
        """This will remove all dependencies of a replicated volume

        It should be used when deleting a replication enabled volume
        or if setting up a remote copy group fails. It will try and do the
        following:
        -Delete the snapshot schedule
        -Delete volume and snapshots on secondary array
        -Delete volume and snapshots on primary array
        """
        # Delete snapshot schedule
        try:
            schedule_name = volume['name'] + self.REP_SCHEDULE_SUFFIX
            client.deleteRemoteSnapshotSchedule(schedule_name)
        except Exception:
            pass

        # Delete volume on secondary array(s)
        remote_vol_name = volume['name']
        for remote_target in self._replication_targets:
            try:
                cl = self._create_replication_client(remote_target)
                volume_info = cl.getVolumeByName(remote_vol_name)
                cl.deleteVolume(volume_info['id'])
            except Exception:
                pass
            finally:
                # Destroy the replication client that was created
                self._destroy_replication_client(cl)

        # Delete volume on primary array
        try:
            volume_info = client.getVolumeByName(volume['name'])
            client.deleteVolume(volume_info['id'])
        except Exception:
            pass
