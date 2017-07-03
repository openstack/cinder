Cinder Style Commandments
=========================

- Step 1: Read the OpenStack Style Commandments
  http://docs.openstack.org/developer/hacking/
- Step 2: Read on

Cinder Specific Commandments
----------------------------
- [N314] Check for vi editor configuration in source files.
- [N322] Ensure default arguments are not mutable.
- [N323] Add check for explicit import of _() to ensure proper translation.
- [N325] str() and unicode() cannot be used on an exception. Remove or use six.text_type().
- [N336] Must use a dict comprehension instead of a dict constructor with a sequence of key-value pairs.
- [C301] timeutils.utcnow() from oslo_utils should be used instead of datetime.now().
- [C302] six.text_type should be used instead of unicode.
- [C303] Ensure that there are no 'print()' statements in code that is being committed.
- [C304] Enforce no use of LOG.audit messages. LOG.info should be used instead.
- [C305] Prevent use of deprecated contextlib.nested.
- [C306] timeutils.strtime() must not be used (deprecated).
- [C307] LOG.warn is deprecated. Enforce use of LOG.warning.
- [C308] timeutils.isotime() must not be used (deprecated).
- [C309] Unit tests should not perform logging.
- [C310] Check for improper use of logging format arguments.
- [C311] Check for proper naming and usage in option registration.
- [C312] Validate that logs are not translated.
- [C313] Check that assertTrue(value) is used and not assertEqual(True, value).

General
-------
- Use 'raise' instead of 'raise e' to preserve original traceback or exception being reraised::

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

Cinder is transitioning to use mock, rather than mox, and so new tests should
use mock only.

For more information on creating unit tests and utilizing the testing
infrastructure in OpenStack Cinder, please see
http://docs.openstack.org/developer/cinder/devref/testing.html
