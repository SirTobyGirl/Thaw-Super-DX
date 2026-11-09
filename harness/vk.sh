#!/bin/bash
# usage: vk.sh KEY|sleep:N ...   (talks to the persistent virtual keyboard)
S="$(cd "$(dirname "$0")" && pwd)"
for a in "$@"; do case $a in sleep:*) sleep ${a#sleep:};; *) echo $a > $S/vk.fifo;; esac; done
