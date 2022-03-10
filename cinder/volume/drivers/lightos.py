# Copyright (C) 2016-2022 Lightbits Labs Ltd.
# Copyright (C) 2020 Intel Corporation
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

import http.client as httpstatus
import json
import random
import time
from typing import Dict


from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units
import requests
import urllib3

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration as config
from cinder.volume import driver


LOG = logging.getLogger(__name__)
ENABLE_TRACE = True
LIGHTOS_DEFAULT_PROJECT_NAME = "default"

urllib3.disable_warnings()

lightos_opts = [
    cfg.ListOpt('lightos_api_address',
                default=None,
                item_type=cfg.types.IPAddress(),
                help='The IP addresses of the LightOS API servers separated'
                ' by commas.'),
    cfg.PortOpt('lightos_api_port',
                default='443',
                help='The TCP/IP port at which the LightOS API'
                     ' endpoints listen.'
                     ' Port 443 is used for HTTPS and other values'
                     ' are used for HTTP.'),
    cfg.StrOpt('lightos_jwt',
               default=None,
               help='JWT to be used for volume and snapshot operations with'
                    ' the LightOS cluster.'
                    ' Do not set this parameter if the cluster is installed'
                    ' with multi-tenancy disabled.'),
    cfg.IntOpt('lightos_default_num_replicas',
               min=1,
               max=3,
               default=3,
               help='The default number of replicas to create for each'
                    ' volume.'),
    cfg.BoolOpt('lightos_default_compression_enabled',
                default=False,
                help='Set to True to create  new volumes compressed assuming'
                     ' no other compression setting is specified via the'
                     ' volumes type.'),
    cfg.IntOpt('lightos_api_service_timeout',
               default=30,
               help='The default amount of time (in seconds) to wait for'
               ' an API endpoint response.')
]

CONF = cfg.CONF
CONF.register_opts(lightos_opts, group=config.SHARED_CONF_GROUP)
BLOCK_SIZE = 8
LIGHTOS = "LIGHTOS"
INTERM_SNAPSHOT_PREFIX = "for_clone_"


