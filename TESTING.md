# Unit Testing
Mecha utilizes the `unittest` framework provided by python and Travis for continuous Integration.

* Any new features must have appropriate and passing Unit Tests in order to be accepted.
* Updates to existing features must not cause any existing Unit Tests to fail
* PRs should pass the CI checks before being merged
##Environment
The tests will be run against Travis CI for verification.

Travis is configured to use `Ubuntu` for the host with `python 3.5` running the tests.
