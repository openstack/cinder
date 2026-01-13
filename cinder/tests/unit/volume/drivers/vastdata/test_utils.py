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
import json
import pickle
import unittest
from unittest.mock import MagicMock

import ddt

from cinder.volume.drivers.vastdata import utils


class TestUtils(unittest.TestCase):

    def test_make_volume_name(self):
        # Mocking the configuration object
        configuration = MagicMock()
        configuration.vast_volume_prefix = "cinder/volumes/"

        # Create a mock volume with the expected attributes
        volume = MagicMock()
        volume.id = "1234"

        # Test the volume name creation
        result = utils.make_volume_name(volume, configuration)
        self.assertEqual(result, "cinder/volumes/1234")

    def test_make_snapshot_name(self):
        # Mocking the configuration object
        configuration = MagicMock()
        configuration.vast_snapshot_prefix = "cinder/snapshots/"

        # Create a mock snapshot with the expected attributes
        snapshot = MagicMock()
        snapshot.id = "5678"

        # Test the snapshot name creation
        result = utils.make_snapshot_name(snapshot, configuration)
        self.assertEqual(result, "cinder/snapshots/5678")

    def test_make_tags(self):
        # Create a mock volume with the expected attributes
        volume = MagicMock()
        volume.display_name = "test-volume"
        volume.availability_zone = "us-east-1"
        volume.id = "1234"
        volume.project_id = "abcd"
        volume.user_id = "user1"

        # Test the tags generation
        result = utils.make_tags(volume)
        expected = {
            "display_name": "test-volume",
            "availability_zone": "us-east-1",
            "id": "1234",
            "project_id": "abcd",
            "user_id": "user1",
        }
        self.assertEqual(result, expected)

    def test_concatenate_paths_abs(self):
        # Test concatenating multiple paths
        result = utils.concatenate_paths_abs("path1", "path2", "path3")
        self.assertEqual(result, "/path1/path2/path3")

        # Test with leading and trailing slashes in paths
        result = utils.concatenate_paths_abs("/path1/", "path2", "/path3/")
        self.assertEqual(result, "/path1/path2/path3")

        # Test with empty paths
        result = utils.concatenate_paths_abs("path1", "", "path3")
        self.assertEqual(result, "/path1/path3")

        # Test with no paths
        result = utils.concatenate_paths_abs()
        self.assertEqual(result, "/")


@ddt.ddt
class TestGenerateIpRange(unittest.TestCase):

    @ddt.data(
        (
            [["15.0.0.1", "15.0.0.4"], ["10.0.0.27", "10.0.0.30"]],
            [
                "15.0.0.1",
                "15.0.0.2",
                "15.0.0.3",
                "15.0.0.4",
                "10.0.0.27",
                "10.0.0.28",
                "10.0.0.29",
                "10.0.0.30",
            ],
        ),
        (
            [["15.0.0.1", "15.0.0.1"], ["10.0.0.20", "10.0.0.20"]],
            ["15.0.0.1", "10.0.0.20"],
        ),
        ([], []),
    )
    @ddt.unpack
    def test_generate_ip_range(self, ip_ranges, expected):
        ips = utils.generate_ip_range(ip_ranges)
        assert ips == expected

    def test_generate_ip_range_edge_cases(self):
        # Test edge cases for generate_ip_range function
        self.assertEqual(utils.generate_ip_range([]), [])
        self.assertEqual(
            utils.generate_ip_range([["15.0.0.1", "15.0.0.1"]]), ["15.0.0.1"]
        )

    def test_generate_ip_range_large_range(self):
        # Test with a large range of IPs
        start_ip = "192.168.0.1"
        end_ip = "192.168.255.255"
        ips = utils.generate_ip_range([[start_ip, end_ip]])
        self.assertEqual(len(ips), 65535)


