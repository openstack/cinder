# Copyright (c) 2020 Zadara Storage, Inc.
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

import json
import re

from oslo_config import cfg
from oslo_log import log as logging
import requests

LOG = logging.getLogger(__name__)

# Number of seconds the repsonse for the request sent to
# vpsa is expected. Else the request will be timed out.
# Setting it to 300 seconds initially.
vpsa_timeout = 300


# Common exception class for all the exceptions that
# are used to redirect to the driver specific exceptions.
class CommonException(Exception):
    def __init__(self):
        pass

    class UnknownCmd(Exception):
        def __init__(self, cmd):
            self.cmd = cmd

    class BadHTTPResponseStatus(Exception):
        def __init__(self, status):
            self.status = status

    class FailedCmdWithDump(Exception):
        def __init__(self, status, data):
            self.status = status
            self.data = data

    class SessionRequestException(Exception):
        def __init__(self, msg):
            self.msg = msg

    class ZadaraInvalidAccessKey(Exception):
        pass


exception = CommonException()


zadara_opts = [
    cfg.HostAddressOpt('zadara_vpsa_host',
                       default=None,
                       help='VPSA - Management Host name or IP address'),
    cfg.PortOpt('zadara_vpsa_port',
                default=None,
                help='VPSA - Port number'),
    cfg.BoolOpt('zadara_vpsa_use_ssl',
                default=False,
                help='VPSA - Use SSL connection'),
    cfg.BoolOpt('zadara_ssl_cert_verify',
                default=True,
                help='If set to True the http client will validate the SSL '
                     'certificate of the VPSA endpoint.'),
    cfg.StrOpt('zadara_access_key',
               default=None,
               help='VPSA access key',
               secret=True),
    cfg.StrOpt('zadara_vpsa_poolname',
               default=None,
               help='VPSA - Storage Pool assigned for volumes'),
    cfg.BoolOpt('zadara_vol_encrypt',
                default=False,
                help='VPSA - Default encryption policy for volumes. '
                     'If the option is neither configured nor provided '
                     'as metadata, the VPSA will inherit the default value.'),
    cfg.BoolOpt('zadara_gen3_vol_dedupe',
                default=False,
                help='VPSA - Enable deduplication for volumes. '
                     'If the option is neither configured nor provided '
                     'as metadata, the VPSA will inherit the default value.'),
    cfg.BoolOpt('zadara_gen3_vol_compress',
                default=False,
                help='VPSA - Enable compression for volumes. '
                     'If the option is neither configured nor provided '
                     'as metadata, the VPSA will inherit the default value.'),
    cfg.BoolOpt('zadara_default_snap_policy',
                default=False,
                help="VPSA - Attach snapshot policy for volumes. "
                     "If the option is neither configured nor provided "
                     "as metadata, the VPSA will inherit the default value.")]


