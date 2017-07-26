# Copyright (c) 2016 Reduxio Systems
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
"""ISCSI Volume driver for Reduxio."""
import random
import string

from oslo_log import log as logging
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
import cinder.interface as cinder_interface
from cinder import utils as cinder_utils
from cinder.volume.drivers.reduxio import rdx_cli_api
from cinder.volume.drivers.san import san


# Constants
REDUXIO_NAME_PREFIX_NUMERIC_REPLACEMENT = "a"
REDUXIO_CLI_HOST_RAND_LENGTH = 12
REDUXIO_CLI_HOST_PREFIX = 'openstack-'
REDUXIO_STORAGE_PROTOCOL = 'iSCSI'
REDUXIO_VENDOR_NAME = 'Reduxio'
AGENT_TYPE_KEY = "agent-type"
AGENT_TYPE_OPENSTACK = "openstack"
EXTERNAL_VOL_ID_KEY = "external-vol-id"
METADATA_KEY = "metadata"
BACKDATE_META_FIELD = "backdate"
RDX_CLI_MAX_VOL_LENGTH = 31
DRIVER_VERSION = '1.0.1'
HX550_INITIAL_PHYSICAL_CAPACITY = 32 * 1024
HX550_CAPACITY_LIMIT = 200 * 1024

LOG = logging.getLogger(__name__)