class LightOSConnection(object):
    def __init__(self, conf):
        self.conf = conf
        self.access_key = None
        self.apiservers = self._init_api_servers()
        self._cur_api_server_idx = random.randint(0, len(self.apiservers) - 1)
        self.targets = dict()
        self.lightos_cluster_uuid = None
        self.subsystemNQN = None
        self._stats = {'total_capacity_gb': 0, 'free_capacity_gb': 0}
        # a single API call must have been answered in this time if the API
        # service/network were up
        self.api_timeout = self.conf.lightos_api_service_timeout

    def _init_api_servers(self) -> Dict[int, Dict]:
        # And verify that port is in range
        apiservers: Dict[int, Dict] = {}
        hosts = self.conf.lightos_api_address
        port = str(self.conf.lightos_api_port)
        apiservers = [dict(api_address=addr, api_port=port) for addr in hosts]
        return apiservers

    def _generate_lightos_cmd(self, cmd, **kwargs):
        """Generate command to be sent to LightOS API service"""

        def _joined_params(params):
            param_str = []
            for k, v in params.items():
                param_str.append("%s=%s" % (k, v))
            return '&'.join(param_str)

        # Dictionary of applicable LightOS commands in the following format:
        # 'command': (method, API_URL, {optional parameters})
        # This is constructed on the fly to include the caller-supplied kwargs
        # Can be optimized by only constructing the specific
        # command the user provided in cmd

        # API V2 common commands
        lightos_commands = {
            # cluster operations,
            'get_cluster_info': ('GET',
                                 '/api/v2/clusterinfo', {}),

            'get_cluster': ('GET',
                            '/api/v2/cluster', {}),

            # node operations
            'get_node': ('GET',
                         '/api/v2/nodes/%s' % kwargs.get('UUID'), {}),

            'get_nodes': ('GET',
                          '/api/v2/nodes', {}),

            # volume operations
            'create_volume': ('POST',
                              '/api/v2/projects/%s/volumes' % kwargs.get(
                                  "project_name"),
                              {
                                  'name': kwargs.get('name'),
                                  'size': kwargs.get('size'),
                                  'replicaCount': kwargs.get('n_replicas'),
                                  'compression': kwargs.get('compression'),
                                  'acl': {
                                      'values': kwargs.get('acl'),
                                  },
                                  'sourceSnapshotUUID': kwargs.get(
                                      'src_snapshot_uuid'),
                                  'sourceSnapshotName': kwargs.get(
                                      'src_snapshot_name'),
                              }),

            'delete_volume': ('DELETE',
                              '/api/v2/projects/%s/volumes/%s' % (kwargs.get(
                                  "project_name"), kwargs.get("volume_uuid")),
                              {}),

            'update_volume': ('PUT',
                              '/api/v2/projects/%s/volumes/%s' % (kwargs.get(
                                  "project_name"), kwargs.get("volume_uuid")),
                              {
                                  'acl': {
                                      'values': kwargs.get('acl'),
                                  },
                              }),

            'extend_volume': ('PUT',
                              '/api/v2/projects/%s/volumes/%s' % (
                                  kwargs.get("project_name"),
                                  kwargs.get("volume_uuid")),
                              {
                                  'UUID': kwargs.get('volume_uuid'),
                                  'size': kwargs.get('size'),
                              }),

            # snapshots operations
            'create_snapshot': ('POST',
                                '/api/v2/projects/%s/snapshots' % kwargs.get(
                                    "project_name"),
                                {
                                    'name': kwargs.get('name'),
                                    'sourceVolumeUUID': kwargs.get(
                                        'src_volume_uuid'),
                                    'sourceVolumeName': kwargs.get(
                                        'src_volume_name'),
                                }),

            'delete_snapshot': ('DELETE',
                                '/api/v2/projects/%s/snapshots/%s' % (
                                    kwargs.get("project_name"),
                                    kwargs.get("snapshot_uuid")),
                                {}),

            # get operations
            'get_volume': ('GET',
                           '/api/v2/projects/%s/volumes/%s' % (
                               kwargs.get("project_name"),
                               kwargs.get("volume_uuid")),
                           {}),

            'get_volume_by_name': ('GET',
                                   '/api/v2/projects/%s/volumes/?name=%s' % (
                                       kwargs.get("project_name"),
                                       kwargs.get("volume_name")),
                                   {}),

            'list_volumes': ('GET',
                             '/api/v2/projects/%s/volumes' % kwargs.get(
                                 "project_name"),
                             {}),

            'get_snapshot': ('GET',
                             '/api/v2/projects/%s/snapshots/%s' % (
                                 kwargs.get("project_name"),
                                 kwargs.get("snapshot_uuid")),
                             {}),

            'get_snapshot_by_name': ('GET',
                                     '/api/v2/projects/%s/snapshots'
                                     '/?Name=%s' % (
                                         kwargs.get("project_name"),
                                         kwargs.get("snapshot_name")),
                                     {})
        }
        if cmd not in lightos_commands:
            raise exception.UnknownCmd(cmd=cmd)
        else:
            (method, url, params) = lightos_commands[cmd]

        if method == 'GET':
            body = params

        elif method == 'DELETE':
            LOG.debug("DELETE params: %s", params)
            # For DELETE commands add parameters to the URL
            url += '?' + _joined_params(params)
            body = ''

        elif method == 'PUT':
            # For PUT commands add parameters to the URL
            body = params

        elif method == 'POST':
            body = params

        else:
            msg = (_('Method %(method)s is not defined') %
                   {'method': method})
            LOG.error(msg)
            raise AssertionError(msg)

        return (method, url, body)

    def pretty_print_req(self, req, timeout):
        request = req.method + ' ' + req.url
        header = ', '.join('"{}: {}"'.format(k, v)
                           for k, v in req.headers.items())
        LOG.debug('Req: %s Headers: %s Body: %s Timeout: %s',
                  request,
                  header,
                  req.body,
                  timeout)

    def send_cmd(self, cmd, timeout, **kwargs):
        """Send command to any LightOS REST API server."""
        start_idx = self._cur_api_server_idx
        stop = time.time() + timeout
        while time.time() <= stop:
            server = self.apiservers[self._cur_api_server_idx]
            host = server['api_address']
            port = server['api_port']

            (success, status_code, data) = self.__send_cmd(
                cmd, host, port, self.api_timeout, **kwargs)
            if success:
                return (status_code, data)
            # go on to the next API server wrapping around as needed
            self._cur_api_server_idx = (
                self._cur_api_server_idx + 1) % len(self.apiservers)
            # if we only have a single API server, keep trying it
            # if we have more than one and we tried all of them, give up
            if (self._cur_api_server_idx ==
                    start_idx and len(self.apiservers) > 1):
                break

        raise exception.VolumeDriverException(
            message="Could not get a response from any API server")

    def __send_cmd(self, cmd, host, port, timeout, **kwargs):
        """Send command to LightOS REST API server.

        Returns: (success = True/False, data)
        """
        ssl_verify = self.conf.driver_ssl_cert_verify
        (method, url, body) = self._generate_lightos_cmd(cmd, **kwargs)
        LOG.info(
            'Invoking %(cmd)s using %(method)s url: %(url)s \
            request.body: %(body)s ssl_verify: %(ssl_verify)s',
            {'cmd': cmd, 'method': method, 'url': url, 'body': body,
             'ssl_verify': ssl_verify})

        api_url = "https://%s:%s%s" % (host, port, url)

        try:
            with requests.Session() as session:
                req = requests.Request(
                    method, api_url, data=json.dumps(body) if body else None)
                req.headers.update({'Accept': 'application/json'})
                # -H 'Expect:'  will prevent us from getting
                # the 100 Continue response from curl
                req.headers.update({'Expect': ''})
                if method in ('POST', 'PUT'):
                    req.headers.update({'Content-Type': 'application/json'})
                if kwargs.get("etag"):
                    req.headers.update({'If-Match': kwargs['etag']})
                if self.conf.lightos_jwt:
                    req.headers.update(
                        {'Authorization':
                         'Bearer %s' % self.conf.lightos_jwt})
                prepped = req.prepare()
                self.pretty_print_req(prepped, timeout)
                response = session.send(
                    prepped, timeout=timeout, verify=ssl_verify)
        except Exception:
            LOG.exception("REST server not responding at '%s'", api_url)
            return (False, None, None)

        try:
            resp = response.json()
        except ValueError:
            resp = response.text
        data = resp

        LOG.debug(
            'Resp(%s): code %s data %s',
            api_url,
            response.status_code,
            data)
        return (True, response.status_code, data)


