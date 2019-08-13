Continuous Integration with Zuul
================================

Cinder uses `Zuul`_ as project gating system. The Zuul web front-end is at
https://status.opendev.org.

Zuul ensures that only tested code gets merged. The configuration is
mainly done in `cinder's .zuul.yaml`_ file.

The following is a partial list of jobs that are configured to run on
changes. Test jobs run initially on proposed changes and get run again
after review and approval. Note that for each job run the code gets
rebased to current HEAD to test exactly the state that gets merged.

openstack-tox-pep8
    Run linters like PEP8 checks.

openstack-tox-pylint
    Run Pylint checks.

openstack-tox-python27
    Run unit tests using python2.7.

openstack-tox-python36
    Run unit tests using python3.6.

openstack-tox-docs
    Build this documentation for review.

The following jobs are some of the jobs that run after a change is
merged:

publish-openstack-tox-docs
    Build this documentation and publish to
    `OpenStack Cinder <https://docs.openstack.org/cinder/latest/>`_.

publish-openstack-python-branch-tarball
    Do ``python setup.py sdist`` to create a tarball of the cinder code and
    upload it to http://tarballs.openstack.org/cinder.

.. _Zuul: https://zuul-ci.org
.. _cinder's .zuul.yaml: https://opendev.org/openstack/cinder/src/.zuul.yaml
