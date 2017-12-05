# Reporting Issues

Please refrain from using GitHub to report Issues, as we have since moved our main Issue Tracking to JIRA. Feel free to report any Issues [there.](http://t.fuelr.at/help)

# Contributing

* You are free to commit to the develop branch directly if you are a Tech Rat Team member.

1. Fork the main repo on github
2. Create a feature branch
3. Develop your feature/fix/whatever
4. Rebase onto upstream develop
5. Submit a PR

## Feature branches

Make a feature branch based on develop using `git checkout develop` followed by 
`git checkout -b feature/my-awesome-feature`. Instead of 'feature' you can also put 'fix' in front of the branch name if it's a bugfix or 'doc' if you only add documentation.

## Hygiene

After branching, you should immediately use `git push -u origin feature/my-awesome-feature` to make that the default upstream ref.

Before opening a PR, rebase onto develop so your PR can be merged fast-forward only, without merge commits. 
The easiest way to do that is to make the main repo a remote using `git remote add upstream git@github.com:fuelrats/pipsqueak` 
and then running `git pull --rebase upstream develop`. 
Your PR should have sensible commits with sensible commit messages. It is *not* required or appreciated to squash PRs 
into a single commit. Every commit by itself should leave the codebase in a working state and not fail any Unit relevant unit tests

## Documentation
New features should have corresponding unit tests showing proper usage.

Use comments and docstrings.
