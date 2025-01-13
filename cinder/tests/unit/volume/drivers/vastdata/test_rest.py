# Copyright 2025 VAST Data Inc.
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

import io
import unittest
from unittest import mock
from unittest.mock import MagicMock
from unittest.mock import patch

import requests

from cinder.volume import configuration as conf
from cinder.volume.drivers.vastdata import driver
from cinder.volume.drivers.vastdata import rest as vast_rest
from cinder.volume.drivers.vastdata import utils as vast_utils


class VastRestTestCase(unittest.TestCase):
    def setUp(self):
        self.fake_conf = conf.Configuration(
            driver.VASTDATA_OPTS, conf.SHARED_CONF_GROUP
        )
        self.fake_conf.set_default("volume_backend_name", "vast")
        self.fake_conf.set_default("vast_subsystem", "subsystem")
        self.fake_conf.set_default("vast_vippool_name", "vippool")
        self.fake_conf.set_default("vast_volume_prefix", "openstack-vol-")
        self.fake_conf.set_default("vast_snapshot_prefix", "openstack-snap-")
        self.fake_conf.set_default("san_login", "username")
        self.fake_conf.set_default("san_password", "password")
        self.fake_conf.set_default("san_ip", "host")
        self.rest = vast_rest.RestApi(
            configuration=self.fake_conf, plugin_version="1.0"
        )


class TestRest(VastRestTestCase):

    def test_do_setup_wrong_version(self):
        with (
            patch.object(self.rest.session, "refresh_auth_token", MagicMock()),
            patch.object(
                self.rest.versions,
                "get_sw_version",
                MagicMock(return_value="4.3.0"),
            ),
        ):
            with self.assertRaises(vast_rest.VastApiException):
                self.rest.do_setup()

    def test_do_setup_ok(self):
        with (
            patch.object(
                self.rest.session,
                "refresh_auth_token",
                MagicMock()
            ),
            patch.object(
                self.rest.versions,
                "get_sw_version",
                MagicMock(return_value="5.3.0")
            ),
        ):
            self.rest.do_setup()


