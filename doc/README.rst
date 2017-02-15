=======================
Cinder Development Docs
=======================

Files under this directory tree are used for generating the documentation
for the Cinder source code.

Developer documentation is built to:
http://docs.openstack.org/developer/cinder/

Tools
=====

Sphinx
  The Python Sphinx package is used to generate the documentation output.
  Information on Sphinx, including formatting information for RST source
  files, can be found in the
  `Sphinx online documentation <http://www.sphinx-doc.org/en/stable/>`_.

Graphviz
  Some of the diagrams are generated using the ``dot`` language
  from Graphviz. See the `Graphviz documentation <http://www.graphviz.org/>`_
  for Graphviz and dot language usage information.


Building Documentation
======================

Doc builds are performed using tox with the ``docs`` target::

 % cd ..
 % tox -e docs

