Continuous Integration with Jenkins
===================================

Cinder uses a `Jenkins`_ server to automate development tasks. The Jenkins
front-end is at http://jenkins.openstack.org. You must have an
account on `Launchpad`_ to be able to access the OpenStack Jenkins site.

Jenkins performs tasks such as:

`gate-cinder-unittests`_
    Run unit tests on proposed code changes that have been reviewed.

`gate-cinder-pep8`_
    Run PEP8 checks on proposed code changes that have been reviewed.

`gate-cinder-merge`_
    Merge reviewed code into the git repository.

`cinder-coverage`_
    Calculate test coverage metrics.

`cinder-docs`_
    Build this documentation and push it to http://cinder.openstack.org.

`cinder-tarball`_
    Do ``python setup.py sdist`` to create a tarball of the cinder code and upload
    it to http://cinder.openstack.org/tarballs

.. _Jenkins: http://jenkins-ci.org
.. _Launchpad: http://launchpad.net
.. _gate-cinder-merge: https://jenkins.openstack.org/view/Cinder/job/gate-cinder-merge
.. _gate-cinder-pep8: https://jenkins.openstack.org/view/Cinder/job/gate-cinder-pep8
.. _gate-cinder-unittests: https://jenkins.openstack.org/view/Cinder/job/gate-cinder-unittests
.. _cinder-coverage: https://jenkins.openstack.org/view/Cinder/job/cinder-coverage
.. _cinder-docs: https://jenkins.openstack.org/view/Cinder/job/cinder-docs
.. _cinder-pylint: https://jenkins.openstack.org/job/cinder-pylint
.. _cinder-tarball: https://jenkins.openstack.org/job/cinder-tarball
