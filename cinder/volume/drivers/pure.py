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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import objects
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import utils as volume_utils
from cinder.zonemanager import utils as fczm_utils

try:
    import purestorage
except ImportError:
    purestorage = None

LOG = logging.getLogger(__name__)

PURE_OPTS = [
    cfg.StrOpt("pure_api_token",
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

UNMANAGED_SUFFIX = '-unmanaged'
MANAGE_SNAP_REQUIRED_API_VERSIONS = ['1.4']


def log_debug_trace(f):
    def wrapper(*args, **kwargs):
        cls_name = args[0].__class__.__name__
        method_name = "%(cls_name)s.%(method)s" % {"cls_name": cls_name,
                                                   "method": f.__name__}
        LOG.debug("Enter " + method_name)
        result = f(*args, **kwargs)
        LOG.debug("Leave " + method_name)
        return result

    return wrapper


class PureBaseVolumeDriver(san.SanDriver):
    """Performs volume management on Pure Storage FlashArray."""

    SUPPORTED_REST_API_VERSIONS = ['1.2', '1.3', '1.4']

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureBaseVolumeDriver, self).__init__(execute=execute, *args,
                                                   **kwargs)
        self.configuration.append_config_values(PURE_OPTS)
        self._array = None
        self._storage_protocol = None
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

    def check_for_setup_error(self):
        # Avoid inheriting check_for_setup_error from SanDriver, which checks
        # for san_password or san_private_key, not relevant to our driver.
        pass

    @log_debug_trace
    def create_volume(self, volume):
        """Creates a volume."""
        vol_name = self._get_vol_name(volume)
        vol_size = volume["size"] * units.Gi
        self._array.create_volume(vol_name, vol_size)

        if volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume['consistencygroup_id'],
                vol_name
            )

    @log_debug_trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        vol_name = self._get_vol_name(volume)
        if snapshot['cgsnapshot_id']:
            snap_name = self._get_pgroup_snap_name_from_snapshot(snapshot)
        else:
            snap_name = self._get_snap_name(snapshot)

        if not snap_name:
            msg = _('Unable to determine snapshot name in Purity for snapshot '
                    '%(id)s.') % {'id': snapshot['id']}
            raise exception.PureDriverException(reason=msg)

        self._array.copy_volume(snap_name, vol_name)
        self._extend_if_needed(vol_name, snapshot["volume_size"],
                               volume["size"])
        if volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume['consistencygroup_id'],
                vol_name
            )

    @log_debug_trace
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_name = self._get_vol_name(volume)
        src_name = self._get_vol_name(src_vref)
        self._array.copy_volume(src_name, vol_name)
        self._extend_if_needed(vol_name, src_vref["size"], volume["size"])

        if volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume['consistencygroup_id'],
                vol_name
            )

    def _extend_if_needed(self, vol_name, src_size, vol_size):
        """Extend the volume from size src_size to size vol_size."""
        if vol_size > src_size:
            vol_size = vol_size * units.Gi
            self._array.extend_volume(vol_name, vol_size)

    @log_debug_trace
    def delete_volume(self, volume):
        """Disconnect all hosts and delete the volume"""
        vol_name = self._get_vol_name(volume)
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
                    LOG.warning(_LW("Volume deletion failed with message: %s"),
                                err.text)

    @log_debug_trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        vol_name, snap_suff = self._get_snap_name(snapshot).split(".")
        self._array.create_snapshot(vol_name, suffix=snap_suff)

    @log_debug_trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        snap_name = self._get_snap_name(snapshot)
        try:
            self._array.destroy_volume(snap_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400:
                    # Happens if the snapshot does not exist.
                    ctxt.reraise = False
                    LOG.error(_LE("Snapshot deletion failed with message:"
                                  " %s"), err.text)

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def _get_host(self, connector):
        """Get a Purity Host that corresponds to the host in the connector.

        This implementation is specific to the host type (iSCSI, FC, etc).
        """
        raise NotImplementedError

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _disconnect(self, volume, connector, **kwargs):
        vol_name = self._get_vol_name(volume)
        host = self._get_host(connector)
        if host:
            host_name = host["name"]
            result = self._disconnect_host(host_name, vol_name)
        else:
            LOG.error(_LE("Unable to disconnect host from volume."))
            result = False

        return result

    @log_debug_trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        self._disconnect(volume, connector, **kwargs)

    @log_debug_trace
    def _disconnect_host(self, host_name, vol_name):
        """Return value indicates if host was deleted on array or not"""
        try:
            self._array.disconnect_host(host_name, vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400:
                    # Happens if the host and volume are not connected.
                    ctxt.reraise = False
                    LOG.error(_LE("Disconnection failed with message: "
                                  "%(msg)s."), {"msg": err.text})
        if (GENERATED_NAME.match(host_name) and
            not self._array.list_host_connections(host_name,
                                                  private=True)):
            LOG.info(_LI("Deleting unneeded host %(host_name)r."),
                     {"host_name": host_name})
            try:
                self._array.delete_host(host_name)
            except purestorage.PureHTTPError as err:
                with excutils.save_and_reraise_exception() as ctxt:
                    if err.code == 400 and ERR_MSG_NOT_EXIST in err.text:
                        # Happens if the host is already deleted.
                        # This is fine though, just treat it as a warning.
                        ctxt.reraise = False
                        LOG.warning(_LW("Purity host deletion failed: "
                                        "%(msg)s."), {"msg": err.text})
            return True

        return False

    @log_debug_trace
    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service.

        If 'refresh' is True, run the update first.
        """

        if refresh:
            LOG.debug("Updating volume stats.")
            self._update_stats()
        return self._stats

    def _update_stats(self):
        """Set self._stats with relevant information."""
        info = self._array.get(space=True)
        total_capacity = float(info["capacity"]) / units.Gi
        used_space = float(info["total"]) / units.Gi
        free_space = float(total_capacity - used_space)
        prov_space, total_vols = self._get_provisioned_space()
        provisioned_space = float(prov_space) / units.Gi
        # If array is empty we can not calculate a max oversubscription ratio.
        # In this case we choose 20 as a default value for the ratio.  Once
        # some volumes are actually created and some data is stored on the
        # array a much more accurate number will be presented based on current
        # usage.
        if used_space == 0 or provisioned_space == 0:
            thin_provisioning = 20
        else:
            thin_provisioning = provisioned_space / used_space
        data = {
            "volume_backend_name": self._backend_name,
            "vendor_name": "Pure Storage",
            "driver_version": self.VERSION,
            "storage_protocol": self._storage_protocol,
            "total_capacity_gb": total_capacity,
            "free_capacity_gb": free_space,
            "reserved_percentage": 0,
            "consistencygroup_support": True,
            "thin_provisioning_support": True,
            "provisioned_capacity": provisioned_space,
            "max_over_subscription_ratio": thin_provisioning,
            "total_volumes": total_vols,
            "filter_function": self.get_filter_function(),
            "multiattach": True,
        }
        self._stats = data

    def _get_provisioned_space(self):
        """Sum up provisioned size of all volumes on array"""
        volumes = self._array.list_volumes(pending=True)
        return sum(item["size"] for item in volumes), len(volumes)

    @log_debug_trace
    def extend_volume(self, volume, new_size):
        """Extend volume to new_size."""
        vol_name = self._get_vol_name(volume)
        new_size = new_size * units.Gi
        self._array.extend_volume(vol_name, new_size)

    def _add_volume_to_consistency_group(self, consistencygroup_id, vol_name):
        pgroup_name = self._get_pgroup_name_from_id(consistencygroup_id)
        self._array.set_pgroup(pgroup_name, addvollist=[vol_name])

    @log_debug_trace
    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""

        self._array.create_pgroup(self._get_pgroup_name_from_id(group.id))

        model_update = {'status': 'available'}
        return model_update

    def _create_cg_from_cgsnap(self, volumes, snapshots):
        """Creates a new consistency group from a cgsnapshot.

        The new volumes will be consistent with the snapshot.
        """
        for volume, snapshot in zip(volumes, snapshots):
            self.create_volume_from_snapshot(volume, snapshot)

    def _create_cg_from_cg(self, group, source_group, volumes, source_vols):
        """Creates a new consistency group from an existing cg.

        The new volumes will be in a consistent state, but this requires
        taking a new temporary group snapshot and cloning from that.
        """
        pgroup_name = self._get_pgroup_name_from_id(source_group.id)
        tmp_suffix = '%s-tmp' % uuid.uuid4()
        tmp_pgsnap_name = '%(pgroup_name)s.%(pgsnap_suffix)s' % {
            'pgroup_name': pgroup_name,
            'pgsnap_suffix': tmp_suffix,
        }
        LOG.debug('Creating temporary Protection Group snapshot %(snap_name)s '
                  'while cloning Consistency Group %(source_group)s.',
                  {'snap_name': tmp_pgsnap_name,
                   'source_group': source_group.id})
        self._array.create_pgroup_snapshot(pgroup_name, suffix=tmp_suffix)
        try:
            for source_vol, cloned_vol in zip(source_vols, volumes):
                source_snap_name = self._get_pgroup_vol_snap_name(
                    pgroup_name,
                    tmp_suffix,
                    self._get_vol_name(source_vol)
                )
                cloned_vol_name = self._get_vol_name(cloned_vol)
                self._array.copy_volume(source_snap_name, cloned_vol_name)
                self._add_volume_to_consistency_group(
                    group.id,
                    cloned_vol_name
                )
        finally:
            self._delete_pgsnapshot(tmp_pgsnap_name)

    @log_debug_trace
    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        self.create_consistencygroup(context, group)
        if cgsnapshot and snapshots:
            self._create_cg_from_cgsnap(volumes,
                                        snapshots)
        elif source_cg:
            self._create_cg_from_cg(group, source_cg, volumes, source_vols)

        return None, None

    @log_debug_trace
    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""

        try:
            self._array.destroy_pgroup(self._get_pgroup_name_from_id(group.id))
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

        return model_update, volumes

    @log_debug_trace
    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):

        pgroup_name = self._get_pgroup_name_from_id(group.id)
        if add_volumes:
            addvollist = [self._get_vol_name(vol) for vol in add_volumes]
        else:
            addvollist = []

        if remove_volumes:
            remvollist = [self._get_vol_name(vol) for vol in remove_volumes]
        else:
            remvollist = []

        self._array.set_pgroup(pgroup_name, addvollist=addvollist,
                               remvollist=remvollist)

        return None, None, None

    @log_debug_trace
    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a cgsnapshot."""

        cg_id = cgsnapshot.consistencygroup_id
        pgroup_name = self._get_pgroup_name_from_id(cg_id)
        pgsnap_suffix = self._get_pgroup_snap_suffix(cgsnapshot)
        self._array.create_pgroup_snapshot(pgroup_name, suffix=pgsnap_suffix)

        snapshots = objects.SnapshotList().get_all_for_cgsnapshot(
            context, cgsnapshot.id)

        for snapshot in snapshots:
            snapshot.status = 'available'

        model_update = {'status': 'available'}

        return model_update, snapshots

    def _delete_pgsnapshot(self, pgsnap_name):
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

    @log_debug_trace
    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""

        pgsnap_name = self._get_pgroup_snap_name(cgsnapshot)
        self._delete_pgsnapshot(pgsnap_name)

        snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
            context, cgsnapshot.id)

        for snapshot in snapshots:
            snapshot.status = 'deleted'

        model_update = {'status': cgsnapshot.status}

        return model_update, snapshots

    def _validate_manage_existing_ref(self, existing_ref, is_snap=False):
        """Ensure that an existing_ref is valid and return volume info

        If the ref is not valid throw a ManageExistingInvalidReference
        exception with an appropriate error.

        Will return volume or snapshot information from the array for
        the object specified by existing_ref.
        """
        if "name" not in existing_ref or not existing_ref["name"]:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("manage_existing requires a 'name'"
                         " key to identify an existing volume."))

        if is_snap:
            # Purity snapshot names are prefixed with the source volume name
            ref_vol_name, ref_snap_suffix = existing_ref['name'].split('.')
        else:
            ref_vol_name = existing_ref['name']

        try:
            volume_info = self._array.get_volume(ref_vol_name, snap=is_snap)
            if volume_info:
                if is_snap:
                    for snap in volume_info:
                        if snap['name'] == existing_ref['name']:
                            return snap
                else:
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
            reason=_("Unable to find Purity ref with name=%s") % ref_vol_name)

    @log_debug_trace
    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        We expect a volume name in the existing_ref that matches one in Purity.
        """

        self._validate_manage_existing_ref(existing_ref)

        ref_vol_name = existing_ref['name']

        connected_hosts = \
            self._array.list_volume_private_connections(ref_vol_name)
        if len(connected_hosts) > 0:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("%(driver)s manage_existing cannot manage a volume "
                         "connected to hosts. Please disconnect this volume "
                         "from existing hosts before importing"
                         ) % {'driver': self.__class__.__name__})
        new_vol_name = self._get_vol_name(volume)
        LOG.info(_LI("Renaming existing volume %(ref_name)s to %(new_name)s"),
                 {"ref_name": ref_vol_name, "new_name": new_vol_name})
        self._rename_volume_object(ref_vol_name,
                                   new_vol_name,
                                   raise_not_exist=True)
        return None

    @log_debug_trace
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        We expect a volume name in the existing_ref that matches one in Purity.
        """

        volume_info = self._validate_manage_existing_ref(existing_ref)
        size = int(math.ceil(float(volume_info["size"]) / units.Gi))

        return size

    def _rename_volume_object(self, old_name, new_name, raise_not_exist=False):
        """Rename a volume object (could be snapshot) in Purity.

        This will not raise an exception if the object does not exist
        """
        try:
            self._array.rename_volume(old_name, new_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    ctxt.reraise = raise_not_exist
                    LOG.warning(_LW("Unable to rename %(old_name)s, error "
                                    "message: %(error)s"),
                                {"old_name": old_name, "error": err.text})
        return new_name

    @log_debug_trace
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        The volume will be renamed with "-unmanaged" as a suffix
        """
        vol_name = self._get_vol_name(volume)
        unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX
        LOG.info(_LI("Renaming existing volume %(ref_name)s to %(new_name)s"),
                 {"ref_name": vol_name, "new_name": unmanaged_vol_name})
        self._rename_volume_object(vol_name, unmanaged_vol_name)

    def _verify_manage_snap_api_requirements(self):
        api_version = self._array.get_rest_version()
        if api_version not in MANAGE_SNAP_REQUIRED_API_VERSIONS:
            msg = _('Unable to do manage snapshot operations with Purity REST '
                    'API version %(api_version)s, requires '
                    '%(required_versions)s.') % {
                'api_version': api_version,
                'required_versions': MANAGE_SNAP_REQUIRED_API_VERSIONS
            }
            raise exception.PureDriverException(reason=msg)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        self._verify_manage_snap_api_requirements()
        self._validate_manage_existing_ref(existing_ref, is_snap=True)
        ref_snap_name = existing_ref['name']
        new_snap_name = self._get_snap_name(snapshot)
        LOG.info(_LI("Renaming existing snapshot %(ref_name)s to "
                     "%(new_name)s"), {"ref_name": ref_snap_name,
                                       "new_name": new_snap_name})
        self._rename_volume_object(ref_snap_name,
                                   new_snap_name,
                                   raise_not_exist=True)
        return None

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        self._verify_manage_snap_api_requirements()
        snap_info = self._validate_manage_existing_ref(existing_ref,
                                                       is_snap=True)
        size = int(math.ceil(float(snap_info["size"]) / units.Gi))
        return size

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        self._verify_manage_snap_api_requirements()
        snap_name = self._get_snap_name(snapshot)
        unmanaged_snap_name = snap_name + UNMANAGED_SUFFIX
        LOG.info(_LI("Renaming existing snapshot %(ref_name)s to "
                     "%(new_name)s"), {"ref_name": snap_name,
                                       "new_name": unmanaged_snap_name})
        self._rename_volume_object(snap_name, unmanaged_snap_name)

    @staticmethod
    def _get_vol_name(volume):
        """Return the name of the volume Purity will use."""
        return volume["name"] + "-cinder"

    @staticmethod
    def _get_snap_name(snapshot):
        """Return the name of the snapshot that Purity will use."""
        return "%s-cinder.%s" % (snapshot["volume_name"], snapshot["name"])

    @staticmethod
    def _get_pgroup_name_from_id(id):
        return "consisgroup-%s-cinder" % id

    @staticmethod
    def _get_pgroup_snap_suffix(cgsnapshot):
        return "cgsnapshot-%s-cinder" % cgsnapshot.id

    @classmethod
    def _get_pgroup_snap_name(cls, cgsnapshot):
        """Return the name of the pgroup snapshot that Purity will use"""
        cg_id = cgsnapshot.consistencygroup_id
        return "%s.%s" % (cls._get_pgroup_name_from_id(cg_id),
                          cls._get_pgroup_snap_suffix(cgsnapshot))

    @staticmethod
    def _get_pgroup_vol_snap_name(pg_name, pgsnap_suffix, volume_name):
        return "%(pgroup_name)s.%(pgsnap_suffix)s.%(volume_name)s" % {
            'pgroup_name': pg_name,
            'pgsnap_suffix': pgsnap_suffix,
            'volume_name': volume_name,
        }

    def _get_pgroup_snap_name_from_snapshot(self, snapshot):
        """Return the name of the snapshot that Purity will use."""

        # TODO(patrickeast): Remove DB calls once the cgsnapshot objects are
        # available to use and can be associated with the snapshot objects.
        ctxt = context.get_admin_context()
        cgsnapshot = self.db.cgsnapshot_get(ctxt, snapshot.cgsnapshot_id)

        pg_vol_snap_name = "%(group_snap)s.%(volume_name)s-cinder" % {
            'group_snap': self._get_pgroup_snap_name(cgsnapshot),
            'volume_name': snapshot.volume_name
        }
        return pg_vol_snap_name

    @staticmethod
    def _generate_purity_host_name(name):
        """Return a valid Purity host name based on the name passed in."""
        if len(name) > 23:
            name = name[0:23]
        name = INVALID_CHARACTERS.sub("-", name)
        name = name.lstrip("-")
        return "{name}-{uuid}-cinder".format(name=name, uuid=uuid.uuid4().hex)

    def _connect_host_to_vol(self, host_name, vol_name):
        connection = None
        try:
            connection = self._array.connect_host(host_name, vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        "Connection already exists" in err.text):
                    # Happens if the volume is already connected to the host.
                    # Treat this as a success.
                    ctxt.reraise = False
                    LOG.debug("Volume connection already exists for Purity "
                              "host with message: %s", err.text)

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

        return connection

    def retype(self, context, volume, new_type, diff, host):
        """Retype from one volume type to another on the same backend.

        For a Pure Array there is currently no differentiation between types
        of volumes. This means that changing from one type to another on the
        same array should be a no-op.
        """
        return True, None


class PureISCSIDriver(PureBaseVolumeDriver, san.SanISCSIDriver):

    VERSION = "3.0.0"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureISCSIDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = "iSCSI"

    def do_setup(self, context):
        super(PureISCSIDriver, self).do_setup(context)

    def _get_host(self, connector):
        """Return dict describing existing Purity host object or None."""
        hosts = self._array.list_hosts()
        for host in hosts:
            if connector["initiator"] in host["iqn"]:
                return host
        return None

    @log_debug_trace
    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info."""
        connection = self._connect(volume, connector, initiator_data)
        target_ports = self._get_target_iscsi_ports()
        multipath = connector.get("multipath", False)

        properties = self._build_connection_properties(connection,
                                                       target_ports,
                                                       multipath)

        if self.configuration.use_chap_auth:
            properties["data"]["auth_method"] = "CHAP"
            properties["data"]["auth_username"] = connection["auth_username"]
            properties["data"]["auth_password"] = connection["auth_password"]

        initiator_update = connection.get("initiator_update", False)
        if initiator_update:
            properties["initiator_update"] = initiator_update

        return properties

    def _build_connection_properties(self, connection, target_ports,
                                     multipath):
        props = {
            "driver_volume_type": "iscsi",
            "data": {
                "target_discovered": False,
                "access_mode": "rw",
                "discard": True,
            },
        }

        port_iter = iter(target_ports)

        target_luns = []
        target_iqns = []
        target_portals = []

        for port in port_iter:
            target_luns.append(connection["lun"])
            target_iqns.append(port["iqn"])
            target_portals.append(port["portal"])

        # If we have multiple ports always report them
        if target_luns and target_iqns and target_portals:
            props["data"]["target_luns"] = target_luns
            props["data"]["target_iqns"] = target_iqns
            props["data"]["target_portals"] = target_portals

        return props

    def _get_target_iscsi_ports(self):
        """Return list of iSCSI-enabled port descriptions."""
        ports = self._array.list_ports()
        iscsi_ports = [port for port in ports if port["iqn"]]
        if not iscsi_ports:
            raise exception.PureDriverException(
                reason=_("No iSCSI-enabled ports on target array."))
        return iscsi_ports

    @staticmethod
    def _generate_chap_secret():
        return volume_utils.generate_password()

    @classmethod
    def _get_chap_credentials(cls, host, data):
        initiator_updates = None
        username = host
        password = None
        if data:
            for d in data:
                if d["key"] == CHAP_SECRET_KEY:
                    password = d["value"]
                    break
        if not password:
            password = cls._generate_chap_secret()
            initiator_updates = {
                "set_values": {
                    CHAP_SECRET_KEY: password
                }
            }
        return username, password, initiator_updates

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _connect(self, volume, connector, initiator_data):
        """Connect the host and volume; return dict describing connection."""
        iqn = connector["initiator"]

        if self.configuration.use_chap_auth:
            (chap_username, chap_password, initiator_update) = \
                self._get_chap_credentials(connector['host'], initiator_data)

        vol_name = self._get_vol_name(volume)
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
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info(_LI("Creating host object %(host_name)r with IQN:"
                         " %(iqn)s."), {"host_name": host_name, "iqn": iqn})
            self._array.create_host(host_name, iqnlist=[iqn])

            if self.configuration.use_chap_auth:
                self._array.set_host(host_name,
                                     host_user=chap_username,
                                     host_password=chap_password)

        connection = self._connect_host_to_vol(host_name, vol_name)

        if self.configuration.use_chap_auth:
            connection["auth_username"] = chap_username
            connection["auth_password"] = chap_password

            if initiator_update:
                connection["initiator_update"] = initiator_update

        return connection


class PureFCDriver(PureBaseVolumeDriver, driver.FibreChannelDriver):

    VERSION = "1.0.0"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureFCDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = "FC"
        self._lookup_service = fczm_utils.create_lookup_service()

    def do_setup(self, context):
        super(PureFCDriver, self).do_setup(context)

    def _get_host(self, connector):
        """Return dict describing existing Purity host object or None."""
        hosts = self._array.list_hosts()
        for host in hosts:
            for wwn in connector["wwpns"]:
                if wwn in str(host["wwn"]).lower():
                    return host

    def _get_array_wwns(self):
        """Return list of wwns from the array"""
        ports = self._array.list_ports()
        return [port["wwn"] for port in ports if port["wwn"]]

    @fczm_utils.AddFCZone
    @log_debug_trace
    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info."""

        connection = self._connect(volume, connector)
        target_wwns = self._get_array_wwns()
        init_targ_map = self._build_initiator_target_map(target_wwns,
                                                         connector)
        properties = {
            "driver_volume_type": "fibre_channel",
            "data": {
                'target_discovered': True,
                "target_lun": connection["lun"],
                "target_wwn": target_wwns,
                'access_mode': 'rw',
                'initiator_target_map': init_targ_map,
                "discard": True,
            }
        }

        return properties

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _connect(self, volume, connector):
        """Connect the host and volume; return dict describing connection."""
        wwns = connector["wwpns"]

        vol_name = self._get_vol_name(volume)
        host = self._get_host(connector)

        if host:
            host_name = host["name"]
            LOG.info(_LI("Re-using existing purity host %(host_name)r"),
                     {"host_name": host_name})
        else:
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info(_LI("Creating host object %(host_name)r with WWN:"
                         " %(wwn)s."), {"host_name": host_name, "wwn": wwns})
            self._array.create_host(host_name, wwnlist=wwns)

        return self._connect_host_to_vol(host_name, vol_name)

    def _build_initiator_target_map(self, target_wwns, connector):
        """Build the target_wwns and the initiator target map."""
        init_targ_map = {}

        if self._lookup_service:
            # use FC san lookup to determine which NSPs to use
            # for the new VLUN.
            dev_map = self._lookup_service.get_device_mapping_from_network(
                connector['wwpns'],
                target_wwns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
        else:
            init_targ_map = dict.fromkeys(connector["wwpns"], target_wwns)

        return init_targ_map

    @fczm_utils.RemoveFCZone
    @log_debug_trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        no_more_connections = self._disconnect(volume, connector, **kwargs)

        properties = {"driver_volume_type": "fibre_channel", "data": {}}

        if no_more_connections:
            target_wwns = self._get_array_wwns()
            init_targ_map = self._build_initiator_target_map(target_wwns,
                                                             connector)
            properties["data"] = {"target_wwn": target_wwns,
                                  "initiator_target_map": init_targ_map}

        return properties
