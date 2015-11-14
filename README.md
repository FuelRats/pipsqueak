# pipsqueak
ED Fuel rats [sopel](http://sopel.chat) module package

# Installation instructions
Requires Sopel to be installed, for more information on this see [Sopel's website](http://sopel.chat/download.html)

## Normal sopel installation

Copy modules in `sopel-modules` to ~/.sopel/modules for automatic detection.
Configure Sopel's [core]extra value for detection in any other folder.

Recommended [core]enable modules:
admin,help,rat-board,rat-facts,rat-search,reload

## Virtualenv

    # setup
    pip install virtualenv
    git clone https://github.com/duk3luk3/pipsqueak.git
    cd pipsqueak
    virtualenv .
    ## adjust config
    vim sopel.cfg
    # run
    source bin/activate
    pip install -r requirements.txt
    sopel -c sopel.cfg

# rat-search.py
## Commands
Command | Parameters | Explanation
--- | --- | ---
`search` | System | Searches for the given system in EDSM's system list and then finds coordinates
 | -r | Download a new system list (Will only execute if list is over 12 hours old.)

## Detailed module information
The system search compares the input with a large list of systems,
downloaded from EDSM, if no list present this will fail.

# rat-board.py
## Commands
Command | Parameters | Explanation
--- | --- | ---
`quote` | Nick | Recites all information on `Nick`'s case.
`clear`/`close` | Nick | Mark `Nick`'s case as closed.
`list` | | List the currently active cases.
 | -i | Also list open, inactive cases.
`grab` | Nick | Grabs the last message `Nick` said and add it to their case.
`inject` | Nick, message | Injects a custom message into a nick's grab list
`sub` | Nick, index, [message] | Substitute or delete line `index` to the `Nick`'s case.
`active`| Nick | Toggle `Nick`'s case active/inactive.
`assign`| Nick, rats   | Assigns `rats` to `Nick`'s case.
`codered` / `cr` | Nick | Toggle the code red status of `Nick`'s case.
`pc` | Nick | Set `nick`'s case to be in the PC universe.
`xbox`/`xb`/`xb1`/`xbone`| Set `nick`'s case to be in the Xbox One universe.

## Detailed module information
pipsqueak includes a tool to keep track of the current board of rescues, called 'cases'.

Every message that starts with the word 'ratsignal' (case insensitive) is
automatically used to create a new case.

# rat-facts.py
## Commands
Defined in JSON file, see config.

## Config
Name | Purpose | Example
--- | --- | ---
filename | the name (and absolute path) to the JSON file containing the facts | /home/pipsqueak/facts.json

## Detailed module information
Scans incoming message that start with ! for keywords specified in the file
configured and replies with the appropriate response.

