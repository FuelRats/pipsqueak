# pipsqueak
ED Fuel rats IRC bot

## Install

Requires Python, tested only with python3

    pip install virtualenv
    git clone https://github.com/duk3luk3/pipsqueak.git
    cd pipsqueak
    virtualenv .
    pip install -r requirements.txt
    cd ratbot
    ./ratbot.py <server[:port]> 'channel1,channel2,...,channeln' <nick> [debug]

## Commands

Command | Parameters | Explanation
------- | ---------- | ----------
`!die`  | [Reason]   | Makes the bot quit IRC
`!reset`| [Reason]   | Makes the bot quit IRC and reconnect
`!join` | Channel    | Makes the bot join a channel
`!part` | [Channel]  | Makes the bot part from a channel (or current if none given)
`!help` |            | Privmsg's a command list similar to this one
`!fact` | [Fact key] | Recites a saved fact, privmsgs's list of known facts if no key given
`!search` | System   | Searches for the given system in EDSM's system list and then finds coordinates and a close simple-named system
        | -x         | Extended name matching: Disables limiting the initial search to systems whose names are close in length to the search term
	| -f         | Performs only the initial search and prints the three best matches
	| -l/ll/lll  | Searches for close systems in 20 / 30/ 50Ly radius instead of the default 10Ly
`!grab` | Nick       | Grabs last message from a nick
`!inject` | Nick, message | Injects a custom message into a nick's grab list
`!sub`    | Nick, index, [message] | substitutes or deletes (if no message given) a grabbed message
`!quote` | Nick      | Recites all grabbed messages from a nick
`!clear` | Nick      | Clears grab list for a nick
`!active`| Nick      | Toggles active/inactive state of a client
`!assign`| Client_nick [Nicks]   | Assigns given rats to a case or yourself
`!list`  |           | Lists all nicks in the grab list
         | -i        | List inactive clients
`!masters` |         | Lists all nicks that are currently authorized to perform privileged commands (die, join, part)
`!silence` |         | Disables many feedback messages as well as automatic grabbing of ratsignals


## System search explained

A system search (via `!search`) performs the following operations:

1. The search term is compared to all system names known to EDSM that have similar length to the search term, unless option `-x` is given, then **all** systems are compared.
2. If option `-f` is given, then the three best matches are simply printed
3. If option `-f` is not given, the best match is selected for close system search **if** coordinates are known
4. All systems in a given radius (depending on the `-l[l[l]]` option being present or not) from the best-matching system are queried from EDSM
5. The closest simple named system (where simple-named is determined as "has at most one space in its name") is selected from the results

EDSM has 100k systems in it but only has coordinates for 50k of them. In a 500Ly sphere around Sol there are 300 million systems. This means the bot has some unsolvable problems:

* It can't reliably detect typos in search terms
* It sometimes "finds" systems that are very far from the actual searched systems
* It can sometimes only print "no coordinates" because the system is in the database but doesn't have coordinates

This means that the user always has to have a close look at the results printed. The "match quality" that is printed is supposed to aid in that.

## Board management

Mecha includes a tool to keep track of the current board of rescues. It does this using a "grab" feature:

* `!grab <nick>` adds the most recent line from `<nick>` to the grab buffer for that nick
* `!inject <nick> <message>` adds a custom messages to `<nick>`'s grab buffer
* `!quote <nick>` prints all grabbed lines from `<nick>`
* `!list` lists all nicks that have grab buffers
* `!clear <nick>` deletes the grab buffer for a nick

Every message that starts with "ratsignal" is automatically grabbed.

When a new client comes in and raises the ratsignal, they will be grabbed. Then after you've handled the client, use `!clear <nick>` to remove them. And then you can use `!list` to see if there are any clients on the queue.  
Important information about the client that can't be captured from a single message can be added using `!inject`.

The board is not saved between restarts.
