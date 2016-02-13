# pipsqueak
ED Fuel rats [sopel](http://sopel.chat) module package

# Installation instructions
Requires Sopel to be installed, for more information on this see [Sopel's website](http://sopel.chat/download.html).  Following the virtualenv setup procedure should install sopel.

## Acquiring source
`git clone https://github.com/FuelRats/pipsqueak.git`

## Create a virtual environment
1. Most Python distributions include a built-in module for creating virtualenvs.  If yours does not:
  - `# pip install virtualenv`   
2. `# cd pipsqueak`
3. `# python -m venv *PATH*` or `virtualenv *PATH*` 
  - *PATH* can be . to create the virtualenv in the current directory.  Using 'venv' as a path is also fine, and will ensure virtual environment files are ignored by git.
	
## Configure the bot
1. Copy sopel.cfg-dist to sopel.cfg
  - `# cp sopel.cfg-dist sopel.cfg`
2. Edit sopel.cfg
  - `# vim sopel.cfg`
   
## Activate the virtual environment and install dependencies
1. `# source *PATH*/bin/activate`
2. `# pip install -r requirements.txt`

## Start the bot   
1. `# source *PATH*/bin/activate`
2. `# python start.py -c sopel.cfg`
  - **Using the built-in sopel command is not recommended, as it won't set PYTHONPATH correctly for imports.**

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

*ref* in the below table refers to a reference to a case.  This can be: the client's nickname, the client's CMDR name (if known), a case number, or a case API ID (beginning with an `@`-sign)

Commands that add quotes to a case will create a new case when *ref* looks like a nickname or CMDR name and no active case can be found.  
 
Command | Parameters | Explanation
--- | --- | ---
`quote` | *ref* | Recites all information on `Nick`'s case.
`clear`/`close` | *ref* | Mark the referenced case as closed.
`list` | | List the currently active cases.
 | -i | Also list open, inactive cases.
 | -@ | Show API IDs in the list in addition to case numbers.
`grab` | Nick | Grabs the last message `Nick` said and add it to their case, creating one if it didn't already exist.
`inject` | *ref*, message | Injects a custom message into the referenced case's quotes.  Creates the case if it doesn't already exist.
`sub` | *ref*, index, [message] | Substitute or delete line `index` to the referenced case.
`active`/`activate`/`inactive`/`deactivate`| *ref* | Toggle the referenced case between inactive and active.  Despite the command names, all of these perform the same action (e.g. `deactivate` will happily re-activate an inactive case) 
`assign`/`add`/`go` | *ref*, rats... | Assigns `rats` to the referenced case.  Separate rats with spaces.
`unassign`/`deassign`/`rm`/`remove`/`standdown` | *ref*, rats... | Removes `rats` from the referenced case if they were assigned to it.
`cr`/`codered`/`casered` | *ref* | Toggle the code red status of the referenced case.
`pc` | *ref* | Sets the referenced case to be in the PC universe.
`xbox`/`xb`/`xb1`/`xbone`/`xbox1` | *ref* | Set the referenced case to be in the Xbox One universe.

## Detailed module information
pipsqueak includes a tool to keep track of the current board of rescues, called 'cases'.

Every message that starts with the word 'ratsignal' (case insensitive) is
automatically used to create a new case.

## Bonus Features

Ratsignals and lines added with `inject` perform some behind-the-scenes magic when they add lines to a case:

- If the system coordinates trigger System Name Autocorrection, the system name is automatically corrected and an
  additional line is added to the case indicating the correction.  This fixes simple cases of accidental letter/number 
  substitution in procedurally-generated system names, but does not otherwise guarantee the system name is correct.
- If the platform is unknown and a new line contains 'PC' as a whole word somewhere, the platform is automatically set
  to PC.  If a new line contains XB, XBox, XB1, Xbone, XboxOne, Xbox1, XB-1, or any of several other variations, the
  platform is automatically set to XBox.  If a line matches both the PC and XBox patterns, the platform is unchanged.

In all situations where this magic occurs, the bot' confirmation message will tell you about it.  For instance, a new
case where the system name was corrected and platform autodetected will end with something like 
`(Case 4, autocorrected, XB)`

`sub` does *not* perform any of this magic, and may be used to correct the bot in the unlikely case of false positives.

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
You do not need to send the command from that channel, but must be currently joined to it.

Command | Parameters | Explanation
--- | --- | ---
`fact` / `facts` | (add|set) *fact*-*lang* *message* | Adds a new fact to the database, replacing the old version if it already existed.
`fact` / `facts` | (del[ete]|remove) set *fact*-*lang* | Deletes a fact from the database.
`fact` / `facts` | import | Tells the bot to (re)import legacy JSON files into the database.  This will not overwrite existing facts.

## Config
Name | Purpose | Example
--- | --- | ---
filename | the name (and absolute path) to the JSON file containing the facts, or a directory containing .json files.  Any files found will be imported to the database on startup | /home/pipsqueak/facts.json
lang | Comma-separated list of languages to search for facts when no language specifier is present. | en,es,de,ru

## Detailed module information
Scans incoming message that start with ! for keywords specified in the database and replies with the appropriate response.  Also allows online editing of facts.

If the language search order is "en,es":
* `!xwing`: Searches for the 'xwing' fact using the default search order (English, Spanish).  The `fact` command will display matching facts as **xwing-en** and **xwing-es**.
* `!xwing-es`: Searches for the 'xwing' fact in Spanish first.  If this fails, falls back to the default search order.
* `!xwing-ru`: Searches for the 'xwing' fact in Russian first.  If this fails, falls back to the default search order.

When adding or deleting facts the full fact+language specifier must be used (`xwing-en` rather than `xwing`).  `fact` will tell you this if you forget.

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

