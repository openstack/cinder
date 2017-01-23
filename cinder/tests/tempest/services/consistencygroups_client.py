# Copyright (C) 2015 EMC Corporation.
# Copyright (C) 2016 Pure Storage, Inc.
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

import time

from oslo_serialization import jsonutils as json
from six.moves import http_client
from tempest import exceptions
from tempest.lib.common import rest_client
from tempest.lib import exceptions as lib_exc


class ConsistencyGroupsClient(rest_client.RestClient):
    """Client class to send CRUD Volume ConsistencyGroup API requests"""

    def __init__(self, auth_provider, service, region, **kwargs):
        super(ConsistencyGroupsClient, self).__init__(
            auth_provider, service, region, **kwargs)

    def create_consistencygroup(self, volume_types, **kwargs):
        """Creates a consistency group."""
        post_body = {'volume_types': volume_types}
        if kwargs.get('availability_zone'):
            post_body['availability_zone'] = kwargs.get('availability_zone')
        if kwargs.get('name'):
            post_body['name'] = kwargs.get('name')
        if kwargs.get('description'):
            post_body['description'] = kwargs.get('description')
        post_body = json.dumps({'consistencygroup': post_body})
        resp, body = self.post('consistencygroups', post_body)
        body = json.loads(body)
        self.expected_success(http_client.ACCEPTED, resp.status)
        return rest_client.ResponseBody(resp, body)

    def create_consistencygroup_from_src(self, **kwargs):
        """Creates a consistency group from source."""
        post_body = {}
        if kwargs.get('cgsnapshot_id'):
            post_body['cgsnapshot_id'] = kwargs.get('cgsnapshot_id')
        if kwargs.get('source_cgid'):
            post_body['source_cgid'] = kwargs.get('source_cgid')
        if kwargs.get('name'):
            post_body['name'] = kwargs.get('name')
        if kwargs.get('description'):
            post_body['description'] = kwargs.get('description')
        post_body = json.dumps({'consistencygroup-from-src': post_body})
        resp, body = self.post('consistencygroups/create_from_src', post_body)
        body = json.loads(body)
        self.expected_success(http_client.ACCEPTED, resp.status)
        return rest_client.ResponseBody(resp, body)

    def delete_consistencygroup(self, cg_id):
        """Delete a consistency group."""
        post_body = {'force': True}
        post_body = json.dumps({'consistencygroup': post_body})
        resp, body = self.post('consistencygroups/%s/delete' % cg_id,
                               post_body)
        self.expected_success(http_client.ACCEPTED, resp.status)
        return rest_client.ResponseBody(resp, body)

    def show_consistencygroup(self, cg_id):
        """Returns the details of a single consistency group."""
        url = "consistencygroups/%s" % str(cg_id)
        resp, body = self.get(url)
        body = json.loads(body)
        self.expected_success(http_client.OK, resp.status)
        return rest_client.ResponseBody(resp, body)

    def list_consistencygroups(self, detail=False):
        """Information for all the tenant's consistency groups."""
        url = "consistencygroups"
        if detail:
            url += "/detail"
        resp, body = self.get(url)
        body = json.loads(body)
        self.expected_success(http_client.OK, resp.status)
        return rest_client.ResponseBody(resp, body)

    def create_cgsnapshot(self, consistencygroup_id, **kwargs):
        """Creates a consistency group snapshot."""
        post_body = {'consistencygroup_id': consistencygroup_id}
        if kwargs.get('name'):
            post_body['name'] = kwargs.get('name')
        if kwargs.get('description'):
            post_body['description'] = kwargs.get('description')
        post_body = json.dumps({'cgsnapshot': post_body})
        resp, body = self.post('cgsnapshots', post_body)
        body = json.loads(body)
        self.expected_success(http_client.ACCEPTED, resp.status)
        return rest_client.ResponseBody(resp, body)

    def delete_cgsnapshot(self, cgsnapshot_id):
        """Delete a consistency group snapshot."""
        resp, body = self.delete('cgsnapshots/%s' % (str(cgsnapshot_id)))
        self.expected_success(http_client.ACCEPTED, resp.status)
        return rest_client.ResponseBody(resp, body)

    def show_cgsnapshot(self, cgsnapshot_id):
        """Returns the details of a single consistency group snapshot."""
        url = "cgsnapshots/%s" % str(cgsnapshot_id)
        resp, body = self.get(url)
        body = json.loads(body)
        self.expected_success(http_client.OK, resp.status)
        return rest_client.ResponseBody(resp, body)

    def list_cgsnapshots(self, detail=False):
        """Information for all the tenant's consistency group snapshotss."""
        url = "cgsnapshots"
        if detail:
            url += "/detail"
        resp, body = self.get(url)
        body = json.loads(body)
        self.expected_success(http_client.OK, resp.status)
        return rest_client.ResponseBody(resp, body)

    def wait_for_consistencygroup_status(self, cg_id, status):
        """Waits for a consistency group to reach a given status."""
        body = self.show_consistencygroup(cg_id)['consistencygroup']
        cg_status = body['status']
        start = int(time.time())

        while cg_status != status:
            time.sleep(self.build_interval)
            body = self.show_consistencygroup(cg_id)['consistencygroup']
            cg_status = body['status']
            if cg_status == 'error':
                raise exceptions.ConsistencyGroupException(cg_id=cg_id)

            if int(time.time()) - start >= self.build_timeout:
                message = ('Consistency group %s failed to reach %s status '
                           '(current %s) within the required time (%s s).' %
                           (cg_id, status, cg_status,
                            self.build_timeout))
                raise exceptions.TimeoutException(message)

    def wait_for_consistencygroup_deletion(self, cg_id):
        """Waits for consistency group deletion"""
        start_time = int(time.time())
        while True:
            try:
                self.show_consistencygroup(cg_id)
            except lib_exc.NotFound:
                return
            if int(time.time()) - start_time >= self.build_timeout:
                raise exceptions.TimeoutException
            time.sleep(self.build_interval)

    def wait_for_cgsnapshot_status(self, cgsnapshot_id, status):
        """Waits for a consistency group snapshot to reach a given status."""
        body = self.show_cgsnapshot(cgsnapshot_id)['cgsnapshot']
        cgsnapshot_status = body['status']
        start = int(time.time())

        while cgsnapshot_status != status:
            time.sleep(self.build_interval)
            body = self.show_cgsnapshot(cgsnapshot_id)['cgsnapshot']
            cgsnapshot_status = body['status']
            if cgsnapshot_status == 'error':
                raise exceptions.ConsistencyGroupSnapshotException(
                    cgsnapshot_id=cgsnapshot_id)

            if int(time.time()) - start >= self.build_timeout:
                message = ('Consistency group snapshot %s failed to reach '
                           '%s status (current %s) within the required time '
                           '(%s s).' %
                           (cgsnapshot_id, status, cgsnapshot_status,
                            self.build_timeout))
                raise exceptions.TimeoutException(message)

    def wait_for_cgsnapshot_deletion(self, cgsnapshot_id):
        """Waits for consistency group snapshot deletion"""
        start_time = int(time.time())
        while True:
            try:
                self.show_cgsnapshot(cgsnapshot_id)
            except lib_exc.NotFound:
                return
            if int(time.time()) - start_time >= self.build_timeout:
                raise exceptions.TimeoutException
            time.sleep(self.build_interval)
