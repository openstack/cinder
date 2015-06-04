Rally job related files
=======================

This directory contains rally tasks and plugins that are run by OpenStack CI.

Structure
---------

* cinder.yaml is a task that will be run in gates against OpenStack deployed
  by DevStack.

* cinder-fake.yaml is a task that will be run in gates against OpenStack
  deployed by DevStack with fake cinder driver.

* plugins - directory where you can add rally plugins. Almost everything in
  Rally is plugin. Benchmark context, Benchmark scenario, SLA checks, Generic
  cleanup resources, ....

* extra - all files from this directory will be copy pasted to gates, so you
  are able to use absolute path in rally tasks.
  Files will be in ~/.rally/extra/*


Useful links
------------

* More about Rally: https://rally.readthedocs.org/en/latest/

* Rally release notes: https://rally.readthedocs.org/en/latest/release_notes.html

* How to add rally-gates: https://rally.readthedocs.org/en/latest/gates.html

* About plugins:  https://rally.readthedocs.org/en/latest/plugins.html

* Plugin samples: https://github.com/openstack/rally/tree/master/samples/plugins
