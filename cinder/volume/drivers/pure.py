# Copyright (c) 2014 Pure Storage, Inc.
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
"""
Volume driver for Pure Storage FlashArray storage system.

This driver requires Purity version 4.0.0 or later.
"""

import math
import re
import uuid

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import utils as volume_utils

try:
    import purestorage
except ImportError:
    purestorage = None

LOG = logging.getLogger(__name__)

PURE_OPTS = [
    cfg.StrOpt("pure_api_token",
               default=None,
               help="REST API authorization token."),
]

CONF = cfg.CONF
CONF.register_opts(PURE_OPTS)

INVALID_CHARACTERS = re.compile(r"[^-a-zA-Z0-9]")
GENERATED_NAME = re.compile(r".*-[a-f0-9]{32}-cinder$")

CHAP_SECRET_KEY = "PURE_TARGET_CHAP_SECRET"

ERR_MSG_NOT_EXIST = "does not exist"
ERR_MSG_PENDING_ERADICATION = "has been destroyed"

CONNECT_LOCK_NAME = 'PureVolumeDriver_connect'


def _get_vol_name(volume):
    """Return the name of the volume Purity will use."""
    return volume["name"] + "-cinder"


def _get_snap_name(snapshot):
    """Return the name of the snapshot that Purity will use."""
    return "%s-cinder.%s" % (snapshot["volume_name"], snapshot["name"])


def _get_pgroup_name_from_id(id):
    return "consisgroup-%s-cinder" % id


def _get_pgroup_snap_suffix(cgsnapshot):
    return "cgsnapshot-%s-cinder" % cgsnapshot.id


def _get_pgroup_snap_name(cgsnapshot):
    """Return the name of the pgroup snapshot that Purity will use"""
    return "%s.%s" % (_get_pgroup_name_from_id(cgsnapshot.consistencygroup_id),
                      _get_pgroup_snap_suffix(cgsnapshot))


def _get_pgroup_vol_snap_name(snapshot):
    """Return the name of the snapshot that Purity will use for a volume."""
    cg_name = _get_pgroup_name_from_id(snapshot.cgsnapshot.consistencygroup_id)
    cgsnapshot_id = _get_pgroup_snap_suffix(snapshot.cgsnapshot)
    volume_name = snapshot.volume_name
    return "%s.%s.%s-cinder" % (cg_name, cgsnapshot_id, volume_name)


def _generate_purity_host_name(name):
    """Return a valid Purity host name based on the name passed in."""
    if len(name) > 23:
        name = name[0:23]
    name = INVALID_CHARACTERS.sub("-", name)
    name = name.lstrip("-")
    return "{name}-{uuid}-cinder".format(name=name, uuid=uuid.uuid4().hex)


def _generate_chap_secret():
    return volume_utils.generate_password()


