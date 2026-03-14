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
    """Unit test class for HBSD utils."""

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
