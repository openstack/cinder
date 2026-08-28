# Copyright (C) 2026, Hitachi Vantara
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
#
"""Unit tests for Hitachi HBSD Driver Utilities."""

import ddt

from cinder import exception
from cinder.tests.unit import test
from cinder.volume.drivers.hitachi import hbsd_utils

SEARCHER_STORAGEID = '12345'

SEARCHER_MISSINGGROUP_NAME = 'missinggroup'

SEARCHER_GROUP3 = 3
SEARCHER_GROUP7 = 7
SEARCHER_GROUP3_WWNS = ['1000000000000000', '1000000000000001',
                        '1000000000000002', '1000000000000004',
                        '1000000000000005']
SEARCHER_GROUP7_WWNS = ['1000000000000003']

SEARCHER_MYGROUP_NAME = 'mygroup'
SEARCHER_MYGROUP_WWNS = SEARCHER_GROUP7_WWNS
SEARCHER_MYGROUP_NUM = SEARCHER_GROUP7

SEARCHER_TEST_PORT = 'CL1-A'
SEARCHER_MISSING_WWNS = ['1000000000000075']

SEARCHER_META_DATA = "META"

# Include 0 in all groups as it can have different behaviors with
# boolean conversions.
SEARCHER_ALL_GROUPS_AND_META = [(0, SEARCHER_META_DATA),
                                (SEARCHER_GROUP3, SEARCHER_META_DATA),
                                (SEARCHER_GROUP7, SEARCHER_META_DATA)]
SEARCHER_ALL_NAMES = [SEARCHER_MYGROUP_NAME, SEARCHER_MISSINGGROUP_NAME]
SEARCHER_ALL_VALID_WWNS = SEARCHER_GROUP3_WWNS + SEARCHER_GROUP7_WWNS
SEARCHER_ALL_VALID_NAMES = [SEARCHER_MYGROUP_NAME]


