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
    git clone https://github.com/FuelRats/pipsqueak.git
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
`xbox`/`xb`/`xb1`/`xbone`| Nick | Set `nick`'s case to be in the Xbox One universe.

## Config
Name | Purpose | Example
--- | --- | ---
urlapi | Determining the host at which the API is hosted. | http://api.fuelrats.com/

## Detailed module information
pipsqueak includes a tool to keep track of the current board of rescues, called 'cases'.

Every message that starts with the word 'ratsignal' (case insensitive) is
automatically used to create a new case.

# rat-facts.py

## Commands
Command | Parameters | Explanation
--- | --- | ---
`fact` / `facts` | | Shows a list of all known facts.
 | *fact* | Reports translation statistics on the listed fact.
 | *fact* `full` | As above, but also PMs you with all translations.
 | *lang* | Reports translation statistics on the listed language.
 | *lang* `full` | As above, but also PMs you with all facts in that language.

## Privileged Commands
Commands listed here are only usable if you have halfop or op on any channel the bot is joined to.
You need not be in that channel when you send the command.

Command | Parameters | Explanation
--- | --- | ---
`fact` / `facts` | (add|set) *fact*-*lang* *message* | Adds a new fact to the database, replacing the old version if it already existed.
`fact` / `facts` | (del[ete]|remove) set *fact*-*lang* | Deletes a fact from the database.
`fact` / `facts` | rescan | Updates the bot's cached knowledge of known facts and languages.  Only needed if the database is modified externally while the bot is running.
`fact` / `facts` | import | Tells the bot to (re)import legacy JSON files into the database.  This will not overwrite existing facts.

## Config
Name | Purpose | Example
--- | --- | ---
filename | the name (and absolute path) to the JSON file containing the facts, or a directory containing .json files.  Any files found will be imported to the database on startup | /home/pipsqueak/facts.json
table | Name of the table in Sopel's SQLite database that facts will be stored in. | ratfacts
language | Comma-separated list of languages to search for facts when no language specifier is present. | en,es,de,ru

## Detailed module information
Scans incoming message that start with ! for keywords specified in the database and replies with the appropriate response.  Also allows online editing of facts.

If the language search order is "en,es":
* `!xwing`: Searches for the 'xwing' fact using the default search order (English, Spanish).  The `fact` command will display matching facts as **xwing-en** and **xwing-es**.
* `!xwing-es`: Searches for the 'xwing' fact in Spanish first.  If this fails, falls back to the default search order.
* `!xwing-ru`: Searches for the 'xwing' fact in Russian first.  If this fails, falls back to the default search order.

When adding or deleting facts the full fact+language specifier must be used (`xwing-en` rather than `xwing`)

# rat-drill.py
## Commands
Command | Parameters | Explanation
--- | --- | ---
`drill` | | Print out both drill lists.
 | `-b` | See above
 | `-r` | Print only the [R]atting drills list.
 | `-d` / `-p` | Print only the [D]is[P]atch drills list.
`drilladd` | -r `name` | Add `name` to the [R]atting drills list.
 | -d `name` / -p `name` | Add `name` to the [D]is[P]atch drills list.
 | -b `name` | Add `name` to [B]oth the ratting and dispatch drills list.
`drillrem` | `name` | Remove `name` from both drill lists (if applicable).
 | | To remove `name` from only 1 list, use `drilladd`

## Config
Name | Purpose | Example
--- | --- | ---
drilllist | The name of the JSON file containing the drill lists | drills.json