# Class used to connect and execute the commands on
# Zadara Virtual Private Storage Array (VPSA).
class ZadaraVPSAConnection(object):
    """Executes driver commands on VPSA."""

    def __init__(self, conf, driver_ssl_cert_path, block):
        self.conf = conf
        self.access_key = conf.zadara_access_key
        if not self.access_key:
            raise exception.ZadaraInvalidAccessKey()
        self.driver_ssl_cert_path = driver_ssl_cert_path
        # Choose the volume type of either block or file-type
        # that will help to filter volumes.
        self.vol_type_str = 'showonlyblock' if block else 'showonlyfile'
        # Dictionary of applicable VPSA commands in the following format:
        # 'command': (method, API_URL, {optional parameters})
        self.vpsa_commands = {
            # Volume operations
            'create_volume': lambda kwargs: (
                'POST',
                '/api/volumes.json',
                {'name': kwargs.get('name'),
                 'capacity': kwargs.get('size'),
                 'pool': self.conf.zadara_vpsa_poolname,
                 'block': 'YES'
                 if self.vol_type_str == 'showonlyblock'
                 else 'NO',
                 'thin': 'YES',
                 'crypt': 'YES'
                 if self.conf.zadara_vol_encrypt else 'NO',
                 'compress': 'YES'
                 if self.conf.zadara_gen3_vol_compress else 'NO',
                 'dedupe': 'YES'
                 if self.conf.zadara_gen3_vol_dedupe else 'NO',
                 'attachpolicies': 'NO'
                 if not self.conf.zadara_default_snap_policy
                 else 'YES'}),
            'delete_volume': lambda kwargs: (
                'DELETE',
                '/api/volumes/%s.json' % kwargs.get('vpsa_vol'),
                {'force': 'YES'}),
            'expand_volume': lambda kwargs: (
                'POST',
                '/api/volumes/%s/expand.json'
                % kwargs.get('vpsa_vol'),
                {'capacity': kwargs.get('size')}),
            'rename_volume': lambda kwargs: (
                'POST',
                '/api/volumes/%s/rename.json'
                % kwargs.get('vpsa_vol'),
                {'new_name': kwargs.get('new_name')}),
            # Snapshot operations
            # Snapshot request is triggered for a single volume though the
            # API call implies that snapshot is triggered for CG (legacy API).
            'create_snapshot': lambda kwargs: (
                'POST',
                '/api/consistency_groups/%s/snapshots.json'
                % kwargs.get('cg_name'),
                {'display_name': kwargs.get('snap_name')}),
            'delete_snapshot': lambda kwargs: (
                'DELETE',
                '/api/snapshots/%s.json'
                % kwargs.get('snap_id'),
                {}),
            'rename_snapshot': lambda kwargs: (
                'POST',
                '/api/snapshots/%s/rename.json'
                % kwargs.get('snap_id'),
                {'newname': kwargs.get('new_name')}),
            'create_clone_from_snap': lambda kwargs: (
                'POST',
                '/api/consistency_groups/%s/clone.json'
                % kwargs.get('cg_name'),
                {'name': kwargs.get('name'),
                 'snapshot': kwargs.get('snap_id')}),
            'create_clone': lambda kwargs: (
                'POST',
                '/api/consistency_groups/%s/clone.json'
                % kwargs.get('cg_name'),
                {'name': kwargs.get('name')}),
            # Server operations
            'create_server': lambda kwargs: (
                'POST',
                '/api/servers.json',
                {'iqn': kwargs.get('iqn'),
                 'iscsi': kwargs.get('iscsi_ip'),
                 'display_name': kwargs.get('iqn')
                 if kwargs.get('iqn')
                 else kwargs.get('iscsi_ip')}),
            # Attach/Detach operations
            'attach_volume': lambda kwargs: (
                'POST',
                '/api/servers/%s/volumes.json'
                % kwargs.get('vpsa_srv'),
                {'volume_name[]': kwargs.get('vpsa_vol'),
                 'access_type': kwargs.get('share_proto'),
                 'readonly': kwargs.get('read_only'),
                 'force': 'YES'}),
            'detach_volume': lambda kwargs: (
                'POST',
                '/api/volumes/%s/detach.json'
                % kwargs.get('vpsa_vol'),
                {'server_name[]': kwargs.get('vpsa_srv'),
                 'force': 'YES'}),
            # Update volume comment
            'update_volume': lambda kwargs: (
                'POST',
                '/api/volumes/%s/update_comment.json'
                % kwargs.get('vpsa_vol'),
                {'new_comment': kwargs.get('new_comment')}),

            # Get operations
            'list_volumes': lambda kwargs: (
                'GET',
                '/api/volumes.json?%s=YES' % self.vol_type_str,
                {}),
            'get_volume': lambda kwargs: (
                'GET',
                '/api/volumes/%s.json' % kwargs.get('vpsa_vol'),
                {}),
            'get_volume_by_name': lambda kwargs: (
                'GET',
                '/api/volumes.json?display_name=%s'
                % kwargs.get('display_name'),
                {}),
            'get_pool': lambda kwargs: (
                'GET',
                '/api/pools/%s.json' % kwargs.get('pool_name'),
                {}),
            'list_controllers': lambda kwargs: (
                'GET',
                '/api/vcontrollers.json',
                {}),
            'list_servers': lambda kwargs: (
                'GET',
                '/api/servers.json',
                {}),
            'list_vol_snapshots': lambda kwargs: (
                'GET',
                '/api/consistency_groups/%s/snapshots.json'
                % kwargs.get('cg_name'),
                {}),
            'list_vol_attachments': lambda kwargs: (
                'GET',
                '/api/volumes/%s/servers.json'
                % kwargs.get('vpsa_vol'),
                {}),
            'list_snapshots': lambda kwargs: (
                'GET',
                '/api/snapshots.json',
                {}),
            # Put operations
            'change_export_name': lambda kwargs: (
                'PUT',
                '/api/volumes/%s/export_name.json'
                % kwargs.get('vpsa_vol'),
                {'exportname': kwargs.get('exportname')})}

    def _generate_vpsa_cmd(self, cmd, **kwargs):
        """Generate command to be sent to VPSA."""
        try:
            method, url, params = self.vpsa_commands[cmd](kwargs)
            # Populate the metadata for the volume creation
            metadata = kwargs.get('metadata')
            if metadata:
                for key, value in metadata.items():
                    params[key] = value
        except KeyError:
            raise exception.UnknownCmd(cmd=cmd)

        if method == 'GET':
            params = dict(page=1, start=0, limit=0)
            body = None

        elif method in ['DELETE', 'POST', 'PUT']:
            body = params
            params = None

        else:
            msg = ('Method %(method)s is not defined' % {'method': method})
            LOG.error(msg)
            raise AssertionError(msg)

        # 'access_key' was generated using username and password
        # or it was taken from the input file
        headers = {'X-Access-Key': self.access_key}

        return method, url, params, body, headers

    def send_cmd(self, cmd, **kwargs):
        """Send command to VPSA Controller."""

        if not self.access_key:
            raise exception.ZadaraInvalidAccessKey()

        method, url, params, body, headers = self._generate_vpsa_cmd(cmd,
                                                                     **kwargs)
        LOG.debug('Invoking %(cmd)s using %(method)s request.',
                  {'cmd': cmd, 'method': method})

        host = self._get_target_host(self.conf.zadara_vpsa_host)
        port = int(self.conf.zadara_vpsa_port)

        protocol = "https" if self.conf.zadara_vpsa_use_ssl else "http"
        if protocol == "https":
            if not self.conf.zadara_ssl_cert_verify:
                verify = False
            else:
                verify = (self.driver_ssl_cert_path
                          if self.driver_ssl_cert_path else True)
        else:
            verify = False

        if port:
            api_url = "%s://%s:%d%s" % (protocol, host, port, url)
        else:
            api_url = "%s://%s%s" % (protocol, host, url)

        try:
            with requests.Session() as session:
                session.headers.update(headers)
                response = session.request(method, api_url, params=params,
                                           data=body, headers=headers,
                                           verify=verify, timeout=vpsa_timeout)
        except requests.exceptions.RequestException as e:
            msg = ('Exception: %s') % e
            raise exception.SessionRequestException(msg=msg)

        if response.status_code != 200:
            raise exception.BadHTTPResponseStatus(
                status=response.status_code)

        data = response.content
        json_data = json.loads(data)
        response = json_data['response']
        status = int(response['status'])
        if status == 5:
            # Invalid Credentials
            raise exception.ZadaraInvalidAccessKey()

        if status != 0:
            raise exception.FailedCmdWithDump(status=status, data=data)

        LOG.debug('Operation completed with status code %(status)s',
                  {'status': status})
        return response

    def _get_target_host(self, vpsa_host):
        """Helper for target host formatting."""
        ipv6_without_brackets = ':' in vpsa_host and vpsa_host[-1] != ']'
        if ipv6_without_brackets:
            return ('[%s]' % vpsa_host)
        return ('%s' % vpsa_host)

    def _get_active_controller_details(self):
        """Return details of VPSA's active controller."""
        data = self.send_cmd('list_controllers')
        ctrl = None
        vcontrollers = data.get('vcontrollers', [])
        for controller in vcontrollers:
            if controller['state'] == 'active':
                ctrl = controller
                break

        if ctrl is not None:
            target_ip = (ctrl['iscsi_ipv6'] if
                         ctrl['iscsi_ipv6'] else
                         ctrl['iscsi_ip'])
            return dict(target=ctrl['target'],
                        ip=target_ip,
                        chap_user=ctrl['vpsa_chap_user'],
                        chap_passwd=ctrl['vpsa_chap_secret'])
        return None

    def _check_access_key_validity(self):
        """Check VPSA access key"""
        if not self.access_key:
            raise exception.ZadaraInvalidAccessKey()
        active_ctrl = self._get_active_controller_details()
        if active_ctrl is None:
            raise exception.ZadaraInvalidAccessKey()

    def _get_vpsa_volume(self, name):
        """Returns a single vpsa volume based on the display name"""
        volume = None
        display_name = name
        if re.search(r"\s", name):
            display_name = re.split(r"\s", name)[0]
        data = self.send_cmd('get_volume_by_name',
                             display_name=display_name)
        if data['status'] != 0:
            return None
        volumes = data['volumes']

        for vol in volumes:
            if vol['display_name'] == name:
                volume = vol
                break
        return volume

    def _get_vpsa_volume_by_id(self, vpsa_vol):
        """Returns a single vpsa volume based on name"""
        data = self.send_cmd('get_volume', vpsa_vol=vpsa_vol)
        return data['volume']

    def _get_volume_cg_name(self, name):
        """Return name of the consistency group for the volume.

        cg-name is a volume uniqe identifier (legacy attribute)
        and not consistency group as it may imply.
        """
        volume = self._get_vpsa_volume(name)
        if volume is not None:
            return volume['cg_name']

        return None

    def _get_all_vpsa_snapshots(self):
        """Returns snapshots from all vpsa volumes"""
        data = self.send_cmd('list_snapshots')
        return data['snapshots']

    def _get_all_vpsa_volumes(self):
        """Returns all vpsa block volumes from the configured pool"""
        data = self.send_cmd('list_volumes')
        # FIXME: Work around to filter volumes belonging to given pool
        # Remove this when we have the API fixed to filter based
        # on pools. This API today does not have virtual_capacity field
        volumes = []

        for volume in data['volumes']:
            if volume['pool_name'] == self.conf.zadara_vpsa_poolname:
                volumes.append(volume)

        return volumes

    def _get_server_name(self, initiator, share):
        """Return VPSA's name for server object.

           'share' will be true to search for filesystem volumes
        """
        data = self.send_cmd('list_servers')
        servers = data.get('servers', [])
        for server in servers:
            if share:
                if server['iscsi_ip'] == initiator:
                    return server['name']
            else:
                if server['iqn'] == initiator:
                    return server['name']
        return None

    def _create_vpsa_server(self, iqn=None, iscsi_ip=None):
        """Create server object within VPSA (if doesn't exist)."""
        initiator = iscsi_ip if iscsi_ip else iqn
        share = True if iscsi_ip else False
        vpsa_srv = self._get_server_name(initiator, share)
        if not vpsa_srv:
            data = self.send_cmd('create_server', iqn=iqn, iscsi_ip=iscsi_ip)
            if data['status'] != 0:
                return None
            vpsa_srv = data['server_name']
        return vpsa_srv

    def _get_servers_attached_to_volume(self, vpsa_vol):
        """Return all servers attached to volume."""
        servers = vpsa_vol.get('server_ext_names')
        list_servers = []
        if servers:
            list_servers = servers.split(',')
        return list_servers

    def _detach_vpsa_volume(self, vpsa_vol, vpsa_srv=None):
        """Detach volume from all attached servers."""
        if vpsa_srv:
            list_servers_ids = [vpsa_srv]
        else:
            list_servers_ids = self._get_servers_attached_to_volume(vpsa_vol)

        for server_id in list_servers_ids:
            # Detach volume from server
            self.send_cmd('detach_volume', vpsa_srv=server_id,
                          vpsa_vol=vpsa_vol['name'])

    def _get_volume_snapshots(self, cg_name):
        """Get snapshots in the consistency group"""
        data = self.send_cmd('list_vol_snapshots', cg_name=cg_name)
        snapshots = data.get('snapshots', [])
        return snapshots

    def _get_snap_id(self, cg_name, snap_name):
        """Return snapshot ID for particular volume."""
        snapshots = self._get_volume_snapshots(cg_name)
        for snap_vol in snapshots:
            if snap_vol['display_name'] == snap_name:
                return snap_vol['name']

        return None

    def _get_pool_capacity(self, pool_name):
        """Return pool's total and available capacities."""
        data = self.send_cmd('get_pool', pool_name=pool_name)
        pool = data.get('pool')
        if pool is not None:
            total = int(pool['capacity'])
            free = int(pool['available_capacity'])
            provisioned = int(pool['provisioned_capacity'])
            LOG.debug('Pool %(name)s: %(total)sGB total, %(free)sGB free, '
                      '%(provisioned)sGB provisioned',
                      {'name': pool_name, 'total': total,
                       'free': free, 'provisioned': provisioned})
            return total, free, provisioned

        return 'unknown', 'unknown', 'unknown'
