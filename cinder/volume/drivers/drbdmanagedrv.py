# Copyright (c) 2014 LINBIT HA Solutions GmbH
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

This driver connects Cinder to an installed DRBDmanage instance, see
http://drbd.linbit.com/users-guide-9.0/ch-openstack.html
for more details.

"""


import eventlet
import json
import six
import socket
import time
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units


from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver

try:
    import dbus
    import drbdmanage.consts as dm_const
    import drbdmanage.exceptions as dm_exc
    import drbdmanage.utils as dm_utils
except ImportError:
    # Used for the tests, when no DRBDmanage is installed
    dbus = None
    dm_const = None
    dm_exc = None
    dm_utils = None


LOG = logging.getLogger(__name__)

drbd_opts = [
    cfg.IntOpt('drbdmanage_redundancy',
               default=1,
               help='Number of nodes that should replicate the data.'),
    cfg.StrOpt('drbdmanage_resource_policy',
               default='{"ratio": "0.51", "timeout": "60"}',
               help='Resource deployment completion wait policy.'),
    cfg.StrOpt('drbdmanage_disk_options',
               default='{"c-min-rate": "4M"}',
               help='Disk options to set on new resources. '
               'See http://www.drbd.org/en/doc/users-guide-90/re-drbdconf'
               ' for all the details.'),
    cfg.StrOpt('drbdmanage_net_options',
               default='{"connect-int": "4", "allow-two-primaries": "yes", '
               '"ko-count": "30", "max-buffers": "20000", '
               '"ping-timeout": "100"}',
               help='Net options to set on new resources. '
               'See http://www.drbd.org/en/doc/users-guide-90/re-drbdconf'
               ' for all the details.'),
    cfg.StrOpt('drbdmanage_resource_options',
               default='{"auto-promote-timeout": "300"}',
               help='Resource options to set on new resources. '
               'See http://www.drbd.org/en/doc/users-guide-90/re-drbdconf'
               ' for all the details.'),
    cfg.StrOpt('drbdmanage_snapshot_policy',
               default='{"count": "1", "timeout": "60"}',
               help='Snapshot completion wait policy.'),
    cfg.StrOpt('drbdmanage_resize_policy',
               default='{"timeout": "60"}',
               help='Volume resize completion wait policy.'),
    cfg.StrOpt('drbdmanage_resource_plugin',
               default="drbdmanage.plugins.plugins.wait_for.WaitForResource",
               help='Resource deployment completion wait plugin.'),
    cfg.StrOpt('drbdmanage_snapshot_plugin',
               default="drbdmanage.plugins.plugins.wait_for.WaitForSnapshot",
               help='Snapshot completion wait plugin.'),
    cfg.StrOpt('drbdmanage_resize_plugin',
               default="drbdmanage.plugins.plugins.wait_for.WaitForVolumeSize",
               help='Volume resize completion wait plugin.'),
    cfg.BoolOpt('drbdmanage_devs_on_controller',
                default=True,
                help='''If set, the c-vol node will receive a useable
                /dev/drbdX device, even if the actual data is stored on
                other nodes only.
                This is useful for debugging, maintenance, and to be
                able to do the iSCSI export from the c-vol node.''')
    # TODO(PM): offsite_redundancy?
    # TODO(PM): choose DRBDmanage storage pool?
]


CONF = cfg.CONF
CONF.register_opts(drbd_opts, group=configuration.SHARED_CONF_GROUP)


AUX_PROP_CINDER_VOL_ID = "cinder-id"
AUX_PROP_TEMP_CLIENT = "cinder-is-temp-client"
DM_VN_PREFIX = 'CV_'  # sadly 2CV isn't allowed by DRBDmanage
DM_SN_PREFIX = 'SN_'


# Need to be set later, so that the tests can fake
CS_DEPLOYED = None
CS_DISKLESS = None
CS_UPD_CON = None


class DrbdManageBaseDriver(driver.VolumeDriver):
    """Cinder driver that uses DRBDmanage for storage."""

    VERSION = '1.1.0'
    drbdmanage_dbus_name = 'org.drbd.drbdmanaged'
    drbdmanage_dbus_interface = '/interface'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Cinder_Jenkins"

    def __init__(self, *args, **kwargs):
        self.empty_list = dbus.Array([], signature="a(s)")
        self.empty_dict = dbus.Array([], signature="a(ss)")

        super(DrbdManageBaseDriver, self).__init__(*args, **kwargs)

        self.configuration.append_config_values(drbd_opts)
        if not self.drbdmanage_dbus_name:
            self.drbdmanage_dbus_name = 'org.drbd.drbdmanaged'
        if not self.drbdmanage_dbus_interface:
            self.drbdmanage_dbus_interface = '/interface'
        self.drbdmanage_redundancy = int(getattr(self.configuration,
                                                 'drbdmanage_redundancy', 1))
        self.drbdmanage_devs_on_controller = bool(
            getattr(self.configuration,
                    'drbdmanage_devs_on_controller',
                    True))
        self.dm_control_vol = ".drbdctrl"

        self.backend_name = self.configuration.safe_get(
            'volume_backend_name') or 'drbdmanage'

        js_decoder = json.JSONDecoder()
        self.policy_resource = js_decoder.decode(
            self.configuration.safe_get('drbdmanage_resource_policy'))
        self.policy_snapshot = js_decoder.decode(
            self.configuration.safe_get('drbdmanage_snapshot_policy'))
        self.policy_resize = js_decoder.decode(
            self.configuration.safe_get('drbdmanage_resize_policy'))

        self.resource_options = js_decoder.decode(
            self.configuration.safe_get('drbdmanage_resource_options'))
        self.net_options = js_decoder.decode(
            self.configuration.safe_get('drbdmanage_net_options'))
        self.disk_options = js_decoder.decode(
            self.configuration.safe_get('drbdmanage_disk_options'))

        self.plugin_resource = self.configuration.safe_get(
            'drbdmanage_resource_plugin')
        self.plugin_snapshot = self.configuration.safe_get(
            'drbdmanage_snapshot_plugin')
        self.plugin_resize = self.configuration.safe_get(
            'drbdmanage_resize_plugin')

        # needed as per pep8:
        #   F841 local variable 'CS_DEPLOYED' is assigned to but never used
        global CS_DEPLOYED, CS_DISKLESS, CS_UPD_CON
        CS_DEPLOYED = dm_const.CSTATE_PREFIX + dm_const.FLAG_DEPLOY
        CS_DISKLESS = dm_const.CSTATE_PREFIX + dm_const.FLAG_DISKLESS
        CS_UPD_CON = dm_const.CSTATE_PREFIX + dm_const.FLAG_UPD_CON

    def dbus_connect(self):
        self.odm = dbus.SystemBus().get_object(self.drbdmanage_dbus_name,
                                               self.drbdmanage_dbus_interface)
        self.odm.ping()

    def call_or_reconnect(self, fn, *args):
        """Call DBUS function; on a disconnect try once to reconnect."""
        try:
            return fn(*args)
        except dbus.DBusException as e:
            LOG.warning("Got disconnected; trying to reconnect. (%s)", e)
            self.dbus_connect()
            # Old function object is invalid, get new one.
            return getattr(self.odm, fn._method_name)(*args)

    def _fetch_answer_data(self, res, key, level=None, req=True):
        for code, fmt, data in res:
            if code == dm_exc.DM_INFO:
                if level and level != fmt:
                    continue

                value = [v for k, v in data if k == key]
                if value:
                    if len(value) == 1:
                        return value[0]
                    else:
                        return value

        if req:
            if level:
                l = level + ":" + key
            else:
                l = key

            msg = _('DRBDmanage driver error: expected key "%s" '
                    'not in answer, wrong DRBDmanage version?') % l
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        return None

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(DrbdManageBaseDriver, self).do_setup(context)
        self.dbus_connect()

    def check_for_setup_error(self):
        """Verify that requirements are in place to use DRBDmanage driver."""
        if not all((dbus, dm_exc, dm_const, dm_utils)):
            msg = _('DRBDmanage driver setup error: some required '
                    'libraries (dbus, drbdmanage.*) not found.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        if self.odm.ping() != 0:
            message = _('Cannot ping DRBDmanage backend')
            raise exception.VolumeBackendAPIException(data=message)

    def _clean_uuid(self):
        """Returns a UUID string, WITHOUT braces."""
        # Some uuid library versions put braces around the result!?
        # We don't want them, just a plain [0-9a-f-]+ string.
        id = str(uuid.uuid4())
        id = id.replace("{", "")
        id = id.replace("}", "")
        return id

    def _check_result(self, res, ignore=None, ret=0):
        seen_success = False
        seen_error = False
        result = ret
        for (code, fmt, arg_l) in res:
            # convert from DBUS to Python
            arg = dict(arg_l)
            if ignore and code in ignore:
                if not result:
                    result = code
                continue
            if code == dm_exc.DM_SUCCESS:
                seen_success = True
                continue
            if code == dm_exc.DM_INFO:
                continue
            seen_error = _("Received error string: %s") % (fmt % arg)

        if seen_error:
            raise exception.VolumeBackendAPIException(data=seen_error)
        if seen_success:
            return ret
        # by default okay - or the ignored error code.
        return ret

    # DRBDmanage works in kiB units; Cinder uses GiB.
    def _vol_size_to_dm(self, size):
        return int(size * units.Gi / units.Ki)

    def _vol_size_to_cinder(self, size):
        return int(size * units.Ki / units.Gi)

    def is_clean_volume_name(self, name, prefix):
        try:
            if (name.startswith(CONF.volume_name_template % "") and
                    uuid.UUID(name[7:]) is not None):
                return prefix + name[7:]
        except ValueError:
            return None

        try:
            if uuid.UUID(name) is not None:
                return prefix + name
        except ValueError:
            return None

    def _call_policy_plugin(self, plugin, pol_base, pol_this):
        """Returns True for done, False for timeout."""

        pol_inp_data = dict(pol_base)
        pol_inp_data.update(pol_this,
                            starttime=str(time.time()))

        retry = 0
        while True:
            res, pol_result = self.call_or_reconnect(
                self.odm.run_external_plugin,
                plugin,
                pol_inp_data)
            self._check_result(res)

            if pol_result['result'] == dm_const.BOOL_TRUE:
                return True

            if pol_result['timeout'] == dm_const.BOOL_TRUE:
                return False

            eventlet.sleep(min(0.5 + retry / 5, 2))
            retry += 1

    def _wait_for_node_assignment(self, res_name, vol_nr, nodenames,
                                  filter_props=None, timeout=90,
                                  check_vol_deployed=True):
        """Return True as soon as one assignment matches the filter."""

        # TODO(LINBIT): unify with policy plugins

        if not filter_props:
            filter_props = self.empty_dict

        end_time = time.time() + timeout

        retry = 0
        while time.time() < end_time:
            res, assgs = self.call_or_reconnect(self.odm.list_assignments,
                                                nodenames, [res_name], 0,
                                                filter_props, self.empty_list)
            self._check_result(res)

            if len(assgs) > 0:
                for assg in assgs:
                    vols = assg[3]

                    for v_nr, v_prop in vols:
                        if (v_nr == vol_nr):
                            if not check_vol_deployed:
                                # no need to check
                                return True

                            if v_prop[CS_DEPLOYED] == dm_const.BOOL_TRUE:
                                return True

            retry += 1
            # Not yet
            LOG.warning('Try #%(try)d: Volume "%(res)s"/%(vol)d '
                        'not yet deployed on "%(host)s", waiting.',
                        {'try': retry, 'host': nodenames,
                         'res': res_name, 'vol': vol_nr})

            eventlet.sleep(min(0.5 + retry / 5, 2))

        # Timeout
        return False

    def _priv_hash_from_volume(self, volume):
        return dm_utils.dict_to_aux_props({
            AUX_PROP_CINDER_VOL_ID: volume['id'],
        })

    def snapshot_name_from_cinder_snapshot(self, snapshot):
        sn_name = self.is_clean_volume_name(snapshot['id'], DM_SN_PREFIX)
        return sn_name

    def _res_and_vl_data_for_volume(self, volume, empty_ok=False):
        """Find DRBD resource and volume ID.

        A DRBD resource might consist of several "volumes"
        (think consistency groups).
        So we have to find the number of the volume within one resource.
        Returns resource name, volume number, and resource
        and volume properties.
        """

        # If we get a string, use it as-is.
        # Else it's a dictionary; then get the ID.
        if isinstance(volume, six.string_types):
            v_uuid = volume
        else:
            v_uuid = volume['id']

        res, rl = self.call_or_reconnect(self.odm.list_volumes,
                                         self.empty_dict,
                                         0,
                                         dm_utils.dict_to_aux_props(
                                             {AUX_PROP_CINDER_VOL_ID: v_uuid}),
                                         self.empty_dict)
        self._check_result(res)

        if (not rl) or (len(rl) == 0):
            if empty_ok:
                LOG.debug("No volume %s found.", v_uuid)
                return None, None, None, None
            raise exception.VolumeBackendAPIException(
                data=_("volume %s not found in drbdmanage") % v_uuid)
        if len(rl) > 1:
            raise exception.VolumeBackendAPIException(
                data=_("multiple resources with name %s found by drbdmanage") %
                v_uuid)

        (r_name, r_props, vols) = rl[0]
        if len(vols) != 1:
            raise exception.VolumeBackendAPIException(
                data=_("not exactly one volume with id %s") %
                v_uuid)

        (v_nr, v_props) = vols[0]

        LOG.debug("volume %(uuid)s is %(res)s/%(nr)d; %(rprop)s, %(vprop)s",
                  {'uuid': v_uuid, 'res': r_name, 'nr': v_nr,
                   'rprop': dict(r_props), 'vprop': dict(v_props)})

        return r_name, v_nr, r_props, v_props

    def _resource_and_snap_data_from_snapshot(self, snapshot, empty_ok=False):
        """Find DRBD resource and snapshot name from the snapshot ID."""
        s_uuid = snapshot['id']
        res, rs = self.call_or_reconnect(self.odm.list_snapshots,
                                         self.empty_dict,
                                         self.empty_dict,
                                         0,
                                         dm_utils.dict_to_aux_props(
                                             {AUX_PROP_CINDER_VOL_ID: s_uuid}),
                                         self.empty_dict)
        self._check_result(res)

        if (not rs) or (len(rs) == 0):
            if empty_ok:
                return None
            else:
                raise exception.VolumeBackendAPIException(
                    data=_("no snapshot with id %s found in drbdmanage") %
                    s_uuid)
        if len(rs) > 1:
            raise exception.VolumeBackendAPIException(
                data=_("multiple resources with snapshot ID %s found") %
                s_uuid)

        (r_name, snaps) = rs[0]
        if len(snaps) != 1:
            raise exception.VolumeBackendAPIException(
                data=_("not exactly one snapshot with id %s") % s_uuid)

        (s_name, s_props) = snaps[0]

        LOG.debug("snapshot %(uuid)s is %(res)s/%(snap)s",
                  {'uuid': s_uuid, 'res': r_name, 'snap': s_name})

        return r_name, s_name, s_props

    def _resource_name_volnr_for_volume(self, volume, empty_ok=False):
        res, vol, __, __ = self._res_and_vl_data_for_volume(volume, empty_ok)
        return res, vol

    def local_path(self, volume):
        d_res_name, d_vol_nr = self._resource_name_volnr_for_volume(volume)

        res, data = self.call_or_reconnect(self.odm.text_query,
                                           [dm_const.TQ_GET_PATH,
                                            d_res_name,
                                            str(d_vol_nr)])
        self._check_result(res)

        if len(data) == 1:
            return data[0]

        message = _('Got bad path information from DRBDmanage! (%s)') % data
        raise exception.VolumeBackendAPIException(data=message)

    def _push_drbd_options(self, d_res_name):
        res_opt = {'resource': d_res_name,
                   'target': 'resource',
                   'type': 'reso'}
        res_opt.update(self.resource_options)
        res = self.call_or_reconnect(self.odm.set_drbdsetup_props, res_opt)
        self._check_result(res)

        res_opt = {'resource': d_res_name,
                   'target': 'resource',
                   'type': 'neto'}
        res_opt.update(self.net_options)
        res = self.call_or_reconnect(self.odm.set_drbdsetup_props, res_opt)
        self._check_result(res)

        res_opt = {'resource': d_res_name,
                   'target': 'resource',
                   'type': 'disko'}
        res_opt.update(self.disk_options)
        res = self.call_or_reconnect(self.odm.set_drbdsetup_props, res_opt)
        self._check_result(res)

    def create_volume(self, volume):
        """Creates a DRBD resource.

        We address it later on via the ID that gets stored
        as a private property.
        """

        # TODO(PM): consistency groups
        d_res_name = self.is_clean_volume_name(volume['id'], DM_VN_PREFIX)

        res = self.call_or_reconnect(self.odm.create_resource,
                                     d_res_name,
                                     self.empty_dict)
        self._check_result(res, ignore=[dm_exc.DM_EEXIST], ret=None)

        self._push_drbd_options(d_res_name)

        # If we get DM_EEXIST, then the volume already exists, eg. because
        # deploy gave an error on a previous try (like ENOSPC).
        # Still, there might or might not be the volume in the resource -
        # we have to check that explicitly.
        (__, drbd_vol) = self._resource_name_volnr_for_volume(volume,
                                                              empty_ok=True)
        if not drbd_vol:
            props = self._priv_hash_from_volume(volume)
            # TODO(PM): properties - redundancy, etc
            res = self.call_or_reconnect(self.odm.create_volume,
                                         d_res_name,
                                         self._vol_size_to_dm(volume['size']),
                                         props)
            self._check_result(res)
            drbd_vol = self._fetch_answer_data(res, dm_const.VOL_ID)

        # If we crashed between create_volume and the deploy call,
        # the volume might be defined but not exist on any server. Oh my.
        res = self.call_or_reconnect(self.odm.auto_deploy,
                                     d_res_name, self.drbdmanage_redundancy,
                                     0, False)
        self._check_result(res)

        okay = self._call_policy_plugin(self.plugin_resource,
                                        self.policy_resource,
                                        dict(resource=d_res_name,
                                             volnr=str(drbd_vol)))
        if not okay:
            message = (_('DRBDmanage timeout waiting for volume creation; '
                         'resource "%(res)s", volume "%(vol)s"') %
                       {'res': d_res_name, 'vol': volume['id']})
            raise exception.VolumeBackendAPIException(data=message)

        if self.drbdmanage_devs_on_controller:
            # TODO(pm): CG
            res = self.call_or_reconnect(self.odm.assign,
                                         socket.gethostname(),
                                         d_res_name,
                                         [(dm_const.FLAG_DISKLESS,
                                           dm_const.BOOL_TRUE)])
            self._check_result(res, ignore=[dm_exc.DM_EEXIST])

        return {}

    def delete_volume(self, volume):
        """Deletes a resource."""
        d_res_name, d_vol_nr = self._resource_name_volnr_for_volume(
            volume,
            empty_ok=True)

        if not d_res_name:
            # OK, already gone.
            return True

        # TODO(PM): check if in use? Ask whether Primary, or just check result?
        res = self.call_or_reconnect(self.odm.remove_volume,
                                     d_res_name, d_vol_nr, False)
        self._check_result(res, ignore=[dm_exc.DM_ENOENT])

        # Ask for volumes in that resource that are not scheduled for deletion.
        res, rl = self.call_or_reconnect(self.odm.list_volumes,
                                         [d_res_name],
                                         0,
                                         [(dm_const.TSTATE_PREFIX +
                                           dm_const.FLAG_REMOVE,
                                           dm_const.BOOL_FALSE)],
                                         self.empty_list)
        self._check_result(res)

        # We expect the _resource_ to be here still (we just got a volnr from
        # it!), so just query the volumes.
        # If the resource has no volumes anymore, the current DRBDmanage
        # version (errorneously, IMO) returns no *resource*, too.
        if len(rl) > 1:
            message = _('DRBDmanage expected one resource ("%(res)s"), '
                        'got %(n)d') % {'res': d_res_name, 'n': len(rl)}
            raise exception.VolumeBackendAPIException(data=message)

        # Delete resource, if empty
        if (not rl) or (not rl[0]) or (len(rl[0][2]) == 0):
            res = self.call_or_reconnect(self.odm.remove_resource,
                                         d_res_name, False)
            self._check_result(res, ignore=[dm_exc.DM_ENOENT])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug("create vol from snap: from %(snap)s make %(vol)s",
                  {'snap': snapshot['id'], 'vol': volume['id']})
        # TODO(PM): Consistency groups.
        d_res_name, sname, sprop = self._resource_and_snap_data_from_snapshot(
            snapshot)

        new_res = self.is_clean_volume_name(volume['id'], DM_VN_PREFIX)

        r_props = self.empty_dict
        # TODO(PM): consistency groups => different volume number possible
        new_vol_nr = 0
        v_props = [(new_vol_nr, self._priv_hash_from_volume(volume))]

        res = self.call_or_reconnect(self.odm.restore_snapshot,
                                     new_res,
                                     d_res_name,
                                     sname,
                                     r_props,
                                     v_props)
        self._check_result(res, ignore=[dm_exc.DM_ENOENT])

        self._push_drbd_options(d_res_name)

        # TODO(PM): CG
        okay = self._call_policy_plugin(self.plugin_resource,
                                        self.policy_resource,
                                        dict(resource=new_res,
                                             volnr=str(new_vol_nr)))
        if not okay:
            message = (_('DRBDmanage timeout waiting for new volume '
                         'after snapshot restore; '
                         'resource "%(res)s", volume "%(vol)s"') %
                       {'res': new_res, 'vol': volume['id']})
            raise exception.VolumeBackendAPIException(data=message)

        if (('size' in volume) and (volume['size'] > snapshot['volume_size'])):
            LOG.debug("resize volume '%(dst_vol)s' from %(src_size)d to "
                      "%(dst_size)d",
                      {'dst_vol': volume['id'],
                       'src_size': snapshot['volume_size'],
                       'dst_size': volume['size']})
            self.extend_volume(volume, volume['size'])

    def create_cloned_volume(self, volume, src_vref):
        temp_id = self._clean_uuid()
        snapshot = {'id': temp_id}

        self.create_snapshot({'id': temp_id,
                              'volume_id': src_vref['id']})

        snapshot['volume_size'] = src_vref['size']
        self.create_volume_from_snapshot(volume, snapshot)

        self.delete_snapshot(snapshot)

    def _update_volume_stats(self):
        data = {}

        data["vendor_name"] = 'Open Source'
        data["driver_version"] = self.VERSION
        # This has to match the name set in the cinder volume driver spec,
        # so keep it lowercase
        data["volume_backend_name"] = self.backend_name
        data["pools"] = []

        res, free, total = self.call_or_reconnect(self.odm.cluster_free_query,
                                                  self.drbdmanage_redundancy)
        self._check_result(res)

        location_info = ('DrbdManageBaseDriver:%(cvol)s:%(dbus)s' %
                         {'cvol': self.dm_control_vol,
                          'dbus': self.drbdmanage_dbus_name})

        # add volumes
        res, rl = self.call_or_reconnect(self.odm.list_volumes,
                                         self.empty_list,
                                         0,
                                         self.empty_dict,
                                         self.empty_list)
        self._check_result(res)
        total_volumes = 0
        for res in rl:
            total_volumes += len(res[2])

        # TODO(PM): multiple DRBDmanage instances and/or multiple pools
        single_pool = {}
        single_pool.update(dict(
            pool_name=data["volume_backend_name"],
            free_capacity_gb=self._vol_size_to_cinder(free),
            total_capacity_gb=self._vol_size_to_cinder(total),
            reserved_percentage=self.configuration.reserved_percentage,
            location_info=location_info,
            total_volumes=total_volumes,
            filter_function=self.get_filter_function(),
            goodness_function=self.get_goodness_function(),
            QoS_support=False))

        data["pools"].append(single_pool)

        self._stats = data
        return self._stats

    def extend_volume(self, volume, new_size):
        d_res_name, d_vol_nr = self._resource_name_volnr_for_volume(volume)

        res = self.call_or_reconnect(self.odm.resize_volume,
                                     d_res_name, d_vol_nr, -1,
                                     self._vol_size_to_dm(new_size),
                                     0)
        self._check_result(res)

        okay = self._call_policy_plugin(self.plugin_resize,
                                        self.policy_resize,
                                        dict(resource=d_res_name,
                                             volnr=str(d_vol_nr),
                                             req_size=str(new_size)))
        if not okay:
            message = (_('DRBDmanage timeout waiting for volume size; '
                         'volume ID "%(id)s" (res "%(res)s", vnr %(vnr)d)') %
                       {'id': volume['id'],
                        'res': d_res_name, 'vnr': d_vol_nr})
            raise exception.VolumeBackendAPIException(data=message)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        sn_name = self.snapshot_name_from_cinder_snapshot(snapshot)

        d_res_name, d_vol_nr = self._resource_name_volnr_for_volume(
            snapshot["volume_id"])

        res, data = self.call_or_reconnect(self.odm.list_assignments,
                                           self.empty_dict,
                                           [d_res_name],
                                           0,
                                           {CS_DISKLESS: dm_const.BOOL_FALSE},
                                           self.empty_list)
        self._check_result(res)

        nodes = [d[0] for d in data]
        if len(nodes) < 1:
            raise exception.VolumeBackendAPIException(
                _('Snapshot res "%s" that is not deployed anywhere?') %
                (d_res_name))

        props = self._priv_hash_from_volume(snapshot)
        res = self.call_or_reconnect(self.odm.create_snapshot,
                                     d_res_name, sn_name, nodes, props)
        self._check_result(res)

        okay = self._call_policy_plugin(self.plugin_snapshot,
                                        self.policy_snapshot,
                                        dict(resource=d_res_name,
                                             snapshot=sn_name))
        if not okay:
            message = (_('DRBDmanage timeout waiting for snapshot creation; '
                         'resource "%(res)s", snapshot "%(sn)s"') %
                       {'res': d_res_name, 'sn': sn_name})
            raise exception.VolumeBackendAPIException(data=message)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        d_res_name, sname, _ = self._resource_and_snap_data_from_snapshot(
            snapshot, empty_ok=True)

        if not d_res_name:
            # resource already gone?
            LOG.warning("snapshot: %s not found, "
                        "skipping delete operation", snapshot['id'])
            LOG.info('Successfully deleted snapshot: %s', snapshot['id'])
            return True

        res = self.call_or_reconnect(self.odm.remove_snapshot,
                                     d_res_name, sname, True)
        return self._check_result(res, ignore=[dm_exc.DM_ENOENT])


# Class with iSCSI interface methods
@interface.volumedriver
class DrbdManageIscsiDriver(DrbdManageBaseDriver):
    """Cinder driver that uses the iSCSI protocol. """

    def __init__(self, *args, **kwargs):
        super(DrbdManageIscsiDriver, self).__init__(*args, **kwargs)
        target_driver = self.target_mapping[
            self.configuration.safe_get('iscsi_helper')]

        LOG.debug('Attempting to initialize DRBD driver with the '
                  'following target_driver: %s',
                  target_driver)

        self.target_driver = importutils.import_object(
            target_driver,
            configuration=self.configuration,
            db=self.db,
            executor=self._execute)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""

        self._update_volume_stats()
        self._stats["storage_protocol"] = "iSCSI"
        return self._stats

    def ensure_export(self, context, volume):
        volume_path = self.local_path(volume)
        return self.target_driver.ensure_export(
            context,
            volume,
            volume_path)

    def create_export(self, context, volume, connector):
        volume_path = self.local_path(volume)
        export_info = self.target_driver.create_export(
            context,
            volume,
            volume_path)

        return {'provider_location': export_info['location'],
                'provider_auth': export_info['auth'], }

    def remove_export(self, context, volume):
        return self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        return self.target_driver.initialize_connection(volume, connector)

    def validate_connector(self, connector):
        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):
        return self.target_driver.terminate_connection(volume,
                                                       connector,
                                                       **kwargs)

# for backwards compatibility keep the old class name, too
DrbdManageDriver = DrbdManageIscsiDriver


# Class with DRBD transport mode
@interface.volumedriver
class DrbdManageDrbdDriver(DrbdManageBaseDriver):
    """Cinder driver that uses the DRBD protocol. """

    def __init__(self, *args, **kwargs):
        super(DrbdManageDrbdDriver, self).__init__(*args, **kwargs)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""

        self._update_volume_stats()
        self._stats["storage_protocol"] = "DRBD"
        return self._stats

    def _return_local_access(self, nodename, volume,
                             d_res_name=None, volume_path=None):

        if not volume_path:
            volume_path = self.local_path(volume)

        return {
            'driver_volume_type': 'local',
            'data': {
                "device_path": volume_path
            }
        }

    def _return_drbdadm_config(self, volume, nodename,
                               d_res_name=None, volume_path=None):

        if not d_res_name:
            d_res_name, d_vol_nr = self._resource_name_volnr_for_volume(volume)

        res, data = self.call_or_reconnect(
            self.odm.text_query,
            ['export_conf_split_up', nodename, d_res_name])
        self._check_result(res)

        config = six.text_type(data.pop(0))
        subst_data = {}
        while len(data):
            k = data.pop(0)
            subst_data[k] = data.pop(0)

        if not volume_path:
            volume_path = self.local_path(volume)

        return {
            'driver_volume_type': 'drbd',
            'data': {
                'provider_location': ' '.join('drbd', nodename),
                'device': volume_path,
                # TODO(pm): consistency groups
                'devices': [volume_path],
                'provider_auth': subst_data['shared-secret'],
                'config': config,
                'name': d_res_name,
            }
        }

    def _is_external_node(self, nodename):
        """Return whether the given node is an "external" node."""

        # If the node accessing the data (the "initiator" in iSCSI speak,
        # "client" or "target" otherwise) is marked as an FLAG_EXTERNAL
        # node, it does not have DRBDmanage active - and that means
        # we have to send the necessary DRBD configuration.
        #
        # If DRBDmanage is running there, just pushing the (client)
        # assignment is enough to make the local path available.

        res, nodes = self.call_or_reconnect(self.odm.list_nodes,
                                            [nodename], 0,
                                            self.empty_dict,
                                            [dm_const.FLAG_EXTERNAL])
        self._check_result(res)

        if len(nodes) != 1:
            msg = _('Expected exactly one node called "%s"') % nodename
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        __, nodeattr = nodes[0]

        return getattr(nodeattr, dm_const.FLAG_EXTERNAL,
                       dm_const.BOOL_FALSE) == dm_const.BOOL_TRUE

    def _return_connection_data(self, nodename, volume, d_res_name=None):
        if nodename and self._is_external_node(nodename):
            return self._return_drbdadm_config(nodename,
                                               volume,
                                               d_res_name=d_res_name)
        else:
            return self._return_local_access(nodename, volume)

    def create_export(self, context, volume, connector):
        d_res_name, d_vol_nr = self._resource_name_volnr_for_volume(volume)

        nodename = connector["host"]

        # Ensure the node is known to DRBDmanage.
        # Note that this does *not* mean that DRBDmanage has to
        # be installed on it!
        # This is just so that DRBD allows the IP to connect.
        node_prop = {
            dm_const.NODE_ADDR: connector["ip"],
            dm_const.FLAG_DRBDCTRL: dm_const.BOOL_FALSE,
            dm_const.FLAG_STORAGE: dm_const.BOOL_FALSE,
            dm_const.FLAG_EXTERNAL: dm_const.BOOL_TRUE,
        }
        res = self.call_or_reconnect(
            self.odm.create_node, nodename, node_prop)
        self._check_result(res, ignore=[dm_exc.DM_EEXIST])

        # Ensure the data is accessible, by creating an assignment.
        assg_prop = {
            dm_const.FLAG_DISKLESS: dm_const.BOOL_TRUE,
        }
        # If we create the assignment here, it's temporary -
        # and has to be removed later on again.
        assg_prop.update(dm_utils.aux_props_to_dict({
            AUX_PROP_TEMP_CLIENT: dm_const.BOOL_TRUE,
        }))

        res = self.call_or_reconnect(
            self.odm.assign, nodename, d_res_name, assg_prop)
        self._check_result(res, ignore=[dm_exc.DM_EEXIST])

        # Wait for DRBDmanage to have completed that action.

        # A DRBDmanage controlled node will set the cstate:deploy flag;
        # an external node will not be available to change it, so we have
        # to wait for the storage nodes to remove the upd_con flag
        # (ie. they're now ready to receive the connection).
        if self._is_external_node(nodename):
            self._wait_for_node_assignment(
                d_res_name, d_vol_nr, [],
                check_vol_deployed=False,
                filter_props={
                    # must be deployed
                    CS_DEPLOYED: dm_const.BOOL_TRUE,
                    # must be a storage node (not diskless),
                    CS_DISKLESS: dm_const.BOOL_FALSE,
                    # connection must be available, no need for updating
                    CS_UPD_CON: dm_const.BOOL_FALSE,
                })
        else:
            self._wait_for_node_assignment(
                d_res_name, d_vol_nr, [nodename],
                check_vol_deployed=True,
                filter_props={
                    CS_DEPLOYED: dm_const.BOOL_TRUE,
                })

        return self._return_connection_data(nodename, volume)

    def ensure_export(self, context, volume):
        p_location = volume['provider_location']
        if p_location:
            fields = p_location.split(" ")
            nodename = fields[1]
        else:
            nodename = None

        return self._return_connection_data(nodename, volume)

    def initialize_connection(self, volume, connector):

        nodename = connector["host"]

        return self._return_connection_data(nodename, volume)

    def terminate_connection(self, volume, connector,
                             force=False, **kwargs):
        d_res_name, d_vol_nr = self._resource_name_volnr_for_volume(
            volume, empty_ok=True)
        if not d_res_name:
            return

        nodename = connector["host"]

        # If the DRBD volume is diskless on that node, we remove it;
        # if it has local storage, we keep it.
        res, data = self.call_or_reconnect(
            self.odm.list_assignments,
            [nodename], [d_res_name], 0,
            self.empty_list, self.empty_list)
        self._check_result(res, ignore=[dm_exc.DM_ENOENT])

        if len(data) < 1:
            # already removed?!
            LOG.info('DRBD connection for %s already removed',
                     volume['id'])
        elif len(data) == 1:
            __, __, props, __ = data[0]
            my_props = dm_utils.dict_to_aux_props(props)
            diskless = getattr(props,
                               dm_const.FLAG_DISKLESS,
                               dm_const.BOOL_FALSE)
            temp_cli = getattr(my_props,
                               AUX_PROP_TEMP_CLIENT,
                               dm_const.BOOL_FALSE)
            # If diskless assigned,
            if ((diskless == dm_const.BOOL_TRUE) and
                    (temp_cli == dm_const.BOOL_TRUE)):
                # remove the assignment

                # TODO(pm): does it make sense to relay "force" here?
                #           What are the semantics?

                # TODO(pm): consistency groups shouldn't really
                #           remove until *all* volumes are detached

                res = self.call_or_reconnect(self.odm.unassign,
                                             nodename, d_res_name, force)
                self._check_result(res, ignore=[dm_exc.DM_ENOENT])
        else:
            # more than one assignment?
            LOG.error("DRBDmanage: too many assignments returned.")
        return

    def remove_export(self, context, volume):
        pass
