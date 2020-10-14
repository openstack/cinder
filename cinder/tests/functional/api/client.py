#    Copyright (c) 2011 Justin Santa Barbara
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

from http import client as http_client
import urllib

from oslo_serialization import jsonutils
from oslo_utils import netutils
import requests

from cinder.i18n import _
from cinder.tests.unit import fake_constants as fake


class OpenStackApiException(Exception):
    message = 'Unspecified error'

    def __init__(self, response=None, msg=None):
        self.response = response
        # Give chance to override default message
        if msg:
            self.message = msg

        if response:
            self.message = _(
                '%(message)s\nStatus Code: %(_status)s\nBody: %(_body)s') % {
                '_status': response.status_code, '_body': response.text,
                'message': self.message}

        super(OpenStackApiException, self).__init__(self.message)


class OpenStackApiException401(OpenStackApiException):
    message = _("401 Unauthorized Error")


class OpenStackApiException404(OpenStackApiException):
    message = _("404 Not Found Error")


class OpenStackApiException413(OpenStackApiException):
    message = _("413 Request entity too large")


class OpenStackApiException400(OpenStackApiException):
    message = _("400 Bad Request")


class OpenStackApiException403(OpenStackApiException):
    message = _("403 Forbidden")


class OpenStackApiException500(OpenStackApiException):
    message = _("500 Internal Server Error")