class PureISCSIDriver(san.SanISCSIDriver):
    """Performs volume management on Pure Storage FlashArray."""

    VERSION = "2.0.6"

    SUPPORTED_REST_API_VERSIONS = ['1.2', '1.3', '1.4']

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureISCSIDriver, self).__init__(execute=execute, *args, **kwargs)
        self.configuration.append_config_values(PURE_OPTS)
        self._array = None
        self._iscsi_port = None
        self._backend_name = (self.configuration.volume_backend_name or
                              self.__class__.__name__)

    def do_setup(self, context):
        """Performs driver initialization steps that could raise exceptions."""
        if purestorage is None:
            msg = _("Missing 'purestorage' python module, ensure the library"
                    " is installed and available.")
            raise exception.PureDriverException(msg)

        # Raises PureDriverException if unable to connect and PureHTTPError
        # if unable to authenticate.
        purestorage.FlashArray.supported_rest_versions = \
            self.SUPPORTED_REST_API_VERSIONS
        self._array = purestorage.FlashArray(
            self.configuration.san_ip,
            api_token=self.configuration.pure_api_token)
        self._iscsi_port = self._choose_target_iscsi_port()

    def check_for_setup_error(self):
        # Avoid inheriting check_for_setup_error from SanDriver, which checks
        # for san_password or san_private_key, not relevant to our driver.
        pass

    def create_volume(self, volume):
        """Creates a volume."""
        LOG.debug("Enter PureISCSIDriver.create_volume.")
        vol_name = _get_vol_name(volume)
        vol_size = volume["size"] * units.Gi
        self._array.create_volume(vol_name, vol_size)

        if volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume['consistencygroup_id'],
                vol_name
            )
        LOG.debug("Leave PureISCSIDriver.create_volume.")

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        LOG.debug("Enter PureISCSIDriver.create_volume_from_snapshot.")
        vol_name = _get_vol_name(volume)
        if snapshot['cgsnapshot_id']:
            snap_name = _get_pgroup_vol_snap_name(snapshot)
        else:
            snap_name = _get_snap_name(snapshot)

        self._array.copy_volume(snap_name, vol_name)
        self._extend_if_needed(vol_name, snapshot["volume_size"],
                               volume["size"])
        if volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume['consistencygroup_id'],
                vol_name
            )
        LOG.debug("Leave PureISCSIDriver.create_volume_from_snapshot.")

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        LOG.debug("Enter PureISCSIDriver.create_cloned_volume.")
        vol_name = _get_vol_name(volume)
        src_name = _get_vol_name(src_vref)
        self._array.copy_volume(src_name, vol_name)
        self._extend_if_needed(vol_name, src_vref["size"], volume["size"])

        if volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume['consistencygroup_id'],
                vol_name
            )

        LOG.debug("Leave PureISCSIDriver.create_cloned_volume.")

    def _extend_if_needed(self, vol_name, src_size, vol_size):
        """Extend the volume from size src_size to size vol_size."""
        if vol_size > src_size:
            vol_size = vol_size * units.Gi
            self._array.extend_volume(vol_name, vol_size)

    def delete_volume(self, volume):
        """Disconnect all hosts and delete the volume"""
        LOG.debug("Enter PureISCSIDriver.delete_volume.")
        vol_name = _get_vol_name(volume)
        try:
            connected_hosts = \
                self._array.list_volume_private_connections(vol_name)
            for host_info in connected_hosts:
                host_name = host_info["host"]
                self._disconnect_host(host_name, vol_name)
            self._array.destroy_volume(vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and \
                        ERR_MSG_NOT_EXIST in err.text:
                    # Happens if the volume does not exist.
                    ctxt.reraise = False
                    LOG.warn(_LW("Volume deletion failed with message: %s"),
                             err.text)
        LOG.debug("Leave PureISCSIDriver.delete_volume.")

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug("Enter PureISCSIDriver.create_snapshot.")
        vol_name, snap_suff = _get_snap_name(snapshot).split(".")
        self._array.create_snapshot(vol_name, suffix=snap_suff)
        LOG.debug("Leave PureISCSIDriver.create_snapshot.")

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug("Enter PureISCSIDriver.delete_snapshot.")
        snap_name = _get_snap_name(snapshot)
        try:
            self._array.destroy_volume(snap_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400:
                    # Happens if the snapshot does not exist.
                    ctxt.reraise = False
                    LOG.error(_LE("Snapshot deletion failed with message:"
                                  " %s"), err.text)
        LOG.debug("Leave PureISCSIDriver.delete_snapshot.")

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info."""
        LOG.debug("Enter PureISCSIDriver.initialize_connection.")
        target_port = self._get_target_iscsi_port()
        connection = self._connect(volume, connector, initiator_data)
        properties = {
            "driver_volume_type": "iscsi",
            "data": {
                "target_iqn": target_port["iqn"],
                "target_portal": target_port["portal"],
                "target_lun": connection["lun"],
                "target_discovered": True,
                "access_mode": "rw",
            },
        }

        if self.configuration.use_chap_auth:
            properties["data"]["auth_method"] = "CHAP"
            properties["data"]["auth_username"] = connection["auth_username"]
            properties["data"]["auth_password"] = connection["auth_password"]

        initiator_update = connection.get("initiator_update", False)
        if initiator_update:
            properties["initiator_update"] = initiator_update

        LOG.debug("Leave PureISCSIDriver.initialize_connection.")
        return properties

    def _get_target_iscsi_port(self):
        """Return dictionary describing iSCSI-enabled port on target array."""
        try:
            self._run_iscsiadm_bare(["-m", "discovery", "-t", "sendtargets",
                                     "-p", self._iscsi_port["portal"]])
        except processutils.ProcessExecutionError as err:
            LOG.warn(_LW("iSCSI discovery of port %(port_name)s at "
                         "%(port_portal)s failed with error: %(err_msg)s"),
                     {"port_name": self._iscsi_port["name"],
                      "port_portal": self._iscsi_port["portal"],
                      "err_msg": err.stderr})
            self._iscsi_port = self._choose_target_iscsi_port()
        return self._iscsi_port

    @utils.retry(exception.PureDriverException, retries=3)
    def _choose_target_iscsi_port(self):
        """Find a reachable iSCSI-enabled port on target array."""
        ports = self._array.list_ports()
        iscsi_ports = [port for port in ports if port["iqn"]]
        for port in iscsi_ports:
            try:
                self._run_iscsiadm_bare(["-m", "discovery",
                                         "-t", "sendtargets",
                                         "-p", port["portal"]])
            except processutils.ProcessExecutionError as err:
                LOG.debug(("iSCSI discovery of port %(port_name)s at "
                           "%(port_portal)s failed with error: %(err_msg)s"),
                          {"port_name": port["name"],
                           "port_portal": port["portal"],
                           "err_msg": err.stderr})
            else:
                LOG.info(_LI("Using port %(name)s on the array at %(portal)s "
                             "for iSCSI connectivity."),
                         {"name": port["name"], "portal": port["portal"]})
                return port
        raise exception.PureDriverException(
            reason=_("No reachable iSCSI-enabled ports on target array."))

    def _get_chap_credentials(self, host, data):
        initiator_updates = None
        username = host
        password = None
        if data:
            for d in data:
                if d["key"] == CHAP_SECRET_KEY:
                    password = d["value"]
                    break
        if not password:
            password = _generate_chap_secret()
            initiator_updates = {
                "set_values": {
                    CHAP_SECRET_KEY: password
                }
            }
        return username, password, initiator_updates

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _connect(self, volume, connector, initiator_data):
        """Connect the host and volume; return dict describing connection."""
        connection = None
        iqn = connector["initiator"]

        if self.configuration.use_chap_auth:
            (chap_username, chap_password, initiator_update) = \
                self._get_chap_credentials(connector['host'], initiator_data)

        vol_name = _get_vol_name(volume)
        host = self._get_host(connector)

        if host:
            host_name = host["name"]
            LOG.info(_LI("Re-using existing purity host %(host_name)r"),
                     {"host_name": host_name})
            if self.configuration.use_chap_auth:
                if not GENERATED_NAME.match(host_name):
                    LOG.error(_LE("Purity host %(host_name)s is not managed "
                                  "by Cinder and can't have CHAP credentials "
                                  "modified. Remove IQN %(iqn)s from the host "
                                  "to resolve this issue."),
                              {"host_name": host_name,
                               "iqn": connector["initiator"]})
                    raise exception.PureDriverException(
                        reason=_("Unable to re-use a host that is not "
                                 "managed by Cinder with use_chap_auth=True,"))
                elif chap_username is None or chap_password is None:
                    LOG.error(_LE("Purity host %(host_name)s is managed by "
                                  "Cinder but CHAP credentials could not be "
                                  "retrieved from the Cinder database."),
                              {"host_name": host_name})
                    raise exception.PureDriverException(
                        reason=_("Unable to re-use host with unknown CHAP "
                                 "credentials configured."))
        else:
            host_name = _generate_purity_host_name(connector["host"])
            LOG.info(_LI("Creating host object %(host_name)r with IQN:"
                         " %(iqn)s."), {"host_name": host_name, "iqn": iqn})
            self._array.create_host(host_name, iqnlist=[iqn])

            if self.configuration.use_chap_auth:
                self._array.set_host(host_name,
                                     host_user=chap_username,
                                     host_password=chap_password)

        try:
            connection = self._array.connect_host(host_name, vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        "Connection already exists" in err.text):
                    # Happens if the volume is already connected to the host.
                    ctxt.reraise = False
                    LOG.warn(_LW("Volume connection already exists with "
                                 "message: %s"), err.text)
                    # Get the info for the existing connection
                    connected_hosts = \
                        self._array.list_volume_private_connections(vol_name)
                    for host_info in connected_hosts:
                        if host_info["host"] == host_name:
                            connection = host_info
                            break
        if not connection:
            raise exception.PureDriverException(
                reason=_("Unable to connect or find connection to host"))

        if self.configuration.use_chap_auth:
            connection["auth_username"] = chap_username
            connection["auth_password"] = chap_password

            if initiator_update:
                connection["initiator_update"] = initiator_update

        return connection

    def _get_host(self, connector):
        """Return dict describing existing Purity host object or None."""
        hosts = self._array.list_hosts()
        for host in hosts:
            if connector["initiator"] in host["iqn"]:
                return host
        return None

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        LOG.debug("Enter PureISCSIDriver.terminate_connection.")
        vol_name = _get_vol_name(volume)
        host = self._get_host(connector)
        if host:
            host_name = host["name"]
            self._disconnect_host(host_name, vol_name)
        else:
            LOG.error(_LE("Unable to find host object in Purity with IQN: "
                          "%(iqn)s."), {"iqn": connector["initiator"]})
        LOG.debug("Leave PureISCSIDriver.terminate_connection.")

    def _disconnect_host(self, host_name, vol_name):
        LOG.debug("Enter PureISCSIDriver._disconnect_host.")
        try:
            self._array.disconnect_host(host_name, vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400:
                    # Happens if the host and volume are not connected.
                    ctxt.reraise = False
                    LOG.error(_LE("Disconnection failed with message: "
                                  "%(msg)s."), {"msg": err.text})
        try:
            if (GENERATED_NAME.match(host_name) and
                not self._array.list_host_connections(host_name,
                                                      private=True)):
                LOG.info(_LI("Deleting unneeded host %(host_name)r."),
                         {"host_name": host_name})
                self._array.delete_host(host_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and ERR_MSG_NOT_EXIST in err.text:
                    # Happens if the host is already deleted.
                    # This is fine though, just treat it as a warning.
                    ctxt.reraise = False
                    LOG.warning(_LW("Purity host deletion failed: "
                                    "%(msg)s."), {"msg": err.text})
        LOG.debug("Leave PureISCSIDriver._disconnect_host.")

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service.

        If 'refresh' is True, run the update first.
        """

        LOG.debug("Enter PureISCSIDriver.get_volume_stats.")
        if refresh:
            LOG.debug("Updating volume stats.")
            self._update_stats()
        LOG.debug("Leave PureISCSIDriver.get_volume_stats.")
        return self._stats

    def _update_stats(self):
        """Set self._stats with relevant information."""
        info = self._array.get(space=True)
        total_capacity = float(info["capacity"]) / units.Gi
        used_space = float(info["total"]) / units.Gi
        free_space = float(total_capacity - used_space)
        provisioned_space = float(self._get_provisioned_space()) / units.Gi
        # If array is empty we can not calculate a max oversubscription ratio.
        # In this case we choose 20 as a default value for the ratio.  Once
        # some volumes are actually created and some data is stored on the
        # array a much more accurate number will be presented based on current
        # usage.
        if used_space == 0 or provisioned_space == 0:
            thin_provisioning = 20
        else:
            thin_provisioning = provisioned_space / used_space
        data = {"volume_backend_name": self._backend_name,
                "vendor_name": "Pure Storage",
                "driver_version": self.VERSION,
                "storage_protocol": "iSCSI",
                "total_capacity_gb": total_capacity,
                "free_capacity_gb": free_space,
                "reserved_percentage": 0,
                "consistencygroup_support": True,
                "thin_provisioning_support": True,
                "provisioned_capacity": provisioned_space,
                "max_over_subscription_ratio": thin_provisioning
                }
        self._stats = data

    def _get_provisioned_space(self):
        """Sum up provisioned size of all volumes on array"""
        volumes = self._array.list_volumes(pending=True)
        return sum(item["size"] for item in volumes)

    def extend_volume(self, volume, new_size):
        """Extend volume to new_size."""
        LOG.debug("Enter PureISCSIDriver.extend_volume.")
        vol_name = _get_vol_name(volume)
        new_size = new_size * units.Gi
        self._array.extend_volume(vol_name, new_size)
        LOG.debug("Leave PureISCSIDriver.extend_volume.")

    def _add_volume_to_consistency_group(self, consistencygroup_id, vol_name):
        pgroup_name = _get_pgroup_name_from_id(consistencygroup_id)
        self._array.set_pgroup(pgroup_name, addvollist=[vol_name])

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        LOG.debug("Enter PureISCSIDriver.create_consistencygroup")

        self._array.create_pgroup(_get_pgroup_name_from_id(group.id))

        model_update = {'status': 'available'}

        LOG.debug("Leave PureISCSIDriver.create_consistencygroup")
        return model_update

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None):
        LOG.debug("Enter PureISCSIDriver.create_consistencygroup_from_src")

        if cgsnapshot and snapshots:
            self.create_consistencygroup(context, group)
            for volume, snapshot in zip(volumes, snapshots):
                self.create_volume_from_snapshot(volume, snapshot)
        else:
            msg = _("create_consistencygroup_from_src only supports a"
                    " cgsnapshot source, other sources cannot be used.")
            raise exception.InvalidInput(msg)

        LOG.debug("Leave PureISCSIDriver.create_consistencygroup_from_src")
        return None, None

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""
        LOG.debug("Enter PureISCSIDriver.delete_consistencygroup")

        try:
            self._array.destroy_pgroup(_get_pgroup_name_from_id(group.id))
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        (ERR_MSG_PENDING_ERADICATION in err.text or
                         ERR_MSG_NOT_EXIST in err.text)):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning(_LW("Unable to delete Protection Group: %s"),
                                err.text)

        volumes = self.db.volume_get_all_by_group(context, group.id)

        for volume in volumes:
            self.delete_volume(volume)
            volume.status = 'deleted'

        model_update = {'status': group['status']}

        LOG.debug("Leave PureISCSIDriver.delete_consistencygroup")
        return model_update, volumes

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        LOG.debug("Enter PureISCSIDriver.update_consistencygroup")

        pgroup_name = _get_pgroup_name_from_id(group.id)
        if add_volumes:
            addvollist = [_get_vol_name(volume) for volume in add_volumes]
        else:
            addvollist = []

        if remove_volumes:
            remvollist = [_get_vol_name(volume) for volume in remove_volumes]
        else:
            remvollist = []

        self._array.set_pgroup(pgroup_name, addvollist=addvollist,
                               remvollist=remvollist)

        LOG.debug("Leave PureISCSIDriver.update_consistencygroup")
        return None, None, None

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a cgsnapshot."""
        LOG.debug("Enter PureISCSIDriver.create_cgsnapshot")

        pgroup_name = _get_pgroup_name_from_id(cgsnapshot.consistencygroup_id)
        pgsnap_suffix = _get_pgroup_snap_suffix(cgsnapshot)
        self._array.create_pgroup_snapshot(pgroup_name, suffix=pgsnap_suffix)

        snapshots = self.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot.id)

        for snapshot in snapshots:
            snapshot.status = 'available'

        model_update = {'status': 'available'}

        LOG.debug("Leave PureISCSIDriver.create_cgsnapshot")
        return model_update, snapshots

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""
        LOG.debug("Enter PureISCSIDriver.delete_cgsnapshot")

        pgsnap_name = _get_pgroup_snap_name(cgsnapshot)

        try:
            # FlashArray.destroy_pgroup is also used for deleting
            # pgroup snapshots. The underlying REST API is identical.
            self._array.destroy_pgroup(pgsnap_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        (ERR_MSG_PENDING_ERADICATION in err.text or
                         ERR_MSG_NOT_EXIST in err.text)):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning(_LW("Unable to delete Protection Group "
                                    "Snapshot: %s"), err.text)

        snapshots = self.db.snapshot_get_all_for_cgsnapshot(
            context, cgsnapshot.id)

        for snapshot in snapshots:
            snapshot.status = 'deleted'

        model_update = {'status': cgsnapshot.status}

        LOG.debug("Leave PureISCSIDriver.delete_cgsnapshot")
        return model_update, snapshots

    def _validate_manage_existing_ref(self, existing_ref):
        """Ensure that an existing_ref is valid and return volume info

        If the ref is not valid throw a ManageExistingInvalidReference
        exception with an appropriate error.
        """
        if "name" not in existing_ref or not existing_ref["name"]:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("PureISCSIDriver manage_existing requires a 'name'"
                         " key to identify an existing volume."))

        ref_vol_name = existing_ref['name']

        try:
            volume_info = self._array.get_volume(ref_vol_name)
            if volume_info:
                return volume_info
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    ctxt.reraise = False

        # If volume information was unable to be retrieved we need
        # to throw a Invalid Reference exception
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref,
            reason=_("Unable to find volume with name=%s") % ref_vol_name)

    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        We expect a volume name in the existing_ref that matches one in Purity.
        """
        LOG.debug("Enter PureISCSIDriver.manage_existing.")

        self._validate_manage_existing_ref(existing_ref)

        ref_vol_name = existing_ref['name']

        connected_hosts = \
            self._array.list_volume_private_connections(ref_vol_name)
        if len(connected_hosts) > 0:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("PureISCSIDriver manage_existing cannot manage a "
                         "volume connected to hosts. Please disconnect the "
                         "volume from existing hosts before importing."))

        new_vol_name = _get_vol_name(volume)
        LOG.info(_LI("Renaming existing volume %(ref_name)s to %(new_name)s"),
                 {"ref_name": ref_vol_name, "new_name": new_vol_name})
        self._array.rename_volume(ref_vol_name, new_vol_name)
        LOG.debug("Leave PureISCSIDriver.manage_existing.")
        return None

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        We expect a volume name in the existing_ref that matches one in Purity.
        """
        LOG.debug("Enter PureISCSIDriver.manage_existing_get_size.")

        volume_info = self._validate_manage_existing_ref(existing_ref)
        size = math.ceil(float(volume_info["size"]) / units.Gi)

        LOG.debug("Leave PureISCSIDriver.manage_existing_get_size.")
        return size

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        The volume will be renamed with "-unmanaged" as a suffix
        """
        vol_name = _get_vol_name(volume)
        unmanaged_vol_name = vol_name + "-unmanaged"
        LOG.info(_LI("Renaming existing volume %(ref_name)s to %(new_name)s"),
                 {"ref_name": vol_name, "new_name": unmanaged_vol_name})
        try:
            self._array.rename_volume(vol_name, unmanaged_vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    ctxt.reraise = False
                    LOG.warn(_LW("Volume unmanage was unable to rename "
                                 "the volume, error message: %s"), err.text)