@ddt.ddt
class TestBunch(unittest.TestCase):
    def setUp(self):
        super(TestBunch, self).setUp()
        self.bunch = utils.Bunch(a=1, b=2)

    def test_bunch_getattr(self):
        self.assertEqual(self.bunch.a, 1)

    def test_bunch_setattr(self):
        self.bunch.c = 3
        self.assertEqual(self.bunch.c, 3)

    def test_bunch_delattr(self):
        del self.bunch.a
        self.assertRaises(AttributeError, lambda: self.bunch.a)

    def test_bunch_to_dict(self):
        self.assertEqual(self.bunch.to_dict(), {"a": 1, "b": 2})

    def test_bunch_from_dict(self):
        self.assertEqual(
            utils.Bunch.from_dict({"a": 1, "b": 2}), self.bunch
        )

    def test_bunch_to_json(self):
        self.assertEqual(self.bunch.to_json(), json.dumps({"a": 1, "b": 2}))

    def test_bunch_without(self):
        self.assertEqual(self.bunch.without("a"), utils.Bunch(b=2))

    def test_bunch_but_with(self):
        self.assertEqual(
            self.bunch.but_with(c=3), utils.Bunch(a=1, b=2, c=3)
        )

    def test_bunch_from_json(self):
        json_bunch = json.dumps({"a": 1, "b": 2})
        self.assertEqual(utils.Bunch.from_json(json_bunch), self.bunch)

    def test_bunch_render(self):
        self.assertEqual(self.bunch.render(), "a=1, b=2")

    def test_bunch_pickle(self):
        pickled_bunch = pickle.dumps(self.bunch)
        unpickled_bunch = pickle.loads(pickled_bunch)
        self.assertEqual(self.bunch, unpickled_bunch)

    @ddt.data(True, False)
    def test_bunch_copy(self, deep):
        copy_bunch = self.bunch.copy(deep=deep)
        self.assertEqual(copy_bunch, self.bunch)
        self.assertIsNot(copy_bunch, self.bunch)

    def test_name_starts_with_underscore_and_digit(self):
        bunch = utils.Bunch()
        bunch["1"] = "value"
        self.assertEqual(bunch._1, "value")

    def test_bunch_recursion(self):
        x = utils.Bunch(
            a="a", b="b", d=utils.Bunch(x="axe", y="why")
        )
        x.d.x = x
        x.d.y = x.b

    def test_bunch_repr(self):
        self.assertEqual(repr(self.bunch), "Bunch(a=1, b=2)")

    def test_getitem_with_integral_key(self):
        self.bunch["1"] = "value"
        self.assertEqual(self.bunch[1], "value")

    def test_bunch_dir(self):
        self.assertEqual(
            set(i for i in dir(self.bunch) if not i.startswith("_")),
            {
                "a",
                "b",
                "but_with",
                "clear",
                "copy",
                "from_dict",
                "from_json",
                "fromkeys",
                "get",
                "items",
                "keys",
                "pop",
                "popitem",
                "render",
                "setdefault",
                "to_dict",
                "to_json",
                "update",
                "values",
                "without",
            },
        )

    def test_bunch_edge_cases(self):
        # Test edge cases for attribute access, setting, and deletion
        self.bunch["key-with-special-chars_123"] = "value"
        self.assertEqual(self.bunch["key-with-special-chars_123"], "value")
        self.bunch["key-with-special-chars_123"] = None
        self.assertIsNone(self.bunch["key-with-special-chars_123"])
        del self.bunch["key-with-special-chars_123"]
        self.assertRaises(
            KeyError,
            lambda: self.bunch["key-with-special-chars_123"]
        )

    def test_bunch_deep_copy(self):
        nested_bunch = utils.Bunch(x=utils.Bunch(y=1))
        deep_copy = nested_bunch.copy(deep=True)
        self.assertIsNot(nested_bunch["x"], deep_copy["x"])
        self.assertEqual(nested_bunch["x"]["y"], deep_copy["x"]["y"])

    def test_bunch_serialization(self):
        # Test serialization with nested structures
        nested_bunch = utils.Bunch(a=1, b=utils.Bunch(c=2))
        self.assertEqual(nested_bunch.to_dict(), {"a": 1, "b": {"c": 2}})
        self.assertEqual(
            nested_bunch.to_json(),
            json.dumps({"a": 1, "b": {"c": 2}})
        )


class TestBunchify(unittest.TestCase):
    def test_bunchify(self):
        self.assertEqual(
            utils.bunchify({"a": 1, "b": 2}, c=3),
            utils.Bunch(a=1, b=2, c=3)
        )
        x = utils.bunchify(dict(a=[dict(b=5), 9, (1, 2)], c=8))
        self.assertEqual(x.a[0].b, 5)
        self.assertEqual(x.a[1], 9)
        self.assertIsInstance(x.a[2], tuple)
        self.assertEqual(x.c, 8)
        self.assertEqual(x.pop("c"), 8)

    def test_bunchify_edge_cases(self):
        # Test edge cases for bunchify function
        self.assertEqual(utils.bunchify({}), utils.Bunch())

    def test_bunchify_nested_structures(self):
        # Test bunchify with nested structures
        nested_dict = {"a": [{"b": 1}, 2]}
        self.assertEqual(utils.bunchify(nested_dict).a[0].b, 1)


class TestUnbunchify(unittest.TestCase):
    def test_unbunchify(self):
        self.assertEqual(
            utils.unbunchify(utils.Bunch(a=1, b=2)),
            {"a": 1, "b": 2}
        )
