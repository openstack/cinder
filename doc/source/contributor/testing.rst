Testing
=======

Cinder contains a few different test suites in the cinder/tests/ directory. The
different test suites are Unit Tests, Functional Tests, and Tempest Tests.

Test Types
----------


Unit Tests
~~~~~~~~~~

Unit tests are tests for individual methods, with at most a small handful of
modules involved. Mock should be used to remove any external dependencies.

All significant code changes should have unit test coverage validating the code
happy path and any failure paths.

Any proposed code change will be automatically rejected by the OpenStack
Jenkins server [#f1]_ if the change causes unit test failures.

Functional Tests
~~~~~~~~~~~~~~~~

Functional tests validate a code path within Cinder. These tests should
validate the interaction of various modules within the project to verify the
code is logically correct.

Functional tests run with a database present and may start Cinder services to
accept requests. These tests should not need to access an other OpenStack
non-Cinder services.

Tempest Tests
~~~~~~~~~~~~~

The tempest tests in the Cinder tree validate the operational correctness
between Cinder and external components such as Nova, Glance, etc. These are
integration tests driven via public APIs to verify actual end user usage
scenarios.

Running the tests
-----------------

There are a number of ways to run tests currently, and there's a combination of
frameworks used depending on what commands you use. The preferred method is to
use tox, which calls ostestr via the tox.ini file.

Unit Tests
~~~~~~~~~~

To run all unit tests simply run::

    tox

This will create a virtual environment, load all the packages from
test-requirements.txt and run all unit tests as well as run flake8 and hacking
checks against the code.

You may run individual test targets, for example only py27 tests, by running::

    tox -e py27

Note that you can inspect the tox.ini file to get more details on the available
options and what the test run does by default.

Functional Tests
~~~~~~~~~~~~~~~~

To run all functional tests, run::

    tox -e functional

Tempest Tests
~~~~~~~~~~~~~

Tempest tests in the Cinder tree are "plugged in" to the normal tempest test
execution. To ensure the Cinder tests are picked up when running tempest, run::

    cd /opt/stack/tempest
    tox -e all-plugin

More information about tempest can be found in the `Tempest Documentation
<http://docs.openstack.org/developer/tempest/overview.html>`_.

Database Setup
~~~~~~~~~~~~~~~

Some unit and functional tests will use a local database. You can use
``tools/test-setup.sh`` to set up your local system the same way as
it's setup in the CI environment.

Running a subset of tests using tox
-----------------------------------
One common activity is to just run a single test, you can do this with tox
simply by specifying to just run py27 or py35 tests against a single test::

    tox -epy27 -- -n cinder.tests.unit.test_volume.AvailabilityZoneTestCase.test_list_availability_zones_cached

Or all tests in the test_volume.py file::

    tox -epy27 -- -n cinder.tests.unit.test_volume

You may also use regular expressions to run any matching tests::

    tox -epy27 -- -r test_volume

For more information on these options and how to run tests, please see the
`ostestr documentation <http://docs.openstack.org/developer/os-testr/>`_.

Gotchas
-------

**Running Tests from Shared Folders**

If you are running the unit tests from a shared folder, you may see tests start
to fail or stop completely as a result of Python lockfile issues. You
can get around this by manually setting or updating the following line in
``cinder/tests/conf_fixture.py``::

    CONF['lock_path'].SetDefault('/tmp')

Note that you may use any location (not just ``/tmp``!) as long as it is not
a shared folder.

**Running py35 tests**

You will need to install python3-dev in order to get py35 tests to run. If you
do not have this, you will get the following::

    netifaces.c:1:20: fatal error: Python.h: No such file or directory
        #include <Python.h>
                ^
        compilation terminated.
        error: command 'x86_64-linux-gnu-gcc' failed with exit status 1

        ----------------------------------------
        <snip>
    ERROR: could not install deps [-r/opt/stack/cinder/test-requirements.txt,
        oslo.versionedobjects[fixtures]]; v = InvocationError('/opt/stack/cinder/
        .tox/py35/bin/pip install -r/opt/stack/cinder/test-requirements.txt
        oslo.versionedobjects[fixtures] (see /opt/stack/cinder/.tox/py35/log/py35-1.log)', 1)
    _______________________________________________________________ summary _______________________________________________________________
    ERROR:   py35: could not install deps [-r/opt/stack/cinder/test-requirements.txt,
        oslo.versionedobjects[fixtures]]; v = InvocationError('/opt/stack/cinder/
        .tox/py35/bin/pip install -r/opt/stack/cinder/test-requirements.txt
        oslo.versionedobjects[fixtures] (see /opt/stack/cinder/.tox/py35/log/py35-1.log)', 1)

To Fix:

- On Ubuntu/Debian::

    sudo apt-get install python3-dev

- On Fedora 21/RHEL7/CentOS7::

    sudo yum install python3-devel

- On Fedora 22 and higher::

    sudo dnf install python3-devel

.. rubric:: Footnotes

.. [#f1] See :doc:`jenkins`.
