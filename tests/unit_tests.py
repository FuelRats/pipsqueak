# core import
import unittest
# import mocked classes
import tests.mock as mock
# import classes to be tested
import ratlib.api.names as name

"""
This is the Unit Test file for PipSqeak.
Test Classes should be per-module
Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.
Licensed under the BSD 3-Clause License.
See LICENSE.md
"""


class RatlibNamesTests(unittest.TestCase):
    """
    Tests for ratlib.api.names
    """
    def setUp(self):
        pass

    def tearDown(self):
        pass

    # @unittest.expectedFailure
    def test_require_role_decorator(self):
        """
        Test the api.names.require_role decorator
        Verifies the role lockouts function as intended (via brute force checking)
        :return:
        """
        for level in name.Permissions:
            with self.subTest(permission=level):
                # define and decorate a test function
                @name.require_permission(level)
                def foo(bot, trigger):
                    return 42  # because failed conditions return 1 (thanks rate limiting!)
                for host in name.privlevels:
                    if name.privlevels[host] < level.value[0]:  # if the vhost does not have sufficient privilages
                        # we know this function call will fail and not return the expected value
                        # print("<<<<<=====>>>>>\n"
                        #       "i={}\tlevel.value[0] = {}\nlevel = {}\nhost={}".format(i, level.value[0], level, host))
                        self.assertNotEqual(foo(mock.Bot(), mock.Trigger(host=host)), 42)  # ensure func is not callable
                    else:
                        # the function call should suceed, and output the expected value
                        self.assertEqual(foo(mock.Bot(), mock.Trigger(host=host)), 42)  # ensure func is callable

    def test_get_priv_level(self):
        """
        Test getPrivLevel for consistency
        :return:
        """
        i = 0
        for level in name.privlevels:
            with self.subTest(level=level, levelValue=name.privlevels[level]):
                self.assertEqual(name.getPrivLevel(mock.Trigger(host=level)), i)
                # netadmin and admin are both level 6, and there is nothing above that (currently)
                i += 1 if i != 6 else 0  # so truncate as not to break the test

    def test_remove_tags(self):
        """
        Tests removeTags for consistency
        Because why not?
        :return:
        """
        # words = {"raw": "expected"}
        words = {"theunkn0wn1[pc]": "theunkn0wn1", "mechasqueak[bot]": "mechasqueak", "theunkn[0wn": "theunkn"}

        for word in words:
            with self.subTest(raw=word, expected=words[word]):
                self.assertEqual(words[word], name.removeTags(word))

# class RatBoardTests(unittest.TestCase):
#     """
#     tests for the rat-board module
#     """
#     def setUp(self):
#         pass
#
#     def tearDown(self):
#         pass


if __name__ == '__main__':  # this prevents script code from being executed on import. (bad!)
    unittest.main()
