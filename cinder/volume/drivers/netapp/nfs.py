# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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
Volume driver for NetApp NFS storage.
"""

import copy
import os
import time

from cinder import exception
from cinder.openstack.common import log as logging
from cinder.volume.drivers.netapp.api import NaApiError
from cinder.volume.drivers.netapp.api import NaElement
from cinder.volume.drivers.netapp.api import NaServer
from cinder.volume.drivers.netapp.options import netapp_basicauth_opts
from cinder.volume.drivers.netapp.options import netapp_connection_opts
from cinder.volume.drivers.netapp.options import netapp_transport_opts
from cinder.volume.drivers.netapp.utils import provide_ems
from cinder.volume.drivers.netapp.utils import validate_instantiation
from cinder.volume.drivers import nfs
from oslo.config import cfg


LOG = logging.getLogger(__name__)


CONF = cfg.CONF
CONF.register_opts(netapp_connection_opts)
CONF.register_opts(netapp_transport_opts)
CONF.register_opts(netapp_basicauth_opts)


class NetAppNFSDriver(nfs.NfsDriver):
    """Base class for NetApp NFS driver.
      Executes commands relating to Volumes.
    """
    def __init__(self, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        validate_instantiation(**kwargs)
        self._execute = None
        self._context = None
        super(NetAppNFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(netapp_connection_opts)
        self.configuration.append_config_values(netapp_basicauth_opts)
        self.configuration.append_config_values(netapp_transport_opts)

    def set_execute(self, execute):
        self._execute = execute

    def do_setup(self, context):
        raise NotImplementedError()

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        raise NotImplementedError()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        vol_size = volume.size
        snap_size = snapshot.volume_size

        if vol_size != snap_size:
            msg = _('Cannot create volume of size %(vol_size)s from '
                    'snapshot of size %(snap_size)s')
            msg_fmt = {'vol_size': vol_size, 'snap_size': snap_size}
            raise exception.CinderException(msg % msg_fmt)

        self._clone_volume(snapshot.name, volume.name, snapshot.volume_id)
        share = self._get_volume_location(snapshot.volume_id)

        return {'provider_location': share}

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self._clone_volume(snapshot['volume_name'],
                           snapshot['name'],
                           snapshot['volume_id'])

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        nfs_mount = self._get_provider_location(snapshot.volume_id)

        if self._volume_not_present(nfs_mount, snapshot.name):
            return True

        self._execute('rm', self._get_volume_path(nfs_mount, snapshot.name),
                      run_as_root=True)

    def _get_client(self):
        """Creates client for server."""
        raise NotImplementedError()

    def _get_volume_location(self, volume_id):
        """Returns NFS mount address as <nfs_ip_address>:<nfs_mount_dir>."""
        nfs_server_ip = self._get_host_ip(volume_id)
        export_path = self._get_export_path(volume_id)
        return (nfs_server_ip + ':' + export_path)

    def _clone_volume(self, volume_name, clone_name, volume_id):
        """Clones mounted volume with OnCommand proxy API."""
        raise NotImplementedError()

    def _get_provider_location(self, volume_id):
        """Returns provider location for given volume."""
        volume = self.db.volume_get(self._context, volume_id)
        return volume.provider_location

    def _get_host_ip(self, volume_id):
        """Returns IP address for the given volume."""
        return self._get_provider_location(volume_id).split(':')[0]

    def _get_export_path(self, volume_id):
        """Returns NFS export path for the given volume."""
        return self._get_provider_location(volume_id).split(':')[1]

    def _volume_not_present(self, nfs_mount, volume_name):
        """Check if volume exists."""
        try:
            self._try_execute('ls', self._get_volume_path(nfs_mount,
                                                          volume_name))
        except exception.ProcessExecutionError:
            # If the volume isn't present
            return True
        return False

    def _try_execute(self, *command, **kwargs):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                self._execute(*command, **kwargs)
                return True
            except exception.ProcessExecutionError:
                tries = tries + 1
                if tries >= self.configuration.num_shell_tries:
                    raise
                LOG.exception(_("Recovering from a failed execute.  "
                                "Try number %s"), tries)
                time.sleep(tries ** 2)

    def _get_volume_path(self, nfs_share, volume_name):
        """Get volume path (local fs path) for given volume name on given nfs
        share.

        @param nfs_share string, example 172.18.194.100:/var/nfs
        @param volume_name string,
            example volume-91ee65ec-c473-4391-8c09-162b00c68a8c
        """
        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume_name)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_size = volume.size
        src_vol_size = src_vref.size

        if vol_size != src_vol_size:
            msg = _('Cannot create clone of size %(vol_size)s from '
                    'volume of size %(src_vol_size)s')
            msg_fmt = {'vol_size': vol_size, 'src_vol_size': src_vol_size}
            raise exception.CinderException(msg % msg_fmt)

        self._clone_volume(src_vref.name, volume.name, src_vref.id)
        share = self._get_volume_location(src_vref.id)

        return {'provider_location': share}

    def _update_volume_status(self):
        """Retrieve status info from volume group."""
        super(NetAppNFSDriver, self)._update_volume_status()


class NetAppDirectNfsDriver (NetAppNFSDriver):
    """Executes commands related to volumes on NetApp filer."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirectNfsDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        self._context = context
        self.check_for_setup_error()
        self._client = self._get_client()
        self._do_custom_setup(self._client)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_flags()

    def _clone_volume(self, volume_name, clone_name, volume_id):
        """Clones mounted volume on NetApp filer."""
        raise NotImplementedError()

    def _check_flags(self):
        """Raises error if any required configuration flag for NetApp
        filer is missing.
        """
        required_flags = ['netapp_login',
                          'netapp_password',
                          'netapp_server_hostname',
                          'netapp_server_port',
                          'netapp_transport_type']
        for flag in required_flags:
            if not getattr(self.configuration, flag, None):
                raise exception.CinderException(_('%s is not set') % flag)

    def _get_client(self):
        """Creates NetApp api client."""
        client = NaServer(
            host=self.configuration.netapp_server_hostname,
            server_type=NaServer.SERVER_TYPE_FILER,
            transport_type=self.configuration.netapp_transport_type,
            style=NaServer.STYLE_LOGIN_PASSWORD,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password)
        return client

    def _do_custom_setup(self, client):
        """Do the customized set up on client if any for different types."""
        raise NotImplementedError()

    def _is_naelement(self, elem):
        """Checks if element is NetApp element."""
        if not isinstance(elem, NaElement):
            raise ValueError('Expects NaElement')

    def _get_ontapi_version(self):
        """Gets the supported ontapi version."""
        ontapi_version = NaElement('system-get-ontapi-version')
        res = self._client.invoke_successfully(ontapi_version, False)
        major = res.get_child_content('major-version')
        minor = res.get_child_content('minor-version')
        return (major, minor)


