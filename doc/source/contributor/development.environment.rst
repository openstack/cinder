..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Setting Up a Development Environment
====================================

This page describes how to setup a working Python development environment that
can be used in developing cinder on Ubuntu, Fedora or macOS. These instructions
assume you're already familiar with git. Refer to GettingTheCode_ for
additional information.

.. _GettingTheCode: https://wiki.openstack.org/wiki/Getting_The_Code

Following these instructions will allow you to run the cinder unit tests.
Running cinder is currently only supported on Linux. Some jobs can be run on
macOS, but unfortunately due to some differences in system packages there are
known issues with running unit tests.

Virtual environments
--------------------

Cinder development uses `virtualenv <https://pypi.org/project/virtualenv>`__
to track and manage Python dependencies while in development and testing. This
allows you to install all of the Python package dependencies in a virtual
environment or "virtualenv" (a special subdirectory of your cinder directory),
instead of installing the packages at the system level.

.. note::

   Virtualenv is useful for running the unit tests, but is not
   typically used for full integration testing or production usage.

Linux Systems
-------------

.. note::

   If you have Ansible and git installed on your system, you may be able to
   get a working development environment quickly set up by running the
   following:

   .. code::

      sudo ansible-pull -U https://github.com/stmcginnis/cinder-dev-setup

   If that does not work for your system, continue on with the manual steps
   below.

Install the prerequisite packages.

On Ubuntu16.04-64::

  sudo apt-get install python-dev libssl-dev python-pip git-core libmysqlclient-dev libpq-dev libffi-dev libxslt-dev

To get a full python3 development environment, the two python3 packages need to
be added to the list above::

  python3-dev python3-pip

On Red Hat-based distributions e.g., Fedora/RHEL/CentOS/Scientific Linux
(tested on CentOS 6.5 and CentOS 7.3)::

  sudo yum install python-virtualenv openssl-devel python-pip git gcc libffi-devel libxslt-devel mysql-devel postgresql-devel

On openSUSE-based distributions (SLES 12, openSUSE 13.1, Factory or
Tumbleweed)::

  sudo zypper install gcc git libmysqlclient-devel libopenssl-devel postgresql-devel python-devel python-pip


macOS Systems
-------------

Install virtualenv::

    sudo pip install virtualenv

Check the version of OpenSSL you have installed::

    openssl version

If you have installed OpenSSL 1.0.0a, which can happen when installing a
MacPorts package for OpenSSL, you will see an error when running
``cinder.tests.auth_unittest.AuthTestCase.test_209_can_generate_x509``.

The stock version of OpenSSL that ships with Mac OS X 10.6 (OpenSSL 0.9.8l)
or later should work fine with cinder.


Getting the code
----------------
Grab the code::

    git clone https://opendev.org/openstack/cinder.git
    cd cinder


Running unit tests
------------------
The preferred way to run the unit tests is using ``tox``. It executes tests in
isolated environment, by creating separate virtualenv and installing
dependencies from the ``requirements.txt`` and ``test-requirements.txt`` files,
so the only package you install is ``tox`` itself::

    sudo pip install tox

Run the unit tests by doing::

    tox -e py35
    tox -e py27

See :doc:`testing` for more details.

.. _virtualenv:

Manually installing and using the virtualenv
--------------------------------------------

You can also manually install the virtual environment::

  tox -e py27 --notest

or::

  tox -e py35 --notest

This will install all of the Python packages listed in the
``requirements.txt`` file into your virtualenv.

To activate the Cinder virtualenv you can run::

     $ source .tox/py27/bin/activate

or::

     $ source .tox/py35/bin/activate

To exit your virtualenv, just type::

     $ deactivate

Or, if you prefer, you can run commands in the virtualenv on a case by case
basis by running::

     $ tox -e venv -- <your command>

Contributing Your Work
----------------------

Once your work is complete you may wish to contribute it to the project.
Cinder uses the Gerrit code review system. For information on how to submit
your branch to Gerrit, see GerritWorkflow_.

.. _GerritWorkflow: https://docs.openstack.org/infra/manual/developers.html#development-workflow
