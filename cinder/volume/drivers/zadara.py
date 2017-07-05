# Copyright (c) 2016 Zadara Storage, Inc.
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
Volume driver for Zadara Virtual Private Storage Array (VPSA).

This driver requires VPSA with API version 15.07 or higher.
"""

from lxml import etree
from oslo_config import cfg
from oslo_log import log as logging
import requests
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver

LOG = logging.getLogger(__name__)

zadara_opts = [
    cfg.BoolOpt('zadara_use_iser',
                default=True,
                help='VPSA - Use ISER instead of iSCSI'),
    cfg.StrOpt('zadara_vpsa_host',
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
    cfg.StrOpt('zadara_user',
               default=None,
               help='VPSA - Username'),
    cfg.StrOpt('zadara_password',
               default=None,
               help='VPSA - Password',
               secret=True),
    cfg.StrOpt('zadara_vpsa_poolname',
               default=None,
               help='VPSA - Storage Pool assigned for volumes'),
    cfg.BoolOpt('zadara_vol_encrypt',
                default=False,
                help='VPSA - Default encryption policy for volumes'),
    cfg.StrOpt('zadara_vol_name_template',
               default='OS_%s',
               help='VPSA - Default template for VPSA volume names'),
    cfg.BoolOpt('zadara_default_snap_policy',
                default=False,
                help="VPSA - Attach snapshot policy for volumes")]

CONF = cfg.CONF
CONF.register_opts(zadara_opts, group=configuration.SHARED_CONF_GROUP)


class ZadaraVPSAConnection(object):
    """Executes volume driver commands on VPSA."""

    def __init__(self, conf):
        self.conf = conf
        self.access_key = None

        self.ensure_connection()

    def _generate_vpsa_cmd(self, cmd, **kwargs):
        """Generate command to be sent to VPSA."""

        def _joined_params(params):
            param_str = []
            for k, v in params.items():
                param_str.append("%s=%s" % (k, v))
            return '&'.join(param_str)

        # Dictionary of applicable VPSA commands in the following format:
        # 'command': (method, API_URL, {optional parameters})
        vpsa_commands = {
            'login': ('POST',
                      '/api/users/login.xml',
                      {'user': self.conf.zadara_user,
                       'password': self.conf.zadara_password}),

            # Volume operations
            'create_volume': ('POST',
                              '/api/volumes.xml',
                              {'name': kwargs.get('name'),
                               'capacity': kwargs.get('size'),
                               'pool': self.conf.zadara_vpsa_poolname,
                               'thin': 'YES',
                               'crypt': 'YES'
                               if self.conf.zadara_vol_encrypt else 'NO',
                               'attachpolicies': 'NO'
                               if not self.conf.zadara_default_snap_policy
                               else 'YES'}),
            'delete_volume': ('DELETE',
                              '/api/volumes/%s.xml' % kwargs.get('vpsa_vol'),
                              {'force': 'YES'}),
            'expand_volume': ('POST',
                              '/api/volumes/%s/expand.xml'
                              % kwargs.get('vpsa_vol'),
                              {'capacity': kwargs.get('size')}),

            # Snapshot operations
            # Snapshot request is triggered for a single volume though the
            # API call implies that snapshot is triggered for CG (legacy API).
            'create_snapshot': ('POST',
                                '/api/consistency_groups/%s/snapshots.xml'
                                % kwargs.get('cg_name'),
                                {'display_name': kwargs.get('snap_name')}),
            'delete_snapshot': ('DELETE',
                                '/api/snapshots/%s.xml'
                                % kwargs.get('snap_id'),
                                {}),

            'create_clone_from_snap': ('POST',
                                       '/api/consistency_groups/%s/clone.xml'
                                       % kwargs.get('cg_name'),
                                       {'name': kwargs.get('name'),
                                        'snapshot': kwargs.get('snap_id')}),

            'create_clone': ('POST',
                             '/api/consistency_groups/%s/clone.xml'
                             % kwargs.get('cg_name'),
                             {'name': kwargs.get('name')}),

            # Server operations
            'create_server': ('POST',
                              '/api/servers.xml',
                              {'display_name': kwargs.get('initiator'),
                               'iqn': kwargs.get('initiator')}),

            # Attach/Detach operations
            'attach_volume': ('POST',
                              '/api/servers/%s/volumes.xml'
                              % kwargs.get('vpsa_srv'),
                              {'volume_name[]': kwargs.get('vpsa_vol'),
                               'force': 'NO'}),
            'detach_volume': ('POST',
                              '/api/volumes/%s/detach.xml'
                              % kwargs.get('vpsa_vol'),
                              {'server_name[]': kwargs.get('vpsa_srv'),
                               'force': 'NO'}),

            # Get operations
            'list_volumes': ('GET',
                             '/api/volumes.xml',
                             {}),
            'list_pools': ('GET',
                           '/api/pools.xml',
                           {}),
            'list_controllers': ('GET',
                                 '/api/vcontrollers.xml',
                                 {}),
            'list_servers': ('GET',
                             '/api/servers.xml',
                             {}),
            'list_vol_attachments': ('GET',
                                     '/api/volumes/%s/servers.xml'
                                     % kwargs.get('vpsa_vol'),
                                     {}),
            'list_vol_snapshots': ('GET',
                                   '/api/consistency_groups/%s/snapshots.xml'
                                   % kwargs.get('cg_name'),
                                   {})}

        if cmd not in vpsa_commands:
            raise exception.UnknownCmd(cmd=cmd)
        else:
            (method, url, params) = vpsa_commands[cmd]

        if method == 'GET':
            # For GET commands add parameters to the URL
            params.update(dict(access_key=self.access_key,
                               page=1, start=0, limit=0))
            url += '?' + _joined_params(params)
            body = ''

        elif method == 'DELETE':
            # For DELETE commands add parameters to the URL
            params.update(dict(access_key=self.access_key))
            url += '?' + _joined_params(params)
            body = ''

        elif method == 'POST':
            if self.access_key:
                params.update(dict(access_key=self.access_key))
            body = _joined_params(params)

        else:
            msg = (_('Method %(method)s is not defined') %
                   {'method': method})
            LOG.error(msg)
            raise AssertionError(msg)

        return (method, url, body)

    def ensure_connection(self, cmd=None):
        """Retrieve access key for VPSA connection."""

        if self.access_key or cmd == 'login':
            return

        cmd = 'login'
        xml_tree = self.send_cmd(cmd)
        user = xml_tree.find('user')
        if user is None:
            raise (exception.MalformedResponse(cmd=cmd,
                   reason=_('no "user" field')))
        access_key = user.findtext('access-key')
        if access_key is None:
            raise (exception.MalformedResponse(cmd=cmd,
                   reason=_('no "access-key" field')))
        self.access_key = access_key

    def send_cmd(self, cmd, **kwargs):
        """Send command to VPSA Controller."""

        self.ensure_connection(cmd)

        (method, url, body) = self._generate_vpsa_cmd(cmd, **kwargs)
        LOG.debug('Invoking %(cmd)s using %(method)s request.',
                  {'cmd': cmd, 'method': method})

        host = self.conf.zadara_vpsa_host
        port = int(self.conf.zadara_vpsa_port)

        protocol = "https" if self.conf.zadara_vpsa_use_ssl else "http"
        if protocol == "https":
            if not self.conf.zadara_ssl_cert_verify:
                verify = False
            else:
                cert = ((self.conf.driver_ssl_cert_path) or None)
                verify = cert if cert else True
        else:
            verify = False

        if port:
            api_url = "%s://%s:%d%s" % (protocol, host, port, url)
        else:
            api_url = "%s://%s%s" % (protocol, host, url)

        try:
            response = requests.request(method, api_url, data=body,
                                        verify=verify)
        except requests.exceptions.RequestException as e:
            message = (_('Exception: %s') % six.text_type(e))
            raise exception.VolumeDriverException(message=message)

        if response.status_code != 200:
            raise exception.BadHTTPResponseStatus(status=response.status_code)

        data = response.content
        xml_tree = etree.fromstring(data)
        status = xml_tree.findtext('status')
        if status != '0':
            raise exception.FailedCmdWithDump(status=status, data=data)

        if method in ['POST', 'DELETE']:
            LOG.debug('Operation completed with status code %(status)s',
                      {'status': status})
        return xml_tree


@interface.volumedriver
class ZadaraVPSAISCSIDriver(driver.ISCSIDriver):
    """Zadara VPSA iSCSI/iSER volume driver.

    Version history:
        15.07 - Initial driver
        16.05 - Move from httplib to requests
    """

    VERSION = '16.05'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "ZadaraStorage_VPSA_CI"

    def __init__(self, *args, **kwargs):
        super(ZadaraVPSAISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(zadara_opts)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting.

        Establishes initial connection with VPSA and retrieves access_key.
        """
        self.vpsa = ZadaraVPSAConnection(self.configuration)

    def check_for_setup_error(self):
        """Returns an error (exception) if prerequisites aren't met."""
        self.vpsa.ensure_connection()

    def local_path(self, volume):
        """Return local path to existing local volume."""
        raise NotImplementedError()

    def _xml_parse_helper(self, xml_tree, first_level, search_tuple,
                          first=True):
        """Helper for parsing VPSA's XML output.

        Returns single item if first==True or list for multiple selection.
        If second argument in search_tuple is None - returns all items with
        appropriate key.
        """

        objects = xml_tree.find(first_level)
        if objects is None:
            return None

        result_list = []
        (key, value) = search_tuple
        for object in objects.getchildren():
            found_value = object.findtext(key)
            if found_value and (found_value == value or value is None):
                if first:
                    return object
                else:
                    result_list.append(object)
        return result_list if result_list else None

    def _get_vpsa_volume_name_and_size(self, name):
        """Return VPSA's name & size for the volume."""
        xml_tree = self.vpsa.send_cmd('list_volumes')
        volume = self._xml_parse_helper(xml_tree, 'volumes',
                                        ('display-name', name))
        if volume is not None:
            return (volume.findtext('name'),
                    int(volume.findtext('virtual-capacity')))

        return (None, None)

    def _get_vpsa_volume_name(self, name):
        """Return VPSA's name for the volume."""
        (vol_name, size) = self._get_vpsa_volume_name_and_size(name)
        return vol_name

    def _get_volume_cg_name(self, name):
        """Return name of the consistency group for the volume.

        cg-name is a volume uniqe identifier (legacy attribute)
        and not consistency group as it may imply.
        """
        xml_tree = self.vpsa.send_cmd('list_volumes')
        volume = self._xml_parse_helper(xml_tree, 'volumes',
                                        ('display-name', name))
        if volume is not None:
            return volume.findtext('cg-name')

        return None

    def _get_snap_id(self, cg_name, snap_name):
        """Return snapshot ID for particular volume."""
        xml_tree = self.vpsa.send_cmd('list_vol_snapshots',
                                      cg_name=cg_name)
        snap = self._xml_parse_helper(xml_tree, 'snapshots',
                                      ('display-name', snap_name))
        if snap is not None:
            return snap.findtext('name')

        return None

    def _get_pool_capacity(self, pool_name):
        """Return pool's total and available capacities."""
        xml_tree = self.vpsa.send_cmd('list_pools')
        pool = self._xml_parse_helper(xml_tree, 'pools',
                                      ('name', pool_name))
        if pool is not None:
            total = int(pool.findtext('capacity'))
            free = int(float(pool.findtext('available-capacity')))
            LOG.debug('Pool %(name)s: %(total)sGB total, %(free)sGB free',
                      {'name': pool_name, 'total': total, 'free': free})
            return (total, free)

        return ('unknown', 'unknown')

    def _get_active_controller_details(self):
        """Return details of VPSA's active controller."""
        xml_tree = self.vpsa.send_cmd('list_controllers')
        ctrl = self._xml_parse_helper(xml_tree, 'vcontrollers',
                                      ('state', 'active'))
        if ctrl is not None:
            return dict(target=ctrl.findtext('target'),
                        ip=ctrl.findtext('iscsi-ip'),
                        chap_user=ctrl.findtext('vpsa-chap-user'),
                        chap_passwd=ctrl.findtext('vpsa-chap-secret'))
        return None

    def _get_server_name(self, initiator):
        """Return VPSA's name for server object with given IQN."""
        xml_tree = self.vpsa.send_cmd('list_servers')
        server = self._xml_parse_helper(xml_tree, 'servers',
                                        ('iqn', initiator))
        if server is not None:
            return server.findtext('name')
        return None

    def _create_vpsa_server(self, initiator):
        """Create server object within VPSA (if doesn't exist)."""
        vpsa_srv = self._get_server_name(initiator)
        if not vpsa_srv:
            xml_tree = self.vpsa.send_cmd('create_server', initiator=initiator)
            vpsa_srv = xml_tree.findtext('server-name')
        return vpsa_srv

    def create_volume(self, volume):
        """Create volume."""
        self.vpsa.send_cmd(
            'create_volume',
            name=self.configuration.zadara_vol_name_template % volume['name'],
            size=volume['size'])

    def delete_volume(self, volume):
        """Delete volume.

        Return ok if doesn't exist. Auto detach from all servers.
        """
        # Get volume name
        name = self.configuration.zadara_vol_name_template % volume['name']
        vpsa_vol = self._get_vpsa_volume_name(name)
        if not vpsa_vol:
            LOG.warning('Volume %s could not be found. '
                        'It might be already deleted', name)
            return

        # Check attachment info and detach from all
        xml_tree = self.vpsa.send_cmd('list_vol_attachments',
                                      vpsa_vol=vpsa_vol)
        servers = self._xml_parse_helper(xml_tree, 'servers',
                                         ('iqn', None), first=False)
        if servers:
            for server in servers:
                vpsa_srv = server.findtext('name')
                if vpsa_srv:
                    self.vpsa.send_cmd('detach_volume',
                                       vpsa_srv=vpsa_srv,
                                       vpsa_vol=vpsa_vol)

        # Delete volume
        self.vpsa.send_cmd('delete_volume', vpsa_vol=vpsa_vol)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        LOG.debug('Create snapshot: %s', snapshot['name'])

        # Retrieve the CG name for the base volume
        volume_name = (self.configuration.zadara_vol_name_template
                       % snapshot['volume_name'])
        cg_name = self._get_volume_cg_name(volume_name)
        if not cg_name:
            msg = _('Volume %(name)s not found') % {'name': volume_name}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        self.vpsa.send_cmd('create_snapshot',
                           cg_name=cg_name,
                           snap_name=snapshot['name'])

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        LOG.debug('Delete snapshot: %s', snapshot['name'])

        # Retrieve the CG name for the base volume
        volume_name = (self.configuration.zadara_vol_name_template
                       % snapshot['volume_name'])
        cg_name = self._get_volume_cg_name(volume_name)
        if not cg_name:
            # If the volume isn't present, then don't attempt to delete
            LOG.warning('snapshot: original volume %s not found, '
                        'skipping delete operation',
                        volume_name)
            return

        snap_id = self._get_snap_id(cg_name, snapshot['name'])
        if not snap_id:
            # If the snapshot isn't present, then don't attempt to delete
            LOG.warning('snapshot: snapshot %s not found, '
                        'skipping delete operation', snapshot['name'])
            return

        self.vpsa.send_cmd('delete_snapshot',
                           snap_id=snap_id)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        LOG.debug('Creating volume from snapshot: %s', snapshot['name'])

        # Retrieve the CG name for the base volume
        volume_name = (self.configuration.zadara_vol_name_template
                       % snapshot['volume_name'])
        cg_name = self._get_volume_cg_name(volume_name)
        if not cg_name:
            LOG.error('Volume %(name)s not found', {'name': volume_name})
            raise exception.VolumeNotFound(volume_id=volume['id'])

        snap_id = self._get_snap_id(cg_name, snapshot['name'])
        if not snap_id:
            LOG.error('Snapshot %(name)s not found',
                      {'name': snapshot['name']})
            raise exception.SnapshotNotFound(snapshot_id=snapshot['id'])

        self.vpsa.send_cmd('create_clone_from_snap',
                           cg_name=cg_name,
                           name=self.configuration.zadara_vol_name_template
                           % volume['name'],
                           snap_id=snap_id)

        if (volume['size'] > snapshot['volume_size']):
            self.extend_volume(volume, volume['size'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        LOG.debug('Creating clone of volume: %s', src_vref['name'])

        # Retrieve the CG name for the base volume
        volume_name = (self.configuration.zadara_vol_name_template
                       % src_vref['name'])
        cg_name = self._get_volume_cg_name(volume_name)
        if not cg_name:
            LOG.error('Volume %(name)s not found', {'name': volume_name})
            raise exception.VolumeNotFound(volume_id=volume['id'])

        self.vpsa.send_cmd('create_clone',
                           cg_name=cg_name,
                           name=self.configuration.zadara_vol_name_template
                           % volume['name'])

        if (volume['size'] > src_vref['size']):
            self.extend_volume(volume, volume['size'])

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        # Get volume name
        name = self.configuration.zadara_vol_name_template % volume['name']
        (vpsa_vol, size) = self._get_vpsa_volume_name_and_size(name)
        if not vpsa_vol:
            msg = (_('Volume %(name)s could not be found. '
                     'It might be already deleted') % {'name': name})
            LOG.error(msg)
            raise exception.ZadaraVolumeNotFound(reason=msg)

        if new_size < size:
            raise exception.InvalidInput(
                reason=_('%(new_size)s < current size %(size)s') %
                {'new_size': new_size, 'size': size})

        expand_size = new_size - size
        self.vpsa.send_cmd('expand_volume',
                           vpsa_vol=vpsa_vol,
                           size=expand_size)

    def create_export(self, context, volume, vg=None):
        """Irrelevant for VPSA volumes. Export created during attachment."""
        pass

    def ensure_export(self, context, volume):
        """Irrelevant for VPSA volumes. Export created during attachment."""
        pass

    def remove_export(self, context, volume):
        """Irrelevant for VPSA volumes. Export removed during detach."""
        pass

    def initialize_connection(self, volume, connector):
        """Attach volume to initiator/host.

        During this call VPSA exposes volume to particular Initiator. It also
        creates a 'server' entity for Initiator (if it was not created before)

        All necessary connection information is returned, including auth data.
        Connection data (target, LUN) is not stored in the DB.
        """

        # Get/Create server name for IQN
        initiator_name = connector['initiator']
        vpsa_srv = self._create_vpsa_server(initiator_name)
        if not vpsa_srv:
            raise exception.ZadaraServerCreateFailure(name=initiator_name)

        # Get volume name
        name = self.configuration.zadara_vol_name_template % volume['name']
        vpsa_vol = self._get_vpsa_volume_name(name)
        if not vpsa_vol:
            raise exception.VolumeNotFound(volume_id=volume['id'])

        # Get Active controller details
        ctrl = self._get_active_controller_details()
        if not ctrl:
            raise exception.ZadaraVPSANoActiveController()

        xml_tree = self.vpsa.send_cmd('list_vol_attachments',
                                      vpsa_vol=vpsa_vol)
        attach = self._xml_parse_helper(xml_tree, 'servers',
                                        ('name', vpsa_srv))
        # Attach volume to server
        if attach is None:
            self.vpsa.send_cmd('attach_volume',
                               vpsa_srv=vpsa_srv,
                               vpsa_vol=vpsa_vol)
        # Get connection info
        xml_tree = self.vpsa.send_cmd('list_vol_attachments',
                                      vpsa_vol=vpsa_vol)
        server = self._xml_parse_helper(xml_tree, 'servers',
                                        ('iqn', initiator_name))
        if server is None:
            raise exception.ZadaraAttachmentsNotFound(name=name)
        target = server.findtext('target')
        lun = int(server.findtext('lun'))
        if target is None or lun is None:
            raise exception.ZadaraInvalidAttachmentInfo(
                name=name,
                reason=_('target=%(target)s, lun=%(lun)s') %
                {'target': target, 'lun': lun})

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%s' % (ctrl['ip'], '3260')
        properties['target_iqn'] = target
        properties['target_lun'] = lun
        properties['volume_id'] = volume['id']
        properties['auth_method'] = 'CHAP'
        properties['auth_username'] = ctrl['chap_user']
        properties['auth_password'] = ctrl['chap_passwd']

        LOG.debug('Attach properties: %(properties)s',
                  {'properties': properties})
        return {'driver_volume_type':
                ('iser' if (self.configuration.safe_get('zadara_use_iser'))
                 else 'iscsi'), 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Detach volume from the initiator."""
        # Get server name for IQN
        initiator_name = connector['initiator']
        vpsa_srv = self._get_server_name(initiator_name)
        if not vpsa_srv:
            raise exception.ZadaraServerNotFound(name=initiator_name)

        # Get volume name
        name = self.configuration.zadara_vol_name_template % volume['name']
        vpsa_vol = self._get_vpsa_volume_name(name)
        if not vpsa_vol:
            raise exception.VolumeNotFound(volume_id=volume['id'])

        # Detach volume from server
        self.vpsa.send_cmd('detach_volume',
                           vpsa_srv=vpsa_srv,
                           vpsa_vol=vpsa_vol)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """

        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""

        LOG.debug("Updating volume stats")
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        storage_protocol = ('iSER' if
                            (self.configuration.safe_get('zadara_use_iser'))
                            else 'iSCSI')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Zadara Storage'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = storage_protocol
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['QoS_support'] = False

        (total, free) = self._get_pool_capacity(self.configuration.
                                                zadara_vpsa_poolname)
        data['total_capacity_gb'] = total
        data['free_capacity_gb'] = free

        self._stats = data