class TestSession(VastRestTestCase):

    @mock.patch("requests.Session.request")
    def test_refresh_auth_token_success(self, mock_request):
        mock_request.return_value.json.return_value = {"access": "test_token"}
        self.rest.session.refresh_auth_token()
        self.assertEqual(
            self.rest.session.headers["authorization"], "Bearer test_token"
        )

    @mock.patch("requests.Session.request")
    def test_refresh_auth_token_failure(self, mock_request):
        mock_request.side_effect = ConnectionError()
        with self.assertRaises(vast_rest.VastApiException):
            self.rest.session.refresh_auth_token()

    @mock.patch("requests.Session.request")
    def test_request_success(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = []
        self.rest.session.request(
            "GET",
            "views",
            log_result=False,
            params={"foo": "bar"},
            resource_factory_name="views",
        )
        mock_request.assert_called_once_with(
            "GET",
            "https://host/api/v4/views/",
            verify=False,
            params={"foo": "bar"},
            log_result=False,
        )

    @mock.patch("requests.Session.request")
    def test_request_failure_400(self, mock_request):
        mock_request.return_value.status_code = 400
        mock_request.return_value.text = "foo/bar"
        with self.assertRaises(vast_rest.VastApiException):
            self.rest.session.request(
                "POST",
                "views",
                data={"data": {"foo": "bar"}},
                resource_factory_name="views",
            )

    def test_request_failure_500(self):
        resp = requests.Response()
        resp.status_code = 500
        resp.raw = io.BytesIO(b"Server error")

        with mock.patch("requests.Session.request", new=lambda *a, **k: resp):
            with self.assertRaises(vast_rest.VastApiException) as exc:
                self.rest.session.request(
                    "GET",
                    "views",
                    log_result=False,
                    resource_factory_name="views",
                )
            self.assertIn("Server Error", str(exc.exception))

    def test_request_no_return_content(self):
        resp = requests.Response()
        resp.status_code = 200
        resp.raw = io.BytesIO(b"")

        with mock.patch("requests.Session.request", new=lambda *a, **k: resp):
            res = self.rest.session.request(
                "GET", "views", resource_factory_name="views"
            )
        self.assertFalse(res)

    @mock.patch("requests.Session.request")
    def test_undefined_vast_resource(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = []
        with self.assertRaises(AssertionError):
            self.rest.session.request(
                "GET",
                "test_resource",
                log_result=False,
                params={"foo": "bar"},
                resource_factory_name="test_resource",
            )

    @mock.patch(
        "cinder.volume.drivers.vastdata.rest.Session.refresh_auth_token",
        mock.MagicMock(),
    )
    def test_refresh_token_retries(self):
        resp = requests.Response()
        resp.status_code = 403
        resp.raw = io.BytesIO(b"Token is invalid")

        with mock.patch("requests.Session.request", new=lambda *a, **k: resp):
            with self.assertRaises(vast_rest.VastApiRetry):
                self.rest.session.request(
                    "POST", "views", foo="bar", resource_factory_name="views"
                )


class TestVastResource(unittest.TestCase):
    def setUp(self):
        self.mock_rest = mock.MagicMock()
        self.vast_resource = vast_rest.VastResource(self.mock_rest)

    def test_list_with_filtering_params(self):
        self.vast_resource.list(name="test")
        self.mock_rest.session.get.assert_called_with(
            self.vast_resource.resource_name,
            params={"name": "test"},
            resource_factory_name=None,
        )

    def test_create_with_provided_params(self):
        self.vast_resource.create(name="test", size=10)
        self.mock_rest.session.post.assert_called_with(
            self.vast_resource.resource_name,
            data={"name": "test", "size": 10},
            resource_factory_name=None,
        )

    def test_update_with_provided_params(self):
        self.vast_resource.update("1", name="test", size=10)
        self.mock_rest.session.patch.assert_called_with(
            f"{self.vast_resource.resource_name}/1",
            data={"name": "test", "size": 10},
            resource_factory_name=None,
        )

    def test_delete_when_entry_not_found(self):
        self.vast_resource.one = mock.MagicMock(return_value=None)
        self.vast_resource.delete(name="test")
        self.mock_rest.session.delete.assert_not_called()

    def test_delete_when_entry_found(self):
        self.vast_resource.one = mock.MagicMock(
            return_value=vast_utils.Bunch(id=1)
        )
        self.vast_resource.delete(name="test")
        self.mock_rest.session.delete.assert_called_with(
            f"{self.vast_resource.resource_name}/1",
            resource_factory_name=None,
        )


class FakeVastResource(vast_rest.VastResource):
    resource_name = "test_resource"


class TestVastResourceEntry(VastRestTestCase):

    def setUp(self):
        super().setUp()
        self.rest.session = mock.MagicMock()
        self.resource = FakeVastResource(rest=self.rest)

    def test_list(self):
        self.rest.session.get.return_value = [dict(id=1, name="Test")]
        result = self.resource.list(foo="bar")
        self.rest.session.get.assert_called_once_with(
            "test_resource",
            params={"foo": "bar"},
            resource_factory_name="test_resource",
        )
        assert result == [dict(id=1, name="Test")]

    def test_create(self):
        self.rest.session.post.return_value = dict(id=1, name="Test")
        result = self.resource.create(foo="bar")
        self.rest.session.post.assert_called_once_with(
            "test_resource",
            data={"foo": "bar"}, resource_factory_name="test_resource"
        )
        assert result == dict(id=1, name="Test")

    def test_update(self):
        self.rest.session.patch.return_value = dict(id=1, name="Updated Test")
        result = self.resource.update(1, foo="bar")
        self.rest.session.patch.assert_called_once_with(
            "test_resource/1",
            data={"foo": "bar"},
            resource_factory_name="test_resource",
        )
        assert result == dict(id=1, name="Updated Test")

    def test_delete(self):
        self.rest.session.get.return_value = [dict(id=1, name="Test")]
        self.rest.session.delete.return_value = dict(status="deleted")
        result = self.resource.delete(foo="bar")
        self.rest.session.delete.assert_called_once_with(
            "test_resource/1", resource_factory_name="test_resource"
        )
        assert result == dict(status="deleted")

    def test_delete_not_found(self):
        self.rest.session.get.return_value = []
        self.resource.delete(foo="bar")
        self.rest.session.delete.assert_not_called()

    def test_one_found(self):
        self.rest.session.get.return_value = [dict(id=1, name="Test")]
        result = self.resource.one(foo="bar")
        self.rest.session.get.assert_called_once_with(
            "test_resource",
            params={"foo": "bar"},
            resource_factory_name="test_resource",
        )
        assert result == dict(id=1, name="Test")

    def test_one_multiple(self):
        self.rest.session.get.return_value = [
            dict(id=1, name="Test"),
            dict(id=2, name="Test 2"),
        ]
        # with pytest.raises(Exception):
        with self.assertRaises(vast_rest.VastApiException):
            self.resource.one(foo="bar")

    def test_one_not_found(self):
        self.rest.session.get.return_value = []
        with self.assertRaises(vast_rest.VastApiException):
            self.resource.one(fail_if_missing=True, foo="bar")

    def test_ensure_exists(self):
        self.rest.session.get.return_value = [dict(id=1, name="Test")]
        result = self.resource.ensure(name="Test", foo="bar")
        self.rest.session.get.assert_called_once_with(
            "test_resource",
            params={"name": "Test"},
            resource_factory_name="test_resource",
        )
        assert result == dict(id=1, name="Test")

    def test_ensure_create(self):
        self.rest.session.get.return_value = []
        self.rest.session.post.return_value = dict(id=1, name="Test")
        result = self.resource.ensure(name="Test", foo="bar")
        self.rest.session.post.assert_called_once_with(
            "test_resource",
            data={"name": "Test", "foo": "bar"},
            resource_factory_name="test_resource",
        )
        assert result == dict(id=1, name="Test")

    def test_get(self):
        self.rest.session.get.return_value = dict(id=1, name="Test")
        result = self.resource.get(1)
        self.rest.session.get.assert_called_once_with(
            "test_resource/1", params={}, resource_factory_name="test_resource"
        )
        assert result == dict(id=1, name="Test")

    def test_list_with_pagination_envelope(self):
        """Test that list() correctly handles paginated API responses."""
        # Use a real Session object to test the full flow
        # Save original session
        original_session = self.rest.session
        try:
            # Create a real session instance
            self.rest.session = vast_rest.Session(
                host="test.example.com",
                username="user",
                password="pass",
                api_token=None,
                ssl_verify=False,
                plugin_version="1.0"
            )
            # Re-initialize the resource with the real session
            self.resource = FakeVastResource(rest=self.rest)

            # Mock the underlying HTTP request
            with mock.patch("requests.Session.request") as mock_request:
                paginated_response = {
                    "count": 2,
                    "results": [
                        {"id": 1, "name": "Test 1"},
                        {"id": 2, "name": "Test 2"},
                    ],
                    "next": None,
                    "previous": None,
                }
                # Create a proper mock response object
                mock_response = mock.MagicMock()
                mock_response.status_code = 200
                mock_response.content = b"response content"
                mock_response.json.return_value = paginated_response
                mock_response.raise_for_status.return_value = None
                mock_request.return_value = mock_response

                result = self.resource.list(foo="bar")

                # Result should be a list of resource entries (unwrapped)
                assert len(result) == 2
                assert result[0]["id"] == 1
                assert result[1]["id"] == 2
        finally:
            # Restore original session
            self.rest.session = original_session
            self.resource = FakeVastResource(rest=self.rest)

    def test_list_without_pagination_envelope(self):
        """Test that list() correctly handles non-paginated API responses."""
        # Use a real Session object to test the full flow
        # Save original session
        original_session = self.rest.session
        try:
            # Create a real session instance
            self.rest.session = vast_rest.Session(
                host="test.example.com",
                username="user",
                password="pass",
                api_token=None,
                ssl_verify=False,
                plugin_version="1.0"
            )
            # Re-initialize the resource with the real session
            self.resource = FakeVastResource(rest=self.rest)

            # Mock the underlying HTTP request
            with mock.patch("requests.Session.request") as mock_request:
                non_paginated_response = [
                    {"id": 1, "name": "Test 1"},
                    {"id": 2, "name": "Test 2"},
                ]
                # Create a proper mock response object
                mock_response = mock.MagicMock()
                mock_response.status_code = 200
                mock_response.content = b"response content"
                mock_response.json.return_value = non_paginated_response
                mock_response.raise_for_status.return_value = None
                mock_request.return_value = mock_response

                result = self.resource.list(foo="bar")

                # Non-paginated responses should work as before
                assert len(result) == 2
                assert result[0]["id"] == 1
                assert result[1]["id"] == 2
        finally:
            # Restore original session
            self.rest.session = original_session
            self.resource = FakeVastResource(rest=self.rest)

    def test_create_with_data_pagination_envelope(self):
        """Test create_with_data handles pagination envelope."""
        resource_factory = vast_rest.VAST_RESOURCES_FACTORY["test_resource"]

        # Test paginated response
        paginated_data = {
            "count": 3,
            "results": [
                {"id": 1, "name": "Item 1"},
                {"id": 2, "name": "Item 2"},
                {"id": 3, "name": "Item 3"},
            ],
            "next": "http://example.com/api/resource?page=2",
            "previous": None,
        }

        result = resource_factory.create_with_data(paginated_data)

        # Should extract results and return a collection
        assert isinstance(result, vast_rest.VastResourceCollection)
        assert len(result) == 3
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2
        assert result[2]["id"] == 3

    def test_create_with_data_non_paginated_list(self):
        """Test VastResourceEntry.create_with_data handles flat list."""
        resource_factory = vast_rest.VAST_RESOURCES_FACTORY["test_resource"]

        # Test non-paginated list response
        list_data = [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"},
        ]

        result = resource_factory.create_with_data(list_data)

        # Should return a collection
        assert isinstance(result, vast_rest.VastResourceCollection)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_create_with_data_single_dict(self):
        """Test VastResourceEntry.create_with_data handles single dict."""
        resource_factory = vast_rest.VAST_RESOURCES_FACTORY["test_resource"]

        # Test single dict response (not pagination envelope)
        dict_data = {"id": 1, "name": "Single Item"}

        result = resource_factory.create_with_data(dict_data)

        # Should return a single entry
        assert isinstance(result, vast_rest.VastResourceEntry)
        assert result["id"] == 1
        assert result["name"] == "Single Item"


class TestVastResourceCollection(unittest.TestCase):
    def setUp(self):
        """Set up mock VastResourceEntry instances."""
        self.entry1 = MagicMock(spec=vast_rest.VastResourceEntry)
        self.entry2 = MagicMock(spec=vast_rest.VastResourceEntry)

        self.entry1.render.side_effect = (
            lambda short: "Entry1 Short" if short else "Entry1 Detailed"
        )
        self.entry2.render.side_effect = (
            lambda short: "Entry2 Short" if short else "Entry2 Detailed"
        )

    def test_empty_collection(self):
        """Test rendering an empty collection."""
        collection = vast_rest.VastResourceCollection()
        self.assertEqual(str(collection), "[]")
        self.assertEqual(collection.render(short=True), "[]")
        self.assertEqual(collection.render(short=False), "[]")

    def test_short_render(self):
        """Test short form rendering."""
        collection = vast_rest.VastResourceCollection(
            [self.entry1, self.entry2]
        )
        expected_short = "\n[\nEntry1 Short\nEntry2 Short\n]"
        self.assertEqual(str(collection), expected_short)
        self.assertEqual(collection.render(short=True), expected_short)

    def test_long_render(self):
        """Test long form rendering."""
        collection = vast_rest.VastResourceCollection(
            [self.entry1, self.entry2]
        )
        expected_long = "\n[\nEntry1 Detailed\nEntry2 Detailed\n]"
        self.assertEqual(collection.render(short=False), expected_long)

    def test_single_entry_collection(self):
        """Test rendering a collection with a single entry."""
        collection = vast_rest.VastResourceCollection([self.entry1])
        self.assertEqual(str(collection), "\n[\nEntry1 Short\n]")
        self.assertEqual(
            collection.render(short=False),
            "\n[\nEntry1 Detailed\n]"
        )

    def test_repr_uses_short_render(self):
        """Test that __repr__ uses short rendering."""
        collection = vast_rest.VastResourceCollection([self.entry1])
        self.assertEqual(repr(collection), "\n[\nEntry1 Short\n]")

    def test_str_aliases_repr(self):
        """Ensure __str__ is an alias for __repr__."""
        collection = vast_rest.VastResourceCollection([self.entry1])
        self.assertEqual(str(collection), repr(collection))


class TestVTask(unittest.TestCase):

    def setUp(self):
        self.rest = mock.Mock()
        self.vtasks = vast_rest.VTask(self.rest)

    def test_wait_task_completed(self):
        task_data = {
            "id": "task_id",
            "name": "TestTask",
            "state": "completed",
            "messages": ["Task completed successfully"],
        }
        self.vtasks.get = mock.Mock(return_value=mock.Mock(**task_data))
        result = self.vtasks.wait_task("task_id")

        self.vtasks.get.assert_called_with("task_id", log_result=False)
        self.assertEqual(result.id, "task_id")
        self.assertEqual(result.state, "completed")

    def test_wait_task_failed(self):
        task_data = {
            "id": "task_id",
            "name": "TestTask",
            "state": "failed",
            "messages": ["Task failed due to an error"],
        }
        self.vtasks.get = mock.Mock(return_value=mock.Mock(**task_data))
        with self.assertRaises(vast_rest.VastApiRetry) as ctx:
            self.vtasks.wait_task("task_id")

        self.assertIn("failed with id task_id", str(ctx.exception))

    @mock.patch("cinder.utils.retry")
    def test_wait_task_running_timeout(self, mock_retry):
        task_data = {
            "id": "task_id",
            "name": "TestTask",
            "state": "running",
            "messages": ["Task is still running"],
        }
        self.vtasks.get = mock.Mock(return_value=mock.Mock(**task_data))
        mock_retry.side_effect = vast_rest.VastApiRetry("Timeout occurred")

        with self.assertRaises(vast_rest.VastApiRetry) as ctx:
            self.vtasks.wait_task("task_id")

        self.assertIn("Timeout occurred", str(ctx.exception))


class TestVolume(VastRestTestCase):

    @mock.patch("requests.Session.request")
    def test_delete_by_id(self, mock_request):
        mock_request.return_value.json.return_value = {"success": True}
        res = self.rest.volumes.delete_by_id("volume_id")
        self.assertTrue(res["success"])


class TestBlockHost(VastRestTestCase):

    def test_ensure_returns_existing_blockhost(self):
        mock_blockhost = mock.Mock()
        self.rest.blockhosts.one = mock.Mock(return_value=mock_blockhost)
        result = self.rest.blockhosts.ensure(
            "host_name", "tenant_id", "nqn"
        )
        self.rest.blockhosts.one.assert_called_with(
            name="host_name", tenant_id="tenant_id"
        )
        self.assertEqual(result, mock_blockhost)

    def test_ensure_creates_new_blockhost(self):
        self.rest.blockhosts.one = mock.Mock(return_value=None)
        self.rest.blockhosts.create = mock.Mock()

        self.rest.blockhosts.ensure("host_name", "tenant_id", "nqn")
        self.rest.blockhosts.create.assert_called_with(
            name="host_name",
            tenant_id="tenant_id",
            os_type="LINUX",
            ana="OPTIMIZED",
            connectivity_type="tcp",
            nqn="nqn",
        )


class TestView(VastRestTestCase):
    def test_get_subsystem(self):
        mock_view = mock.Mock()
        mock_view.protocols = ["BLOCK"]
        self.rest.views.one = mock.Mock(return_value=mock_view)

        result = self.rest.views.get_subsystem("subsystem_name")
        self.rest.views.one.assert_called_with(
            name="subsystem_name", fail_if_missing=True
        )
        self.assertEqual(result, mock_view)

    def test_get_subsystem_by_id(self):
        mock_view = mock.Mock()
        mock_view.protocols = ["BLOCK"]
        self.rest.views.get = mock.Mock(return_value=mock_view)

        result = self.rest.views.get_subsystem_by_id("entry_id")
        self.rest.views.get.assert_called_with("entry_id")
        self.assertEqual(result, mock_view)


class TestSnapshot(VastRestTestCase):
    @mock.patch("requests.Session.request")
    def test_clone_volume(self, mock_request):
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"id": "new_volume"}'
        mock_response.json.return_value = {"id": "new_volume"}
        mock_response.raise_for_status.return_value = None
        mock_request.return_value = mock_response

        result = self.rest.snapshots.clone_volume(
            "snapshot_id", "subsystem_id", "target_path"
        )

        # Verify the result was properly processed
        assert result is not None


class TestVersion(VastRestTestCase):
    def test_get_sw_version(self):
        self.rest.versions.list = mock.Mock(
            return_value=[mock.Mock(sys_version="1-2-3")]
        )
        version = self.rest.versions.get_sw_version()
        self.assertEqual(version, "1.2.3")

    def test_check_min_vast_version_compatible(self):
        self.rest.versions.get_sw_version = mock.Mock(return_value="1.2.3")
        self.assertIsNone(self.rest.versions.check_min_vast_version("1.2.0"))

    def test_check_min_vast_version_incompatible(self):
        self.rest.versions.get_sw_version = mock.Mock(return_value="1.2.3")
        with self.assertRaises(vast_rest.VastApiException):
            self.rest.versions.check_min_vast_version("1.3.0")


class TestVipPool(VastRestTestCase):

    def setUp(self):
        super().setUp()
        self.vip_pool = vast_rest.VipPool(self.rest)

    @mock.patch("cinder.volume.drivers.vastdata.rest.VipPool.one")
    @mock.patch("cinder.volume.drivers.vastdata.utils.generate_ip_range")
    def test_get_vips_success(self, mock_generate_ip_range, mock_one):
        # Setup mock behavior
        mock_one.return_value = mock.Mock(
            name="test_pool", tenant_id=123, ip_ranges=["192.168.1.0/24"]
        )
        mock_generate_ip_range.return_value = ["192.168.1.1", "192.168.1.2"]

        # Test with correct pool name and tenant
        result = self.vip_pool.get_vips("test_pool", tenant_id=123)
        self.assertEqual(result, ["192.168.1.1", "192.168.1.2"])

    @mock.patch("cinder.volume.drivers.vastdata.rest.VipPool.one")
    def test_get_vips_tenant_mismatch(self, mock_one):
        # Setup mock behavior
        mock_one.return_value = mock.Mock(
            name="test_pool", tenant_id=123, ip_ranges=["192.168.1.0/24"]
        )

        # Test with tenant_id mismatch
        with self.assertRaises(vast_rest.VastApiException):
            self.vip_pool.get_vips("test_pool", tenant_id=999)

    @mock.patch("cinder.volume.drivers.vastdata.rest.VipPool.one")
    @mock.patch("cinder.volume.drivers.vastdata.utils.generate_ip_range")
    def test_get_vips_no_ips(self, mock_generate_ip_range, mock_one):
        # Setup mock behavior
        mock_one.return_value = mock.Mock(
            name="test_pool", tenant_id=123, ip_ranges=["192.168.1.0/24"]
        )
        mock_generate_ip_range.return_value = []


class TestCapacityMetrics(VastRestTestCase):

    @mock.patch("requests.Session.request")
    def test_capacity_metrics(self, mock_request):
        mock_request.return_value.json.return_value = {
            "data": [
                [
                    1.2,
                    505846398976.0,
                    22420306196.0,
                    711246584217.0,
                    30635248783.0,
                ]
            ],
            "prop_list": [
                "Capacity,drr",
                "Capacity,logical_space",
                "Capacity,logical_space_in_use",
                "Capacity,physical_space",
                "Capacity,physical_space_in_use",
            ],
        }
        metrics = self.rest.capacity_metrics.get()
        expected = {
            "drr": 1.2,
            "logical_space": 505846398976.0,
            "logical_space_in_use": 22420306196.0,
            "physical_space": 711246584217.0,
            "physical_space_in_use": 30635248783.0,
        }
        self.assertDictEqual(expected, metrics.to_dict())


class TestBlockHostMapping(VastRestTestCase):

    @mock.patch("requests.Session.request")
    def test_map(self, mock_request):
        mock_request.return_value.json.return_value = {
            "id": "task_id",
            "state": "completed",
            "messages": [],
        }
        res = self.rest.blockhostmappings.map("volume_id", "host_id")
        self.assertDictEqual(
            res.to_dict(),
            {"id": "task_id", "state": "completed", "messages": []}
        )

    def test_ensure_map_calls_map_if_not_exists(self):
        self.rest.blockhostmappings.one = mock.Mock(return_value=None)
        self.rest.blockhostmappings.map = mock.Mock()

        self.rest.blockhostmappings.ensure_map("volume_id", "host_id")
        self.rest.blockhostmappings.map.assert_called_with(
            "volume_id", "host_id"
        )

    def test_ensure_map_does_not_call_map_if_exists(self):
        self.rest.blockhostmappings.one = mock.Mock(
            return_value="existing_mapping"
        )
        self.rest.blockhostmappings.map = mock.Mock()

        result = self.rest.blockhostmappings.ensure_map("volume_id", "host_id")
        self.rest.blockhostmappings.map.assert_not_called()
        self.assertIsNone(result)

    @mock.patch("requests.Session.request")
    def test_unmap(self, mock_request):
        mock_request.return_value.json.return_value = {
            "id": "task_id",
            "state": "completed",
            "messages": [],
        }
        res = self.rest.blockhostmappings.unmap("volume_id", "host_id")
        self.assertDictEqual(
            res.to_dict(),
            {"id": "task_id", "state": "completed", "messages": []}
        )

    def test_ensure_unmap_calls_unmap_if_mapping_exists(self):
        mock_mapping = mock.Mock()
        mock_mapping.volume = {"id": "volume_id"}
        mock_mapping.block_host = {"id": "host_id"}

        self.rest.blockhostmappings.one = mock.Mock(return_value=mock_mapping)
        self.rest.blockhostmappings.unmap = mock.Mock()

        self.rest.blockhostmappings.ensure_unmap(
            volume__id="volume_id", block_host__id="host_id"
        )
        self.rest.blockhostmappings.unmap.assert_called_with(
            volume_id="volume_id", host_id="host_id"
        )

    def test_ensure_unmap_does_not_call_unmap_if_no_mapping(self):
        self.rest.blockhostmappings.one = mock.Mock(return_value=None)
        self.rest.blockhostmappings.unmap = mock.Mock()

        result = self.rest.blockhostmappings.ensure_unmap(
            volume__id="volume_id", block_host__id="host_id"
        )
        self.rest.blockhostmappings.unmap.assert_not_called()
        self.assertIsNone(result)


class TestGlobalSnapshotStream(VastRestTestCase):

    @mock.patch("requests.Session.request")
    def test_stop_snapshot_stream(self, mock_request):
        mock_request.return_value.json.return_value = {
            "id": "task_id",
            "state": "completed",
            "messages": [],
        }
        res = self.rest.globalsnapstreams.stop_snapshot_stream("stream_id")
        self.assertEqual(
            res.to_dict(),
            {"id": "task_id", "state": "completed", "messages": []}
        )

    @mock.patch("requests.Session.request")
    def test_ensure_existing_snapshot_stream(self, mock_request):
        mock_request.return_value.json.return_value = {
            "id": "stream_id",
            "name": "TestStream",
        }
        self.rest.globalsnapstreams.one = mock.MagicMock(
            return_value={"id": "stream_id", "name": "TestStream"}
        )
        res = self.rest.globalsnapstreams.ensure(
            "TestStream", "snapshot_id", "tenant_id", "/path"
        )
        self.rest.globalsnapstreams.one.assert_called_once_with(
            name="TestStream"
        )
        self.assertEqual(
            res,
            {"id": "stream_id", "name": "TestStream"}
        )

    @mock.patch("requests.Session.request")
    def test_ensure_new_snapshot_stream(self, mock_request):
        mock_request.return_value.json.return_value = {
            "id": "new_stream_id",
            "name": "NewStream",
        }
        self.rest.globalsnapstreams.one = mock.MagicMock(return_value=None)
        res = self.rest.globalsnapstreams.ensure(
            "NewStream", "snapshot_id", "tenant_id", "/path"
        )
        self.rest.globalsnapstreams.one.assert_called_once_with(
            name="NewStream"
        )
        # Verify the call was made with correct method and URL
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args[0][0], "POST")
        self.assertIn("snapshots/snapshot_id/clone/", call_args[0][1])
        self.assertEqual(
            call_args[1]['data'],
            '{"loanee_root_path": "/path", '
            '"name": "NewStream", "enabled": true, '
            '"loanee_tenant_id": "tenant_id"}'
        )
        self.assertEqual(
            res.to_dict(),
            {"id": "new_stream_id", "name": "NewStream"}
        )

    @mock.patch("requests.Session.request")
    def test_ensure_snapshot_stream_deleted(self, mock_request):
        mock_request.return_value.json.return_value = {
            "id": "stream_id",
            "state": "in_progress",
        }
        self.rest.globalsnapstreams.one = mock.MagicMock(
            return_value={
                "id": "stream_id", "status": {"state": "in_progress"}
            }
        )
        self.rest.globalsnapstreams.stop_snapshot_stream = mock.MagicMock(
            return_value={
                "id": "task_id", "status": {"state": "in_progress"}
            }
        )
        self.rest.vtasks.wait_task = mock.MagicMock()
        self.rest.globalsnapstreams.delete_by_id = mock.MagicMock()
        self.rest.globalsnapstreams.ensure_snapshot_stream_deleted("volume_id")
        self.rest.globalsnapstreams.one.assert_called_once_with(
            name__endswith="volume_id"
        )
        (self.rest.globalsnapstreams
            .stop_snapshot_stream
            .assert_called_once_with("stream_id")
         )
        self.rest.vtasks.wait_task.assert_called_once_with("task_id")
        self.rest.globalsnapstreams.delete_by_id.assert_called_once_with(
            entry_id="stream_id", data={"remove_dir": True}
        )
