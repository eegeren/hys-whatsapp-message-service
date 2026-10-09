import sqlite3,sys
with sqlite3.connect('hys-local.db') as source,sqlite3.connect(sys.argv[1]) as target:source.backup(target)
