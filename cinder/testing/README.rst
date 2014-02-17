=====================================
OpenStack Cinder Testing Infrastructure
=====================================

A note of clarification is in order, to help those who are new to testing in
OpenStack cinder:

- actual unit tests are created in the "tests" directory;
- the "testing" directory is used to house the infrastructure needed to support
  testing in OpenStack Cinder.

This README file attempts to provide current and prospective contributors with
everything they need to know in order to start creating unit tests and
utilizing the convenience code provided in cinder.testing.

For more detailed information on cinder unit tests visit:
http://docs.openstack.org/developer/cinder/devref/unit_tests.html

Running Tests
-----------------------------------------------

In the root of the cinder source code run the run_tests.sh script. This will
offer to create a virtual environment and populate it with dependencies.
If you don't have dependencies installed that are needed for compiling cinder's
direct dependencies, you'll have to use your operating system's method of
installing extra dependencies. To get help using this script execute it with
the -h parameter to get options `./run_tests.sh -h`

Writing Unit Tests
------------------

- All new unit tests are to be written in python-mock.
- Old tests that are still written in mox should be updated to use python-mock.
    Usage of mox has been deprecated for writing Cinder unit tests.
- use addCleanup in favor of tearDown
