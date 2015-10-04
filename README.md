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