class NetAppDirectCmodeNfsDriver (NetAppDirectNfsDriver):
    """Executes commands related to volumes on c mode."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirectCmodeNfsDriver, self).__init__(*args, **kwargs)

    def _do_custom_setup(self, client):
        """Do the customized set up on client for cluster mode."""
        # Default values to run first api
        client.set_api_version(1, 15)
        (major, minor) = self._get_ontapi_version()
        client.set_api_version(major, minor)

    def _invoke_successfully(self, na_element, vserver=None):
        """Invoke the api for successful result.

        If vserver is present then invokes vserver api
        else Cluster api.
        :param vserver: vserver name.
        """
        self._is_naelement(na_element)
        server = copy.copy(self._client)
        if vserver:
            server.set_vserver(vserver)
        else:
            server.set_vserver(None)
        result = server.invoke_successfully(na_element, True)
        return result

    def _clone_volume(self, volume_name, clone_name, volume_id):
        """Clones mounted volume on NetApp Cluster."""
        host_ip = self._get_host_ip(volume_id)
        export_path = self._get_export_path(volume_id)
        ifs = self._get_if_info_by_ip(host_ip)
        vserver = ifs[0].get_child_content('vserver')
        exp_volume = self._get_vol_by_junc_vserver(vserver, export_path)
        self._clone_file(exp_volume, volume_name, clone_name, vserver)

    def _get_if_info_by_ip(self, ip):
        """Gets the network interface info by ip."""
        net_if_iter = NaElement('net-interface-get-iter')
        net_if_iter.add_new_child('max-records', '10')
        query = NaElement('query')
        net_if_iter.add_child_elem(query)
        query.add_node_with_children('net-interface-info', **{'address': ip})
        result = self._invoke_successfully(net_if_iter)
        if result.get_child_content('num-records') and\
                int(result.get_child_content('num-records')) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            return attr_list.get_children()
        raise exception.NotFound(
            _('No interface found on cluster for ip %s')
            % (ip))

    def _get_vol_by_junc_vserver(self, vserver, junction):
        """Gets the volume by junction path and vserver."""
        vol_iter = NaElement('volume-get-iter')
        vol_iter.add_new_child('max-records', '10')
        query = NaElement('query')
        vol_iter.add_child_elem(query)
        vol_attrs = NaElement('volume-attributes')
        query.add_child_elem(vol_attrs)
        vol_attrs.add_node_with_children(
            'volume-id-attributes',
            **{'junction-path': junction,
            'owning-vserver-name': vserver})
        des_attrs = NaElement('desired-attributes')
        des_attrs.add_node_with_children('volume-attributes',
                                         **{'volume-id-attributes': None})
        vol_iter.add_child_elem(des_attrs)
        result = self._invoke_successfully(vol_iter, vserver)
        if result.get_child_content('num-records') and\
                int(result.get_child_content('num-records')) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            vols = attr_list.get_children()
            vol_id = vols[0].get_child_by_name('volume-id-attributes')
            return vol_id.get_child_content('name')
        msg_fmt = {'vserver': vserver, 'junction': junction}
        raise exception.NotFound(_("""No volume on cluster with vserver
                                   %(vserver)s and junction path %(junction)s
                                   """) % msg_fmt)

    def _clone_file(self, volume, src_path, dest_path, vserver=None):
        """Clones file on vserver."""
        msg = _("""Cloning with params volume %(volume)s,src %(src_path)s,
                    dest %(dest_path)s, vserver %(vserver)s""")
        msg_fmt = {'volume': volume, 'src_path': src_path,
                   'dest_path': dest_path, 'vserver': vserver}
        LOG.debug(msg % msg_fmt)
        clone_create = NaElement.create_node_with_children(
            'clone-create',
            **{'volume': volume, 'source-path': src_path,
            'destination-path': dest_path})
        self._invoke_successfully(clone_create, vserver)

    def _update_volume_status(self):
        """Retrieve status info from volume group."""
        super(NetAppDirectCmodeNfsDriver, self)._update_volume_status()
        netapp_backend = 'NetApp_NFS_cluster_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats["volume_backend_name"] = (backend_name or
                                              netapp_backend)
        self._stats["vendor_name"] = 'NetApp'
        self._stats["driver_version"] = '1.0'
        provide_ems(self, self._client, self._stats, netapp_backend)


class NetAppDirect7modeNfsDriver (NetAppDirectNfsDriver):
    """Executes commands related to volumes on 7 mode."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirect7modeNfsDriver, self).__init__(*args, **kwargs)

    def _do_custom_setup(self, client):
        """Do the customized set up on client if any for 7 mode."""
        (major, minor) = self._get_ontapi_version()
        client.set_api_version(major, minor)

    def _invoke_successfully(self, na_element, vfiler=None):
        """Invoke the api for successful result.

        If vfiler is present then invokes vfiler api
        else filer api.
        :param vfiler: vfiler name.
        """
        self._is_naelement(na_element)
        server = copy.copy(self._client)
        if vfiler:
            server.set_vfiler(vfiler)
        else:
            server.set_vfiler(None)
        result = server.invoke_successfully(na_element, True)
        return result

    def _clone_volume(self, volume_name, clone_name, volume_id):
        """Clones mounted volume with NetApp filer."""
        export_path = self._get_export_path(volume_id)
        storage_path = self._get_actual_path_for_export(export_path)
        target_path = '%s/%s' % (storage_path, clone_name)
        (clone_id, vol_uuid) = self._start_clone('%s/%s' % (storage_path,
                                                            volume_name),
                                                 target_path)
        if vol_uuid:
            try:
                self._wait_for_clone_finish(clone_id, vol_uuid)
            except NaApiError as e:
                if e.code != 'UnknownCloneId':
                    self._clear_clone(clone_id)
                raise

    def _get_actual_path_for_export(self, export_path):
        """Gets the actual path on the filer for export path."""
        storage_path = NaElement.create_node_with_children(
            'nfs-exportfs-storage-path', **{'pathname': export_path})
        result = self._invoke_successfully(storage_path, None)
        if result.get_child_content('actual-pathname'):
            return result.get_child_content('actual-pathname')
        raise exception.NotFound(_('No storage path found for export path %s')
                                 % (export_path))

    def _start_clone(self, src_path, dest_path):
        """Starts the clone operation.

        :returns: clone-id
        """
        msg_fmt = {'src_path': src_path, 'dest_path': dest_path}
        LOG.debug(_("""Cloning with src %(src_path)s, dest %(dest_path)s""")
                  % msg_fmt)
        clone_start = NaElement.create_node_with_children(
            'clone-start',
            **{'source-path': src_path,
            'destination-path': dest_path,
            'no-snap': 'true'})
        result = self._invoke_successfully(clone_start, None)
        clone_id_el = result.get_child_by_name('clone-id')
        cl_id_info = clone_id_el.get_child_by_name('clone-id-info')
        vol_uuid = cl_id_info.get_child_content('volume-uuid')
        clone_id = cl_id_info.get_child_content('clone-op-id')
        return (clone_id, vol_uuid)

    def _wait_for_clone_finish(self, clone_op_id, vol_uuid):
        """Waits till a clone operation is complete or errored out."""
        clone_ls_st = NaElement('clone-list-status')
        clone_id = NaElement('clone-id')
        clone_ls_st.add_child_elem(clone_id)
        clone_id.add_node_with_children('clone-id-info',
                                        **{'clone-op-id': clone_op_id,
                                        'volume-uuid': vol_uuid})
        task_running = True
        while task_running:
            result = self._invoke_successfully(clone_ls_st, None)
            status = result.get_child_by_name('status')
            ops_info = status.get_children()
            if ops_info:
                state = ops_info[0].get_child_content('clone-state')
                if state == 'completed':
                    task_running = False
                elif state == 'failed':
                    code = ops_info[0].get_child_content('error')
                    reason = ops_info[0].get_child_content('reason')
                    raise NaApiError(code, reason)
                else:
                    time.sleep(1)
            else:
                raise NaApiError(
                    'UnknownCloneId',
                    'No clone operation for clone id %s found on the filer'
                    % (clone_id))

    def _clear_clone(self, clone_id):
        """Clear the clone information.

        Invoke this in case of failed clone.
        """
        clone_clear = NaElement.create_node_with_children(
            'clone-clear',
            **{'clone-id': clone_id})
        retry = 3
        while retry:
            try:
                self._invoke_successfully(clone_clear, None)
                break
            except Exception as e:
                # Filer might be rebooting
                time.sleep(5)
            retry = retry - 1

    def _update_volume_status(self):
        """Retrieve status info from volume group."""
        super(NetAppDirect7modeNfsDriver, self)._update_volume_status()
        netapp_backend = 'NetApp_NFS_7mode_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats["volume_backend_name"] = (backend_name or
                                              'NetApp_NFS_7mode_direct')
        self._stats["vendor_name"] = 'NetApp'
        self._stats["driver_version"] = '1.0'
        provide_ems(self, self._client, self._stats, netapp_backend,
                    server_type="7mode")
