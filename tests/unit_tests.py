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

@unittest.expectedFailure
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
        level = name.Permissions.rat
        for level in name.Permissions:
            with self.subTest(permission=level):
                # define and decorate a test function
                @name.require_permission(level)
                def foo(bot, trigger):
                    return 42  # because failed conditions return 1 (thanks rate limiting!)
                # define and reset the itterator, used during the loop over hostnames
                i = 0
                for host in name.privlevels:
                    if i < level.value[0]:  # if the vhost does not have sufficient privilages
                        # we know this function call will fail and not return the expected value
                        self.assertNotEqual(foo(mock.Bot(), mock.Trigger(host=host)), 42)  # ensure func is not callable
                    else:
                        # the function call should suceed, and output the expected value
                        self.assertEqual(foo(mock.Bot(), mock.Trigger(host=host)), 42)  # ensure func is callable
                    i += 1


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
