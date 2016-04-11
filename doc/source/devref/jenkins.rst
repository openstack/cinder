Continuous Integration with Jenkins
===================================

Cinder uses a `Jenkins`_ server to automate development tasks. The Jenkins
front-end is at http://jenkins.openstack.org. You must have an
account on `Launchpad`_ to be able to access the OpenStack Jenkins site.

Jenkins performs tasks such as:

`gate-cinder-pep8`_
    Run PEP8 checks on proposed code changes that have been reviewed.

`gate-cinder-pylint`_
    Run Pylint checks on proposed code changes that have been reviewed.

`gate-cinder-python27`_
    Run unit tests using python2.7 on proposed code changes that have been reviewed.

`gate-cinder-python34`_
    Run unit tests using python3.4 on proposed code changes that have been reviewed.

`cinder-coverage`_
    Calculate test coverage metrics.

`cinder-docs`_
    Build this documentation and push it to http://cinder.openstack.org.

`cinder-merge-release-tags`_
    Merge reviewed code into the git repository.

`cinder-tarball`_
    Do ``python setup.py sdist`` to create a tarball of the cinder code and upload
    it to http://cinder.openstack.org/tarballs

.. _Jenkins: http://jenkins-ci.org
.. _Launchpad: http://launchpad.net
.. _gate-cinder-pep8: https://jenkins.openstack.org/job/gate-cinder-pep8
.. _gate-cinder-pylint: https://jenkins.openstack.org/job/gate-cinder-pylint
.. _gate-cinder-python27: https://jenkins.openstack.org/job/gate-cinder-python27
.. _gate-cinder-python34: https://jenkins.openstack.org/job/gate-cinder-python34
.. _cinder-coverage: https://jenkins.openstack.org/job/cinder-coverage
.. _cinder-docs: https://jenkins.openstack.org/job/cinder-docs
.. _cinder-merge-release-tags: https://jenkins.openstack.org/job/cinder-merge-release-tags
.. _cinder-tarball: https://jenkins.openstack.org/job/cinder-tarball
