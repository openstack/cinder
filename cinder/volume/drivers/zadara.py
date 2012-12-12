# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Zadara Storage, Inc.
# Copyright (c) 2012 OpenStack LLC.
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

This driver requires VPSA with API ver.12.06 or higher.
"""

import httplib

from cinder import exception
from cinder import flags
from cinder.openstack.common import cfg
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver
from cinder.volume import iscsi

from lxml import etree


LOG = logging.getLogger("cinder.volume.driver")

zadara_opts = [
    cfg.StrOpt('zadara_vpsa_ip',
               default=None,
               help='Management IP of Zadara VPSA'),
    cfg.StrOpt('zadara_vpsa_port',
               default=None,
               help='Zadara VPSA port number'),
    cfg.BoolOpt('zadara_vpsa_use_ssl',
                default=False,
                help='Use SSL connection'),
    cfg.StrOpt('zadara_user',
               default=None,
               help='User name for the VPSA'),
    cfg.StrOpt('zadara_password',
               default=None,
               help='Password for the VPSA'),

    cfg.StrOpt('zadara_vpsa_poolname',
               default=None,
               help='Name of VPSA storage pool for volumes'),

    cfg.StrOpt('zadara_default_cache_policy',
               default='write-through',
               help='Default cache policy for volumes'),
    cfg.StrOpt('zadara_default_encryption',
               default='NO',
               help='Default encryption policy for volumes'),
    cfg.StrOpt('zadara_default_striping_mode',
               default='simple',
               help='Default striping mode for volumes'),
    cfg.StrOpt('zadara_default_stripesize',
               default='64',
               help='Default stripe size for volumes'),
    cfg.StrOpt('zadara_vol_name_template',
               default='OS_%s',
               help='Default template for VPSA volume names'),
    cfg.BoolOpt('zadara_vpsa_auto_detach_on_delete',
                default=True,
                help="Automatically detach from servers on volume delete"),
    cfg.BoolOpt('zadara_vpsa_allow_nonexistent_delete',
                default=True,
                help="Don't halt on deletion of non-existing volumes"), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(zadara_opts)


class ZadaraVPSAConnection(object):
    """Executes volume driver commands on VPSA."""

    def __init__(self, host, port, ssl, user, password):
        self.host = host
        self.port = port
        self.use_ssl = ssl
        self.user = user
        self.password = password
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
                      {'user': self.user,
                       'password': self.password}),

            # Volume operations
            'create_volume': ('POST',
                              '/api/volumes.xml',
                              {'display_name': kwargs.get('name'),
                               'virtual_capacity': kwargs.get('size'),
                               'raid_group_name[]': FLAGS.zadara_vpsa_poolname,
                               'quantity': 1,
                               'cache': FLAGS.zadara_default_cache_policy,
                               'crypt': FLAGS.zadara_default_encryption,
                               'mode': FLAGS.zadara_default_striping_mode,
                               'stripesize': FLAGS.zadara_default_stripesize,
                               'force': 'NO'}),
            'delete_volume': ('DELETE',
                              '/api/volumes/%s.xml' % kwargs.get('vpsa_vol'),
                              {}),

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
            'list_controllers': ('GET',
                                 '/api/vcontrollers.xml',
                                 {}),
            'list_servers': ('GET',
                             '/api/servers.xml',
                             {}),
            'list_vol_attachments': ('GET',
                                     '/api/volumes/%s/servers.xml'
                                     % kwargs.get('vpsa_vol'),
                                     {}), }

        if cmd not in vpsa_commands.keys():
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
            raise exception.UnknownCmd(cmd=method)

        return (method, url, body)

    def ensure_connection(self, cmd=None):
        """Retrieve access key for VPSA connection."""

        if self.access_key or cmd == 'login':
            return

        cmd = 'login'
        xml_tree = self.send_cmd(cmd)
        user = xml_tree.find('user')
        if user is None:
            raise exception.MalformedResponse(cmd=cmd,
                                              reason='no "user" field')

        access_key = user.findtext('access-key')
        if access_key is None:
            raise exception.MalformedResponse(cmd=cmd,
                                              reason='no "access-key" field')

        self.access_key = access_key

    def send_cmd(self, cmd, **kwargs):
        """Send command to VPSA Controller."""

        self.ensure_connection(cmd)

        (method, url, body) = self._generate_vpsa_cmd(cmd, **kwargs)
        LOG.debug(_('Sending %(method)s to %(url)s. Body "%(body)s"')
                  % locals())

        if self.use_ssl:
            connection = httplib.HTTPSConnection(self.host, self.port)
        else:
            connection = httplib.HTTPConnection(self.host, self.port)
        connection.request(method, url, body)
        response = connection.getresponse()

        if response.status != 200:
            connection.close()
            raise exception.BadHTTPResponseStatus(status=response.status)
        data = response.read()
        connection.close()

        xml_tree = etree.fromstring(data)
        status = xml_tree.findtext('status')
        if status != '0':
            raise exception.FailedCmdWithDump(status=status, data=data)

        if method in ['POST', 'DELETE']:
            LOG.debug(_('Operation completed. %(data)s') % locals())
        return xml_tree


class ZadaraVPSAISCSIDriver(driver.ISCSIDriver):
    """Zadara VPSA iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(ZadaraVPSAISCSIDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """
        Any initialization the volume driver does while starting.
        Establishes initial connection with VPSA and retrieves access_key.
        """
        self.vpsa = ZadaraVPSAConnection(FLAGS.zadara_vpsa_ip,
                                         FLAGS.zadara_vpsa_port,
                                         FLAGS.zadara_vpsa_use_ssl,
                                         FLAGS.zadara_user,
                                         FLAGS.zadara_password)

    def check_for_setup_error(self):
        """Returns an error (exception) if prerequisites aren't met."""
        self.vpsa.ensure_connection()

    def local_path(self, volume):
        """Return local path to existing local volume."""
        raise NotImplementedError()

    def _xml_parse_helper(self, xml_tree, first_level, search_tuple,
                          first=True):
        """
        Helper for parsing VPSA's XML output.

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

    def _get_vpsa_volume_name(self, name):
        """Return VPSA's name for the volume."""
        xml_tree = self.vpsa.send_cmd('list_volumes')
        volume = self._xml_parse_helper(xml_tree, 'volumes',
                                        ('display-name', name))
        if volume is not None:
            return volume.findtext('name')

        return None

    def _get_active_controller_details(self):
        """Return details of VPSA's active controller."""
        xml_tree = self.vpsa.send_cmd('list_controllers')
        ctrl = self._xml_parse_helper(xml_tree, 'vcontrollers',
                                      ('state', 'active'))
        if ctrl is not None:
            return dict(target=ctrl.findtext('target'),
                        ip=ctrl.findtext('iscsi-ip'),
                        chap_user=ctrl.findtext('chap-username'),
                        chap_passwd=ctrl.findtext('chap-target-secret'))
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
            name=FLAGS.zadara_vol_name_template % volume['name'],
            size=volume['size'])

    def delete_volume(self, volume):
        """
        Delete volume.

        Return ok if doesn't exist. Auto detach from all servers.
        """
        # Get volume name
        name = FLAGS.zadara_vol_name_template % volume['name']
        vpsa_vol = self._get_vpsa_volume_name(name)
        if not vpsa_vol:
            msg = _('Volume %(name)s could not be found. '
                    'It might be already deleted') % locals()
            LOG.warning(msg)
            if FLAGS.zadara_vpsa_allow_nonexistent_delete:
                return
            else:
                raise exception.VolumeNotFound(volume_id=name)

        # Check attachment info and detach from all
        xml_tree = self.vpsa.send_cmd('list_vol_attachments',
                                      vpsa_vol=vpsa_vol)
        servers = self._xml_parse_helper(xml_tree, 'servers',
                                         ('iqn', None), first=False)
        if servers:
            if not FLAGS.zadara_vpsa_auto_detach_on_delete:
                raise exception.VolumeAttached(volume_id=name)

            for server in servers:
                vpsa_srv = server.findtext('name')
                if vpsa_srv:
                    self.vpsa.send_cmd('detach_volume',
                                       vpsa_srv=vpsa_srv,
                                       vpsa_vol=vpsa_vol)

        # Delete volume
        self.vpsa.send_cmd('delete_volume', vpsa_vol=vpsa_vol)

    def create_export(self, context, volume):
        """Irrelevant for VPSA volumes. Export created during attachment."""
        pass

    def ensure_export(self, context, volume):
        """Irrelevant for VPSA volumes. Export created during attachment."""
        pass

    def remove_export(self, context, volume):
        """Irrelevant for VPSA volumes. Export removed during detach."""
        pass

    def initialize_connection(self, volume, connector):
        """
        Attach volume to initiator/host.

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
        name = FLAGS.zadara_vol_name_template % volume['name']
        vpsa_vol = self._get_vpsa_volume_name(name)
        if not vpsa_vol:
            raise exception.VolumeNotFound(volume_id=name)

        # Get Active controller details
        ctrl = self._get_active_controller_details()
        if not ctrl:
            raise exception.ZadaraVPSANoActiveController()

        # Attach volume to server
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
        lun = server.findtext('lun')
        if target is None or lun is None:
            raise exception.ZadaraInvalidAttachmentInfo(
                name=name,
                reason='target=%s, lun=%s' % (target, lun))

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%s' % (ctrl['ip'], '3260')
        properties['target_iqn'] = target
        properties['target_lun'] = lun
        properties['volume_id'] = volume['id']

        properties['auth_method'] = 'CHAP'
        properties['auth_username'] = ctrl['chap_user']
        properties['auth_password'] = ctrl['chap_passwd']

        LOG.debug(_('Attach properties: %(properties)s') % locals())
        return {'driver_volume_type': 'iscsi',
                'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """
        Detach volume from the initiator.
        """
        # Get server name for IQN
        initiator_name = connector['initiator']
        vpsa_srv = self._get_server_name(initiator_name)
        if not vpsa_srv:
            raise exception.ZadaraServerNotFound(name=initiator_name)

        # Get volume name
        name = FLAGS.zadara_vol_name_template % volume['name']
        vpsa_vol = self._get_vpsa_volume_name(name)
        if not vpsa_vol:
            raise exception.VolumeNotFound(volume_id=name)

        # Detach volume from server
        self.vpsa.send_cmd('detach_volume',
                           vpsa_srv=vpsa_srv,
                           vpsa_vol=vpsa_vol)

    def create_volume_from_snapshot(self, volume, snapshot):
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        raise NotImplementedError()

    def delete_snapshot(self, snapshot):
        raise NotImplementedError()

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        raise NotImplementedError()

    def copy_volume_to_image(self, context, volume, image_service, image_id):
        """Copy the volume to the specified image."""
        raise NotImplementedError()

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        raise NotImplementedError()
