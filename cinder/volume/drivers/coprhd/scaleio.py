# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""Driver for EMC CoprHD ScaleIO volumes."""

from oslo_config import cfg
from oslo_log import log as logging
import requests
import six
from six.moves import http_client
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.coprhd import common as coprhd_common
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

scaleio_opts = [
    cfg.StrOpt('coprhd_scaleio_rest_gateway_host',
               default='None',
               help='Rest Gateway IP or FQDN for Scaleio'),
    cfg.PortOpt('coprhd_scaleio_rest_gateway_port',
                default=4984,
                help='Rest Gateway Port for Scaleio'),
    cfg.StrOpt('coprhd_scaleio_rest_server_username',
               default=None,
               help='Username for Rest Gateway'),
    cfg.StrOpt('coprhd_scaleio_rest_server_password',
               default=None,
               help='Rest Gateway Password',
               secret=True),
    cfg.BoolOpt('scaleio_verify_server_certificate',
                default=False,
                help='verify server certificate'),
    cfg.StrOpt('scaleio_server_certificate_path',
               default=None,
               help='Server certificate path')
]

CONF = cfg.CONF
CONF.register_opts(scaleio_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class EMCCoprHDScaleIODriver(driver.VolumeDriver):
    """CoprHD ScaleIO Driver."""
    VERSION = "3.0.0.0"
    server_token = None

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "EMC_CoprHD_CI"

    def __init__(self, *args, **kwargs):
        super(EMCCoprHDScaleIODriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(scaleio_opts)
        self.common = self._get_common_driver()

    def _get_common_driver(self):
        return coprhd_common.EMCCoprHDDriverCommon(
            protocol='scaleio',
            default_backend_name=self.__class__.__name__,
            configuration=self.configuration)

    def check_for_setup_error(self):
        self.common.check_for_setup_error()
        if (self.configuration.scaleio_verify_server_certificate is True and
                self.configuration.scaleio_server_certificate_path is None):
            message = _("scaleio_verify_server_certificate is True but"
                        " scaleio_server_certificate_path is not provided"
                        " in cinder configuration")
            raise exception.VolumeBackendAPIException(data=message)

    def create_volume(self, volume):
        """Creates a Volume."""
        self.common.create_volume(volume, self, True)
        self.common.set_volume_tags(volume, ['_obj_volume_type'], True)
        vol_size = self._update_volume_size(int(volume.size))
        return {'size': vol_size}

    def _update_volume_size(self, vol_size):
        """update the openstack volume size."""
        default_size = 8
        if (vol_size % default_size) != 0:
            return (vol_size / default_size) * default_size + default_size
        else:
            return vol_size

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned Volume."""
        self.common.create_cloned_volume(volume, src_vref, True)
        self.common.set_volume_tags(volume, ['_obj_volume_type'], True)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.common.create_volume_from_snapshot(snapshot, volume, True)
        self.common.set_volume_tags(volume, ['_obj_volume_type'], True)

    def extend_volume(self, volume, new_size):
        """expands the size of the volume."""
        self.common.expand_volume(volume, new_size)

    def delete_volume(self, volume):
        """Deletes an volume."""
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.common.create_snapshot(snapshot, True)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common.delete_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume, connector=None):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver exntry point to remove an export for a volume."""
        pass

    def create_group(self, context, group):
        """Creates a group."""
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self.common.create_consistencygroup(context, group, True)

        # If the group is not consistency group snapshot enabled, then
        # we shall rely on generic volume group implementation
        raise NotImplementedError()

    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        """Updates volumes in group."""
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self.common.update_consistencygroup(group, add_volumes,
                                                       remove_volumes)

        # If the group is not consistency group snapshot enabled, then
        # we shall rely on generic volume group implementation
        raise NotImplementedError()

    def create_group_from_src(self, ctxt, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source."""
        if volume_utils.is_group_a_cg_snapshot_type(group):
            message = _("create group from source is not supported "
                        "for CoprHD if the group type supports "
                        "consistent group snapshot.")
            raise exception.VolumeBackendAPIException(data=message)
        else:
            raise NotImplementedError()

    def delete_group(self, context, group, volumes):
        """Deletes a group."""
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self.common.delete_consistencygroup(context, group,
                                                       volumes, True)

        # If the group is not consistency group snapshot enabled, then
        # we shall rely on generic volume group implementation
        raise NotImplementedError()

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group snapshot."""
        if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            LOG.debug("creating a group snapshot")
            return self.common.create_cgsnapshot(group_snapshot, snapshots,
                                                 True)

        # If the group is not consistency group snapshot enabled, then
        # we shall rely on generic volume group implementation
        raise NotImplementedError()

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group snapshot."""
        if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self.common.delete_cgsnapshot(group_snapshot, snapshots,
                                                 True)

        # If the group is not consistency group snapshot enabled, then
        # we shall rely on generic volume group implementation
        raise NotImplementedError()

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""

        volname = self.common._get_resource_name(volume,
                                                 coprhd_common.MAX_SIO_LEN,
                                                 True)

        properties = {}
        properties['scaleIO_volname'] = volname
        properties['scaleIO_volume_id'] = volume.provider_id
        properties['hostIP'] = connector['ip']
        properties[
            'serverIP'] = self.configuration.coprhd_scaleio_rest_gateway_host
        properties[
            'serverPort'] = self.configuration.coprhd_scaleio_rest_gateway_port
        properties[
            'serverUsername'] = (
            self.configuration.coprhd_scaleio_rest_server_username)
        properties[
            'serverPassword'] = (
            self.configuration.coprhd_scaleio_rest_server_password)
        properties['iopsLimit'] = None
        properties['bandwidthLimit'] = None
        properties['serverToken'] = self.server_token

        initiator_ports = []
        initiator_port = self._get_client_id(properties['serverIP'],
                                             properties['serverPort'],
                                             properties['serverUsername'],
                                             properties['serverPassword'],
                                             properties['hostIP'])
        initiator_ports.append(initiator_port)

        properties['serverToken'] = self.server_token
        self.common.initialize_connection(volume,
                                          'scaleio',
                                          initiator_ports,
                                          connector['host'])

        dictobj = {
            'driver_volume_type': 'scaleio',
            'data': properties,
        }

        return dictobj

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""

        volname = volume.display_name
        properties = {}
        properties['scaleIO_volname'] = volname
        properties['scaleIO_volume_id'] = volume.provider_id
        properties['hostIP'] = connector['ip']
        properties[
            'serverIP'] = self.configuration.coprhd_scaleio_rest_gateway_host
        properties[
            'serverPort'] = self.configuration.coprhd_scaleio_rest_gateway_port
        properties[
            'serverUsername'] = (
            self.configuration.coprhd_scaleio_rest_server_username)
        properties[
            'serverPassword'] = (
            self.configuration.coprhd_scaleio_rest_server_password)
        properties['serverToken'] = self.server_token

        initiator_port = self._get_client_id(properties['serverIP'],
                                             properties['serverPort'],
                                             properties['serverUsername'],
                                             properties['serverPassword'],
                                             properties['hostIP'])
        init_ports = []
        init_ports.append(initiator_port)
        self.common.terminate_connection(volume,
                                         'scaleio',
                                         init_ports,
                                         connector['host'])

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from virtual pool/virtual array."""
        LOG.debug("Updating volume stats")
        self._stats = self.common.update_volume_stats()

    def _get_client_id(self, server_ip, server_port, server_username,
                       server_password, sdc_ip):
        ip_encoded = urllib.parse.quote(sdc_ip, '')
        ip_double_encoded = urllib.parse.quote(ip_encoded, '')

        request = ("https://%s:%s/api/types/Sdc/instances/getByIp::%s/" %
                   (server_ip, six.text_type(server_port), ip_double_encoded))

        LOG.info("ScaleIO get client id by ip request: %s", request)

        if self.configuration.scaleio_verify_server_certificate:
            verify_cert = self.configuration.scaleio_server_certificate_path
        else:
            verify_cert = False

        r = requests.get(
            request, auth=(server_username, self.server_token),
            verify=verify_cert)
        r = self._check_response(
            r, request, server_ip, server_port,
            server_username, server_password)

        sdc_id = r.json()
        if not sdc_id:
            msg = (_("Client with ip %s wasn't found ") % sdc_ip)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if r.status_code != http_client.OK and "errorCode" in sdc_id:
            msg = (_("Error getting sdc id from ip %(sdc_ip)s:"
                     " %(sdc_id_message)s") % {'sdc_ip': sdc_ip,
                                               'sdc_id_message': sdc_id[
                                                   'message']})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        LOG.info("ScaleIO sdc id is %s", sdc_id)
        return sdc_id

    def _check_response(self, response, request,
                        server_ip, server_port,
                        server_username, server_password):
        if (response.status_code == http_client.UNAUTHORIZED) or (
                response.status_code == http_client.FORBIDDEN):
            LOG.info(
                "Token is invalid, going to re-login and get a new one")

            login_request = ("https://%s:%s/api/login" %
                             (server_ip, six.text_type(server_port)))
            if self.configuration.scaleio_verify_server_certificate:
                verify_cert = (
                    self.configuration.scaleio_server_certificate_path)
            else:
                verify_cert = False

            r = requests.get(
                login_request, auth=(server_username, server_password),
                verify=verify_cert)

            token = r.json()
            self.server_token = token
            # repeat request with valid token
            LOG.info("Going to perform request again %s with valid token",
                     request)
            res = requests.get(
                request, auth=(server_username, self.server_token),
                verify=verify_cert)
            return res
        return response

    def retype(self, ctxt, volume, new_type, diff, host):
        """Change the volume type."""
        return self.common.retype(ctxt, volume, new_type, diff, host)