class TestOpenStackClient(object):
    """Simple OpenStack API Client.

    This is a really basic OpenStack API client that is under our control,
    so we can make changes / insert hooks for testing

    """

    def __init__(self, auth_user, auth_key, auth_uri, api_version=None):
        super(TestOpenStackClient, self).__init__()
        self.auth_result = None
        self.auth_user = auth_user
        self.auth_key = auth_key
        self.auth_uri = auth_uri
        # default project_id
        self.project_id = fake.PROJECT_ID
        self.api_version = api_version

    def request(self, url, method='GET', body=None, headers=None,
                ssl_verify=True, stream=False):
        _headers = {'Content-Type': 'application/json'}
        _headers.update(headers or {})

        parsed_url = urllib.parse.urlparse(url)
        port = parsed_url.port
        hostname = parsed_url.hostname
        scheme = parsed_url.scheme

        if netutils.is_valid_ipv6(hostname):
            hostname = "[%s]" % hostname

        relative_url = parsed_url.path
        if parsed_url.query:
            relative_url = relative_url + "?" + parsed_url.query

        if port:
            _url = "%s://%s:%d%s" % (scheme, hostname, int(port), relative_url)
        else:
            _url = "%s://%s%s" % (scheme, hostname, relative_url)

        response = requests.request(method, _url, data=body, headers=_headers,
                                    verify=ssl_verify, stream=stream)

        return response

    def _authenticate(self, reauthenticate=False):
        if self.auth_result and not reauthenticate:
            return self.auth_result

        auth_uri = self.auth_uri
        headers = {'X-Auth-User': self.auth_user,
                   'X-Auth-Key': self.auth_key,
                   'X-Auth-Project-Id': self.project_id}
        response = self.request(auth_uri,
                                headers=headers)

        http_status = response.status_code

        if http_status == http_client.UNAUTHORIZED:
            raise OpenStackApiException401(response=response)

        self.auth_result = response.headers
        return self.auth_result

    def update_project(self, new_project_id):
        self.project_id = new_project_id
        self._authenticate(True)

    def api_request(self, relative_uri, check_response_status=None,
                    strip_version=False, base_url=True, **kwargs):
        auth_result = self._authenticate()

        if base_url:
            # NOTE(justinsb): httplib 'helpfully' converts headers to lower
            # case
            base_uri = auth_result['x-server-management-url']
        else:
            base_uri = self.auth_uri

        if strip_version:
            # cut out version number and tenant_id
            base_uri = '/'.join(base_uri.split('/', 3)[:-1])

        full_uri = '%s/%s' % (base_uri, relative_uri)

        headers = kwargs.setdefault('headers', {})
        headers['X-Auth-Token'] = auth_result['x-auth-token']

        if self.api_version:
            headers['OpenStack-API-Version'] = 'volume ' + self.api_version

        response = self.request(full_uri, **kwargs)

        http_status = response.status_code
        if check_response_status:
            if http_status not in check_response_status:
                message = None
                try:
                    exc = globals()["OpenStackApiException%s" % http_status]
                except KeyError:
                    exc = OpenStackApiException
                    message = _("Unexpected status code")
                raise exc(response, message)

        return response

    def _decode_json(self, response):
        body = response.text
        if body:
            return jsonutils.loads(body)
        else:
            return ""

    def api_get(self, relative_uri, base_url=True, **kwargs):
        kwargs.setdefault('check_response_status', [http_client.OK])
        response = self.api_request(relative_uri, base_url=base_url, **kwargs)
        return self._decode_json(response)

    def api_post(self, relative_uri, body, base_url=True, **kwargs):
        kwargs['method'] = 'POST'
        if body:
            headers = kwargs.setdefault('headers', {})
            headers['Content-Type'] = 'application/json'
            kwargs['body'] = jsonutils.dumps(body)

        kwargs.setdefault('check_response_status', [http_client.OK,
                                                    http_client.ACCEPTED])
        response = self.api_request(relative_uri, base_url=base_url, **kwargs)
        return self._decode_json(response)

    def api_put(self, relative_uri, body, base_url=True, **kwargs):
        kwargs['method'] = 'PUT'
        if body:
            headers = kwargs.setdefault('headers', {})
            headers['Content-Type'] = 'application/json'
            kwargs['body'] = jsonutils.dumps(body)

        kwargs.setdefault('check_response_status', [http_client.OK,
                                                    http_client.ACCEPTED,
                                                    http_client.NO_CONTENT])
        response = self.api_request(relative_uri, base_url=base_url, **kwargs)
        return self._decode_json(response)

    def api_delete(self, relative_uri, base_url=True, **kwargs):
        kwargs['method'] = 'DELETE'
        kwargs.setdefault('check_response_status', [http_client.OK,
                                                    http_client.ACCEPTED,
                                                    http_client.NO_CONTENT])
        return self.api_request(relative_uri, base_url=base_url, **kwargs)

    def get_volume(self, volume_id):
        return self.api_get('/volumes/%s' % volume_id)['volume']

    def get_volumes(self, detail=True):
        rel_url = '/volumes/detail' if detail else '/volumes'
        return self.api_get(rel_url)['volumes']

    def post_volume(self, volume):
        return self.api_post('/volumes', volume)['volume']

    def delete_volume(self, volume_id):
        return self.api_delete('/volumes/%s' % volume_id)

    def put_volume(self, volume_id, volume):
        return self.api_put('/volumes/%s' % volume_id, volume)['volume']

    def get_snapshot(self, snapshot_id):
        return self.api_get('/snapshots/%s' % snapshot_id)['snapshot']

    def post_snapshot(self, snapshot):
        return self.api_post('/snapshots', snapshot)['snapshot']

    def delete_snapshot(self, snapshot_id):
        return self.api_delete('/snapshots/%s' % snapshot_id)

    def quota_set(self, project_id, quota_update):
        return self.api_put(
            'os-quota-sets/%s' % project_id,
            {'quota_set': quota_update})['quota_set']

    def quota_get(self, project_id, usage=True):

        return self.api_get('os-quota-sets/%s?usage=%s'
                            % (project_id, usage))['quota_set']

    def create_type(self, type_name, extra_specs=None):
        type = {"volume_type": {"name": type_name}}
        if extra_specs:
            type['extra_specs'] = extra_specs

        return self.api_post('/types', type)['volume_type']

    def delete_type(self, type_id):
        return self.api_delete('/types/%s' % type_id)

    def get_type(self, type_id):
        return self.api_get('/types/%s' % type_id)['volume_type']

    def create_volume_type_extra_specs(self, volume_type_id, extra_specs):
        extra_specs = {"extra_specs": extra_specs}
        url = "/types/%s/extra_specs" % volume_type_id
        return self.api_post(url, extra_specs)['extra_specs']

    def create_group_type_specs(self, grp_type_id, group_specs):
        group_specs = {"group_specs": group_specs}
        url = "/group_types/%s/group_specs" % grp_type_id
        return self.api_post(url, group_specs)['group_specs']

    def create_group_type(self, type_name, grp_specs=None):
        grp_type = {"group_type": {"name": type_name}}
        if grp_specs:
            grp_type['group_specs'] = grp_specs

        return self.api_post('/group_types', grp_type)['group_type']

    def delete_group_type(self, group_type_id):
        return self.api_delete('/group_types/%s' % group_type_id)

    def get_group_type(self, grp_type_id):
        return self.api_get('/group_types/%s' % grp_type_id)['group_type']

    def get_group(self, group_id):
        return self.api_get('/groups/%s' % group_id)['group']

    def get_groups(self, detail=True):
        rel_url = '/groups/detail' if detail else '/groups'
        return self.api_get(rel_url)['groups']

    def post_group(self, group):
        return self.api_post('/groups', group)['group']

    def post_group_from_src(self, group):
        return self.api_post('/groups/action', group)['group']

    def delete_group(self, group_id, params):
        return self.api_post('/groups/%s/action' % group_id, params)

    def reset_group(self, group_id, params):
        return self.api_post('/groups/%s/action' % group_id, params)

    def put_group(self, group_id, group):
        return self.api_put('/groups/%s' % group_id, group)['group']

    def get_group_snapshot(self, group_snapshot_id):
        return self.api_get('/group_snapshots/%s' % group_snapshot_id)[
            'group_snapshot']

    def get_group_snapshots(self, detail=True):
        rel_url = '/group_snapshots/detail' if detail else '/group_snapshots'
        return self.api_get(rel_url)['group_snapshots']

    def post_group_snapshot(self, group_snapshot):
        return self.api_post('/group_snapshots', group_snapshot)[
            'group_snapshot']

    def delete_group_snapshot(self, group_snapshot_id):
        return self.api_delete('/group_snapshots/%s' % group_snapshot_id)

    def reset_group_snapshot(self, group_snapshot_id, params):
        return self.api_post('/group_snapshots/%s/action' % group_snapshot_id,
                             params)

    def enable_group_replication(self, group_id, params):
        return self.api_post('/groups/%s/action' % group_id, params)

    def disable_group_replication(self, group_id, params):
        return self.api_post('/groups/%s/action' % group_id, params)

    def failover_group_replication(self, group_id, params):
        return self.api_post('/groups/%s/action' % group_id, params)

    def list_group_replication_targets(self, group_id, params):
        return self.api_post('/groups/%s/action' % group_id, params)

    def set_default_type(self, project_id, params):
        body = {"default_type": params}
        return self.api_put('default-types/%s' % project_id, body,
                            base_url=False)['default_type']

    def get_default_type(self, project_id=None):
        if project_id:
            return self.api_get('default-types/%s' % project_id,
                                base_url=False)['default_type']
        return self.api_get('default-types',
                            base_url=False)['default_types']

    def unset_default_type(self, project_id):
        self.api_delete('default-types/%s' % project_id,
                        base_url=False)