@interface.volumedriver
class LightOSVolumeDriver(driver.VolumeDriver):
    """OpenStack NVMe/TCP cinder drivers for Lightbits LightOS.

    .. code-block:: default

      Version history:
          2.3.12 - Initial upstream driver version.
    """

    VERSION = '2.3.12'
    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "LightbitsLabs_CI"

    def __init__(self, *args, **kwargs):
        super(LightOSVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(lightos_opts)
        # connector implements NVMe/TCP initiator functionality.
        if not self.configuration.__dict__.get("initiator_connector", None):
            self.configuration.initiator_connector = (
                "os_brick.initiator.connector.InitiatorConnector")
        if not self.configuration.__dict__.get("lightos_client", None):
            self.configuration.lightos_client = (
                "cinder.volume.drivers.lightos.LightOSConnection")

        initiator_connector = importutils.import_class(
            self.configuration.initiator_connector)
        self.connector = initiator_connector.factory(
            LIGHTOS,
            root_helper=utils.get_root_helper(),
            message_queue=None,
            device_scan_attempts=
            self.configuration.num_volume_device_scan_tries)

        lightos_client_ctor = importutils.import_class(
            self.configuration.lightos_client)
        self.cluster = lightos_client_ctor(self.configuration)

        self.logical_op_timeout = \
            self.configuration.lightos_api_service_timeout * 3 + 10

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'driver_ssl_cert_verify', 'reserved_percentage',
            'volume_backend_name')
        return lightos_opts + additional_opts

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        If volume_type extra specs includes 'replication: <is> True' the
        driver needs to create a volume replica (secondary)
        and setup replication between the newly created volume
        and the secondary volume.
        """
        project_name = self._get_lightos_project_name(volume)
        # Create an intermediate snapshot
        snapshot_name = self._interm_snapshotname(volume)
        src_volume_name = self._lightos_volname(src_vref)
        try:
            self._create_snapshot(project_name,
                                  snapshot_name, src_volume_name)
        except Exception as e:
            LOG.warning(
                "Failed to create intermediate snapshot \
                 %s from source volume %s.",
                snapshot_name,
                src_volume_name)
            raise e

        # Create a volume from the intermediate snapshot
        try:
            self._create_volume(volume,
                                src_snapshot_lightos_name=snapshot_name)
        except Exception as e:
            LOG.error("Failed to create volume %s from intermediate "
                      " snapshot %s. Trying to clean up.",
                      src_volume_name, snapshot_name)
            raise e

        # Delete the intermediate snapshot
        finally:
            try:
                self._delete_lightos_snapshot(project_name, snapshot_name)
            except Exception as e:
                LOG.warning("Failed to delete the intermediate snapshot %s for"
                            " volume %s. Trying to clean up.",
                            snapshot_name, src_volume_name)
                raise e

    def create_export(self, context, volume, vg=None):
        """Irrelevant for lightos volumes.

        Export created during attachment.
        """
        pass

    def ensure_export(self, context, volume):
        """Irrelevant for lightos volumes.

        Export created during attachment.
        """
        pass

    def remove_export(self, context, volume):
        """Irrelevant for lightos volumes.

        Export removed during detach.
        """
        pass

    def _get_lightos_volume(
            self,
            project_name,
            timeout,
            vol_uuid=None,
            vol_name=None):
        assert vol_uuid or vol_name, 'LightOS volume name or UUID \
        must be specified'
        if vol_uuid:
            return self.cluster.send_cmd(
                cmd='get_volume',
                project_name=project_name,
                timeout=timeout,
                volume_uuid=vol_uuid)

        return self.cluster.send_cmd(
            cmd='get_volume_by_name',
            project_name=project_name,
            timeout=timeout,
            volume_name=vol_name)

    def _lightos_volname(self, volume):
        volid = volume.name_id
        lightos_volname = CONF.volume_name_template % volid
        return lightos_volname

    def _get_lightos_project_name(self, volume):
        try:
            extra_specs = volume.volume_type.extra_specs
            project_name = extra_specs.get(
                'lightos:project_name',
                LIGHTOS_DEFAULT_PROJECT_NAME)
        except Exception:
            LOG.debug(
                "LIGHTOS volume %s has no lightos:project_name",
                volume)
            project_name = LIGHTOS_DEFAULT_PROJECT_NAME

        return project_name

    def _lightos_snapshotname(self, snapshot_id):
        return CONF.snapshot_name_template % snapshot_id

    def _interm_snapshotname(self, snapshot):
        id = snapshot['id']
        return '%s%s' % (INTERM_SNAPSHOT_PREFIX, id)

    def _get_lightos_snapshot(
            self,
            project_name,
            timeout,
            snapshot_uuid=None,
            snapshot_name=None):
        assert snapshot_uuid or snapshot_name, 'LightOS snapshot name or \
        UUID must be specified'
        if snapshot_uuid:
            return self.cluster.send_cmd(
                cmd='get_snapshot',
                project_name=project_name,
                timeout=timeout,
                snapshot_uuid=snapshot_uuid)

        return self.cluster.send_cmd(
            cmd='get_snapshot_by_name',
            project_name=project_name,
            timeout=timeout,
            snapshot_name=snapshot_name)

    def _wait_for_volume_available(
            self,
            project_name,
            timeout,
            vol_uuid=None,
            vol_name=None):
        """Wait until the volume is available."""
        assert vol_uuid or vol_name, 'LightOS volume UUID or name \
        must be supplied'
        # while creating lightos volume we can stop on any terminal status
        # possible states: Unknown, Creating, Available, Deleting, Deleted,
        # Failed, Updating
        states = ('Available', 'Deleting', 'Deleted', 'Failed', 'UNKNOWN')

        stop = time.time() + timeout
        while time.time() <= stop:
            (status_code,
             resp) = self._get_lightos_volume(project_name,
                                              timeout=self.logical_op_timeout,
                                              vol_uuid=vol_uuid,
                                              vol_name=vol_name)
            state = resp.get('state', 'UNKNOWN') if \
                status_code == httpstatus.OK and resp else 'UNKNOWN'
            if state in states and status_code != httpstatus.NOT_FOUND:
                break
            time.sleep(1)

        return state

    def _parse_extra_spec(self, extra_spec_value, default_value):
        extra_spec_value = str(extra_spec_value)
        extra_spec_value = extra_spec_value.casefold()
        if "true" in extra_spec_value:
            return "True"
        elif "false" in extra_spec_value:
            return "False"
        return default_value

    def _get_volume_specs(self, volume):
        default_compression = 'True' if self.configuration. \
            lightos_default_compression_enabled else 'False'
        num_replicas = str(self.configuration.lightos_default_num_replicas)

        if not volume.volume_type:
            return (default_compression, num_replicas,
                    LIGHTOS_DEFAULT_PROJECT_NAME)

        specs = getattr(volume.volume_type, 'extra_specs', {})
        type_compression = specs.get('compression', default_compression)
        compression = self._parse_extra_spec(type_compression,
                                             default_compression)
        num_replicas = str(specs.get('lightos:num_replicas', num_replicas))
        project_name = specs.get(
            'lightos:project_name',
            LIGHTOS_DEFAULT_PROJECT_NAME)
        return (compression, num_replicas, project_name)

    def _create_new_lightos_volume(self,
                                   os_volume,
                                   project_name,
                                   lightos_name,
                                   src_snapshot_lightos_name=None):
        """Create a new LightOS volume for this openstack volume."""
        (compression, num_replicas, _) = self._get_volume_specs(os_volume)
        return self.cluster.send_cmd(
            cmd='create_volume',
            project_name=project_name,
            timeout=self.logical_op_timeout,
            name=lightos_name,
            size=str(os_volume['size']) + ' gib',
            n_replicas=num_replicas,
            compression=compression,
            src_snapshot_name=src_snapshot_lightos_name,
            acl=['ALLOW_NONE']
        )

    def _get_lightos_uuid(self, project_name, volume):
        lightos_name = self._lightos_volname(volume)
        timeout = self.logical_op_timeout

        (status, data) = self._get_lightos_volume(project_name=project_name,
                                                  timeout=timeout,
                                                  vol_name=lightos_name)
        if status != httpstatus.OK or not data:
            LOG.error(
                'Failed to get LightOS volume %s project %s status: \
                %s data: %s',
                lightos_name,
                project_name,
                status,
                str(data))
            raise exception.VolumeNotFound(volume_id=volume)

        lightos_uuid = data.get('UUID')
        if not lightos_uuid:
            LOG.error('Failed to get LightOS volume UUID status: %s, data: %s',
                      status, str(data))
            raise exception.VolumeNotFound(volume_id=volume)

        return lightos_uuid

    def create_volume(self, volume):
        return self._create_volume(volume, src_snapshot_lightos_name=None)

    def create_volume_from_snapshot(self, volume, snapshot):
        snapshotname = self._lightos_snapshotname(snapshot["id"])
        return self._create_volume(volume,
                                   src_snapshot_lightos_name=snapshotname)

    def _create_volume(self, volume, src_snapshot_lightos_name):
        lightos_name = self._lightos_volname(volume)
        project_name = self._get_lightos_project_name(volume)
        lightos_uuid = '<UNKNOWN>'
        vol_state = 'UNKNOWN'

        # first, check if such a volume exists
        # if it exists, we must have created it earlier in a previous
        # invocation of create volume since it takes a while for
        # openstack to retry the call, it's highly unlikely that we created
        # it but it does not show up yet, so assume that if it does not show
        # up, it was never created
        status_code, resp = self._get_lightos_volume(project_name,
                                                     timeout=self.
                                                     logical_op_timeout,
                                                     vol_name=lightos_name)
        if status_code == httpstatus.NOT_FOUND:
            status_code, resp = self._create_new_lightos_volume(
                os_volume=volume,
                project_name=project_name,
                lightos_name=lightos_name,
                src_snapshot_lightos_name=src_snapshot_lightos_name)

        if status_code in (httpstatus.OK, httpstatus.CREATED):
            lightos_uuid = resp['UUID']
            vol_state = self._wait_for_volume_available(
                project_name,
                timeout=self.logical_op_timeout,
                vol_uuid=lightos_uuid)
            if vol_state == 'Available':
                LOG.debug(
                    "LIGHTOS created volume name %s lightos_uuid \
                     %s project %s",
                    lightos_name,
                    lightos_uuid,
                    project_name)
                return

            # if volume was created in failed state we should clean it up
            LOG.warning(
                'LightOS volume with UUID %s project %s last_state is %s',
                lightos_uuid,
                project_name,
                vol_state)
            if vol_state != 'UNKNOWN':
                LOG.debug(
                    'Cleaning up LightOS volume with UUID %s project %s',
                    lightos_uuid,
                    project_name)
                self._delete_lightos_volume(project_name, lightos_uuid)
                # wait for openstack to call us again to create it

        msg = (
            "Did not succeed creating LightOS volume with UUID %(uuid)s"
            " status_code %(code)s last state %(state)s" %
            dict(uuid=lightos_uuid, code=status_code, state=vol_state))
        msg = _(msg)
        raise exception.VolumeBackendAPIException(message=msg)

    def _wait_for_snapshot_available(self, project_name,
                                     timeout,
                                     snapshot_uuid=None,
                                     snapshot_name=None):
        """Wait until the snapshot is available."""
        assert snapshot_uuid or snapshot_name, \
            'LightOS snapshot UUID or name must be supplied'
        # we can stop on any terminal status
        # possible states: Unknown, Creating, Available, Deleting, Deleted,
        # Failed, Updating
        states = ('Available', 'Deleting', 'Deleted', 'Failed', 'UNKNOWN')

        stop = time.time() + timeout
        while time.time() <= stop:
            (status_code,
             resp) = self._get_lightos_snapshot(project_name,
                                                timeout=
                                                self.logical_op_timeout,
                                                snapshot_uuid=snapshot_uuid,
                                                snapshot_name=snapshot_name)
            state = resp.get('state', 'UNKNOWN') if \
                status_code == httpstatus.OK and resp else 'UNKNOWN'
            if state in states and status_code != httpstatus.NOT_FOUND:
                break
            time.sleep(1)

        return state

    def _wait_for_snapshot_deleted(self,
                                   project_name,
                                   timeout,
                                   snapshot_uuid):
        """Wait until the snapshot has been deleted."""
        assert snapshot_uuid, 'LightOS snapshot UUID must be specified'
        states = ('Deleted', 'Deleting', 'UNKNOWN')

        stop = time.time() + timeout
        while time.time() <= stop:
            status_code, resp = (
                self._get_lightos_snapshot(project_name,
                                           timeout=self.logical_op_timeout,
                                           snapshot_uuid=snapshot_uuid))
            if status_code == httpstatus.NOT_FOUND:
                return 'Deleted'
            state = resp.get('state', 'UNKNOWN') if \
                status_code == httpstatus.OK and resp else 'UNKNOWN'
            if state in states:
                break
            time.sleep(1)

        return state

    def _wait_for_volume_deleted(self, project_name, timeout, vol_uuid):
        """Wait until the volume has been deleted."""
        assert vol_uuid, 'LightOS volume UUID must be specified'
        states = ('Deleted', 'Deleting', 'UNKNOWN')

        stop = time.time() + timeout
        while time.time() <= stop:
            (status_code,
             resp) = self._get_lightos_volume(project_name,
                                              timeout=self.logical_op_timeout,
                                              vol_uuid=vol_uuid)
            if status_code == httpstatus.NOT_FOUND:
                return 'Deleted'
            state = resp.get('state', 'UNKNOWN') if \
                status_code == httpstatus.OK and resp else 'UNKNOWN'
            if state in states:
                break
            time.sleep(1)

        return state

    def _delete_lightos_volume(self, project_name, lightos_uuid):
        end = time.time() + self.logical_op_timeout
        while (time.time() < end):
            status_code, resp = (
                self.cluster.send_cmd(
                    cmd='delete_volume',
                    project_name=project_name,
                    timeout=self. logical_op_timeout,
                    volume_uuid=lightos_uuid))
            if status_code == httpstatus.OK:
                break

            LOG.warning(
                "delete_volume for volume with LightOS UUID %s failed \
                with status code %s response %s",
                lightos_uuid,
                status_code,
                resp)
            time.sleep(1)
        else:  # no break
            LOG.error(
                "Failed to delete volume with LightOS UUID %s. Final status \
                code %s response %s",
                lightos_uuid,
                status_code,
                resp)
            return False

        deleted_state = self._wait_for_volume_deleted(
            project_name, timeout=self.logical_op_timeout,
            vol_uuid=lightos_uuid)
        return deleted_state in ('Deleted', 'Deleting', 'UNKNOWN')

    def delete_volume(self, volume):
        """Delete volume."""
        project_name = self._get_lightos_project_name(volume)
        try:
            lightos_uuid = self._get_lightos_uuid(project_name, volume)
        except exception.VolumeNotFound:
            return True

        if not self._delete_lightos_volume(project_name, lightos_uuid):
            msg = ('Failed to delete LightOS volume with UUID'
                   ' %(uuid)s project %(project_name)s' % (
                       dict(uuid=lightos_uuid, project_name=project_name)))
            raise exception.VolumeBackendAPIException(message=msg)

    def get_vol_by_id(self, volume):
        LOG.warning('UNIMPLEMENTED: get vol by id')

    def get_vols(self):
        LOG.warning('UNIMPLEMENTED: get vols')

    def check_for_setup_error(self):
        subsysnqn = self.cluster.subsystemNQN
        if not subsysnqn:
            msg = ('LIGHTOS: Cinder driver requires the'
                   ' LightOS cluster subsysnqn')
            raise exception.VolumeBackendAPIException(message=msg)

        hostnqn = (
            self.connector.get_connector_properties(
                utils.get_root_helper())['nqn'])
        if not hostnqn:
            msg = ("LIGHTOS: Cinder driver requires a local hostnqn for"
                   " image_to/from_volume operations")
            raise exception.VolumeBackendAPIException(message=msg)

    def get_cluster_info(self):
        status_code, cluster_info = self.cluster.send_cmd(
            cmd='get_cluster_info', timeout=self.logical_op_timeout)
        if status_code == httpstatus.UNAUTHORIZED:
            msg = f'LIGHTOS: failed to connect to cluster. code: {status_code}'
            raise exception.InvalidAuthKey(message=_(msg))
        if status_code != httpstatus.OK:
            msg = 'LIGHTOS: Could not connect to LightOS cluster'
            raise exception.VolumeBackendAPIException(message=_(msg))

        LOG.info("Connected to LightOS cluster %s subsysnqn %s",
                 cluster_info['UUID'], cluster_info['subsystemNQN'])
        self.cluster.lightos_cluster_uuid = cluster_info['UUID']
        self.cluster.subsystemNQN = cluster_info['subsystemNQN']

    def get_cluster_stats(self):
        status_code, cluster_info = self.cluster.send_cmd(
            cmd='get_cluster', timeout=self.logical_op_timeout)
        if status_code != httpstatus.OK:
            msg = 'LIGHTOS: Could not connect to LightOS cluster'
            raise exception.VolumeBackendAPIException(message=_(msg))

        return cluster_info['statistics']

    def valid_nodes_info(self, nodes_info):
        if not nodes_info or 'nodes' not in nodes_info:
            return False

        return True

    def wait_for_lightos_cluster(self):
        cmd = 'get_nodes'
        end = time.time() + self.logical_op_timeout
        while (time.time() < end):
            status_code, nodes_info = self.cluster.send_cmd(
                cmd=cmd, timeout=self.logical_op_timeout)
            if status_code != httpstatus.OK or not self.valid_nodes_info(
                    nodes_info):
                time.sleep(1)
                continue

            return nodes_info

        # bail out if we got here, timeout elapsed
        msg = 'Failed to get nodes, last status was {} nodes_info {}'.format(
            status_code, nodes_info)
        raise exception.VolumeBackendAPIException(message=_(msg))

    def do_setup(self, context):

        self.get_cluster_info()
        nodes_info = self.wait_for_lightos_cluster()

        self.cluster.targets = dict()
        node_list = nodes_info['nodes']
        for node in node_list:
            self.cluster.targets[node['UUID']] = node

        # reduce the logical op timeout if single server LightOS cluster
        if len(node_list) == 1:
            self.logical_op_timeout = self.configuration. \
                lightos_api_service_timeout + 10

    def extend_volume(self, volume, size):
        # loop because lightos api is async
        end = time.time() + self.logical_op_timeout
        while (time.time() < end):
            try:
                finished = self._extend_volume(volume, size)
                if finished:
                    break
            except exception.VolumeNotFound as e:
                raise e
            except Exception as e:
                # bail out if the time out elapsed...
                if time.time() >= end:
                    LOG.warning('Timed out extend volume operation')
                    raise e
                # if we still have more time, just print the exception
                LOG.warning(
                    'caught this in extend_volume() ... will retry: %s',
                    str(e))
                time.sleep(1)

    def _extend_volume(self, volume, size):
        lightos_volname = self._lightos_volname(volume)
        project_name = self._get_lightos_project_name(volume)

        try:
            (status, data) = self._get_lightos_volume(
                project_name,
                timeout=self.
                logical_op_timeout,
                vol_name=lightos_volname)
            if status != httpstatus.OK or not data:
                LOG.error(
                    'Failed to get LightOS volume status: %s data: %s',
                    status,
                    str(data))
                raise exception.VolumeNotFound(volume_id=volume.id)
            lightos_uuid = data['UUID']
            etag = data.get('ETag', '')
        except Exception as e:
            raise e

        try:
            code, message = self.cluster.send_cmd(
                cmd='extend_volume',
                project_name=project_name,
                timeout=self.logical_op_timeout,
                volume_uuid=lightos_uuid,
                size=str(size) + ' gib',
                etag=etag
            )
            if code == httpstatus.OK:
                LOG.info(
                    "Successfully extended volume %s project %s size:%s",
                    volume,
                    project_name,
                    size)
            else:
                raise exception.ExtendVolumeError(reason=message)

        except exception.ExtendVolumeError as e:
            raise e
        except Exception as e:
            raise exception.ExtendVolumeError(raised_exception=e)
        return True

    @staticmethod
    def byte_to_gb(bbytes):
        return int(int(bbytes) / units.Gi)

    def get_volume_stats(self, refresh=False):
        """Retrieve stats info for the volume *service*,

        not a specific volume.
        """

        LOG.debug("getting volume stats (refresh=%s)", refresh)

        if not refresh:
            return self._stats

        backend_name = self.configuration.safe_get('volume_backend_name')
        res_percentage = self.configuration.safe_get('reserved_percentage')
        storage_protocol = 'lightos'
        # as a tenant we dont have access to cluster stats
        # in the future we might expose this per project via get_project API
        # currently we remove this stats call.
        # cluster_stats = self.get_cluster_stats()

        data = {'vendor_name': 'LightOS Storage',
                'volume_backend_name': backend_name or self.__class__.__name__,
                'driver_version': self.VERSION,
                'storage_protocol': storage_protocol,
                'reserved_percentage': res_percentage,
                'QoS_support': False,
                'online_extend_support': True,
                'thin_provisioning_support': True,
                'compression': [True, False],
                'multiattach': True}
        # data['total_capacity_gb'] =
        # self.byte_to_gb(cluster_stats['effectivePhysicalStorage'])
        # It would be preferable to return
        # self.byte_to_gb(cluster_stats['freePhysicalStorage'])
        # here but we return 'infinite' due to the Cinder bug described in
        # https://bugs.launchpad.net/cinder/+bug/1871371
        data['free_capacity_gb'] = 'infinite'
        self._stats = data

        return self._stats

    def _get_connection_properties(self, project_name, volume):
        lightos_targets = {}
        for target in self.cluster.targets.values():
            properties = dict()
            data_address, _ = target['nvmeEndpoint'].split(':')
            properties['target_portal'] = data_address
            properties['target_port'] = 8009  # spec specified discovery port
            properties['transport_type'] = 'tcp'
            lightos_targets[data_address] = properties

        server_properties = {}
        server_properties['lightos_nodes'] = lightos_targets
        server_properties['uuid'] = (
            self._get_lightos_uuid(project_name, volume))
        server_properties['subsysnqn'] = self.cluster.subsystemNQN

        return server_properties

    def set_volume_acl(self, project_name, lightos_uuid, acl, etag):
        return self.cluster.send_cmd(
            cmd='update_volume',
            project_name=project_name,
            timeout=self.logical_op_timeout,
            volume_uuid=lightos_uuid,
            acl=acl,
            etag=etag
        )

    def __add_volume_acl(self, project_name, lightos_volname, acl_to_add):
        (status, data) = self._get_lightos_volume(project_name,
                                                  self.logical_op_timeout,
                                                  vol_name=lightos_volname)
        if status != httpstatus.OK or not data:
            LOG.error('Failed to get LightOS volume %s status %s data %s',
                      lightos_volname, status, data)
            return False

        lightos_uuid = data.get('UUID')
        if not lightos_uuid:
            LOG.warning('Got LightOS volume without UUID?! data: %s', data)
            return False

        acl = data.get('acl')
        if not acl:
            LOG.warning('Got LightOS volume without ACL?! data: %s', data)
            return False

        acl = acl.get('values', [])

        # remove ALLOW_NONE and add our acl_to_add if not already there
        if 'ALLOW_NONE' in acl:
            acl.remove('ALLOW_NONE')
        if acl_to_add not in acl:
            acl.append(acl_to_add)

        return self.set_volume_acl(
            project_name,
            lightos_uuid,
            acl,
            etag=data.get(
                'ETag',
                ''))

    def add_volume_acl(self, project_name, volume, acl_to_add):
        LOG.debug(
            'add_volume_acl got volume %s project %s acl %s',
            volume,
            project_name,
            acl_to_add)
        lightos_volname = self._lightos_volname(volume)
        return self.update_volume_acl(
            self.__add_volume_acl,
            project_name,
            lightos_volname,
            acl_to_add)

    def __remove_volume_acl(
            self,
            project_name,
            lightos_volname,
            acl_to_remove):
        (status, data) = self._get_lightos_volume(project_name,
                                                  self.logical_op_timeout,
                                                  vol_name=lightos_volname)
        if not data:
            LOG.error(
                'Could not get data for LightOS volume %s project %s',
                lightos_volname,
                project_name)
            return False

        lightos_uuid = data.get('UUID')
        if not lightos_uuid:
            LOG.warning('Got LightOS volume without UUID?! data: %s', data)
            return False

        acl = data.get('acl')
        if not acl:
            LOG.warning('Got LightOS volume without ACL?! data: %s', data)
            return False

        acl = acl.get('values')
        if not acl:
            LOG.warning(
                'Got LightOS volume without ACL values?! data: %s', data)
            return False

        try:
            acl.remove(acl_to_remove)
        except ValueError:
            LOG.warning(
                'Could not remove acl %s from LightOS volume %s project \
                %s with acl %s',
                acl_to_remove,
                lightos_volname,
                project_name,
                acl)

        # if the ACL is empty here, put in ALLOW_NONE
        if not acl:
            acl.append('ALLOW_NONE')

        return self.set_volume_acl(
            project_name,
            lightos_uuid,
            acl,
            etag=data.get(
                'ETag',
                ''))

    def __overwrite_volume_acl(
            self,
            project_name,
            lightos_volname,
            acl):
        status, data = self._get_lightos_volume(project_name,
                                                self.logical_op_timeout,
                                                vol_name=lightos_volname)
        if not data:
            LOG.error(
                'Could not get data for LightOS volume %s project %s',
                lightos_volname,
                project_name)
            return False

        lightos_uuid = data.get('UUID')
        if not lightos_uuid:
            LOG.warning('Got LightOS volume without UUID?! data: %s', data)
            return False

        return self.set_volume_acl(
            project_name,
            lightos_uuid,
            acl,
            etag=data.get(
                'ETag',
                ''))

    def remove_volume_acl(self, project_name, volume, acl_to_remove):
        lightos_volname = self._lightos_volname(volume)
        LOG.debug('remove_volume_acl volume %s project %s acl %s',
                  volume, project_name, acl_to_remove)
        return self.update_volume_acl(
            self.__remove_volume_acl,
            project_name,
            lightos_volname,
            acl_to_remove)

    def remove_all_volume_acls(self, project_name, volume):
        lightos_volname = self._lightos_volname(volume)
        LOG.debug('remove_all_volume_acls volume %s project %s',
                  volume, project_name)
        return self.update_volume_acl(
            self.__overwrite_volume_acl,
            project_name,
            lightos_volname,
            ['ALLOW_NONE'])

    def update_volume_acl(self, func, project_name, lightos_volname, acl):
        # loop because lightos api is async
        end = time.time() + self.logical_op_timeout
        first_iteration = True
        while (time.time() < end):
            if not first_iteration:
                time.sleep(1)
            first_iteration = False
            res = func(project_name, lightos_volname, acl)
            if not isinstance(res, tuple):
                LOG.debug('Update_volume: func %s(%s project %s) failed',
                          func, lightos_volname, project_name)
                continue
            if len(res) != 2:
                LOG.debug("Unexpected number of values to unpack")
                continue
            (status, resp) = res
            if status != httpstatus.OK:
                LOG.debug(
                    'update_volume: func %s(%s project %s) got \
                    http status %s',
                    func,
                    lightos_volname,
                    project_name,
                    status)
            else:
                break

        # bail out if the time out elapsed...
        if time.time() >= end:
            LOG.warning(
                'Timed out %s(%s project %s)',
                func,
                lightos_volname,
                project_name)
            return False

        # or the call succeeded and we need to wait
        # for the volume to stabilize
        vol_state = self._wait_for_volume_available(
            project_name, timeout=end - time.time(), vol_name=lightos_volname)
        if vol_state != 'Available':
            LOG.warning(
                'Timed out waiting for volume %s project %s to stabilize, \
                last state %s',
                lightos_volname,
                project_name,
                vol_state)
            return False

        return True

    def _wait_for_volume_acl(
            self,
            project_name,
            lightos_volname,
            acl,
            requested_membership):
        end = time.time() + self.logical_op_timeout
        while (time.time() < end):
            (status, resp) = self._get_lightos_volume(
                project_name,
                self.logical_op_timeout,
                vol_name=lightos_volname)
            if status == httpstatus.OK:
                if not resp or not resp.get('acl'):
                    LOG.warning(
                        'Got LightOS volume %s without ACL?! data: %s',
                        lightos_volname,
                        resp)
                    return False

                volume_acls = resp.get('acl').get('values', [])
                membership = acl in volume_acls
                if membership == requested_membership:
                    return True

            LOG.debug(
                'ACL did not settle for volume %s project %s, status \
                %s resp %s',
                lightos_volname,
                project_name,
                status,
                resp)
            time.sleep(1)
        LOG.warning(
            'ACL did not settle for volume %s, giving up',
            lightos_volname)
        return False

    def create_snapshot(self, snapshot):
        snapshot_name = self._lightos_snapshotname(snapshot["id"])
        src_volume_name = self._lightos_volname(snapshot["volume"])
        project_name = self._get_lightos_project_name(snapshot.volume)
        self._create_snapshot(project_name, snapshot_name, src_volume_name)

    @coordination.synchronized('lightos-create_snapshot-{src_volume_name}')
    def _create_snapshot(self, project_name, snapshot_name, src_volume_name):
        (status_code_get, response) = self._get_lightos_snapshot(
            project_name, self.logical_op_timeout,
            snapshot_name=snapshot_name)
        if status_code_get != httpstatus.OK:
            end = time.time() + self.logical_op_timeout
            while (time.time() < end):
                (status_code_create, response) = self.cluster.send_cmd(
                    cmd='create_snapshot',
                    project_name=project_name,
                    timeout=self.logical_op_timeout,
                    name=snapshot_name,
                    src_volume_name=src_volume_name,
                )

                if status_code_create == httpstatus.INTERNAL_SERVER_ERROR:
                    pass
                else:
                    break

                time.sleep(1)

            if status_code_create != httpstatus.OK:
                msg = ('Did not succeed creating LightOS snapshot %s'
                       ' project %s'
                       ' status code %s response %s' %
                       (snapshot_name, project_name, status_code_create,
                        response))
                raise exception.VolumeBackendAPIException(message=_(msg))

        state = self._wait_for_snapshot_available(project_name,
                                                  timeout=
                                                  self.logical_op_timeout,
                                                  snapshot_name=snapshot_name)

        if state == 'Available':
            LOG.debug(
                'Successfully created LightOS snapshot %s', snapshot_name)
            return

        LOG.error(
            'Failed to create snapshot %s project %s for volume %s. \
            state = %s.',
            snapshot_name,
            project_name,
            src_volume_name,
            state)
        try:
            self._delete_lightos_snapshot(project_name, snapshot_name)
        except exception.CinderException as ex:
            LOG.warning("Error deleting snapshot during cleanup: %s", ex)

        msg = ('Did not succeed creating LightOS snapshot %s project'
               '%s last state %s' % (snapshot_name, project_name, state))
        raise exception.VolumeBackendAPIException(message=_(msg))

    def delete_snapshot(self, snapshot):
        lightos_snapshot_name = self._lightos_snapshotname(snapshot["id"])
        project_name = self._get_lightos_project_name(snapshot.volume)
        self._delete_lightos_snapshot(project_name=project_name,
                                      snapshot_name=lightos_snapshot_name)

    def _get_lightos_snapshot_uuid(self, project_name, lightos_snapshot_name):
        (status_code, data) = self._get_lightos_snapshot(
            project_name=project_name,
            timeout=self.logical_op_timeout,
            snapshot_name=lightos_snapshot_name)

        if status_code == httpstatus.OK:
            uuid = data.get("UUID")
            if uuid:
                return uuid

        if status_code == httpstatus.NOT_FOUND:
            return None

        msg = ('Unable to fetch UUID of snapshot named %s. status code'
               ' %s data %s' % (lightos_snapshot_name, status_code, data))
        raise exception.VolumeBackendAPIException(message=_(msg))

    def _delete_lightos_snapshot(self, project_name, snapshot_name):
        snapshot_uuid = self._get_lightos_snapshot_uuid(
            project_name, snapshot_name)
        if snapshot_uuid is None:
            LOG.warning(
                "Unable to find lightos snapshot %s project %s for deletion",
                snapshot_name,
                project_name)
            return False

        (status_code, _) = self.cluster.send_cmd(cmd='delete_snapshot',
                                                 project_name=project_name,
                                                 timeout=self.
                                                 logical_op_timeout,
                                                 snapshot_uuid=snapshot_uuid)
        if status_code == httpstatus.OK:
            state = self._wait_for_snapshot_deleted(
                project_name,
                timeout=self.logical_op_timeout,
                snapshot_uuid=snapshot_uuid)
            if state in ('Deleted', 'Deleting', 'UNKNOWN'):
                LOG.debug(
                    "Successfully detected that snapshot %s was deleted.",
                    snapshot_name)
                return True
            LOG.warning("Snapshot %s was not deleted. It is in state %s.",
                        snapshot_name, state)
            return False
        LOG.warning(
            "Request to delete snapshot %s"
            " was rejected with status code %s.",
            snapshot_name,
            status_code)
        return False

    def initialize_connection(self, volume, connector):
        hostnqn = connector.get('nqn')
        found_dsc = connector.get('found_dsc')
        LOG.debug(
            'initialize_connection: connector hostnqn is %s found_dsc %s',
            hostnqn,
            found_dsc)
        if not hostnqn:
            msg = 'Connector (%s) did not contain a hostnqn, aborting' % (
                connector)
            raise exception.VolumeBackendAPIException(message=_(msg))

        if not found_dsc:
            msg = ('Connector (%s) did not indicate a discovery'
                   'client, aborting' % (connector))
            raise exception.VolumeBackendAPIException(message=_(msg))

        lightos_volname = self._lightos_volname(volume)
        project_name = self._get_lightos_project_name(volume)
        success = self.add_volume_acl(project_name, volume, hostnqn)
        if not success or not self._wait_for_volume_acl(
                project_name, lightos_volname, hostnqn, True):
            msg = ('Could not add ACL for hostnqn %s LightOS volume'
                   ' %s, aborting' % (hostnqn, lightos_volname))
            raise exception.VolumeBackendAPIException(message=_(msg))

        props = self._get_connection_properties(project_name, volume)
        return {'driver_volume_type': ('lightos'), 'data': props}

    def terminate_connection(self, volume, connector, **kwargs):
        force = 'force' in kwargs
        hostnqn = connector.get('nqn') if connector else None
        LOG.debug(
            'terminate_connection: force %s kwargs %s hostnqn %s',
            force,
            kwargs,
            hostnqn)

        project_name = self._get_lightos_project_name(volume)

        if not hostnqn:
            if force:
                LOG.debug(
                    'Terminating connection with extreme prejudice for \
                    volume %s',
                    volume)
                self.remove_all_volume_acls(project_name, volume)
                return

            msg = 'Connector (%s) did not return a hostnqn, aborting' % (
                connector)
            raise exception.VolumeBackendAPIException(message=_(msg))

        lightos_volname = self._lightos_volname(volume)
        project_name = self._get_lightos_project_name(volume)
        success = self.remove_volume_acl(project_name, volume, hostnqn)
        if not success or not self._wait_for_volume_acl(
                project_name, lightos_volname, hostnqn, False):
            LOG.warning(
                'Could not remove ACL for hostnqn %s LightOS \
                volume %s, limping along',
                hostnqn,
                lightos_volname)

    def _init_vendor_properties(self):
        # compression is one of the standard properties,
        # no need to add it here
        # see the definition of this function in cinder/volume/driver.py
        properties = {}
        self._set_property(
            properties,
            "lightos:num_replicas",
            "Number of replicas for LightOS volume",
            _(
                "Specifies the number of replicas to create for the \
                LightOS volume."),
            "integer",
            minimum=1,
            maximun=3,
            default=3)

        return properties, 'lightos'

    def backup_use_temp_snapshot(self):
        return False

    def snapshot_revert_use_temp_snapshot(self):
        """Disable the use of a temporary snapshot on revert."""
        return False

    def snapshot_remote_attachable(self):
        """LightOS does not support 'mount a snapshot'"""
        return False
