# Copyright 2014 IBM Corp.
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
Tests for volume replication API code.
"""

import json

import mock
from oslo_config import cfg
import webob

from cinder import context
from cinder import test
from cinder.tests.api import fakes
from cinder.tests import utils as tests_utils

CONF = cfg.CONF


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


class VolumeReplicationAPITestCase(test.TestCase):
    """Test Cases for replication API."""

    def setUp(self):
        super(VolumeReplicationAPITestCase, self).setUp()
        self.ctxt = context.RequestContext('admin', 'fake', True)
        self.volume_params = {
            'host': CONF.host,
            'size': 1}

    def _get_resp(self, operation, volume_id, xml=False):
        """Helper for a replication action req for the specified volume_id."""
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume_id)
        req.method = 'POST'
        if xml:
            body = '<os-%s-replica/>' % operation
            req.headers['Content-Type'] = 'application/xml'
            req.headers['Accept'] = 'application/xml'
            req.body = body
        else:
            body = {'os-%s-replica' % operation: ''}
            req.headers['Content-Type'] = 'application/json'
            req.body = json.dumps(body)
        req.environ['cinder.context'] = context.RequestContext('admin',
                                                               'fake',
                                                               True)
        res = req.get_response(app())
        return req, res

    def test_promote_bad_id(self):
        (req, res) = self._get_resp('promote', 'fake')
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 404, msg)

    def test_promote_bad_id_xml(self):
        (req, res) = self._get_resp('promote', 'fake', xml=True)
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 404, msg)

    def test_promote_volume_not_replicated(self):
        volume = tests_utils.create_volume(
            self.ctxt,
            **self.volume_params)
        (req, res) = self._get_resp('promote', volume['id'])
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 400, msg)

    def test_promote_volume_not_replicated_xml(self):
        volume = tests_utils.create_volume(
            self.ctxt,
            **self.volume_params)
        (req, res) = self._get_resp('promote', volume['id'], xml=True)
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 400, msg)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.promote_replica')
    def test_promote_replication_volume_status(self,
                                               _rpcapi_promote):
        for status in ['error', 'in-use']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = status,
                                               replication_status = 'active',
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'])
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 400, msg)

        for status in ['available']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = status,
                                               replication_status = 'active',
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'])
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 202, msg)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.promote_replica')
    def test_promote_replication_volume_status_xml(self,
                                                   _rpcapi_promote):
        for status in ['error', 'in-use']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = status,
                                               replication_status = 'active',
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'], xml=True)
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 400, msg)

        for status in ['available']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = status,
                                               replication_status = 'active',
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'], xml=True)
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 202, msg)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.promote_replica')
    def test_promote_replication_replication_status(self,
                                                    _rpcapi_promote):
        for status in ['error', 'copying', 'inactive']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'])
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 400, msg)

        for status in ['active', 'active-stopped']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'])
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 202, msg)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.promote_replica')
    def test_promote_replication_replication_status_xml(self,
                                                        _rpcapi_promote):
        for status in ['error', 'copying', 'inactive']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'], xml=True)
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 400, msg)

        for status in ['active', 'active-stopped']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('promote', volume['id'], xml=True)
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 202, msg)

    def test_reenable_bad_id(self):
        (req, res) = self._get_resp('reenable', 'fake')
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 404, msg)

    def test_reenable_bad_id_xml(self):
        (req, res) = self._get_resp('reenable', 'fake', xml=True)
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 404, msg)

    def test_reenable_volume_not_replicated(self):
        volume = tests_utils.create_volume(
            self.ctxt,
            **self.volume_params)
        (req, res) = self._get_resp('reenable', volume['id'])
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 400, msg)

    def test_reenable_volume_not_replicated_xml(self):
        volume = tests_utils.create_volume(
            self.ctxt,
            **self.volume_params)
        (req, res) = self._get_resp('reenable', volume['id'], xml=True)
        msg = ("request: %s\nresult: %s" % (req, res))
        self.assertEqual(res.status_int, 400, msg)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.reenable_replication')
    def test_reenable_replication_replication_status(self,
                                                     _rpcapi_promote):
        for status in ['active', 'copying']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('reenable', volume['id'])
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 400, msg)

        for status in ['inactive', 'active-stopped', 'error']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('reenable', volume['id'])
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 202, msg)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.reenable_replication')
    def test_reenable_replication_replication_status_xml(self,
                                                         _rpcapi_promote):
        for status in ['active', 'copying']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('reenable', volume['id'], xml=True)
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 400, msg)

        for status in ['inactive', 'active-stopped', 'error']:
            volume = tests_utils.create_volume(self.ctxt,
                                               status = 'available',
                                               replication_status = status,
                                               **self.volume_params)
            (req, res) = self._get_resp('reenable', volume['id'], xml=True)
            msg = ("request: %s\nresult: %s" % (req, res))
            self.assertEqual(res.status_int, 202, msg)
