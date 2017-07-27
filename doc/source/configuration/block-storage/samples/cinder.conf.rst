===========
cinder.conf
===========

The ``cinder.conf`` file is installed in ``/etc/cinder`` by default.
When you manually install the Block Storage service, the options in the
``cinder.conf`` file are set to default values.

The ``cinder.conf`` file contains most of the options needed to configure
the Block Storage service. You can generate the latest configuration file
by using the tox provided by the Block Storage service. Here is a sample
configuration file:

.. literalinclude:: ../../../_static/cinder.conf.sample
   :language: ini
