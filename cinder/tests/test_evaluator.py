# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
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

from cinder import exception
from cinder.scheduler.evaluator import evaluator
from cinder import test


class EvaluatorTestCase(test.TestCase):
    def test_simple_integer(self):
        self.assertEqual(2, evaluator.evaluate("1+1"))
        self.assertEqual(9, evaluator.evaluate("2+3+4"))
        self.assertEqual(23, evaluator.evaluate("11+12"))
        self.assertEqual(30, evaluator.evaluate("5*6"))
        self.assertEqual(2, evaluator.evaluate("22/11"))
        self.assertEqual(38, evaluator.evaluate("109-71"))
        self.assertEqual(
            493, evaluator.evaluate("872 - 453 + 44 / 22 * 4 + 66"))

    def test_simple_float(self):
        self.assertEqual(2.0, evaluator.evaluate("1.0 + 1.0"))
        self.assertEqual(2.5, evaluator.evaluate("1.5 + 1.0"))
        self.assertEqual(3.0, evaluator.evaluate("1.5 * 2.0"))

    def test_int_float_mix(self):
        self.assertEqual(2.5, evaluator.evaluate("1.5 + 1"))
        self.assertEqual(4.25, evaluator.evaluate("8.5 / 2"))
        self.assertEqual(5.25, evaluator.evaluate("10/4+0.75    + 2"))

    def test_negative_numbers(self):
        self.assertEqual(-2, evaluator.evaluate("-2"))
        self.assertEqual(-1, evaluator.evaluate("-2+1"))
        self.assertEqual(3, evaluator.evaluate("5+-2"))

    def test_exponent(self):
        self.assertEqual(8, evaluator.evaluate("2^3"))
        self.assertEqual(-8, evaluator.evaluate("-2 ^ 3"))
        self.assertEqual(15.625, evaluator.evaluate("2.5 ^ 3"))
        self.assertEqual(8, evaluator.evaluate("4 ^ 1.5"))

    def test_function(self):
        self.assertEqual(5, evaluator.evaluate("abs(-5)"))
        self.assertEqual(2, evaluator.evaluate("abs(2)"))
        self.assertEqual(1, evaluator.evaluate("min(1, 100)"))
        self.assertEqual(100, evaluator.evaluate("max(1, 100)"))

    def test_parentheses(self):
        self.assertEqual(1, evaluator.evaluate("(1)"))
        self.assertEqual(-1, evaluator.evaluate("(-1)"))
        self.assertEqual(2, evaluator.evaluate("(1+1)"))
        self.assertEqual(15, evaluator.evaluate("(1+2) * 5"))
        self.assertEqual(3, evaluator.evaluate("(1+2)*(3-1)/((1+(2-1)))"))
        self.assertEqual(
            -8.0, evaluator. evaluate("((1.0 / 0.5) * (2)) *(-2)"))

    def test_comparisons(self):
        self.assertTrue(evaluator.evaluate("1 < 2"))
        self.assertTrue(evaluator.evaluate("2 > 1"))
        self.assertTrue(evaluator.evaluate("2 != 1"))
        self.assertFalse(evaluator.evaluate("1 > 2"))
        self.assertFalse(evaluator.evaluate("2 < 1"))
        self.assertFalse(evaluator.evaluate("2 == 1"))
        self.assertTrue(evaluator.evaluate("(1 == 1) == !(1 == 2)"))

    def test_logic_ops(self):
        self.assertTrue(evaluator.evaluate("(1 == 1) AND (2 == 2)"))
        self.assertTrue(evaluator.evaluate("(1 == 1) and (2 == 2)"))
        self.assertTrue(evaluator.evaluate("(1 == 1) && (2 == 2)"))
        self.assertFalse(evaluator.evaluate("(1 == 1) && (5 == 2)"))

        self.assertTrue(evaluator.evaluate("(1 == 1) OR (5 == 2)"))
        self.assertTrue(evaluator.evaluate("(1 == 1) or (5 == 2)"))
        self.assertTrue(evaluator.evaluate("(1 == 1) || (5 == 2)"))
        self.assertFalse(evaluator.evaluate("(5 == 1) || (5 == 2)"))

        self.assertFalse(evaluator.evaluate("(1 == 1) AND NOT (2 == 2)"))
        self.assertFalse(evaluator.evaluate("(1 == 1) AND not (2 == 2)"))
        self.assertFalse(evaluator.evaluate("(1 == 1) AND !(2 == 2)"))
        self.assertTrue(evaluator.evaluate("(1 == 1) AND NOT (5 == 2)"))
        self.assertTrue(evaluator.evaluate("(1 == 1) OR NOT (2 == 2) "
                                           "AND (5 == 5)"))

    def test_ternary_conditional(self):
        self.assertEqual(5, evaluator.evaluate("(1 < 2) ? 5 : 10"))
        self.assertEqual(10, evaluator.evaluate("(1 > 2) ? 5 : 10"))

    def test_variables_dict(self):
        stats = {'iops': 1000, 'usage': 0.65, 'count': 503, 'free_space': 407}
        request = {'iops': 500, 'size': 4}
        self.assertEqual(1500, evaluator.evaluate("stats.iops + request.iops",
                                                  stats=stats,
                                                  request=request))

    def test_missing_var(self):
        stats = {'iops': 1000, 'usage': 0.65, 'count': 503, 'free_space': 407}
        request = {'iops': 500, 'size': 4}
        self.assertRaises(exception.EvaluatorParseException,
                          evaluator.evaluate,
                          "foo.bob + 5",
                          stats=stats, request=request)
        self.assertRaises(exception.EvaluatorParseException,
                          evaluator.evaluate,
                          "stats.bob + 5",
                          stats=stats, request=request)
        self.assertRaises(exception.EvaluatorParseException,
                          evaluator.evaluate,
                          "fake.var + 1",
                          stats=stats, request=request, fake=None)

    def test_bad_expression(self):
        self.assertRaises(exception.EvaluatorParseException,
                          evaluator.evaluate,
                          "1/*1")

    def test_nonnumber_comparison(self):
        nonnumber = {'test': 'foo'}
        request = {'test': 'bar'}
        self.assertRaises(
            exception.EvaluatorParseException,
            evaluator.evaluate,
            "nonnumber.test != request.test",
            nonnumber=nonnumber, request=request)

    def test_div_zero(self):
        self.assertRaises(exception.EvaluatorParseException,
                          evaluator.evaluate,
                          "7 / 0")
