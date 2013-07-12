Cinder Style Commandments
=========================

- Step 1: Read the OpenStack Style Commandments
  https://github.com/openstack-dev/hacking/blob/master/HACKING.rst
- Step 2: Read on

Cinder Specific Commandments
----------------------------

General
-------
- Do not use locals(). Example::

    LOG.debug(_("volume %(vol_name)s: creating size %(vol_size)sG") %
              locals()) # BAD

    LOG.debug(_("volume %(vol_name)s: creating size %(vol_size)sG") %
              {'vol_name': vol_name,
               'vol_size': vol_size}) # OKAY

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

For more information on creating unit tests and utilizing the testing
infrastructure in OpenStack Cinder, please read cinder/testing/README.rst.
