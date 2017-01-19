# Copyright (c) 2016 Red Hat, Inc.
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

import ddt
import mock

from cinder.common import constants
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import utils
from cinder.tests.unit import volume as base
from cinder.volume import manager


@ddt.ddt
class ReplicationTestCase(base.BaseVolumeTestCase):
    def setUp(self):
        super(ReplicationTestCase, self).setUp()
        self.host = 'host@backend#pool'
        self.manager = manager.VolumeManager(host=self.host)

    @mock.patch('cinder.objects.VolumeList.get_all')
    @mock.patch('cinder.volume.driver.BaseVD.failover_host',
                side_effect=exception.InvalidReplicationTarget(''))
    @ddt.data(('backend2', 'default', fields.ReplicationStatus.FAILED_OVER),
              ('backend2', 'backend3', fields.ReplicationStatus.FAILED_OVER),
              (None, 'backend2', fields.ReplicationStatus.ENABLED),
              ('', 'backend2', fields.ReplicationStatus.ENABLED))
    @ddt.unpack
    def test_failover_host_invalid_target(self, svc_backend, new_backend,
                                          expected, mock_failover,
                                          mock_getall):
        """Test replication failover_host with invalid_target.

        When failingover fails due to an invalid target exception we return
        replication_status to its previous status, and we decide what that is
        depending on the currect active backend.
        """
        svc = utils.create_service(
            self.context,
            {'host': self.host,
             'binary': constants.VOLUME_BINARY,
             'active_backend_id': svc_backend,
             'replication_status': fields.ReplicationStatus.FAILING_OVER})

        self.manager.failover_host(self.context, new_backend)
        mock_getall.assert_called_once_with(self.context,
                                            filters={'host': self.host})
        mock_failover.assert_called_once_with(self.context,
                                              mock_getall.return_value,
                                              secondary_id=new_backend)

        db_svc = objects.Service.get_by_id(self.context, svc.id)
        self.assertEqual(expected, db_svc.replication_status)

    @mock.patch('cinder.volume.driver.BaseVD.failover_host',
                mock.Mock(side_effect=exception.VolumeDriverException('')))
    def test_failover_host_driver_exception(self):
        svc = utils.create_service(
            self.context,
            {'host': self.host,
             'binary': constants.VOLUME_BINARY,
             'active_backend_id': None,
             'replication_status': fields.ReplicationStatus.FAILING_OVER})

        self.manager.failover_host(self.context, mock.sentinel.backend_id)

        db_svc = objects.Service.get_by_id(self.context, svc.id)
        self.assertEqual(fields.ReplicationStatus.FAILOVER_ERROR,
                         db_svc.replication_status)
