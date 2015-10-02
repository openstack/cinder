# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Ben Swartzlander.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2015 Alex Meade.  All rights reserved.
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
Storage service catalog utility functions and classes for NetApp systems.
"""

import copy
import threading

from oslo_log import log as logging
from oslo_utils import timeutils
import six

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)


class NetAppVolume(object):
    """Represents a NetApp volume.

       Present attributes
       id - name, vserver, junction_path, type
       aggr - name, raid_type, ha_policy, disk_type
       sis - dedup, compression
       state - status, vserver_root, cluster_volume,
       inconsistent, invalid, junction_active
       qos - qos_policy_group
       space - space-guarantee-enabled, space-guarantee,
       thin_provisioned, size_avl_bytes, size_total_bytes
       mirror - mirrored i.e. dp mirror
       export - path
    """
    def __init__(self, name, vserver=None):
        self.id = {}
        self.aggr = {}
        self.sis = {}
        self.state = {}
        self.qos = {}
        self.space = {}
        self.mirror = {}
        self.export = {}
        self.id['name'] = name
        self.id['vserver'] = vserver

    def __eq__(self, other):
        """Checks for equality."""
        if (self.id['name'] == other.id['name'] and
                self.id['vserver'] == other.id['vserver']):
            return True

    def __hash__(self):
        """Computes hash for the object."""
        return hash(self.id['name'])

    def __cmp__(self, other):
        """Implements comparison logic for volumes."""
        self_size_avl = self.space.get('size_avl_bytes')
        other_size_avl = other.space.get('size_avl_bytes')
        if self_size_avl is None and other_size_avl is not None:
            return -1
        elif self_size_avl is not None and other_size_avl is None:
            return 1
        elif self_size_avl is None and other_size_avl is None:
            return 0
        elif int(self_size_avl) < int(other_size_avl):
            return -1
        elif int(self_size_avl) > int(other_size_avl):
            return 1
        else:
            return 0

    def __str__(self):
        """Returns human readable form for object."""
        vol_str = "NetApp Volume id: %s, aggr: %s,"\
            " space: %s, sis: %s, state: %s, qos: %s"\
            % (self.id, self.aggr, self.space, self.sis, self.state, self.qos)
        return vol_str


@utils.trace_method
def get_cluster_vols_with_ssc(na_server, vserver, volume=None):
    """Gets ssc vols for cluster vserver."""
    volumes = query_cluster_vols_for_ssc(na_server, vserver, volume)
    sis_vols = get_sis_vol_dict(na_server, vserver, volume)
    mirrored_vols = get_snapmirror_vol_dict(na_server, vserver, volume)
    aggrs = {}
    for vol in volumes:
        aggr_name = vol.aggr['name']
        if aggr_name:
            if aggr_name in aggrs:
                aggr_attrs = aggrs[aggr_name]
            else:
                aggr_attrs = query_aggr_options(na_server, aggr_name)
                if aggr_attrs:
                    eff_disk_type = query_aggr_storage_disk(na_server,
                                                            aggr_name)
                    aggr_attrs['disk_type'] = eff_disk_type
                aggrs[aggr_name] = aggr_attrs
            vol.aggr['raid_type'] = aggr_attrs.get('raid_type')
            vol.aggr['ha_policy'] = aggr_attrs.get('ha_policy')
            vol.aggr['disk_type'] = aggr_attrs.get('disk_type')
        if sis_vols:
            if vol.id['name'] in sis_vols:
                vol.sis['dedup'] = sis_vols[vol.id['name']]['dedup']
                vol.sis['compression'] =\
                    sis_vols[vol.id['name']]['compression']
            else:
                vol.sis['dedup'] = False
                vol.sis['compression'] = False
        if (vol.space['space-guarantee-enabled'] and
                (vol.space['space-guarantee'] == 'file' or
                 vol.space['space-guarantee'] == 'volume')):
            vol.space['thin_provisioned'] = False
        else:
            vol.space['thin_provisioned'] = True
        if mirrored_vols:
            vol.mirror['mirrored'] = False
            if vol.id['name'] in mirrored_vols:
                for mirr_attrs in mirrored_vols[vol.id['name']]:
                    if (mirr_attrs['rel_type'] == 'data_protection' and
                            mirr_attrs['mirr_state'] == 'snapmirrored'):
                        vol.mirror['mirrored'] = True
                        break
    return volumes


@utils.trace_method
def query_cluster_vols_for_ssc(na_server, vserver, volume=None):
    """Queries cluster volumes for ssc."""
    query = {'volume-attributes': None}
    volume_id = {
        'volume-id-attributes': {
            'owning-vserver-name': vserver,
            'type': 'rw',
            'style': 'flex',
        },
    }
    if volume:
        volume_id['volume-id-attributes']['name'] = volume
    query['volume-attributes'] = volume_id
    des_attr = {'volume-attributes':
                ['volume-id-attributes',
                 'volume-space-attributes',
                 'volume-state-attributes',
                 'volume-qos-attributes']}
    result = netapp_api.invoke_api(na_server, api_name='volume-get-iter',
                                   api_family='cm', query=query,
                                   des_result=des_attr,
                                   additional_elems=None,
                                   is_iter=True)
    vols = set()
    for res in result:
        records = res.get_child_content('num-records')
        if int(records) > 0:
            attr_list = res.get_child_by_name('attributes-list')
            if attr_list:
                vol_attrs = attr_list.get_children()
                vols_found = create_vol_list(vol_attrs)
                vols.update(vols_found)
    return vols


@utils.trace_method
def create_vol_list(vol_attrs):
    """Creates vol list with features from attr list."""
    vols = set()
    for v in vol_attrs:
        try:
            # name and vserver are mandatory
            # Absence will skip by giving KeyError.
            name = v['volume-id-attributes']['name']
            vserver = v['volume-id-attributes']['owning-vserver-name']
            vol = NetAppVolume(name, vserver)
            vol.id['type'] =\
                v['volume-id-attributes'].get_child_content('type')
            if vol.id['type'] == "tmp":
                continue
            vol.id['junction_path'] =\
                v['volume-id-attributes'].get_child_content('junction-path')
            # state attributes mandatory.
            vol.state['vserver_root'] =\
                na_utils.to_bool(
                    v['volume-state-attributes'].get_child_content(
                        'is-vserver-root'))
            if vol.state['vserver_root']:
                continue
            vol.state['status'] =\
                v['volume-state-attributes'].get_child_content('state')
            vol.state['inconsistent'] =\
                na_utils.to_bool(
                    v['volume-state-attributes'].get_child_content(
                        'is-inconsistent'))
            vol.state['invalid'] =\
                na_utils.to_bool(
                    v['volume-state-attributes'].get_child_content(
                        'is-invalid'))
            vol.state['junction_active'] =\
                na_utils.to_bool(
                    v['volume-state-attributes'].get_child_content(
                        'is-junction-active'))
            vol.state['cluster_volume'] =\
                na_utils.to_bool(
                    v['volume-state-attributes'].get_child_content(
                        'is-cluster-volume'))
            if (vol.state['status'] != 'online' or
                    vol.state['inconsistent'] or vol.state['invalid']):
                # offline, invalid and inconsistent volumes are not usable
                continue
            # aggr attributes mandatory.
            vol.aggr['name'] =\
                v['volume-id-attributes']['containing-aggregate-name']
            # space attributes mandatory.
            vol.space['size_avl_bytes'] =\
                v['volume-space-attributes']['size-available']
            vol.space['size_total_bytes'] =\
                v['volume-space-attributes']['size-total']
            vol.space['space-guarantee-enabled'] =\
                na_utils.to_bool(
                    v['volume-space-attributes'].get_child_content(
                        'is-space-guarantee-enabled'))
            vol.space['space-guarantee'] =\
                v['volume-space-attributes'].get_child_content(
                    'space-guarantee')
            # qos attributes optional.
            if v.get_child_by_name('volume-qos-attributes'):
                vol.qos['qos_policy_group'] =\
                    v['volume-qos-attributes'].get_child_content(
                        'policy-group-name')
            else:
                vol.qos['qos_policy_group'] = None
            vols.add(vol)
        except KeyError as e:
            LOG.debug('Unexpected error while creating'
                      ' ssc vol list. Message - %s', e)
            continue
    return vols


@utils.trace_method
def query_aggr_options(na_server, aggr_name):
    """Queries cluster aggr for attributes.

        Currently queries for raid and ha-policy.
    """
    add_elems = {'aggregate': aggr_name}
    attrs = {}
    try:
        result = netapp_api.invoke_api(na_server,
                                       api_name='aggr-options-list-info',
                                       api_family='cm', query=None,
                                       des_result=None,
                                       additional_elems=add_elems,
                                       is_iter=False)
        for res in result:
            options = res.get_child_by_name('options')
            if options:
                op_list = options.get_children()
                for op in op_list:
                    if op.get_child_content('name') == 'ha_policy':
                        attrs['ha_policy'] = op.get_child_content('value')
                    if op.get_child_content('name') == 'raidtype':
                        attrs['raid_type'] = op.get_child_content('value')
    except Exception as e:
        LOG.debug("Exception querying aggr options. %s", e)
    return attrs


@utils.trace_method
def get_sis_vol_dict(na_server, vserver, volume=None):
    """Queries sis for volumes.

        If volume is present sis is queried for it.
        Records dedup and compression enabled.
    """

    sis_vols = {}
    query_attr = {'vserver': vserver}
    if volume:
        vol_path = '/vol/%s' % (volume)
        query_attr['path'] = vol_path
    query = {'sis-status-info': query_attr}
    try:
        result = netapp_api.invoke_api(na_server,
                                       api_name='sis-get-iter',
                                       api_family='cm',
                                       query=query,
                                       is_iter=True)
        for res in result:
            attr_list = res.get_child_by_name('attributes-list')
            if attr_list:
                sis_status = attr_list.get_children()
                for sis in sis_status:
                    path = sis.get_child_content('path')
                    if not path:
                        continue
                    (___, __, vol) = path.rpartition('/')
                    if not vol:
                        continue
                    v_sis = {}
                    v_sis['compression'] = na_utils.to_bool(
                        sis.get_child_content('is-compression-enabled'))
                    v_sis['dedup'] = na_utils.to_bool(
                        sis.get_child_content('state'))
                    sis_vols[vol] = v_sis
    except Exception as e:
        LOG.debug("Exception querying sis information. %s", e)
    return sis_vols


@utils.trace_method
def get_snapmirror_vol_dict(na_server, vserver, volume=None):
    """Queries snapmirror volumes."""
    mirrored_vols = {}
    query_attr = {'source-vserver': vserver}
    if volume:
        query_attr['source-volume'] = volume
    query = {'snapmirror-info': query_attr}
    try:
        result = netapp_api.invoke_api(na_server,
                                       api_name='snapmirror-get-iter',
                                       api_family='cm', query=query,
                                       is_iter=True)
        for res in result:
            attr_list = res.get_child_by_name('attributes-list')
            if attr_list:
                snap_info = attr_list.get_children()
                for snap in snap_info:
                    src_volume = snap.get_child_content('source-volume')
                    v_snap = {}
                    v_snap['dest_loc'] =\
                        snap.get_child_content('destination-location')
                    v_snap['rel_type'] =\
                        snap.get_child_content('relationship-type')
                    v_snap['mirr_state'] =\
                        snap.get_child_content('mirror-state')
                    if mirrored_vols.get(src_volume):
                        mirrored_vols.get(src_volume).append(v_snap)
                    else:
                        mirrored_vols[src_volume] = [v_snap]
    except Exception as e:
        LOG.debug("Exception querying mirror information. %s", e)
    return mirrored_vols


@utils.trace_method
def query_aggr_storage_disk(na_server, aggr):
    """Queries for storage disks associated to an aggregate."""
    query = {'storage-disk-info': {'disk-raid-info':
                                   {'disk-aggregate-info':
                                       {'aggregate-name': aggr}}}}
    des_attr = {'storage-disk-info':
                {'disk-raid-info': ['effective-disk-type']}}
    try:
        result = netapp_api.invoke_api(na_server,
                                       api_name='storage-disk-get-iter',
                                       api_family='cm', query=query,
                                       des_result=des_attr,
                                       additional_elems=None,
                                       is_iter=True)
        for res in result:
            attr_list = res.get_child_by_name('attributes-list')
            if attr_list:
                storage_disks = attr_list.get_children()
                for disk in storage_disks:
                    raid_info = disk.get_child_by_name('disk-raid-info')
                    if raid_info:
                        eff_disk_type =\
                            raid_info.get_child_content('effective-disk-type')
                        if eff_disk_type:
                            return eff_disk_type
                        else:
                            continue
    except Exception as e:
        LOG.debug("Exception querying storage disk. %s", e)
    return 'unknown'


@utils.trace_method
def get_cluster_ssc(na_server, vserver):
    """Provides cluster volumes with ssc."""
    netapp_volumes = get_cluster_vols_with_ssc(na_server, vserver)
    mirror_vols = set()
    dedup_vols = set()
    compress_vols = set()
    thin_prov_vols = set()
    ssc_map = {'mirrored': mirror_vols, 'dedup': dedup_vols,
               'compression': compress_vols,
               'thin': thin_prov_vols, 'all': netapp_volumes}
    for vol in netapp_volumes:
        if vol.sis.get('dedup'):
            dedup_vols.add(vol)
        if vol.sis.get('compression'):
            compress_vols.add(vol)
        if vol.mirror.get('mirrored'):
            mirror_vols.add(vol)
        if vol.space.get('thin_provisioned'):
            thin_prov_vols.add(vol)
    return ssc_map


@utils.trace_method
def refresh_cluster_stale_ssc(*args, **kwargs):
    """Refreshes stale ssc volumes with latest."""
    backend = args[0]
    na_server = args[1]
    vserver = args[2]
    identity = six.text_type(id(backend))
    lock_pr = '%s_%s' % ('refresh_ssc', identity)
    try:
        job_set = na_utils.set_safe_attr(
            backend, 'refresh_stale_running', True)
        if not job_set:
            return

        @utils.synchronized(lock_pr)
        def refresh_stale_ssc():
            stale_vols = backend._update_stale_vols(reset=True)
            LOG.info(_LI('Running stale ssc refresh job for %(server)s'
                         ' and vserver %(vs)s'),
                     {'server': na_server, 'vs': vserver})
            # refreshing single volumes can create inconsistency
            # hence doing manipulations on copy
            ssc_vols_copy = copy.deepcopy(backend.ssc_vols)
            refresh_vols = set()
            expired_vols = set()
            for vol in stale_vols:
                name = vol.id['name']
                res = get_cluster_vols_with_ssc(na_server, vserver, name)
                if res:
                    refresh_vols.add(res.pop())
                else:
                    expired_vols.add(vol)
            for vol in refresh_vols:
                for k in ssc_vols_copy:
                    vol_set = ssc_vols_copy[k]
                    vol_set.discard(vol)
                    if k == "mirrored" and vol.mirror.get('mirrored'):
                        vol_set.add(vol)
                    if k == "dedup" and vol.sis.get('dedup'):
                        vol_set.add(vol)
                    if k == "compression" and vol.sis.get('compression'):
                        vol_set.add(vol)
                    if k == "thin" and vol.space.get('thin_provisioned'):
                        vol_set.add(vol)
                    if k == "all":
                        vol_set.add(vol)
            for vol in expired_vols:
                for k in ssc_vols_copy:
                    vol_set = ssc_vols_copy[k]
                    vol_set.discard(vol)
            backend.refresh_ssc_vols(ssc_vols_copy)
            LOG.info(_LI('Successfully completed stale refresh job for'
                         ' %(server)s and vserver %(vs)s'),
                     {'server': na_server, 'vs': vserver})

        refresh_stale_ssc()
    finally:
        na_utils.set_safe_attr(backend, 'refresh_stale_running', False)


@utils.trace_method
def get_cluster_latest_ssc(*args, **kwargs):
    """Updates volumes including ssc."""
    backend = args[0]
    na_server = args[1]
    vserver = args[2]
    identity = six.text_type(id(backend))
    lock_pr = '%s_%s' % ('refresh_ssc', identity)

    # As this depends on stale job running state
    # set flag as soon as job starts to avoid
    # job accumulation.
    try:
        job_set = na_utils.set_safe_attr(backend, 'ssc_job_running', True)
        if not job_set:
            return

        @utils.synchronized(lock_pr)
        def get_latest_ssc():
            LOG.info(_LI('Running cluster latest ssc job for %(server)s'
                         ' and vserver %(vs)s'),
                     {'server': na_server, 'vs': vserver})
            ssc_vols = get_cluster_ssc(na_server, vserver)
            backend.refresh_ssc_vols(ssc_vols)
            backend.ssc_run_time = timeutils.utcnow()
            LOG.info(_LI('Successfully completed ssc job for %(server)s'
                         ' and vserver %(vs)s'),
                     {'server': na_server, 'vs': vserver})

        get_latest_ssc()
    finally:
        na_utils.set_safe_attr(backend, 'ssc_job_running', False)


@utils.trace_method
def refresh_cluster_ssc(backend, na_server, vserver, synchronous=False):
    """Refresh cluster ssc for backend."""
    if not isinstance(na_server, netapp_api.NaServer):
        raise exception.InvalidInput(reason=_("Backend server not NaServer."))
    delta_secs = getattr(backend, 'ssc_run_delta_secs', 1800)
    if getattr(backend, 'ssc_job_running', None):
        LOG.warning(_LW('ssc job in progress. Returning... '))
        return
    elif (getattr(backend, 'ssc_run_time', None) is None or
          (backend.ssc_run_time and
           timeutils.is_older_than(backend.ssc_run_time, delta_secs))):
        if synchronous:
            get_cluster_latest_ssc(backend, na_server, vserver)
        else:
            t = threading.Timer(0, get_cluster_latest_ssc,
                                args=[backend, na_server, vserver])
            t.start()
    elif getattr(backend, 'refresh_stale_running', None):
        LOG.warning(_LW('refresh stale ssc job in progress. Returning... '))
        return
    else:
        if backend.stale_vols:
            if synchronous:
                refresh_cluster_stale_ssc(backend, na_server, vserver)
            else:
                t = threading.Timer(0, refresh_cluster_stale_ssc,
                                    args=[backend, na_server, vserver])
                t.start()


@utils.trace_method
def get_volumes_for_specs(ssc_vols, specs):
    """Shortlists volumes for extra specs provided."""
    if specs is None or specs == {} or not isinstance(specs, dict):
        return ssc_vols['all']
    result = copy.deepcopy(ssc_vols['all'])
    raid_type = specs.get('netapp:raid_type')
    disk_type = specs.get('netapp:disk_type')
    bool_specs_list = ['netapp_mirrored', 'netapp_unmirrored',
                       'netapp_dedup', 'netapp_nodedup',
                       'netapp_compression', 'netapp_nocompression',
                       'netapp_thin_provisioned', 'netapp_thick_provisioned']
    b_specs = {}
    for spec in bool_specs_list:
        b_specs[spec] = na_utils.to_bool(specs.get(spec))\
            if specs.get(spec) else None

    def _spec_ineffect(b_specs, spec, opp_spec):
        """If the spec with opposite spec is ineffective."""
        if ((b_specs[spec] is None and b_specs[opp_spec] is None)
                or (b_specs[spec] == b_specs[opp_spec])):
            return True
        else:
            return False

    if _spec_ineffect(b_specs, 'netapp_mirrored', 'netapp_unmirrored'):
        pass
    else:
        if b_specs['netapp_mirrored'] or b_specs['netapp_unmirrored'] is False:
            result = result & ssc_vols['mirrored']
        else:
            result = result - ssc_vols['mirrored']
    if _spec_ineffect(b_specs, 'netapp_dedup', 'netapp_nodedup'):
        pass
    else:
        if b_specs['netapp_dedup'] or b_specs['netapp_nodedup'] is False:
            result = result & ssc_vols['dedup']
        else:
            result = result - ssc_vols['dedup']
    if _spec_ineffect(b_specs, 'netapp_compression', 'netapp_nocompression'):
        pass
    else:
        if (b_specs['netapp_compression'] or
                b_specs['netapp_nocompression'] is False):
            result = result & ssc_vols['compression']
        else:
            result = result - ssc_vols['compression']
    if _spec_ineffect(b_specs, 'netapp_thin_provisioned',
                      'netapp_thick_provisioned'):
        pass
    else:
        if (b_specs['netapp_thin_provisioned'] or
                b_specs['netapp_thick_provisioned'] is False):
            result = result & ssc_vols['thin']
        else:
            result = result - ssc_vols['thin']
    if raid_type or disk_type:
        tmp = copy.deepcopy(result)
        for vol in tmp:
            if raid_type:
                vol_raid = vol.aggr['raid_type']
                vol_raid = vol_raid.lower() if vol_raid else None
                if raid_type.lower() != vol_raid:
                    result.discard(vol)
            if disk_type:
                vol_dtype = vol.aggr['disk_type']
                vol_dtype = vol_dtype.lower() if vol_dtype else None
                if disk_type.lower() != vol_dtype:
                    result.discard(vol)
    return result


@utils.trace_method
def check_ssc_api_permissions(client_cmode):
    """Checks backend SSC API permissions for the user."""
    api_map = {'storage-disk-get-iter': ['netapp:disk_type'],
               'snapmirror-get-iter': ['netapp_mirrored',
                                       'netapp_unmirrored'],
               'sis-get-iter': ['netapp_dedup', 'netapp_nodedup',
                                'netapp_compression',
                                'netapp_nocompression'],
               'aggr-options-list-info': ['netapp:raid_type'],
               'volume-get-iter': []}
    failed_apis = client_cmode.check_apis_on_cluster(api_map.keys())
    if failed_apis:
        if 'volume-get-iter' in failed_apis:
            msg = _("Fatal error: User not permitted"
                    " to query NetApp volumes.")
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            unsupp_ssc_features = []
            for fail in failed_apis:
                unsupp_ssc_features.extend(api_map[fail])
            LOG.warning(_LW("The user does not have access or sufficient "
                            "privileges to use all netapp APIs. The "
                            "following extra_specs will fail or be ignored: "
                            "%s"), unsupp_ssc_features)