@cinder_interface.volumedriver
class ReduxioISCSIDriver(san.SanISCSIDriver):
    """OpenStack driver to support Reduxio storage systems.

    .. code-block:: default

      Version history:
      1.0.0   -  Initial version - volume management, snapshots,
                 BackDating(TM).
      1.0.1   -  Capacity stats, fixed error handling for volume deletions.

    """
    VERSION = '1.0.1'
    CI_WIKI_NAME = "Reduxio_HX550_CI"

    # TODO(smcginnis) Remove driver in Queens if CI issues haven't been fixed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        """Initialize Reduxio ISCSI Driver."""
        LOG.info("Initializing Reduxio ISCSI Driver")
        super(ReduxioISCSIDriver, self).__init__(*args, **kwargs)
        self.rdxApi = None  # type: rdx_cli_api.ReduxioAPI
        self._stats = {}

    def _check_config(self):
        """Ensure that the flags we care about are set."""
        required_config = ['san_ip', 'san_login', 'san_password']
        for attr in required_config:
            if not getattr(self.configuration, attr, None):
                raise exception.InvalidInput(reason=_('%s is not set.') % attr)

    def do_setup(self, context):
        """Set up the driver."""
        self._check_config()
        self.rdxApi = rdx_cli_api.ReduxioAPI(
            user=self.configuration.san_login,
            password=self.configuration.san_password,
            host=self.configuration.san_ip)

    # Reduxio entities names (which are also ids) are restricted to at most
    # 31 chars. The following function maps cinder unique id to reduxio name.
    # Reduxio name also cannot begin with a number, so we replace this number
    # with a constant letter. The probability of a uuid conflict is still low.
    def _cinder_id_to_rdx(self, cinder_id):
        normalized = cinder_id.replace("-", "")[:RDX_CLI_MAX_VOL_LENGTH]
        if normalized[0].isalpha():
            return normalized
        else:
            return REDUXIO_NAME_PREFIX_NUMERIC_REPLACEMENT + normalized[1:]

    # We use Reduxio volume description to represent metadata regarding
    # the cinder agent, in order to avoid multi managing the same volume
    # from multiple cinder volume.
    def _create_vol_managed_description(self, volume):
        return AGENT_TYPE_OPENSTACK + "_" + volume["name"]

    # This function parses the cli volume description and returns a dictionary
    # containing the managed data (agent, cinder_volume_id)
    def _get_managed_info(self, cli_vol):
        try:
            splited = cli_vol["description"].split("_")
            if len(splited) == 0:
                return {AGENT_TYPE_KEY: None}
            return {AGENT_TYPE_KEY: splited[0],
                    EXTERNAL_VOL_ID_KEY: splited[1]}
        except Exception:
            return {AGENT_TYPE_KEY: None}

    def _get_existing_volume_ref_name(self, existing_ref):
        """Return the volume name of an existing ref."""
        if 'source-name' in existing_ref:
            vol_name = existing_ref['source-name']
        else:
            reason = _("Reference must contain source-name.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason)

        return vol_name

    @cinder_utils.trace
    def create_volume(self, volume):
        """Create a new volume."""
        LOG.info(
            "Creating a new volume(%(name)s) with size(%(size)s)",
            {'name': volume["name"], 'size': volume["size"]})
        vol_name = self._cinder_id_to_rdx(volume["id"])
        self.rdxApi.create_volume(
            name=vol_name,
            size=volume["size"],
            description=self._create_vol_managed_description(volume)
        )

    @cinder_utils.trace
    def manage_existing(self, volume, external_ref):
        """Create a new Cinder volume out of an existing Reduxio volume."""
        LOG.info("Manage existing volume(%(cinder_vol)s) "
                 "from Reduxio Volume(%(rdx_vol)s)",
                 {'cinder_vol': volume["id"],
                  'rdx_vol': external_ref["source-name"]})
        # Get the volume name from the external reference
        target_vol_name = self._get_existing_volume_ref_name(external_ref)

        # Get vol info from the volume name obtained from the reference
        cli_vol = self.rdxApi.find_volume_by_name(target_vol_name)
        managed_info = self._get_managed_info(cli_vol)

        # Check if volume is already managed by OpenStack
        if managed_info[AGENT_TYPE_KEY] == AGENT_TYPE_OPENSTACK:
            raise exception.ManageExistingAlreadyManaged(
                volume_ref=volume['id'])

        # If agent-type is not None then raise exception
        if not managed_info[AGENT_TYPE_KEY] is None:
            msg = _('Volume should have agent-type set as None.')
            raise exception.InvalidVolume(reason=msg)

        new_vol_name = self._cinder_id_to_rdx(volume['id'])

        # edit the volume
        self.rdxApi.update_volume(
            target_vol_name,
            new_name=new_vol_name,
            description=self._create_vol_managed_description(volume)
        )

    @cinder_utils.trace
    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing volume."""
        target_vol_name = self._get_existing_volume_ref_name(external_ref)
        cli_vol = self.rdxApi.find_volume_by_name(target_vol_name)

        return int(cli_vol['size'] / units.Gi)

    @cinder_utils.trace
    def unmanage(self, volume):
        """Remove the specified volume from Cinder management."""
        LOG.info("Unmanaging volume(%s)", volume["id"])
        vol_name = self._cinder_id_to_rdx(volume['id'])
        cli_vol = self.rdxApi.find_volume_by_name(vol_name)
        managed_info = self._get_managed_info(cli_vol)

        if managed_info['agent-type'] != AGENT_TYPE_OPENSTACK:
            msg = _('Only volumes managed by OpenStack can be unmanaged.')
            raise exception.InvalidVolume(reason=msg)

        # update the agent-type to None
        self.rdxApi.update_volume(name=vol_name, description="")

    @cinder_utils.trace
    def delete_volume(self, volume):
        """Delete the specified volume."""
        LOG.info("Deleting volume(%s)", volume["id"])
        try:
            self.rdxApi.delete_volume(
                name=self._cinder_id_to_rdx(volume["id"]))
        except exception.RdxAPICommandException as e:
            if "No such volume" not in six.text_type(e):
                raise

    @cinder_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Clone volume from snapshot.

        Extend the volume if the size of the volume is more than the snapshot.
        """
        LOG.info(
            "cloning new volume(%(new_vol)s) from snapshot(%(snapshot)s),"
            " src volume(%(src_vol)s)",
            {'new_vol': volume["name"],
                'snapshot': snapshot["name"],
                'src_vol': snapshot["volume_name"]}
        )

        parent_name = self._cinder_id_to_rdx(snapshot["volume_id"])
        clone_name = self._cinder_id_to_rdx(volume["id"])
        bookmark_name = self._cinder_id_to_rdx(snapshot["id"])

        self.rdxApi.clone_volume(
            parent_name=parent_name,
            clone_name=clone_name,
            bookmark_name=bookmark_name,
            description=self._create_vol_managed_description(volume)
        )

        if volume['size'] > snapshot['volume_size']:
            self.rdxApi.update_volume(name=clone_name, size=volume["size"])

    @cinder_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Clone volume from existing cinder volume.

        :param volume: The clone volume object.

        If the volume 'metadata' field contains a 'backdate' key
        (If using Cinder CLI, should be provided by --meta flag),
        then we create a clone from the specified time.
        The 'backdate' metadata value should be in the format of
        Reduxio CLI date: mm/dd/yyyy-hh:mm:ss.
        for example: '02/17/2015-11:39:00.
        Note: Different timezones might be configured
        for Reduxio and OpenStack.
        The specified date must be related to Reduxio time settings.

        If meta key 'backdate' was not specified,
        then we create a clone from the volume's current state.

        :param src_vref: The source volume to clone from
        :return: None
        """
        LOG.info("cloning new volume(%(clone)s) from src(%(src)s)",
                 {'clone': volume['name'], 'src': src_vref['name']})
        parent_name = self._cinder_id_to_rdx(src_vref["id"])
        clone_name = self._cinder_id_to_rdx(volume["id"])
        description = self._create_vol_managed_description(volume)
        if BACKDATE_META_FIELD in volume[METADATA_KEY]:
            LOG.info("Cloning from backdate %s",
                     volume[METADATA_KEY][BACKDATE_META_FIELD])

            self.rdxApi.clone_volume(
                parent_name=parent_name,
                clone_name=clone_name,
                description=description,
                str_date=volume[METADATA_KEY][BACKDATE_META_FIELD]
            )
        else:
            LOG.info("Cloning from now")
            self.rdxApi.clone_volume(
                parent_name=parent_name,
                clone_name=clone_name,
                description=description
            )

        if src_vref['size'] < volume['size']:
            self.rdxApi.update_volume(name=clone_name, size=volume["size"])

    @cinder_utils.trace
    def create_snapshot(self, snapshot):
        """Create a snapshot from an existing Cinder volume.

        We use Reduxio manual bookmark to represent a snapshot.

        :param snapshot: The snapshot object.

        If the snapshot 'metadata' field contains a 'backdate' key
        (If using Cinder CLI, should be provided by --meta flag),
        then we create a snapshot from the specified time.
        The 'backdate' metadata value should be in the format of
        Reduxio CLI date: mm/dd/yyyy-hh:mm:ss.
        for example: '02/17/2015-11:39:00'.
        Note: Different timezones might be configured
        for Reduxio and OpenStack.
        The specified date must be related to Reduxio time settings.

        If meta key 'backdate' was not specified, then we create a snapshot
        from the volume's current state.

        :return: None
        """
        LOG.info(
            "Creating snapshot(%(snap)s) from volume(%(vol)s)",
            {'snap': snapshot['name'], 'vol': snapshot['volume_name']})
        cli_vol_name = self._cinder_id_to_rdx(snapshot['volume_id'])
        cli_bookmark_name = self._cinder_id_to_rdx(snapshot['id'])
        bookmark_type = "manual"
        if BACKDATE_META_FIELD in snapshot[METADATA_KEY]:
            self.rdxApi.add_vol_bookmark(vol=cli_vol_name,
                                         bm_name=cli_bookmark_name,
                                         bm_type=bookmark_type,
                                         str_date=snapshot[METADATA_KEY][
                                             BACKDATE_META_FIELD]
                                         )
        else:
            self.rdxApi.add_vol_bookmark(vol=cli_vol_name,
                                         bm_name=cli_bookmark_name,
                                         bm_type=bookmark_type)

    @cinder_utils.trace
    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        LOG.info("Deleting snapshot(%(snap)s) from volume(%(vol)s)",
                 {'snap': snapshot['name'], 'vol': snapshot['volume_name']})

        volume_name = self._cinder_id_to_rdx(snapshot['volume_id'])
        bookmark_name = self._cinder_id_to_rdx(snapshot['id'])
        try:
            self.rdxApi.delete_vol_bookmark(vol=volume_name,
                                            bm_name=bookmark_name)
        except exception.RdxAPICommandException as e:
            if "No such bookmark" not in six.text_type(e):
                raise

    @cinder_utils.trace
    def get_volume_stats(self, refresh=False):
        """Get Reduxio Storage attributes."""
        if refresh:
            backend_name = self.configuration.safe_get(
                'volume_backend_name') or self.__class__.__name__
            ratio = self.rdxApi.get_savings_ratio()
            total = HX550_INITIAL_PHYSICAL_CAPACITY * ratio

            if total > HX550_CAPACITY_LIMIT:
                total = HX550_CAPACITY_LIMIT

            current_space_usage = self.rdxApi.get_current_space_usage()
            physical_used = current_space_usage["physical_total"] / units.Gi
            free = (HX550_INITIAL_PHYSICAL_CAPACITY - physical_used) * ratio

            if free > HX550_CAPACITY_LIMIT:
                free = HX550_CAPACITY_LIMIT

            self._stats = {
                'volume_backend_name': backend_name,
                'vendor_name': REDUXIO_VENDOR_NAME,
                'driver_version': DRIVER_VERSION,
                'storage_protocol': REDUXIO_STORAGE_PROTOCOL,
                'consistencygroup_support': False,
                'pools': [{
                    "pool_name": backend_name,
                    "total_capacity_gb": total,
                    "free_capacity_gb": free,
                    "reserved_percentage":
                        self.configuration.reserved_percentage,
                    "QoS_support": False,
                    'multiattach': False
                }]}

        return self._stats

    @cinder_utils.trace
    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        volume_name = self._cinder_id_to_rdx(volume['id'])
        self.rdxApi.update_volume(volume_name, size=new_size)

    @cinder_utils.trace
    def _generate_initiator_name(self):
        """Generates random host name for reduxio cli."""
        char_set = string.ascii_lowercase
        rand_str = ''.join(
            random.sample(char_set, REDUXIO_CLI_HOST_RAND_LENGTH))
        return "%s%s" % (REDUXIO_CLI_HOST_PREFIX, rand_str)

    @cinder_utils.trace
    def _get_target_portal(self, settings, controller, port):
        network = "iscsi_network%s" % port
        iscsi_port = six.text_type(
            settings["network_configuration"]["iscsi_target_tcp_port"])
        controller_port_key = ("controller_%(controller)s_port_%(port)s"
                               % {"controller": controller, "port": port})
        return settings[network][controller_port_key] + ":" + iscsi_port

    @cinder_utils.trace
    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance."""
        LOG.info(
            "Assigning volume(%(vol)s) with initiator(%(initiator)s)",
            {'vol': volume['name'], 'initiator': connector['initiator']})

        initiator_iqn = connector['initiator']
        vol_rdx_name = self._cinder_id_to_rdx(volume["id"])
        initiator_name = None
        found = False

        # Get existing cli initiator name by its iqn, or create a new one
        # if it doesnt exist
        for host in self.rdxApi.list_hosts():
            if host["iscsi_name"] == initiator_iqn:
                LOG.info("initiator exists in Reduxio")
                found = True
                initiator_name = host["name"]
                break
        if not found:
            LOG.info("Initiator doesn't exist in Reduxio, Creating it")
            initiator_name = self._generate_initiator_name()
            self.rdxApi.create_host(name=initiator_name,
                                    iscsi_name=initiator_iqn)

        existing_assignment = self.rdxApi.get_single_assignment(
            vol=vol_rdx_name, host=initiator_name, raise_on_non_exists=False)

        if existing_assignment is None:
            # Create assignment between the host and the volume
            LOG.info("Creating assignment")
            self.rdxApi.assign(vol_rdx_name, host_name=initiator_name)
        else:
            LOG.debug("Assignment already exists")

        # Query cli settings in order to fill requested output
        settings = self.rdxApi.get_settings()

        target_iqn = settings["network_configuration"]["iscsi_target_iqn"]
        target_portal = self._get_target_portal(settings, 1, 1)

        if existing_assignment is None:
            target_lun = self.rdxApi.get_single_assignment(
                vol=vol_rdx_name,
                host=initiator_name)["lun"]
        else:
            target_lun = existing_assignment["lun"]

        properties = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_discovered': False,
                'discard': False,
                'volume_id': volume['id'],
                'target_iqn': target_iqn,
                'target_portal': target_portal,
                'target_lun': target_lun,
            }
        }

        # if iscsi_network2 is not available,
        # than multipath is disabled (ReduxioVE)
        connector_multipath = connector.get("multipath", False)
        rdx_multipath = "iscsi_network2" in settings
        if rdx_multipath and connector_multipath:
            target_portal2 = self._get_target_portal(settings, 2, 1)
            target_portal3 = self._get_target_portal(settings, 1, 2)
            target_portal4 = self._get_target_portal(settings, 2, 2)

            properties['data']['target_portals'] = [
                target_portal,
                target_portal2,
                target_portal3,
                target_portal4
            ]
            # Reduxio is a single iqn storage
            properties['data']['target_iqns'] = [target_iqn] * 4
            # Lun num is the same for each path
            properties['data']['target_luns'] = [target_lun] * 4

        LOG.info("Assignment complete. Assignment details: %s",
                 properties)

        return properties

    @cinder_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance."""
        iqn = connector['initiator']
        LOG.info("Deleting assignment volume(%(vol)s) with "
                 "initiator(%(initiator)s)",
                 {'vol': volume['name'], 'initiator': iqn})

        for cli_host in self.rdxApi.list_hosts():
            if cli_host["iscsi_name"] == iqn:
                try:
                    self.rdxApi.unassign(
                        self._cinder_id_to_rdx(volume["id"]),
                        host_name=cli_host["name"]
                    )
                except exception.RdxAPICommandException as e:
                    error_msg = six.text_type(e)
                    if "No such assignment" not in error_msg:
                        raise
                    else:
                        LOG.debug("Assignment doesn't exist")
                return

        LOG.warning("Did not find matching reduxio host for initiator %s",
                    iqn)
