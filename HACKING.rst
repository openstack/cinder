Cinder Style Commandments
=========================

- Step 1: Read the OpenStack Style Commandments
  https://docs.openstack.org/hacking/latest/
- Step 2: Read on

Cinder Specific Commandments
----------------------------
- [N322] Ensure default arguments are not mutable.
- [N323] Add check for explicit import of _() to ensure proper translation.
- [C301] timeutils.utcnow() from oslo_utils should be used instead of
  datetime.now().
- [C303] Ensure that there are no 'print()' statements are used in code that
  should be using LOG calls.
- [C306] timeutils.strtime() must not be used (deprecated).
- [C308] timeutils.isotime() must not be used (deprecated).
- [C309] Unit tests should not perform logging.
- [C310] Check for improper use of logging format arguments.
- [C311] Check for proper naming and usage in option registration.
- [C312] Validate that logs are not translated.
- [C313] Check that assertTrue(value) is used and not assertEqual(True, value).
- [C336] Must use a dict comprehension instead of a dict constructor with a
  sequence of key-value pairs.
- [C337] Ensure the standard library mock modules is used and not the third
  party mock library that was needed for Python 2 support.

General
-------
- Use 'raise' instead of 'raise e' to preserve original traceback or exception
  being reraised::

    except Exception as e:
        ...
        raise e  # BAD

    except Exception:
        ...
        raise  # OKAY



Creating Unit Tests
-------------------
For every new feature, unit tests should be created that both test and
(implicitly) document the usage of said feature. If submitting a patch for a
bug that had no unit test, a new passing unit test should be added. If a
submitted bug fix does have a unit test, be sure to add a new one that fails
without the patch and passes with the patch.

For more information on creating unit tests and utilizing the testing
infrastructure in OpenStack Cinder, please see
https://docs.openstack.org/cinder/latest/contributor/testing.html
