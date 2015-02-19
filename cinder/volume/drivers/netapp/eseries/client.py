# Copyright (c) 2014 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2015 Alex Meade.  All Rights Reserved.
# Copyright (c) 2015 Rushil Chugh.  All Rights Reserved.
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
Client classes for web services.
"""

import copy
import json

from oslo_log import log as logging
import requests
import six.moves.urllib.parse as urlparse

from cinder import exception
from cinder.i18n import _, _LE


LOG = logging.getLogger(__name__)


class WebserviceClient(object):
    """Base client for e-series web services."""

    def __init__(self, scheme, host, port, service_path, username,
                 password, **kwargs):
        self._validate_params(scheme, host, port)
        self._create_endpoint(scheme, host, port, service_path)
        self._username = username
        self._password = password
        self._init_connection()

    def _validate_params(self, scheme, host, port):
        """Does some basic validation for web service params."""
        if host is None or port is None or scheme is None:
            msg = _("One of the required inputs from host, port"
                    " or scheme not found.")
            raise exception.InvalidInput(reason=msg)
        if scheme not in ('http', 'https'):
            raise exception.InvalidInput(reason=_("Invalid transport type."))

    def _create_endpoint(self, scheme, host, port, service_path):
        """Creates end point url for the service."""
        netloc = '%s:%s' % (host, port)
        self._endpoint = urlparse.urlunparse((scheme, netloc, service_path,
                                              None, None, None))

    def _init_connection(self):
        """Do client specific set up for session and connection pooling."""
        self.conn = requests.Session()
        if self._username and self._password:
            self.conn.auth = (self._username, self._password)

    def invoke_service(self, method='GET', url=None, params=None, data=None,
                       headers=None, timeout=None, verify=False):
        url = url or self._endpoint
        try:
            response = self.conn.request(method, url, params, data,
                                         headers=headers, timeout=timeout,
                                         verify=verify)
        # Catching error conditions other than the perceived ones.
        # Helps propagating only known exceptions back to the caller.
        except Exception as e:
            LOG.exception(_LE("Unexpected error while invoking web service."
                              " Error - %s."), e)
            raise exception.NetAppDriverException(
                _("Invoking web service failed."))
        self._eval_response(response)
        return response

    def _eval_response(self, response):
        """Evaluates response before passing result to invoker."""
        pass


class RestClient(WebserviceClient):
    """REST client specific to e-series storage service."""

    def __init__(self, scheme, host, port, service_path, username,
                 password, **kwargs):
        super(RestClient, self).__init__(scheme, host, port, service_path,
                                         username, password, **kwargs)
        kwargs = kwargs or {}
        self._system_id = kwargs.get('system_id')
        self._content_type = kwargs.get('content_type') or 'json'

    def set_system_id(self, system_id):
        """Set the storage system id."""
        self._system_id = system_id

    def get_system_id(self):
        """Get the storage system id."""
        return getattr(self, '_system_id', None)

    def _get_resource_url(self, path, use_system=True, **kwargs):
        """Creates end point url for rest service."""
        kwargs = kwargs or {}
        if use_system:
            if not self._system_id:
                raise exception.NotFound(_('Storage system id not set.'))
            kwargs['system-id'] = self._system_id
        path = path.format(**kwargs)
        if not self._endpoint.endswith('/'):
            self._endpoint = '%s/' % self._endpoint
        return urlparse.urljoin(self._endpoint, path.lstrip('/'))

    def _invoke(self, method, path, data=None, use_system=True,
                timeout=None, verify=False, **kwargs):
        """Invokes end point for resource on path."""
        scrubbed_data = copy.deepcopy(data)
        if scrubbed_data:
            if 'password' in scrubbed_data:
                scrubbed_data['password'] = "****"
            if 'storedPassword' in scrubbed_data:
                scrubbed_data['storedPassword'] = "****"

        params = {'m': method, 'p': path, 'd': scrubbed_data,
                  'sys': use_system, 't': timeout, 'v': verify, 'k': kwargs}
        LOG.debug("Invoking rest with method: %(m)s, path: %(p)s,"
                  " data: %(d)s, use_system: %(sys)s, timeout: %(t)s,"
                  " verify: %(v)s, kwargs: %(k)s." % (params))
        url = self._get_resource_url(path, use_system, **kwargs)
        if self._content_type == 'json':
            headers = {'Accept': 'application/json',
                       'Content-Type': 'application/json'}
            data = json.dumps(data) if data else None
            res = self.invoke_service(method, url, data=data,
                                      headers=headers,
                                      timeout=timeout, verify=verify)
            return res.json() if res.text else None
        else:
            raise exception.NetAppDriverException(
                _("Content type not supported."))

    def _eval_response(self, response):
        """Evaluates response before passing result to invoker."""
        super(RestClient, self)._eval_response(response)
        status_code = int(response.status_code)
        # codes >= 300 are not ok and to be treated as errors
        if status_code >= 300:
            # Response code 422 returns error code and message
            if status_code == 422:
                msg = _("Response error - %s.") % response.text
            else:
                msg = _("Response error code - %s.") % status_code
            raise exception.NetAppDriverException(msg)

    def create_volume(self, pool, label, size, unit='gb', seg_size=0):
        """Creates volume on array."""
        path = "/storage-systems/{system-id}/volumes"
        data = {'poolId': pool, 'name': label, 'sizeUnit': unit,
                'size': int(size), 'segSize': seg_size}
        return self._invoke('POST', path, data)

    def delete_volume(self, object_id):
        """Deletes given volume from array."""
        path = "/storage-systems/{system-id}/volumes/{object-id}"
        return self._invoke('DELETE', path, **{'object-id': object_id})

    def list_volumes(self):
        """Lists all volumes in storage array."""
        path = "/storage-systems/{system-id}/volumes"
        return self._invoke('GET', path)

    def list_volume(self, object_id):
        """List given volume from array."""
        path = "/storage-systems/{system-id}/volumes/{object-id}"
        return self._invoke('GET', path, **{'object-id': object_id})

    def update_volume(self, object_id, label):
        """Renames given volume in array."""
        path = "/storage-systems/{system-id}/volumes/{object-id}"
        data = {'name': label}
        return self._invoke('POST', path, data, **{'object-id': object_id})

    def get_volume_mappings(self):
        """Creates volume mapping on array."""
        path = "/storage-systems/{system-id}/volume-mappings"
        return self._invoke('GET', path)

    def create_volume_mapping(self, object_id, target_id, lun):
        """Creates volume mapping on array."""
        path = "/storage-systems/{system-id}/volume-mappings"
        data = {'mappableObjectId': object_id, 'targetId': target_id,
                'lun': lun}
        return self._invoke('POST', path, data)

    def delete_volume_mapping(self, map_object_id):
        """Deletes given volume mapping from array."""
        path = "/storage-systems/{system-id}/volume-mappings/{object-id}"
        return self._invoke('DELETE', path, **{'object-id': map_object_id})

    def list_hardware_inventory(self):
        """Lists objects in the hardware inventory."""
        path = "/storage-systems/{system-id}/hardware-inventory"
        return self._invoke('GET', path)

    def list_hosts(self):
        """Lists host objects in the system."""
        path = "/storage-systems/{system-id}/hosts"
        return self._invoke('GET', path)

    def create_host(self, label, host_type, ports=None, group_id=None):
        """Creates host on array."""
        path = "/storage-systems/{system-id}/hosts"
        data = {'name': label, 'hostType': host_type}
        data.setdefault('groupId', group_id) if group_id else None
        data.setdefault('ports', ports) if ports else None
        return self._invoke('POST', path, data)

    def create_host_with_port(self, label, host_type, port_id,
                              port_label, port_type='iscsi', group_id=None):
        """Creates host on array with given port information."""
        port = {'type': port_type, 'port': port_id, 'label': port_label}
        return self.create_host(label, host_type, [port], group_id)

    def update_host_type(self, host_ref, host_type):
        """Updates host type for a given host."""
        path = "/storage-systems/{system-id}/hosts/{object-id}"
        data = {'hostType': host_type}
        return self._invoke('POST', path, data, **{'object-id': host_ref})

    def list_host_types(self):
        """Lists host types in storage system."""
        path = "/storage-systems/{system-id}/host-types"
        return self._invoke('GET', path)

    def list_snapshot_groups(self):
        """Lists snapshot groups."""
        path = "/storage-systems/{system-id}/snapshot-groups"
        return self._invoke('GET', path)

    def create_snapshot_group(self, label, object_id, storage_pool_id,
                              repo_percent=99, warn_thres=99, auto_del_limit=0,
                              full_policy='failbasewrites'):
        """Creates snapshot group on array."""
        path = "/storage-systems/{system-id}/snapshot-groups"
        data = {'baseMappableObjectId': object_id, 'name': label,
                'storagePoolId': storage_pool_id,
                'repositoryPercentage': repo_percent,
                'warningThreshold': warn_thres,
                'autoDeleteLimit': auto_del_limit, 'fullPolicy': full_policy}
        return self._invoke('POST', path, data)

    def delete_snapshot_group(self, object_id):
        """Deletes given snapshot group from array."""
        path = "/storage-systems/{system-id}/snapshot-groups/{object-id}"
        return self._invoke('DELETE', path, **{'object-id': object_id})

    def create_snapshot_image(self, group_id):
        """Creates snapshot image in snapshot group."""
        path = "/storage-systems/{system-id}/snapshot-images"
        data = {'groupId': group_id}
        return self._invoke('POST', path, data)

    def delete_snapshot_image(self, object_id):
        """Deletes given snapshot image in snapshot group."""
        path = "/storage-systems/{system-id}/snapshot-images/{object-id}"
        return self._invoke('DELETE', path, **{'object-id': object_id})

    def list_snapshot_images(self):
        """Lists snapshot images."""
        path = "/storage-systems/{system-id}/snapshot-images"
        return self._invoke('GET', path)

    def create_snapshot_volume(self, image_id, label, base_object_id,
                               storage_pool_id,
                               repo_percent=99, full_thres=99,
                               view_mode='readOnly'):
        """Creates snapshot volume."""
        path = "/storage-systems/{system-id}/snapshot-volumes"
        data = {'snapshotImageId': image_id, 'fullThreshold': full_thres,
                'storagePoolId': storage_pool_id,
                'name': label, 'viewMode': view_mode,
                'repositoryPercentage': repo_percent,
                'baseMappableObjectId': base_object_id,
                'repositoryPoolId': storage_pool_id}
        return self._invoke('POST', path, data)

    def delete_snapshot_volume(self, object_id):
        """Deletes given snapshot volume."""
        path = "/storage-systems/{system-id}/snapshot-volumes/{object-id}"
        return self._invoke('DELETE', path, **{'object-id': object_id})

    def list_storage_pools(self):
        """Lists storage pools in the array."""
        path = "/storage-systems/{system-id}/storage-pools"
        return self._invoke('GET', path)

    def list_drives(self):
        """Lists drives in the array."""
        path = "/storage-systems/{system-id}/drives"
        return self._invoke('GET', path)

    def list_storage_systems(self):
        """Lists managed storage systems registered with web service."""
        path = "/storage-systems"
        return self._invoke('GET', path, use_system=False)

    def list_storage_system(self):
        """List current storage system registered with web service."""
        path = "/storage-systems/{system-id}"
        return self._invoke('GET', path)

    def register_storage_system(self, controller_addresses, password=None,
                                wwn=None):
        """Registers storage system with web service."""
        path = "/storage-systems"
        data = {'controllerAddresses': controller_addresses}
        data.setdefault('wwn', wwn) if wwn else None
        data.setdefault('password', password) if password else None
        return self._invoke('POST', path, data, use_system=False)

    def update_stored_system_password(self, password):
        """Update array password stored on web service."""
        path = "/storage-systems/{system-id}"
        data = {'storedPassword': password}
        return self._invoke('POST', path, data)

    def create_volume_copy_job(self, src_id, tgt_id, priority='priority4',
                               tgt_wrt_protected='true'):
        """Creates a volume copy job."""
        path = "/storage-systems/{system-id}/volume-copy-jobs"
        data = {'sourceId': src_id, 'targetId': tgt_id,
                'copyPriority': priority,
                'targetWriteProtected': tgt_wrt_protected}
        return self._invoke('POST', path, data)

    def control_volume_copy_job(self, obj_id, control='start'):
        """Controls a volume copy job."""
        path = ("/storage-systems/{system-id}/volume-copy-jobs-control"
                "/{object-id}?control={String}")
        return self._invoke('PUT', path, **{'object-id': obj_id,
                                            'String': control})

    def list_vol_copy_job(self, object_id):
        """List volume copy job."""
        path = "/storage-systems/{system-id}/volume-copy-jobs/{object-id}"
        return self._invoke('GET', path, **{'object-id': object_id})

    def delete_vol_copy_job(self, object_id):
        """Delete volume copy job."""
        path = "/storage-systems/{system-id}/volume-copy-jobs/{object-id}"
        return self._invoke('DELETE', path, **{'object-id': object_id})
