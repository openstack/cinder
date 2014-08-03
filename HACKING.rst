Cinder Style Commandments
=========================

- Step 1: Read the OpenStack Style Commandments
  http://docs.openstack.org/developer/hacking/
- Step 2: Read on

Cinder Specific Commandments
----------------------------
- [N314] Check for vi editor configuration in source files.
- [N319] Validate that debug level logs are not translated
- [N322] Ensure default arguments are not mutable.
- [N323] Add check for explicit import of _() to ensure proper translation.
- [N324] Enforce no use of LOG.audit messages.  LOG.info should be used instead.


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
infrastructure in OpenStack Cinder, please read the Cinder testing
`README.rst <https://github.com/openstack/cinder/blob/master/cinder/testing/README.rst>`_.
