Internationalization
====================
cinder uses `gettext <http://docs.python.org/library/gettext.html>`_ so that
user-facing strings such as log messages appear in the appropriate
language in different locales.

To use gettext, make sure that the strings passed to the logger are wrapped
in a ``_()`` function call. For example::

    LOG.info(_("block_device_mapping %s") % block_device_mapping)

Do not use ``locals()`` for formatting messages because:
1. It is not as clear as using explicit dicts.
2. It could produce hidden errors during refactoring.
3. Changing the name of a variable causes a change in the message.
4. It creates a lot of otherwise unused variables.

If you do not follow the project conventions, your code may cause the
LocalizationTestCase.test_multiple_positional_format_placeholders test to fail
in cinder/tests/test_localization.py.

For translation to work properly, the top level scripts for Cinder need
to first do the following before any Cinder modules are imported::

    from cinder import i18n
    i18n.enable_lazy()

Any files that use the _() for translation then must have the following
lines::

    from cinder.i18n import _

If the above code is missing, it may result in an error that looks
like::

    NameError: name '_' is not defined