@ddt.ddt
class HBSDGroupSearcherTest(test.TestCase):
    """Unit test class for HBSD utils group searcher."""

    def setUp(self):
        """Set up the test environment."""

        super(HBSDGroupSearcherTest, self).setUp()

    def tearDown(self):
        super(HBSDGroupSearcherTest, self).tearDown()

    class QueryObject():

        def __init__(self):
            self.group_target_lookup = 0
            self.group_name_lookup = 0
            self.all_group_lookup = 0

        def query(self, port: str, group: int | str |
                  None) -> list[str] | tuple[int, list[str]] | list[int]:

            def _lookup_group_targets(port: str, groupNum: int):
                targets = list()
                if groupNum == SEARCHER_GROUP7:
                    targets = SEARCHER_GROUP7_WWNS
                elif groupNum == SEARCHER_GROUP3:
                    targets = SEARCHER_GROUP3_WWNS
                return targets

            def _lookup_group_by_name(port: str, group: str):
                if group == SEARCHER_MYGROUP_NAME:
                    targets = SEARCHER_MYGROUP_WWNS
                    groupNum = SEARCHER_MYGROUP_NUM
                    return (groupNum, SEARCHER_META_DATA), targets
                return None

            def _lookup_all_groups(port: str):
                return SEARCHER_ALL_GROUPS_AND_META

            if isinstance(group, int):
                self.group_target_lookup += 1
                return _lookup_group_targets(port, group)
            elif isinstance(group, str):
                self.group_name_lookup += 1
                return _lookup_group_by_name(port, group)

            self.all_group_lookup += 1
            return _lookup_all_groups(port)

    @ddt.data(hbsd_utils.HostConnectorSearcher(QueryObject().query),
              hbsd_utils.CachingHostConnectorSearcher(
                  SEARCHER_STORAGEID,
                  QueryObject().query))
    def test_group_searcher(self, searcher):

        # Test that all of our searches return the exected result
        # regardless of caching.
        groupAndMeta = searcher.find(SEARCHER_TEST_PORT,
                                     [SEARCHER_GROUP3_WWNS[4]],
                                     list())
        self.assertEqual((SEARCHER_GROUP3, SEARCHER_META_DATA), groupAndMeta)

        groups = list()
        groups.append(SEARCHER_MISSINGGROUP_NAME)
        groupAndMeta = searcher.find(SEARCHER_TEST_PORT,
                                     [SEARCHER_GROUP3_WWNS[2]],
                                     groups)
        self.assertEqual((SEARCHER_GROUP3, SEARCHER_META_DATA), groupAndMeta)

        groups = list()
        groups.append(SEARCHER_MYGROUP_NAME)
        groupAndMeta = searcher.find(SEARCHER_TEST_PORT,
                                     [SEARCHER_GROUP7_WWNS[0]],
                                     groups)
        self.assertEqual((SEARCHER_GROUP7, SEARCHER_META_DATA), groupAndMeta)

        groups = list()
        groups.append(SEARCHER_MISSINGGROUP_NAME)
        groupAndMeta = searcher.find(SEARCHER_TEST_PORT,
                                     [SEARCHER_GROUP7_WWNS[0]],
                                     groups)
        self.assertEqual((SEARCHER_GROUP7, SEARCHER_META_DATA), groupAndMeta)

        groups = list()
        groups.append(SEARCHER_MYGROUP_NAME)
        groupAndMeta = searcher.find(SEARCHER_TEST_PORT,
                                     [SEARCHER_MISSING_WWNS[0]],
                                     groups)
        self.assertIsNone(groupAndMeta)

        groups = list()
        groups.append(SEARCHER_MISSINGGROUP_NAME)
        groupAndMeta = searcher.find(SEARCHER_TEST_PORT,
                                     [SEARCHER_MISSING_WWNS[0]],
                                     groups)
        self.assertIsNone(groupAndMeta)

        groups = list()
        groups.append(SEARCHER_MISSINGGROUP_NAME)
        groups.append(SEARCHER_MYGROUP_NAME)
        groupAndMeta = searcher.find(SEARCHER_TEST_PORT,
                                     [SEARCHER_GROUP7_WWNS[0]],
                                     groups)
        self.assertEqual((SEARCHER_GROUP7, SEARCHER_META_DATA), groupAndMeta)

        is_caching = hasattr(searcher, '_connector_cache')

        if is_caching:
            # Validate that all our items were cached as expected.
            self.assertEqual(len(SEARCHER_ALL_VALID_WWNS),
                             len(searcher._connector_cache._target_cache))
            self.assertEqual(len(SEARCHER_ALL_VALID_NAMES),
                             len(searcher._connector_cache._group_name_cache))
            self.assertEqual(len(SEARCHER_ALL_GROUPS_AND_META),
                             len(searcher._connector_cache._group_cache))
            for wwn in SEARCHER_ALL_VALID_WWNS:
                self.assertTrue(
                    searcher._connector_cache._generate_target_key(
                        SEARCHER_TEST_PORT, wwn) in
                    searcher._connector_cache._target_cache)
            for name in SEARCHER_ALL_VALID_NAMES:
                self.assertTrue(
                    searcher._connector_cache._generate_group_name_key(
                        SEARCHER_TEST_PORT, name) in
                    searcher._connector_cache._group_name_cache)
            for groupAndMeta in SEARCHER_ALL_GROUPS_AND_META:
                group, meta = groupAndMeta
                self.assertTrue(
                    searcher._connector_cache._generate_group_key(
                        SEARCHER_TEST_PORT, group) in
                    searcher._connector_cache._group_cache)
                self.assertEqual(SEARCHER_META_DATA, meta)
            # Validate that the internal queries executed the expected
            # number of times (negating cache hits).
            self.assertEqual(2,
                             searcher._queryFunc.__self__.group_name_lookup)
            self.assertEqual(2,
                             searcher._queryFunc.__self__.group_target_lookup)
            self.assertEqual(3,
                             searcher._queryFunc.__self__.all_group_lookup)
        else:
            # Validate that the internal queries executed the expected
            # number of times.
            self.assertEqual(7,
                             searcher._queryFunc.__self__.group_name_lookup)
            self.assertEqual(13,
                             searcher._queryFunc.__self__.group_target_lookup)
            self.assertEqual(5,
                             searcher._queryFunc.__self__.all_group_lookup)

        # Test resetting the cache for group 3.
        searcher.on_reset_group(SEARCHER_TEST_PORT, SEARCHER_GROUP3)

        if is_caching:
            # Validate that the required items were removed from the cache.
            self.assertEqual(len(SEARCHER_ALL_VALID_WWNS) -
                             len(SEARCHER_GROUP3_WWNS),
                             len(searcher._connector_cache._target_cache))
            self.assertEqual(len(SEARCHER_ALL_VALID_NAMES),
                             len(searcher._connector_cache._group_name_cache))
            self.assertEqual(len(SEARCHER_ALL_GROUPS_AND_META) - 1,
                             len(searcher._connector_cache._group_cache))
            for wwn in SEARCHER_ALL_VALID_WWNS:
                if wwn in SEARCHER_GROUP3_WWNS:
                    self.assertFalse(
                        searcher._connector_cache._generate_target_key(
                            SEARCHER_TEST_PORT, wwn) in
                        searcher._connector_cache._target_cache)
                else:
                    self.assertTrue(
                        searcher._connector_cache._generate_target_key(
                            SEARCHER_TEST_PORT, wwn) in
                        searcher._connector_cache._target_cache)
            for name in SEARCHER_ALL_VALID_NAMES:
                self.assertTrue(
                    searcher._connector_cache._generate_group_name_key(
                        SEARCHER_TEST_PORT, name) in
                    searcher._connector_cache._group_name_cache)
            for groupAndMeta in SEARCHER_ALL_GROUPS_AND_META:
                group, meta = groupAndMeta
                if group == SEARCHER_GROUP3:
                    self.assertFalse(
                        searcher._connector_cache._generate_group_key(
                            SEARCHER_TEST_PORT, group) in
                        searcher._connector_cache._group_cache)
                else:
                    self.assertTrue(
                        searcher._connector_cache._generate_group_key(
                            SEARCHER_TEST_PORT, group) in
                        searcher._connector_cache._group_cache)

        # Re-find our WWN by group and check the lookups.
        group = searcher.find(SEARCHER_TEST_PORT, [SEARCHER_GROUP3_WWNS[0]],
                              list())
        self.assertEqual((SEARCHER_GROUP3, SEARCHER_META_DATA), group)

        if is_caching:
            self.assertEqual(2,
                             searcher._queryFunc.__self__.group_name_lookup)
            self.assertEqual(3,
                             searcher._queryFunc.__self__.group_target_lookup)
            self.assertEqual(4,
                             searcher._queryFunc.__self__.all_group_lookup)
        else:
            self.assertEqual(7,
                             searcher._queryFunc.__self__.group_name_lookup)
            self.assertEqual(15,
                             searcher._queryFunc.__self__.group_target_lookup)
            self.assertEqual(6,
                             searcher._queryFunc.__self__.all_group_lookup)

        # Reset entire cache and validate that it is cleared.
        searcher.on_reset()
        if is_caching:
            self.assertEqual(0, len(searcher._connector_cache._target_cache))
            self.assertEqual(0, len(searcher._connector_cache._group_cache))
            self.assertEqual(0,
                             len(searcher._connector_cache._group_name_cache))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_generate_target_key(self, cache):
        self.assertEqual("PORT\tWWN",
                         cache._generate_target_key("PORT", "WWN"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_generate_group_key(self, cache):
        self.assertEqual("PORT\t1",
                         cache._generate_group_key("PORT", 1))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_generate_group_name_key(self, cache):
        self.assertEqual("PORT\tNAME",
                         cache._generate_group_name_key("PORT", "NAME"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_lookup_cache_empty(self, cache):
        self.assertIsNone(cache.lookup("PORT", "WWN"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_lookup_not_cached(self, cache):
        cache.cache("PORT2", (1, None), None, ["WWN2"])
        self.assertIsNone(cache.lookup("PORT", "WWN"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_lookup_cached_unnamed(self, cache):
        cache.cache("PORT", (1, None), None, ["WWN"])
        self.assertEqual((1, None), cache.lookup("PORT", "WWN"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_lookup_cached_named(self, cache):
        cache.cache("PORT", (1, None), "NAME", ["WWN"])
        self.assertEqual((1, None), cache.lookup("PORT", "WWN"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_lookup_cached_with_meta(self, cache):
        cache.cache("PORT", (1, 3), None, ["WWN"])
        self.assertEqual((1, 3), cache.lookup("PORT", "WWN"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_is_group_cached(self, cache):
        self.assertFalse(cache.is_group_cached("PORT", 1))
        cache.cache("PORT", (1, None), None, ["WWN"])
        self.assertTrue(cache.is_group_cached("PORT", 1))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_is_group_name_cached(self, cache):
        self.assertFalse(cache.is_group_name_cached("PORT", "NAME"))
        cache.cache("PORT", (1, None), "NAME", ["WWN"])
        self.assertTrue(cache.is_group_name_cached("PORT", "NAME"))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_multi_port(self, cache):
        cache.cache("PORT", (1, None), None, ["WWN"])
        cache.cache("PORT2", (1, None), None, ["WWN"])
        cache.cache("PORT3", (1, None), None, [])
        self.assertEqual(3, len(cache._group_cache))
        self.assertEqual(2, len(cache._target_cache))
        self.assertEqual(0, len(cache._group_name_cache))
        self.assertTrue(
            cache._generate_group_key("PORT", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_key("PORT2", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT2", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_key("PORT3", 1) in cache._group_cache)
        self.assertFalse(
            cache._generate_target_key("PORT3", "WWN") in cache._target_cache)

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_multi_port_with_name(self, cache):
        cache.cache("PORT", (1, None), "NAME", ["WWN"])
        cache.cache("PORT2", (1, None), "NAME", ["WWN"])
        cache.cache("PORT3", (1, None), "NAME", [])
        self.assertEqual(3, len(cache._group_cache))
        self.assertEqual(2, len(cache._target_cache))
        self.assertEqual(3, len(cache._group_name_cache))
        self.assertTrue(
            cache._generate_group_key("PORT", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT", "NAME") in
            cache._group_name_cache)
        self.assertTrue(
            cache._generate_group_key("PORT2", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT2", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT2", "NAME") in
            cache._group_name_cache)
        self.assertTrue(
            cache._generate_group_key("PORT3", 1) in cache._group_cache)
        self.assertFalse(
            cache._generate_target_key("PORT3", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT3", "NAME") in
            cache._group_name_cache)

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_multi_wwn(self, cache):
        cache.cache("PORT", (1, None), None, ["WWN", "WWN2", "WWN3"])
        self.assertEqual(1, len(cache._group_cache))
        self.assertEqual(3, len(cache._target_cache))
        self.assertEqual(0, len(cache._group_name_cache))
        self.assertTrue(
            cache._generate_group_key("PORT", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN2") in cache._target_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN3") in cache._target_cache)

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_multi_wwn_with_name(self, cache):
        cache.cache("PORT", (1, None), "NAME", ["WWN", "WWN2", "WWN3"])
        self.assertEqual(1, len(cache._group_cache))
        self.assertEqual(3, len(cache._target_cache))
        self.assertEqual(1, len(cache._group_name_cache))
        self.assertTrue(
            cache._generate_group_key("PORT", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN2") in cache._target_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN3") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT", "NAME") in
            cache._group_name_cache)

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_no_wwn(self, cache):
        cache.cache("PORT", (1, None), None, [])
        self.assertEqual(1, len(cache._group_cache))
        self.assertEqual(0, len(cache._target_cache))
        self.assertEqual(0, len(cache._group_name_cache))
        self.assertTrue(
            cache._generate_group_key("PORT", 1) in cache._group_cache)

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_no_wwn_with_name(self, cache):
        cache.cache("PORT", (1, None), "NAME", [])
        self.assertEqual(1, len(cache._group_cache))
        self.assertEqual(0, len(cache._target_cache))
        self.assertEqual(1, len(cache._group_name_cache))
        self.assertTrue(
            cache._generate_group_key("PORT", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT", "NAME") in
            cache._group_name_cache)

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_clear_empty(self, cache):
        cache.clear()
        self.assertEqual(0, len(cache._group_cache))
        self.assertEqual(0, len(cache._target_cache))
        self.assertEqual(0, len(cache._group_name_cache))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_clear(self, cache):
        cache.cache("PORT", (1, None), "NAME", ["WWN"])
        cache.cache("PORT2", (1, None), "NAME", ["WWN"])
        cache.cache("PORT3", (1, None), "NAME", [])
        cache.clear()
        self.assertEqual(0, len(cache._group_cache))
        self.assertEqual(0, len(cache._target_cache))
        self.assertEqual(0, len(cache._group_name_cache))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_clear_group_empty(self, cache):
        cache.clear_group("PORT", 1)
        self.assertEqual(0, len(cache._group_cache))
        self.assertEqual(0, len(cache._target_cache))
        self.assertEqual(0, len(cache._group_name_cache))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_clear_group_not_found(self, cache):
        cache.cache("PORT", (1, None), "NAME", ["WWN"])
        cache.cache("PORT2", (1, None), "NAME", ["WWN"])
        cache.cache("PORT3", (1, None), "NAME", [])
        cache.clear_group("PORT", 7)
        self.assertEqual(3, len(cache._group_cache))
        self.assertEqual(2, len(cache._target_cache))
        self.assertEqual(3, len(cache._group_name_cache))
        self.assertTrue(
            cache._generate_group_key("PORT", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT", "NAME") in
            cache._group_name_cache)
        self.assertTrue(
            cache._generate_group_key("PORT2", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT2", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT2", "NAME") in
            cache._group_name_cache)
        self.assertTrue(
            cache._generate_group_key("PORT3", 1) in cache._group_cache)
        self.assertFalse(
            cache._generate_target_key("PORT3", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT3", "NAME") in
            cache._group_name_cache)

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_clear_group(self, cache):
        cache.cache("PORT", (1, None), "NAME", ["WWN"])
        cache.clear_group("PORT", 1)
        self.assertEqual(0, len(cache._group_cache))
        self.assertEqual(0, len(cache._target_cache))
        self.assertEqual(0, len(cache._group_name_cache))

    @ddt.data(hbsd_utils.ConnectorSearcherCache())
    def test_cache_clear_1_group(self, cache):
        cache.cache("PORT", (1, None), "NAME", ["WWN"])
        cache.cache("PORT2", (1, None), "NAME", ["WWN"])
        cache.cache("PORT3", (1, None), "NAME", [])
        cache.clear_group("PORT", 1)
        self.assertEqual(2, len(cache._group_cache))
        self.assertEqual(1, len(cache._target_cache))
        self.assertEqual(2, len(cache._group_name_cache))
        self.assertFalse(
            cache._generate_group_key("PORT", 1) in cache._group_cache)
        self.assertFalse(
            cache._generate_target_key("PORT", "WWN") in cache._target_cache)
        self.assertFalse(
            cache._generate_group_name_key("PORT", "NAME") in
            cache._group_name_cache)
        self.assertTrue(
            cache._generate_group_key("PORT2", 1) in cache._group_cache)
        self.assertTrue(
            cache._generate_target_key("PORT2", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT2", "NAME") in
            cache._group_name_cache)
        self.assertTrue(
            cache._generate_group_key("PORT3", 1) in cache._group_cache)
        self.assertFalse(
            cache._generate_target_key("PORT3", "WWN") in cache._target_cache)
        self.assertTrue(
            cache._generate_group_name_key("PORT3", "NAME") in
            cache._group_name_cache)


@ddt.ddt
class HBSDUtilsTest(test.TestCase):
    """Unit test class for HBSD utils."""

    def setUp(self):
        """Set up the test environment."""

        super(HBSDUtilsTest, self).setUp()

    def tearDown(self):
        super(HBSDUtilsTest, self).tearDown()

    def _init_driver_context(self, driver_name, drs_setting, drs_csv_setting):

        class MockConf(object):
            def __init__(self, drs_setting, drs_csv_setting):
                self.hitachi_use_drs_volumes = drs_setting
                self.hitachi_drs_default_csv = drs_csv_setting

        driver_info = {'driver_prefix': 'HBSD'}
        if driver_name is not None:
            driver_info['driver_dir_name'] = driver_name

        conf = MockConf(drs_setting, drs_csv_setting)

        return hbsd_utils.DriverContext(driver_info, conf, "ABCDEF123456")

    def _init_drs_csv_extra_specs(self, drs_extra_spec, csv_extra_spec):
        extra_specs = {}
        if drs_extra_spec is not None:
            extra_specs['hbsd:drs'] = drs_extra_spec
        if csv_extra_spec is not None:
            extra_specs['hbsd:capacity_saving'] = csv_extra_spec
        return extra_specs

    @ddt.data((("", False), False, "deduplication_compression", None, None,
               "hbsd"),
              (("", False), False, "deduplication_compression", "<is> False",
               None, "hbsd"),
              (("", False), True, "deduplication_compression", "<is> False",
               None, "hbsd"),
              (("", False), False, "compression", None, None,
               "hbsd"),
              (("", False), False, "compression", "<is> False",
               None, "hbsd"),
              (("", False), True, "compression", "<is> False",
               None, "hbsd"),
              (("deduplication_compression", False), False, "compression",
               None, "deduplication_compression", "hbsd"),
              (("compression", False), False, "deduplication_compression",
               None, "compression", "hbsd"),
              (("deduplication_compression", False), False, "compression",
               "<is> False", "deduplication_compression", "hbsd"),
              (("compression", False), False, "deduplication_compression",
               "<is> False", "compression", "hbsd"),
              (("deduplication_compression", True), False, "compression",
               "<is> True", "deduplication_compression", "hbsd"),
              (("compression", True), False, "deduplication_compression",
               "<is> True", "compression", "hbsd"),
              (("deduplication_compression", False), True, "compression",
               "<is> False", "deduplication_compression", "hbsd"),
              (("compression", False), True, "deduplication_compression",
               "<is> False", "compression", "hbsd"),
              (("deduplication_compression", True), True, "compression",
               "<is> True", "deduplication_compression", "hbsd"),
              (("compression", True), True, "deduplication_compression",
               "<is> True", "compression", "hbsd"),
              (("deduplication_compression", True), True, "compression",
               None, "deduplication_compression", "hbsd"),
              (("compression", True), True, "deduplication_compression",
               None, "compression", "hbsd"),
              (("", False), False, "disable", None, None, "hbsd"),
              (("", False), False, "disable", "<is> False", None, "hbsd"),
              (("", False), False, "", None, None, "hbsd"),
              (("", False), False, "", "<is> False", None, "hbsd"),
              (("", False), False, "invalid", None, None, "hbsd"),
              (("", False), False, "invalid", "<is> False", None, "hbsd"),
              (("", False), True, "disable", "<is> False", None, "hbsd"),
              (("", False), True, "", "<is> False", None, "hbsd"),
              (("", False), True, "invalid", "<is> False", None, "hbsd"),
              (("", False), "invalid", "deduplication_compression",
               "<is> False", None, "hbsd"),
              (("", False), False, "deduplication_compression", "<is> False",
               "deduplication_compression", None),
              (("", False), False, "deduplication_compression", "<is> True",
               "deduplication_compression", None),
              (("", False), False, "deduplication_compression", "invalid",
               "invalid", None),
              (("deduplication_compression", False), False,
               "deduplication_compression", None, "deduplication_compression",
               "hbsd"),
              (("deduplication_compression", False), False,
               "deduplication_compression", "<is> False",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), True,
               "deduplication_compression", "<is> False",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), False, "disable", None,
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), False, "disable",
               "<is> False", "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), False, "", None,
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), False, "", "<is> False",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), False, "invalid", None,
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), False, "invalid",
               "<is> False", "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), True, "disable",
               "<is> False", "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), True, "", "<is> False",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), True, "invalid",
               "<is> False", "deduplication_compression", "hbsd"),
              (("deduplication_compression", False), "invalid",
               "deduplication_compression", "<is> False",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), False,
               "deduplication_compression", "<is> True", None, "hbsd"),
              (("deduplication_compression", True), False,
               "deduplication_compression", "<is> True",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True,
               "deduplication_compression", None, None, "hbsd"),
              (("deduplication_compression", True), True,
               "deduplication_compression", None, "deduplication_compression",
               "hbsd"),
              (("deduplication_compression", True), True,
               "deduplication_compression", "<is> True", None, "hbsd"),
              (("deduplication_compression", True), True,
               "deduplication_compression", "<is> True",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), False, "disable",
               "<is> True", "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), False, "", "<is> True",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), False, "invalid",
               "<is> True", "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True, "disable", None,
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True, "disable",
               "<is> True", "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True, "", None,
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True, "", "<is> True",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True, "invalid", None,
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True, "invalid",
               "<is> True", "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), "invalid",
               "deduplication_compression", "<is> True", None, "hbsd"),
              (("deduplication_compression", True), "invalid",
               "deduplication_compression", "<is> True",
               "deduplication_compression", "hbsd"),
              (("deduplication_compression", True), True,
               "deduplication_compression", "<is> False", "disable", None),
              (("deduplication_compression", True), True,
               "deduplication_compression", "<is> True", "disable", None),
              (("deduplication_compression", True), True,
               "deduplication_compression", "invalid", "invalid", None),
              (("disable", False), False, "deduplication_compression", None,
               "disable", "hbsd"),
              (("disable", False), False, "deduplication_compression",
               "<is> False", "disable", "hbsd"),
              (("disable", False), True, "deduplication_compression",
               "<is> False", "disable", "hbsd"),
              (("", False), "invalid", "compression",
               "<is> False", None, "hbsd"),
              (("", False), False, "compression", "<is> False",
               "compression", None),
              (("", False), False, "compression", "<is> True",
               "compression", None),
              (("", False), False, "compression", "invalid",
               "invalid", None),
              (("compression", False), False,
               "compression", None, "compression",
               "hbsd"),
              (("compression", False), False,
               "compression", "<is> False",
               "compression", "hbsd"),
              (("compression", False), True,
               "compression", "<is> False",
               "compression", "hbsd"),
              (("compression", False), False, "disable", None,
               "compression", "hbsd"),
              (("compression", False), False, "disable",
               "<is> False", "compression", "hbsd"),
              (("compression", False), False, "", None,
               "compression", "hbsd"),
              (("compression", False), False, "", "<is> False",
               "compression", "hbsd"),
              (("compression", False), False, "invalid", None,
               "compression", "hbsd"),
              (("compression", False), False, "invalid",
               "<is> False", "compression", "hbsd"),
              (("compression", False), True, "disable",
               "<is> False", "compression", "hbsd"),
              (("compression", False), True, "", "<is> False",
               "compression", "hbsd"),
              (("compression", False), True, "invalid",
               "<is> False", "compression", "hbsd"),
              (("compression", False), "invalid",
               "compression", "<is> False",
               "compression", "hbsd"),
              (("compression", True), False,
               "compression", "<is> True", None, "hbsd"),
              (("compression", True), False,
               "compression", "<is> True",
               "compression", "hbsd"),
              (("compression", True), True,
               "compression", None, None, "hbsd"),
              (("compression", True), True,
               "compression", None, "compression",
               "hbsd"),
              (("compression", True), True,
               "compression", "<is> True", None, "hbsd"),
              (("compression", True), True,
               "compression", "<is> True",
               "compression", "hbsd"),
              (("compression", True), False, "disable",
               "<is> True", "compression", "hbsd"),
              (("compression", True), False, "", "<is> True",
               "compression", "hbsd"),
              (("compression", True), False, "invalid",
               "<is> True", "compression", "hbsd"),
              (("compression", True), True, "disable", None,
               "compression", "hbsd"),
              (("compression", True), True, "disable",
               "<is> True", "compression", "hbsd"),
              (("compression", True), True, "", None,
               "compression", "hbsd"),
              (("compression", True), True, "", "<is> True",
               "compression", "hbsd"),
              (("compression", True), True, "invalid", None,
               "compression", "hbsd"),
              (("compression", True), True, "invalid",
               "<is> True", "compression", "hbsd"),
              (("compression", True), "invalid",
               "compression", "<is> True", None, "hbsd"),
              (("compression", True), "invalid",
               "compression", "<is> True",
               "compression", "hbsd"),
              (("compression", True), True,
               "compression", "<is> False", "disable", None),
              (("compression", True), True,
               "compression", "<is> True", "disable", None),
              (("compression", True), True,
               "compression", "invalid", "invalid", None),
              (("disable", False), False, "compression", None,
               "disable", "hbsd"),
              (("disable", False), False, "compression",
               "<is> False", "disable", "hbsd"),
              (("disable", False), True, "compression",
               "<is> False", "disable", "hbsd"),
              (("disable", False), False, "disable", None, "disable", "hbsd"),
              (("disable", False), False, "disable", "<is> False", "disable",
               "hbsd"),
              (("disable", False), False, "", None, "disable", "hbsd"),
              (("disable", False), False, "", "<is> False", "disable", "hbsd"),
              (("disable", False), False, "invalid", None, "disable", "hbsd"),
              (("disable", False), False, "invalid", "<is> False", "disable",
               "hbsd"),
              (("disable", False), True, "disable", "<is> False", "disable",
               "hbsd"),
              (("disable", False), True, "", "<is> False", "disable", "hbsd"),
              (("disable", False), True, "invalid", "<is> False", "disable",
               "hbsd"),
              (("disable", False), "invalid", "deduplication_compression",
               "<is> False", "disable", "hbsd"),
              (("disable", False), "invalid", "compression",
               "<is> False", "disable", "hbsd"))
    @ddt.unpack
    def test_get_csv_and_drs(self, expected, drs_setting, drs_csv_setting,
                             drs_extra_spec, csv_extra_spec, driver_name):

        ctx = self._init_driver_context(driver_name, drs_setting,
                                        drs_csv_setting)
        extra_specs = self._init_drs_csv_extra_specs(drs_extra_spec,
                                                     csv_extra_spec)
        self.assertEqual(expected,
                         hbsd_utils.get_csv_and_drs(ctx, extra_specs))

    @ddt.data((False, "deduplication_compression", None, "invalid", "hbsd"),
              (False, "deduplication_compression", "<is> False", "invalid",
               "hbsd"),
              (False, "deduplication_compression", "<is> True", "disable",
               "hbsd"),
              (False, "deduplication_compression", "<is> True", "invalid",
               "hbsd"),
              (False, "deduplication_compression", "invalid", None, "hbsd"),
              (False, "deduplication_compression", "invalid", "disable",
               "hbsd"),
              (False, "deduplication_compression", "invalid",
               "deduplication_compression", "hbsd"),
              (False, "deduplication_compression", "invalid", "invalid",
               "hbsd"),
              (True, "deduplication_compression", None, "disable", "hbsd"),
              (True, "deduplication_compression", None, "invalid", "hbsd"),
              (True, "deduplication_compression", "<is> False", "invalid",
               "hbsd"),
              (True, "deduplication_compression", "<is> True", "disable",
               "hbsd"),
              (True, "deduplication_compression", "<is> True", "invalid",
               "hbsd"),
              (True, "deduplication_compression", "invalid", None, "hbsd"),
              (True, "deduplication_compression", "invalid", "disable",
               "hbsd"),
              (True, "deduplication_compression", "invalid",
               "deduplication_compression", "hbsd"),
              (True, "deduplication_compression", "invalid", "invalid",
               "hbsd"),
              (False, "compression", None, "invalid", "hbsd"),
              (False, "compression", "<is> False", "invalid",
               "hbsd"),
              (False, "compression", "<is> True", "disable",
               "hbsd"),
              (False, "compression", "<is> True", "invalid",
               "hbsd"),
              (False, "compression", "invalid", None, "hbsd"),
              (False, "compression", "invalid", "disable",
               "hbsd"),
              (False, "compression", "invalid",
               "compression", "hbsd"),
              (False, "compression", "invalid", "invalid",
               "hbsd"),
              (True, "compression", None, "disable", "hbsd"),
              (True, "compression", None, "invalid", "hbsd"),
              (True, "compression", "<is> False", "invalid",
               "hbsd"),
              (True, "compression", "<is> True", "disable",
               "hbsd"),
              (True, "compression", "<is> True", "invalid",
               "hbsd"),
              (True, "compression", "invalid", None, "hbsd"),
              (True, "compression", "invalid", "disable",
               "hbsd"),
              (True, "compression", "invalid",
               "compression", "hbsd"),
              (True, "compression", "invalid", "invalid",
               "hbsd"),
              (False, "disable", None, "invalid", "hbsd"),
              (False, "disable", "<is> False", "invalid", "hbsd"),
              (False, "disable", "<is> True", None, "hbsd"),
              (False, "disable", "<is> True", "disable", "hbsd"),
              (False, "disable", "<is> True", "invalid", "hbsd"),
              (False, "disable", "invalid", None, "hbsd"),
              (False, "disable", "invalid", "disable", "hbsd"),
              (False, "disable", "invalid", "deduplication_compression",
               "hbsd"),
              (False, "disable", "invalid", "compression",
               "hbsd"),
              (False, "disable", "invalid", "invalid", "hbsd"),
              (False, "", None, "invalid", "hbsd"),
              (False, "", "<is> False", "invalid", "hbsd"),
              (False, "", "<is> True", None, "hbsd"),
              (False, "", "<is> True", "disable", "hbsd"),
              (False, "", "<is> True", "invalid", "hbsd"),
              (False, "", "invalid", None, "hbsd"),
              (False, "", "invalid", "disable", "hbsd"),
              (False, "", "invalid", "deduplication_compression", "hbsd"),
              (False, "", "invalid", "compression", "hbsd"),
              (False, "", "invalid", "invalid", "hbsd"),
              (False, "invalid", None, "invalid", "hbsd"),
              (False, "invalid", "<is> False", "invalid", "hbsd"),
              (False, "invalid", "<is> True", None, "hbsd"),
              (False, "invalid", "<is> True", "disable", "hbsd"),
              (False, "invalid", "<is> True", "invalid", "hbsd"),
              (False, "invalid", "invalid", None, "hbsd"),
              (False, "invalid", "invalid", "disable", "hbsd"),
              (False, "invalid", "invalid", "deduplication_compression",
               "hbsd"),
              (False, "invalid", "invalid", "compression",
               "hbsd"),
              (False, "invalid", "invalid", "invalid", "hbsd"),
              (True, "disable", None, None, "hbsd"),
              (True, "disable", None, "disable", "hbsd"),
              (True, "disable", None, "invalid", "hbsd"),
              (True, "disable", "<is> False", "invalid", "hbsd"),
              (True, "disable", "<is> True", None, "hbsd"),
              (True, "disable", "<is> True", "disable", "hbsd"),
              (True, "disable", "<is> True", "invalid", "hbsd"),
              (True, "disable", "invalid", None, "hbsd"),
              (True, "disable", "invalid", "disable", "hbsd"),
              (True, "disable", "invalid", "deduplication_compression",
               "hbsd"),
              (True, "disable", "invalid", "compression",
               "hbsd"),
              (True, "disable", "invalid", "invalid", "hbsd"),
              (True, "", None, None, "hbsd"),
              (True, "", None, "disable", "hbsd"),
              (True, "", None, "invalid", "hbsd"),
              (True, "", "<is> False", "invalid", "hbsd"),
              (True, "", "<is> True", None, "hbsd"),
              (True, "", "<is> True", "disable", "hbsd"),
              (True, "", "<is> True", "invalid", "hbsd"),
              (True, "", "invalid", None, "hbsd"),
              (True, "", "invalid", "disable", "hbsd"),
              (True, "", "invalid", "deduplication_compression", "hbsd"),
              (True, "", "invalid", "compression", "hbsd"),
              (True, "", "invalid", "invalid", "hbsd"),
              (True, "invalid", None, None, "hbsd"),
              (True, "invalid", None, "disable", "hbsd"),
              (True, "invalid", None, "invalid", "hbsd"),
              (True, "invalid", "<is> False", "invalid", "hbsd"),
              (True, "invalid", "<is> True", None, "hbsd"),
              (True, "invalid", "<is> True", "disable", "hbsd"),
              (True, "invalid", "<is> True", "invalid", "hbsd"),
              (True, "invalid", "invalid", None, "hbsd"),
              (True, "invalid", "invalid", "disable", "hbsd"),
              (True, "invalid", "invalid", "deduplication_compression",
               "hbsd"),
              (True, "invalid", "invalid", "compression",
               "hbsd"),
              (True, "invalid", "invalid", "invalid", "hbsd"),
              ("invalid", "deduplication_compression", None, None, "hbsd"),
              ("invalid", "deduplication_compression", None, "disable",
               "hbsd"),
              ("invalid", "deduplication_compression", None,
               "deduplication_compression", "hbsd"),
              ("invalid", "deduplication_compression", None, "invalid",
               "hbsd"),
              ("invalid", "deduplication_compression", "<is> False", "invalid",
               "hbsd"),
              ("invalid", "deduplication_compression", "<is> True", "disable",
               "hbsd"),
              ("invalid", "deduplication_compression", "<is> True", "invalid",
               "hbsd"),
              ("invalid", "deduplication_compression", "invalid", None,
               "hbsd"),
              ("invalid", "deduplication_compression", "invalid", "disable",
               "hbsd"),
              ("invalid", "deduplication_compression", "invalid",
               "deduplication_compression", "hbsd"),
              ("invalid", "deduplication_compression", "invalid", "invalid",
               "hbsd"),
              ("invalid", "compression", None, None, "hbsd"),
              ("invalid", "compression", None, "disable",
               "hbsd"),
              ("invalid", "compression", None,
               "compression", "hbsd"),
              ("invalid", "compression", None, "invalid",
               "hbsd"),
              ("invalid", "compression", "<is> False", "invalid",
               "hbsd"),
              ("invalid", "compression", "<is> True", "disable",
               "hbsd"),
              ("invalid", "compression", "<is> True", "invalid",
               "hbsd"),
              ("invalid", "compression", "invalid", None,
               "hbsd"),
              ("invalid", "compression", "invalid", "disable",
               "hbsd"),
              ("invalid", "compression", "invalid",
               "compression", "hbsd"),
              ("invalid", "compression", "invalid", "invalid",
               "hbsd"))
    @ddt.unpack
    def test_get_csv_and_drs_negative(self, drs_setting, drs_csv_setting,
                                      drs_extra_spec, csv_extra_spec,
                                      driver_name):
        ctx = self._init_driver_context(driver_name, drs_setting,
                                        drs_csv_setting)
        extra_specs = self._init_drs_csv_extra_specs(drs_extra_spec,
                                                     csv_extra_spec)
        self.assertRaises(exception.VolumeDriverException,
                          hbsd_utils.get_csv_and_drs,
                          ctx, extra_specs)

    @ddt.data((("", False), True, "deduplication_compression", None, "",
              "hbsd"),
              (("", False), True, "deduplication_compression", "<is> False",
               "", "hbsd"),
              (("", False), True, "compression", None, "",
              "hbsd"),
              (("", False), True, "compression", "<is> False",
               "", "hbsd"),
              (("disable", False), "invalid", "invalid", "<is> False",
               "disable", "hbsd"),
              (("deduplication_compression", True), "invalid",
               "invalid", "<is> True", "deduplication_compression", "hbsd"),
              (("compression", True), "invalid",
               "invalid", "<is> True", "compression", "hbsd"))
    @ddt.unpack
    def test_get_csv_and_drs_specs_only(self, expected, drs_setting,
                                        drs_csv_setting,
                                        drs_extra_spec, csv_extra_spec,
                                        driver_name):

        ctx = self._init_driver_context(driver_name, drs_setting,
                                        drs_csv_setting)
        extra_specs = self._init_drs_csv_extra_specs(drs_extra_spec,
                                                     csv_extra_spec)
        self.assertEqual(expected,
                         hbsd_utils.get_csv_and_drs(ctx, extra_specs,
                                                    specs_only=True))
